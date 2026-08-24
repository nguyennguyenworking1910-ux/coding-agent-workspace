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
        time_since_mod = max(
            0.0,
            time.time() - snapshot1.modified_time,
        )

        if (
            self.quiet_period_seconds > 0
            and time_since_mod < self.quiet_period_seconds
        ):
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
            )

        # Create normalized text
        normalized_text = self._create_normalized_text(parsed)

        # Redact secrets
        redactor = ChatRedactor()
        redaction_result = redactor.redact(normalized_text)
        redacted_text = redaction_result.redacted_text

        # Compute hash from redacted text
        content_hash = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()

        # Create title from redacted content (secrets safe)
        title = self._create_title(parsed, redacted_text)

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
            "source_key": f"claude-chat:{session_id}",
            "source_type": "claude_chat",
            "source_path": f"{session_id}.jsonl",
            "trust_level": "user_generated",
            "include_tool_results": False,
            "include_thinking": False,
            "include_subagents": False,
            "importer_version": LOADER_VERSION,
            "redaction_version": REDACTION_VERSION,
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
        non_empty_line_count = 0
        user_message_count = 0
        assistant_message_count = 0
        models_used = set()
        seen_uuids = set()
        started_at = None
        ended_at = None
        total_text_chars = 0

        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                non_empty_line_count += 1

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

                    # Check aggregate text limit before adding
                    msg_text_len = len(message_data["text"])
                    if total_text_chars + msg_text_len > self.max_text_chars:
                        raise TranscriptLoadError(
                            file_path,
                            "extracted text exceeds limit",
                        )
                    total_text_chars += msg_text_len

                    messages.append(message_data)

                    # Count by role
                    if message_data["role"] == "user":
                        user_message_count += 1
                    elif message_data["role"] == "assistant":
                        assistant_message_count += 1
                        # Extract model info (message.model takes precedence)
                        if message := record.get("message"):
                            if isinstance(message, dict):
                                if model := message.get("model"):
                                    models_used.add(model)
                        if model := record.get("model"):
                            if model not in models_used:
                                models_used.add(model)

                    # Track timestamps from included messages only
                    if ts := message_data.get("timestamp"):
                        if not started_at:
                            started_at = ts
                        ended_at = ts

        # Check for usable messages before checking invalid ratio
        if not messages:
            raise TranscriptLoadError(
                file_path,
                "no usable messages",
            )

        # Check invalid line ratio (use non-empty lines as denominator)
        invalid_ratio = invalid_line_count / non_empty_line_count if non_empty_line_count > 0 else 0
        if invalid_ratio > self.max_invalid_line_ratio:
            raise TranscriptLoadError(
                file_path,
                "too many invalid lines",
                f"ratio={invalid_ratio:.2%}",
            )

        return {
            "messages": messages,
            "started_at": started_at,
            "ended_at": ended_at,
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

        # Exclude metadata flags
        if record.get("isMeta"):
            return True

        if record.get("isSidechain"):
            return True

        # Exclude internal record types
        if record.get("type") in [
            "progress",
            "summary",
            "file_history",
            "file-history-snapshot",
            "queue",
            "queue-operation",
            "hook",
            "debug",
        ]:
            return True

        # Get role: message.role > top-level role > type (only if "user" or "assistant")
        message = record.get("message", {})
        role = None

        if isinstance(message, dict):
            role = message.get("role")

        if not role:
            role = record.get("role")

        if not role:
            # Fallback to type only if it's exactly "user" or "assistant"
            record_type = record.get("type")
            if record_type in ["user", "assistant"]:
                role = record_type

        # Only include user and assistant roles
        if role not in ["user", "assistant"]:
            return True

        return False

    def _extract_message(self, record: dict) -> dict | None:
        """Extract message content from record.

        Returns:
            Dict with role, text and timestamp, or None if no text.
            Only accepts string content; ignores tool_use, thinking, tool_result.
        """
        # Get role: message.role > top-level role > type (only if "user" or "assistant")
        message = record.get("message", {})
        role = None

        if isinstance(message, dict):
            role = message.get("role")

        if not role:
            role = record.get("role")

        if not role:
            # Fallback to type only if it's exactly "user" or "assistant"
            record_type = record.get("type")
            if record_type in ["user", "assistant"]:
                role = record_type

        # Only include user and assistant
        if role not in ["user", "assistant"]:
            return None

        # Extract text from content array, content string, or direct text
        text_parts = []
        content_was_processed = False

        if isinstance(message, dict):
            # Handle content field (string or array)
            if content := message.get("content"):
                if isinstance(content, str):
                    # Direct string content
                    trimmed = content.strip()
                    if trimmed:
                        text_parts.append(trimmed)
                        content_was_processed = True
                elif isinstance(content, list):
                    # Array of content blocks
                    for block in content:
                        if isinstance(block, dict):
                            block_type = block.get("type")
                            # Only accept text blocks; ignore tool_use, thinking, tool_result
                            if block_type == "text":
                                if text := block.get("text"):
                                    # Only accept string text
                                    if isinstance(text, str):
                                        trimmed = text.strip()
                                        if trimmed:
                                            text_parts.append(trimmed)
                                            content_was_processed = True
                            # All other block types (thinking, tool_use, tool_result) are ignored

            # Handle direct text field (only if string and not already from content)
            if not content_was_processed:
                if text := message.get("text"):
                    if isinstance(text, str):
                        trimmed = text.strip()
                        if trimmed:
                            text_parts.append(trimmed)

        # Also check top-level text (only if string)
        if text := record.get("text"):
            if isinstance(text, str):
                trimmed = text.strip()
                if trimmed and trimmed not in text_parts:
                    text_parts.append(trimmed)

        # Combine text
        full_text = "\n".join(text_parts).strip()
        if not full_text:
            return None

        return {
            "role": role,
            "text": full_text,
            "timestamp": record.get("timestamp"),
        }

    def _create_normalized_text(self, parsed: dict) -> str:
        """Create normalized Markdown-like text from messages.

        Timestamps are included only if present (deterministic).
        """
        lines = ["# Claude Code Session\n"]

        for message in parsed["messages"]:
            role = message["role"].capitalize()
            timestamp = message.get("timestamp")
            text = message["text"]

            if timestamp:
                lines.append(f"## {role} — {timestamp}")
            else:
                lines.append(f"## {role}")
            lines.append(text)
            lines.append("")

        return "\n".join(lines).strip()

    def _create_title(self, parsed: dict, redacted_content: str) -> str:
        """Create title from first user message (from redacted content).

        Uses the redacted content to ensure secrets never appear in the title.
        """
        # Parse redacted content to extract first user message
        lines = redacted_content.split("\n")
        in_first_user_message = False
        title_lines = []

        for line in lines:
            # Check if we're starting a user message section
            if line.startswith("## User"):
                in_first_user_message = True
                continue
            elif line.startswith("##"):
                # Hit another section, stop
                if title_lines:
                    break
            elif in_first_user_message:
                if line.strip():
                    title_lines.append(line)
                    # Get first non-empty line
                    break

        if title_lines:
            text = title_lines[0]
            # Truncate if needed
            if len(text) > 100:
                text = text[:97] + "..."
            return text

        # Fallback to session ID
        return "Claude Code session"
