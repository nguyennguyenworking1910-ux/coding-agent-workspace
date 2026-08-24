"""Tests for Claude transcript loader."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.ingestion.claude_transcript_loader import (
    ClaudeTranscriptLoader,
    TranscriptLoadError,
    TranscriptSnapshot,
)


class TestTranscriptBasics:
    """Test basic transcript loading."""

    def test_simple_transcript_loaded(self, tmp_path: Path) -> None:
        """Test loading a simple transcript."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty file first

        records = [
            {
                "uuid": "user-1",
                "role": "user",
                "text": "Hello",
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "uuid": "assistant-1",
                "role": "assistant",
                "text": "Hi there!",
                "timestamp": "2026-01-01T00:00:01Z",
                "model": "claude-opus-5",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test_session")

        assert doc.source_key == "claude-chat:test_session"
        assert doc.source_type == "claude_chat"
        assert "Hello" in doc.content
        assert "Hi there!" in doc.content
        assert doc.metadata["user_message_count"] == 1
        assert doc.metadata["assistant_message_count"] == 1

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Test handling of missing file."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        nonexistent = tmp_path / "nonexistent.jsonl"

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)

        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(nonexistent, "test_session")
        assert "file not found" in str(exc_info.value)


class TestJsonlParsing:
    """Test JSONL parsing."""

    def test_user_text_included(self, tmp_path: Path) -> None:
        """Test that user text is included."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "role": "user",
            "text": "User message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        assert "User message" in doc.content

    def test_assistant_text_included(self, tmp_path: Path) -> None:
        """Test that assistant text is included."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "role": "assistant",
            "text": "Assistant response",
            "timestamp": "2026-01-01T00:00:00Z",
            "model": "claude-opus-5",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        assert "Assistant response" in doc.content

    def test_tool_use_excluded(self, tmp_path: Path) -> None:
        """Test that tool_use blocks are excluded."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty file first

        records = [
            {
                "role": "user",
                "text": "Run tool",
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "bash", "input": {"command": "ls"}},
                    ]
                },
                "timestamp": "2026-01-01T00:00:01Z",
                "model": "claude-opus-5",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Tool use should be excluded
        assert "tool_use" not in doc.content
        assert "bash" not in doc.content

    def test_system_records_excluded(self, tmp_path: Path) -> None:
        """Test that system records are excluded."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty file first

        records = [
            {
                "system": True,
                "text": "System message",
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "role": "user",
                "text": "User message",
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # System should be excluded
        assert "System message" not in doc.content
        assert "User message" in doc.content

    def test_thinking_excluded(self, tmp_path: Path) -> None:
        """Test that thinking blocks are excluded."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty file first

        records = [
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "text": "Internal reasoning"},
                        {"type": "text", "text": "Response"},
                    ]
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "model": "claude-opus-5",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Thinking should be excluded
        assert "Internal reasoning" not in doc.content
        # But text should be included
        assert "Response" in doc.content


class TestUuidDeduplication:
    """Test UUID deduplication."""

    def test_duplicate_uuid_removed(self, tmp_path: Path) -> None:
        """Test that records with same UUID are deduplicated."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty file first

        # Same UUID twice
        records = [
            {
                "uuid": "dup-1",
                "role": "user",
                "text": "First occurrence",
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "uuid": "dup-1",
                "role": "user",
                "text": "Duplicate",
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Only first should be kept
        assert doc.metadata["user_message_count"] == 1


class TestMalformedLineHandling:
    """Test malformed line handling."""

    def test_invalid_json_counted(self, tmp_path: Path) -> None:
        """Test that invalid JSON lines are counted."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        # Mix of valid and invalid (with enough valid to pass ratio check)
        history_file.write_text("not json\n", encoding="utf-8")
        for i in range(20):
            record = {
                "role": "user",
                "text": f"Valid message {i}",
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            }
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0, max_invalid_line_ratio=0.1)
        doc = loader.load(history_file, "test")

        assert doc.metadata["invalid_line_count"] >= 1

    def test_excessive_invalid_lines_fail(self, tmp_path: Path) -> None:
        """Test that excessive invalid lines cause failure."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty first

        content = ""
        # Mostly invalid lines
        for i in range(10):
            content += f"invalid {i}\n"
        history_file.write_text(content)

        # One valid line
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(
            history_file.read_text() + json.dumps(record) + "\n"
        )

        loader = ClaudeTranscriptLoader(
            repo_root,
            max_invalid_line_ratio=0.05,  # 5% tolerance
            quiet_period_seconds=0,
        )

        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "too many invalid" in str(exc_info.value).lower()

    def test_no_usable_messages_fails(self, tmp_path: Path) -> None:
        """Test that transcript with no usable messages fails."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        # Only system records (excluded)
        record = {
            "system": True,
            "text": "System only",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)

        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "no usable messages" in str(exc_info.value).lower()

    def test_empty_file_raises_error(self, tmp_path: Path) -> None:
        """Test that empty file raises TranscriptLoadError, not UnboundLocalError."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Empty file

        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)

        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "no usable messages" in str(exc_info.value).lower()

    def test_blank_only_file_raises_error(self, tmp_path: Path) -> None:
        """Test that blank-only file raises TranscriptLoadError."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("\n\n\n")  # Only blank lines

        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)

        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "no usable messages" in str(exc_info.value).lower()


class TestRedactionInMetadata:
    """Test that redaction is applied to content hash."""

    def test_content_hash_from_redacted_text(self, tmp_path: Path) -> None:
        """Test that content hash is computed from redacted text."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty first

        record = {
            "role": "user",
            "text": "My key is sk-ant-abc123def456ghi789jkl012mno345",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Hash should be from redacted content
        assert "[REDACTED:ANTHROPIC_API_KEY]" in doc.content
        # Hash should be computed from redacted text
        assert len(doc.content_hash) == 64  # SHA-256 hex


class TestMessageMetadata:
    """Test message metadata recording."""

    def test_message_counts(self, tmp_path: Path) -> None:
        """Test that message counts are recorded."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty first

        records = [
            {"role": "user", "text": "Q1", "timestamp": "2026-01-01T00:00:00Z", "cwd": str(repo_root)},
            {"role": "assistant", "text": "A1", "timestamp": "2026-01-01T00:00:01Z", "model": "claude-opus-5", "cwd": str(repo_root)},
            {"role": "user", "text": "Q2", "timestamp": "2026-01-01T00:00:02Z", "cwd": str(repo_root)},
            {"role": "assistant", "text": "A2", "timestamp": "2026-01-01T00:00:03Z", "model": "claude-opus-5", "cwd": str(repo_root)},
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        assert doc.metadata["message_count"] == 4
        assert doc.metadata["user_message_count"] == 2
        assert doc.metadata["assistant_message_count"] == 2
        assert "claude-opus-5" in doc.metadata["models_used"]


class TestExcludedContentTypes:
    """Test that excluded content types are properly handled."""

    def test_tool_result_block_excluded(self, tmp_path: Path) -> None:
        """Test that tool_result blocks are excluded."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")

        records = [
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_result", "content": "result data"}
                    ]
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "model": "claude-opus-5",
                "cwd": str(repo_root),
            },
            {
                "role": "user",
                "text": "Valid message",
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Tool result should be excluded
        assert "tool_result" not in doc.content
        assert "result data" not in doc.content

    def test_dictionary_content_not_stringified(self, tmp_path: Path) -> None:
        """Test that dictionary content is ignored, not str() converted."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty file first

        records = [
            {
                "role": "assistant",
                "message": {
                    "content": {"type": "dict_content"}  # Not a list
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "model": "claude-opus-5",
                "cwd": str(repo_root),
            },
            {
                "role": "user",
                "text": "Valid message",
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Dictionary should not be stringified/included
        assert "{'type': 'dict_content'}" not in doc.content
        assert "dict_content" not in doc.content
        # But user message should be there
        assert "Valid message" in doc.content

    def test_sidechain_records_excluded(self, tmp_path: Path) -> None:
        """Test that isSidechain records are excluded."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")

        records = [
            {
                "role": "user",
                "text": "Regular message",
                "isSidechain": True,
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "role": "user",
                "text": "Valid message",
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Sidechain should be excluded
        assert "Regular message" not in doc.content
        assert "Valid message" in doc.content
        assert doc.metadata["message_count"] == 1

    def test_type_system_records_excluded(self, tmp_path: Path) -> None:
        """Test that type=system records are excluded."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")

        records = [
            {
                "type": "progress",  # Changed from "system" to "progress" which is excluded
                "role": "user",
                "text": "Progress message",
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "role": "user",
                "text": "Valid message",
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Progress should be excluded
        assert "Progress message" not in doc.content
        assert "Valid message" in doc.content


class TestAggregateTextLimit:
    """Test aggregate text size limit enforcement."""

    def test_aggregate_text_limit_enforced(self, tmp_path: Path) -> None:
        """Test that aggregate text size is enforced."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty file first

        # Create records that exceed the limit
        large_text = "x" * 1500000
        records = [
            {
                "role": "user",
                "text": large_text,
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "role": "assistant",
                "text": large_text,  # This will exceed 2MB limit
                "timestamp": "2026-01-01T00:00:01Z",
                "model": "claude-opus-5",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        loader = ClaudeTranscriptLoader(
            repo_root,
            max_text_chars=2000000,
            quiet_period_seconds=0,
        )

        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "exceeds limit" in str(exc_info.value).lower()


class TestDeterministicHashes:
    """Test that hashes are deterministic."""

    def test_missing_timestamp_produces_stable_hash(self, tmp_path: Path) -> None:
        """Test that missing timestamp produces stable content_hash."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")  # Create empty file first

        records = [
            {
                "role": "user",
                "text": "Message without timestamp",
                # No timestamp field
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        # Wait a bit to ensure file is not considered "active"
        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc1 = loader.load(history_file, "test")

        # Load again
        doc2 = loader.load(history_file, "test")

        # Hashes should be identical (not dependent on current time)
        assert doc1.content_hash == doc2.content_hash


class TestSecretSafety:
    """Test that secrets are not exposed in public fields."""

    def test_secret_not_in_title(self, tmp_path: Path) -> None:
        """Test that secrets in first user message are not in title."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "role": "user",
            "text": "My API key is sk-ant-abc123def456ghi789jkl012mno345",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Secret should not be in title
        assert "sk-ant-" not in doc.title
        assert "abc123def456" not in doc.title
        # But should have a title
        assert len(doc.title) > 0

    def test_secret_not_in_content(self, tmp_path: Path) -> None:
        """Test that secrets are redacted from content."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "role": "user",
            "text": "Key: sk-ant-abc123def456ghi789jkl012mno345",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Secret should not be in content
        assert "sk-ant-abc123def456" not in doc.content
        # But redaction marker should be
        assert "[REDACTED:" in doc.content

    def test_secret_not_in_metadata(self, tmp_path: Path) -> None:
        """Test that secrets are not in metadata."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "role": "user",
            "text": "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Check metadata doesn't contain secret
        metadata_str = json.dumps(doc.metadata)
        assert "ghp_" not in metadata_str
        assert "abcdefghijklmnopqrstuv" not in metadata_str


class TestModelExtraction:
    """Test model extraction logic."""

    def test_nested_message_model_recorded(self, tmp_path: Path) -> None:
        """Test that nested message.model is recorded correctly."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")

        records = [
            {
                "role": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-5",  # Nested model
                    "content": [
                        {"type": "text", "text": "Response"}
                    ]
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Nested model should be recorded
        assert "claude-sonnet-5" in doc.metadata["models_used"]


class TestSafeFileReading:
    """Test safe file reading with change detection."""

    def test_active_transcript_skipped(self, tmp_path: Path) -> None:
        """Test that recently modified transcript is skipped."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(
            repo_root,
            quiet_period_seconds=60,  # Wait 60 seconds
        )

        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "transcript_active" in str(exc_info.value).lower()

    def test_oversized_file_rejected(self, tmp_path: Path) -> None:
        """Test that oversized file is rejected."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        # Create large file
        history_file.write_bytes(b"x" * (60 * 1024 * 1024))
        # Wait a bit to ensure file is not considered "active"
        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(
            repo_root,
            max_file_bytes=50 * 1024 * 1024,
            quiet_period_seconds=0,  # Don't skip for age
        )

        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "exceeds limit" in str(exc_info.value).lower()


class TestStringContentHandling:
    """Test message.content as string (real Claude Code prompts)."""

    def test_string_content_included(self, tmp_path: Path) -> None:
        """Test that message.content string is included."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")

        records = [
            {
                "uuid": "user-1",
                "message": {
                    "role": "user",
                    "content": "Fix the broken test in app.py"
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "uuid": "assistant-1",
                "message": {
                    "role": "assistant",
                    "content": "I'll help fix the test."
                },
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)
        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Both string messages should be included
        assert "Fix the broken test" in doc.content
        assert "I'll help fix the test" in doc.content
        assert doc.metadata["user_message_count"] == 1
        assert doc.metadata["assistant_message_count"] == 1

    def test_string_content_with_fake_secret(self, tmp_path: Path) -> None:
        """Test that string content with fake secret is redacted."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "uuid": "user-1",
            "message": {
                "role": "user",
                "content": "Use this API key sk-ant-v1-abcdefghijklmnopqrstuv"
            },
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)
        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Content should be loaded but secret redacted
        assert "Use this API key" in doc.content
        assert "sk-ant-" not in doc.content
        assert "abcdefgh" not in doc.content

    def test_tool_result_list_ignored(self, tmp_path: Path) -> None:
        """Test that user messages with only tool_result blocks are ignored."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")

        records = [
            {
                "uuid": "user-1",
                "role": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_name": "bash",
                            "content": "command output"
                        }
                    ]
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)
        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)

        # Should fail: no usable messages
        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "no usable messages" in str(exc_info.value).lower()

    def test_mixed_content_list_accepted(self, tmp_path: Path) -> None:
        """Test that content with mixed text and tool blocks is accepted."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "uuid": "assistant-1",
            "role": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll help with that."},
                    {
                        "type": "tool_use",
                        "name": "bash",
                        "input": {"command": "ls"}
                    },
                    {"type": "text", "text": "And then we can check results."}
                ]
            },
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)
        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Both text blocks should be included
        assert "I'll help with that" in doc.content
        assert "And then we can check results" in doc.content
        # Tool blocks should NOT be included
        assert "tool_use" not in doc.content
        assert "bash" not in doc.content

    def test_dictionary_content_ignored(self, tmp_path: Path) -> None:
        """Test that message.content dict is ignored (never str() called)."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "uuid": "unknown-1",
            "message": {
                "role": "user",
                "content": {
                    "type": "unknown",
                    "data": "should be ignored"
                }
            },
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)
        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)

        # Should fail: no usable messages (dict is not processed with str())
        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "no usable messages" in str(exc_info.value).lower()

    def test_role_fallback_from_type(self, tmp_path: Path) -> None:
        """Test that role falls back to type field when needed."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")

        records = [
            {
                "uuid": "rec-1",
                "type": "user",  # No role, type=user
                "message": {
                    "content": "Message with type fallback"
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "uuid": "rec-2",
                "type": "assistant",  # No role, type=assistant
                "message": {
                    "content": "Response with type fallback"
                },
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)
        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Both should be included using type fallback
        assert "Message with type fallback" in doc.content
        assert "Response with type fallback" in doc.content
        assert doc.metadata["user_message_count"] == 1
        assert doc.metadata["assistant_message_count"] == 1

    def test_uuid_deduplication_preserves_string_content(self, tmp_path: Path) -> None:
        """Test that UUID deduplication works with string content."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        history_file.write_text("")

        records = [
            {
                "uuid": "user-1",
                "message": {
                    "role": "user",
                    "content": "Original message"
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "uuid": "user-1",  # Duplicate UUID
                "message": {
                    "role": "user",
                    "content": "Duplicate should be ignored"
                },
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]

        for record in records:
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)
        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Only first message included
        assert "Original message" in doc.content
        assert "Duplicate should be ignored" not in doc.content
        assert doc.metadata["user_message_count"] == 1
