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
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        # Mix of valid and invalid
        history_file.write_text("not json\n", encoding="utf-8")
        record = {
            "role": "user",
            "text": "Valid message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(
            history_file.read_text() + json.dumps(record) + "\n"
        )

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        assert doc.metadata["invalid_line_count"] >= 1

    def test_excessive_invalid_lines_fail(self, tmp_path: Path) -> None:
        """Test that excessive invalid lines cause failure."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
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


class TestRedactionInMetadata:
    """Test that redaction is applied to content hash."""

    def test_content_hash_from_redacted_text(self, tmp_path: Path) -> None:
        """Test that content hash is computed from redacted text."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "role": "user",
            "text": "My key is sk-ant-abc123def456",
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
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
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

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        assert doc.metadata["message_count"] == 4
        assert doc.metadata["user_message_count"] == 2
        assert doc.metadata["assistant_message_count"] == 2
        assert "claude-opus-5" in doc.metadata["models_used"]


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
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        # Create large file
        history_file.write_bytes(b"x" * (60 * 1024 * 1024))

        loader = ClaudeTranscriptLoader(
            repo_root,
            max_file_bytes=50 * 1024 * 1024,
            quiet_period_seconds=0,  # Don't skip for age
        )

        with pytest.raises(TranscriptLoadError) as exc_info:
            loader.load(history_file, "test")
        assert "exceeds limit" in str(exc_info.value).lower()
