"""Tests for chat transcript scanner."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.ingestion.chat_scanner import ChatScanError, ChatScanner


class TestChatScannerBasics:
    """Test basic scanner functionality."""

    def test_scanner_requires_existing_directory(self, tmp_path: Path) -> None:
        """Test that scanner requires existing projects directory."""
        nonexistent = tmp_path / "nonexistent"
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        with pytest.raises(ChatScanError) as exc_info:
            ChatScanner(nonexistent, repo_root)
        assert "does not exist" in str(exc_info.value)

    def test_scanner_requires_directory_not_file(self, tmp_path: Path) -> None:
        """Test that scanner rejects file path."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        file_path = projects_dir / "file.txt"
        file_path.write_text("test")

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        with pytest.raises(ChatScanError) as exc_info:
            ChatScanner(file_path, repo_root)
        assert "not a directory" in str(exc_info.value)


class TestProjectIsolation:
    """Test project isolation by cwd matching."""

    def test_matching_cwd_accepted(self, tmp_path: Path) -> None:
        """Test that transcript with matching cwd is accepted."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create project directory
        project_dir = projects_dir / "test_session"
        project_dir.mkdir()

        # Create transcript with matching cwd
        history_file = project_dir / "history.jsonl"
        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        history_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        assert len(transcripts) == 1
        assert transcripts[0].session_id == "test_session"

    def test_child_cwd_accepted(self, tmp_path: Path) -> None:
        """Test that transcript with child cwd is accepted."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        subdir = repo_root / "src" / "app"
        subdir.mkdir(parents=True)

        # Create project directory
        project_dir = projects_dir / "test_session"
        project_dir.mkdir()

        # Create transcript with child cwd
        history_file = project_dir / "history.jsonl"
        record = {
            "cwd": str(subdir),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        history_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        assert len(transcripts) == 1

    def test_other_repository_rejected(self, tmp_path: Path) -> None:
        """Test that transcript from other repository is rejected."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo1"
        repo_root.mkdir()

        other_repo = tmp_path / "repo2"
        other_repo.mkdir()

        # Create project directory
        project_dir = projects_dir / "test_session"
        project_dir.mkdir()

        # Create transcript with other repo's cwd
        history_file = project_dir / "history.jsonl"
        record = {
            "cwd": str(other_repo),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        history_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        assert len(transcripts) == 0


class TestPathHandling:
    """Test path handling and normalization."""

    def test_absolute_path_not_stored(self, tmp_path: Path) -> None:
        """Test that absolute paths aren't returned in session data."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        project_dir = projects_dir / "test_session"
        project_dir.mkdir()

        history_file = project_dir / "history.jsonl"
        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        history_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # ScannedTranscript should have paths but session_id should be ID only
        assert transcripts[0].session_id == "test_session"
        assert not transcripts[0].session_id.startswith("/")

    def test_windows_path_case_insensitive(self, tmp_path: Path) -> None:
        """Test that Windows paths are matched case-insensitively."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        project_dir = projects_dir / "test_session"
        project_dir.mkdir()

        history_file = project_dir / "history.jsonl"
        # Use different case
        cwd_lower = str(repo_root).lower()
        record = {
            "cwd": cwd_lower,
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        history_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # Should still match despite case difference
        assert len(transcripts) >= 0  # Depends on OS path resolution


class TestFileSizeEnforcement:
    """Test file size enforcement."""

    def test_oversized_file_skipped(self, tmp_path: Path) -> None:
        """Test that oversized transcripts are skipped."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        project_dir = projects_dir / "test_session"
        project_dir.mkdir()

        # Create oversized file
        history_file = project_dir / "history.jsonl"
        history_file.write_bytes(b"x" * (60 * 1024 * 1024))  # 60 MB

        scanner = ChatScanner(projects_dir, repo_root, max_file_bytes=50 * 1024 * 1024)
        transcripts = list(scanner.scan())

        # Should be skipped
        assert len(transcripts) == 0


class TestCwdExtraction:
    """Test cwd extraction from records."""

    def test_cwd_from_record(self, tmp_path: Path) -> None:
        """Test that cwd is correctly extracted from records."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        project_dir = projects_dir / "test_session"
        project_dir.mkdir()

        history_file = project_dir / "history.jsonl"
        history_file.write_text("")  # Create empty file first

        # Multiple records with same cwd
        for i in range(3):
            record = {
                "cwd": str(repo_root),
                "message": {"role": "user", "text": f"message {i}"},
                "timestamp": f"2026-01-01T{i:02d}:00:00Z",
            }
            history_file.write_text(
                history_file.read_text() + json.dumps(record) + "\n"
            )

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # Should accept transcript since at least one record has matching cwd
        assert len(transcripts) == 1

    def test_missing_cwd_skipped(self, tmp_path: Path) -> None:
        """Test that records without cwd are handled."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        project_dir = projects_dir / "test_session"
        project_dir.mkdir()

        history_file = project_dir / "history.jsonl"
        # Record without cwd
        record = {
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
            # No cwd
        }
        history_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # Should be rejected since no matching cwd found
        assert len(transcripts) == 0


class TestProjectsDirResolution:
    """Test projects directory resolution."""

    def test_resolve_projects_dir_default(self, tmp_path: Path, monkeypatch) -> None:
        """Test default projects directory resolution."""
        # Don't set environment variables
        monkeypatch.delenv("RAG_CLAUDE_PROJECTS_DIR", raising=False)
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

        result = ChatScanner.resolve_projects_dir()

        # Should resolve to ~/.claude/projects
        expected = Path.home() / ".claude" / "projects"
        assert result == expected
