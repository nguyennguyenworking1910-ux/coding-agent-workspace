"""Claude Code transcript loader."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .chat_redaction import ChatRedactor, REDACTION_VERSION
from .models import LoadedDocument

logger = logging.getLogger(__name__)

LOADER_VERSION = "1.0.0"


@dataclass(frozen=True)
class TranscriptSnapshot:
    """Snapshot of transcript file state."""

    file_size_bytes: int
    modified_time: float


class TranscriptLoadError(Exception):
    """Error loading transcript."""

    def __init__(self, path: str | Path, reason: str, detail: str = ""):
        self.path = str(path)
        self.reason = reason
        self.detail = detail
        msg = f"{reason}: {path}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)


class ClaudeTranscriptLoader:
    """Loads Claude Code JSONL transcripts."""

    def __init__(
        self,
        repo_root: str | Path,
        max_file_bytes: int = 52428800,
        max_text_chars: int = 2000000,
        quiet_period_seconds: int = 60,
        max_invalid_line_ratio: float = 0.05,
    ):
        """Initialize transcript loader.

        Args:
            repo_root: Repository root for path resolution
            max_file_bytes: Maximum file size (default 50 MB)
            max_text_chars: Maximum extracted text size (default 2 MB)
            quiet_period_seconds: Skip files modified within this period
            max_invalid_line_ratio: Maximum ratio of invalid JSON lines
        """
        self.repo_root = Path(repo_root).resolve()
        self.max_file_bytes = max_file_bytes
        self.max_text_chars = max_text_chars
        self.quiet_period_seconds = quiet_period_seconds
        self.max_invalid_line_ratio = max_invalid_line_ratio

    def load(
        self,
        file_path: Path,
        session_id: str,
        initial_snapshot: TranscriptSnapshot | None = None,
    ) -> LoadedDocument:
        """Load and parse a transcript file.

        Args:
            file_path: Path to history.jsonl file
            session_id: Session ID for source_key
            initial_snapshot: Optional initial file snapshot

        Returns:
            LoadedDocument with parsed transcript

        Raises:
            TranscriptLoadError: If transcript cannot be loaded
        """
        # Take initial snapshot
        try:
            snapshot1 = self._snapshot_file(file_path)
        except (OSError, ValueError) as e:
            raise TranscriptLoadError(file_path, "file not found", str(e))

        # Check if file was modified recently (still being written)
        time_since_mod = time.time() - snapshot1.modified_time
        if time_since_mod < self.quiet_period_seconds:
            raise TranscriptLoadError(
                file_path,
                "transcript_active",
                f"modified {time_since_mod:.0f}s ago",
            )

        # Check file size
        if snapshot1.file_size_bytes > self.max_file_bytes:
            raise TranscriptLoadError(
                file_path,
                "file size exceeds limit",
                f"{snapshot1.file_size_bytes} > {self.max_file_bytes}",
            )

        # Parse transcript
        try:
            parsed = self._parse_jsonl(file_path)
        except TranscriptLoadError:
            raise
        except Exception as e:
            raise TranscriptLoadError(
                file_path,
                "parse error",
                str(e),
            )

        # Take final snapshot
        try:
            snapshot2 = self._snapshot_file(file_path)
        except (OSError, ValueError):
            snapshot2 = snapshot1

        # Check if file changed during read
        if snapshot2.file_size_bytes != snapshot1.file_size_bytes or (
            snapshot2.modified_time != snapshot1.modified_time
        ):
            # Retry once
            try:
                logger.debug(f"Transcript changed, retrying: {file_path}")
                snapshot1 = snapshot2
                parsed = self._parse_jsonl(file_path)
                snapshot2 = self._snapshot_file(file_path)

                if snapshot2.file_size_bytes != snapshot1.file_size_bytes or (
                    snapshot2.modified_time != snapshot1.modified_time
                ):
                    # Changed again, skip
                    raise TranscriptLoadError(
                        file_path,
                        "transcript_changed_during_read",
                    )
            except TranscriptLoadError:
                raise
            except Exception as e:
                raise TranscriptLoadError(
                    file_path,
                    "parse error on retry",
                    str(e),
                )

        # Validate parsed content
        if not parsed["messages"]:
            raise TranscriptLoadError(
                file_path,
                "no usable messages",
                f"invalid_lines={parsed['invalid_line_count']}",
            )

        # Create normalized text
        normalized_text = self._create_normalized_text(parsed)

        # Redact secrets
        redactor = ChatRedactor()
        redaction_result = redactor.redact(normalized_text)
        redacted_text = redaction_result.redacted_text

        # Compute hash from redacted text
        content_hash = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()

        # Create title
        title = self._create_title(parsed)

        # Build metadata
        metadata = {
            "origin": "claude_code_local_transcript",
            "repository_scope": "coding-agent-workspace",
            "session_id": session_id,
            "started_at": parsed["started_at"],
            "ended_at": parsed["ended_at"],
            "message_count": len(parsed["messages"]),
            "user_message_count": parsed["user_message_count"],
            "assistant_message_count": parsed["assistant_message_count"],
            "models_used": parsed["models_used"],
            "invalid_line_count": parsed["invalid_line_count"],
            "redaction_count": redaction_result.redaction_count,
            "importer_version": LOADER_VERSION,
            "redaction_version": REDACTION_VERSION,
            "trust_level": "user_generated",
            "contains_instructions": True,
            "include_tool_results": False,
            "include_thinking": False,
            "include_subagents": False,
            "loader_version": LOADER_VERSION,
        }

        return LoadedDocument(
            source_key=f"claude-chat:{session_id}",
            source_type="claude_chat",
            title=title,
            source_path=f"{session_id}.jsonl",
            content=redacted_text,
            content_hash=content_hash,
            metadata=metadata,
        )

    def _snapshot_file(self, file_path: Path) -> TranscriptSnapshot:
        """Take a snapshot of file state."""
        stat = file_path.stat()
        return TranscriptSnapshot(
            file_size_bytes=stat.st_size,
            modified_time=stat.st_mtime,
        )

    def _parse_jsonl(self, file_path: Path) -> dict:
        """Parse JSONL transcript file.

        Returns:
            Dict with messages, counts, timestamps
        """
        messages = []
        invalid_line_count = 0
        user_message_count = 0
        assistant_message_count = 0
        models_used = set()
        seen_uuids = set()
        started_at = None
        ended_at = None

        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    invalid_line_count += 1
                    continue

                # Skip excluded record types
                if self._should_exclude_record(record):
                    continue

                # Extract message data
                message_data = self._extract_message(record)
                if message_data:
                    # Check for duplicates by UUID
                    uuid = record.get("uuid")
                    if uuid:
                        if uuid in seen_uuids:
                            continue
                        seen_uuids.add(uuid)

                    messages.append(message_data)

                    # Count by role
                    if message_data["role"] == "user":
                        user_message_count += 1
                    elif message_data["role"] == "assistant":
                        assistant_message_count += 1
                        # Extract model info
                        if model := record.get("model"):
                            models_used.add(model)

                # Track timestamps
                if ts := record.get("timestamp"):
                    if not started_at:
                        started_at = ts
                    ended_at = ts

        # Check invalid line ratio
        total_lines = line_num
        invalid_ratio = invalid_line_count / total_lines if total_lines > 0 else 0
        if invalid_ratio > self.max_invalid_line_ratio:
            raise TranscriptLoadError(
                file_path,
                "too many invalid lines",
                f"ratio={invalid_ratio:.2%}",
            )

        # Check for usable messages
        if not messages:
            raise TranscriptLoadError(
                file_path,
                "no usable messages",
            )

        return {
            "messages": messages,
            "started_at": started_at or datetime.now().isoformat(),
            "ended_at": ended_at or started_at or datetime.now().isoformat(),
            "user_message_count": user_message_count,
            "assistant_message_count": assistant_message_count,
            "models_used": sorted(models_used),
            "invalid_line_count": invalid_line_count,
        }

    def _should_exclude_record(self, record: dict) -> bool:
        """Check if record should be excluded."""
        # Exclude system records
        if record.get("system"):
            return True

        # Exclude progress/status records
        if record.get("type") == "progress":
            return True

        # Exclude metadata
        if record.get("isMeta"):
            return True

        # Exclude internal metadata
        if record.get("type") in [
            "summary",
            "file_history",
            "queue",
            "hook",
            "debug",
        ]:
            return True

        # Only include records with role/message
        if not (record.get("message") or record.get("role")):
            return True

        return False

    def _extract_message(self, record: dict) -> dict | None:
        """Extract message content from record.

        Returns:
            Dict with role and text, or None if no text
        """
        # Get role from message or top level
        message = record.get("message", {})
        if isinstance(message, dict):
            role = message.get("role")
        else:
            role = None

        if not role:
            role = record.get("role")

        # Only include user and assistant
        if role not in ["user", "assistant"]:
            return None

        # Extract text from content array or direct text
        text_parts = []

        if isinstance(message, dict):
            # Handle content array
            if content := message.get("content"):
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                if text := block.get("text"):
                                    text_parts.append(text)
                else:
                    # Direct text content
                    text_parts.append(str(content))

            # Handle direct text field
            if text := message.get("text"):
                text_parts.append(text)

        # Also check top-level text
        if text := record.get("text"):
            text_parts.append(text)

        # Combine text
        full_text = "\n".join(text_parts).strip()
        if not full_text:
            return None

        # Check text size
        if len(full_text) > self.max_text_chars:
            logger.warning(f"Message text exceeds limit, truncating")
            full_text = full_text[:self.max_text_chars]

        return {
            "role": role,
            "text": full_text,
            "timestamp": record.get("timestamp", datetime.now().isoformat()),
        }

    def _create_normalized_text(self, parsed: dict) -> str:
        """Create normalized Markdown-like text from messages."""
        lines = ["# Claude Code Session\n"]

        for message in parsed["messages"]:
            role = message["role"].capitalize()
            timestamp = message.get("timestamp", "")
            text = message["text"]

            lines.append(f"## {role} — {timestamp}")
            lines.append(text)
            lines.append("")

        return "\n".join(lines).strip()

    def _create_title(self, parsed: dict) -> str:
        """Create title from first user message or default."""
        for message in parsed["messages"]:
            if message["role"] == "user":
                text = message["text"]
                # Use first line, truncated
                first_line = text.split("\n")[0]
                if len(first_line) > 100:
                    first_line = first_line[:97] + "..."
                return first_line

        # Fallback to session ID
        return "Claude Code session"
