"""Tests for chat CLI integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ingestion.chat_scanner import ChatScanner
from app.ingestion.claude_transcript_loader import ClaudeTranscriptLoader


class TestChatSourceKeys:
    """Test source key generation."""

    def test_source_key_format(self, tmp_path: Path) -> None:
        """Test that source keys use claude-chat prefix."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        transcript_file = tmp_path / "test-session.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(transcript_file, "test-session")

        assert doc.source_key.startswith("claude-chat:")
        assert "test-session" in doc.source_key

    def test_source_type_is_claude_chat(self, tmp_path: Path) -> None:
        """Test that source_type is claude_chat."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        transcript_file = tmp_path / "test.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(transcript_file, "test")

        assert doc.source_type == "claude_chat"


class TestChatMetadata:
    """Test chat metadata."""

    def test_no_absolute_path_in_metadata(self, tmp_path: Path) -> None:
        """Test that absolute paths are not stored in metadata."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        transcript_file = tmp_path / "test.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(transcript_file, "test")

        # Check metadata for absolute paths
        metadata_str = str(doc.metadata)
        assert ":\\" not in metadata_str  # Windows absolute path
        assert not metadata_str.startswith("/")  # Unix absolute path

    def test_origin_is_claude_code(self, tmp_path: Path) -> None:
        """Test that origin is set to claude_code_local_transcript."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        transcript_file = tmp_path / "test.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(transcript_file, "test")

        assert doc.metadata["origin"] == "claude_code_local_transcript"

    def test_repository_scope_set(self, tmp_path: Path) -> None:
        """Test that repository_scope is set."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        transcript_file = tmp_path / "test.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(transcript_file, "test")

        assert doc.metadata["repository_scope"] == "coding-agent-workspace"


class TestScannerIntegration:
    """Test scanner integration."""

    def test_scan_finds_transcripts(self, tmp_path: Path) -> None:
        """Test that scanner finds transcripts."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create project directory
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Create transcript using session ID as file stem
        transcript_file = project_dir / "test_session.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        assert len(transcripts) == 1
        assert transcripts[0].session_id == "test_session"


class TestIdempotency:
    """Test idempotency of transcript loading."""

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        """Test that same transcript content produces same hash."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        transcript_file = tmp_path / "test.jsonl"
        record = {
            "role": "user",
            "text": "Fixed message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        # Wait a bit to ensure file is not considered "active"
        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc1 = loader.load(transcript_file, "test")
        doc2 = loader.load(transcript_file, "test")

        # Hashes should be identical
        assert doc1.content_hash == doc2.content_hash


class TestPreviewSafety:
    """Test that preview/error output contains no secrets."""

    def test_error_message_contains_no_secret(self, tmp_path: Path) -> None:
        """Test that error messages do not contain secret values."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        transcript_file = tmp_path / "test.jsonl"
        # Create invalid JSON to trigger an error
        transcript_file.write_text("not valid json with secret sk-ant-abc123def456")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)

        try:
            loader.load(transcript_file, "test")
        except Exception as e:
            error_msg = str(e)
            # Error message should not contain the secret
            assert "sk-ant-abc123def456" not in error_msg

    def test_metadata_contains_no_absolute_path(self, tmp_path: Path) -> None:
        """Test that metadata contains no absolute local paths."""
        import time

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        transcript_file = tmp_path / "test.jsonl"
        record = {
            "role": "user",
            "text": "Test",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(transcript_file, "test")

        # source_path should be relative, not absolute
        assert doc.source_path == "test.jsonl"
        assert "\\" not in doc.source_path
        assert ":" not in doc.source_path  # No Windows drive letter
