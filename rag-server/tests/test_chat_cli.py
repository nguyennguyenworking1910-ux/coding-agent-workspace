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

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test_session")

        assert doc.source_key.startswith("claude-chat:")
        assert "test_session" in doc.source_key

    def test_source_type_is_claude_chat(self, tmp_path: Path) -> None:
        """Test that source_type is claude_chat."""
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

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        assert doc.source_type == "claude_chat"


class TestChatMetadata:
    """Test chat metadata."""

    def test_no_absolute_path_in_metadata(self, tmp_path: Path) -> None:
        """Test that absolute paths are not stored in metadata."""
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

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        # Check metadata for absolute paths
        metadata_str = str(doc.metadata)
        assert ":\\" not in metadata_str  # Windows absolute path
        assert not metadata_str.startswith("/")  # Unix absolute path

    def test_origin_is_claude_code(self, tmp_path: Path) -> None:
        """Test that origin is set to claude_code_local_transcript."""
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

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

        assert doc.metadata["origin"] == "claude_code_local_transcript"

    def test_repository_scope_set(self, tmp_path: Path) -> None:
        """Test that repository_scope is set."""
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

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc = loader.load(history_file, "test")

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
        project_dir = projects_dir / "test_session"
        project_dir.mkdir()

        # Create transcript
        history_file = project_dir / "history.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        assert len(transcripts) == 1
        assert transcripts[0].session_id == "test_session"


class TestIdempotency:
    """Test idempotency of transcript loading."""

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        """Test that same transcript content produces same hash."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        history_file = tmp_path / "history.jsonl"
        record = {
            "role": "user",
            "text": "Fixed message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        history_file.write_text(json.dumps(record) + "\n")

        loader = ClaudeTranscriptLoader(repo_root, quiet_period_seconds=0)
        doc1 = loader.load(history_file, "test")
        doc2 = loader.load(history_file, "test")

        # Hashes should be identical
        assert doc1.content_hash == doc2.content_hash
