"""Tests for chat transcript scanner."""

from __future__ import annotations

import json
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


class TestDirectSessionDiscovery:
    """Test discovery of individual session JSONL files."""

    def test_scan_finds_direct_jsonl_sessions(self, tmp_path: Path) -> None:
        """Test that scanner finds direct *.jsonl files with session IDs as stems."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create project directory
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Create two direct .jsonl session files
        session_one_file = project_dir / "session-one.jsonl"
        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        session_one_file.write_text(json.dumps(record) + "\n")

        session_two_file = project_dir / "session-two.jsonl"
        session_two_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # Should find both sessions
        assert len(transcripts) == 2
        session_ids = {t.session_id for t in transcripts}
        assert session_ids == {"session-one", "session-two"}

    def test_scan_session_returns_exact_match(self, tmp_path: Path) -> None:
        """Test that scan(session_id) returns exactly matching session."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create project directory
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Create multiple sessions
        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }

        (project_dir / "session-one.jsonl").write_text(json.dumps(record) + "\n")
        (project_dir / "session-two.jsonl").write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan(session_id="session-one"))

        assert len(transcripts) == 1
        assert transcripts[0].session_id == "session-one"

    def test_unknown_session_returns_none(self, tmp_path: Path) -> None:
        """Test that unknown session_id returns no results."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create project directory with one session
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        (project_dir / "session-one.jsonl").write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan(session_id="unknown"))

        assert len(transcripts) == 0

    def test_unsafe_session_id_rejected(self, tmp_path: Path) -> None:
        """Test that unsafe session IDs are rejected."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        scanner = ChatScanner(projects_dir, repo_root)

        # Test various unsafe IDs
        unsafe_ids = [
            "session/../dangerous",
            "session/slash",
            "session\\backslash",
            "session\x00null",
            "",
        ]

        for unsafe_id in unsafe_ids:
            transcripts = list(scanner.scan(session_id=unsafe_id))
            assert len(transcripts) == 0

    def test_nested_subagents_excluded(self, tmp_path: Path) -> None:
        """Test that nested subagent JSONL files are excluded."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create project directory
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Create direct session file
        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        (project_dir / "main-session.jsonl").write_text(json.dumps(record) + "\n")

        # Create nested subagent directory with JSONL
        subagent_dir = project_dir / "subagents"
        subagent_dir.mkdir()
        (subagent_dir / "sub.jsonl").write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # Should find only the direct session, not nested subagent
        assert len(transcripts) == 1
        assert transcripts[0].session_id == "main-session"


class TestProjectIsolation:
    """Test project isolation by cwd matching."""

    def test_matching_cwd_accepted(self, tmp_path: Path) -> None:
        """Test that transcript with matching cwd is accepted."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create project directory
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Create transcript with matching cwd
        session_file = project_dir / "session-one.jsonl"
        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        session_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        assert len(transcripts) == 1
        assert transcripts[0].session_id == "session-one"

    def test_child_cwd_accepted(self, tmp_path: Path) -> None:
        """Test that transcript with child cwd is accepted."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        subdir = repo_root / "src" / "app"
        subdir.mkdir(parents=True)

        # Create project directory
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Create transcript with child cwd
        session_file = project_dir / "session-one.jsonl"
        record = {
            "cwd": str(subdir),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        session_file.write_text(json.dumps(record) + "\n")

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
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Create transcript with other repo's cwd
        session_file = project_dir / "session-one.jsonl"
        record = {
            "cwd": str(other_repo),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        session_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        assert len(transcripts) == 0


class TestPathHandling:
    """Test path handling and normalization."""

    def test_session_id_from_file_stem(self, tmp_path: Path) -> None:
        """Test that session_id comes from file stem, not directory."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Directory name doesn't matter
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Session ID comes from file stem
        session_file = project_dir / "my-session.jsonl"
        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        session_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # Session ID should be file stem, not directory name
        assert len(transcripts) == 1
        assert transcripts[0].session_id == "my-session"

    def test_absolute_path_not_in_session_id(self, tmp_path: Path) -> None:
        """Test that session_id is file stem only, not absolute path."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        session_file = project_dir / "session-one.jsonl"
        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        session_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # ScannedTranscript.session_id should be the stem only
        assert transcripts[0].session_id == "session-one"
        assert not transcripts[0].session_id.startswith("/")
        assert not transcripts[0].session_id.startswith(str(tmp_path))


class TestFileSizeEnforcement:
    """Test file size enforcement."""

    def test_oversized_file_skipped(self, tmp_path: Path) -> None:
        """Test that oversized transcripts are skipped."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Create oversized file
        session_file = project_dir / "large-session.jsonl"
        session_file.write_bytes(b"x" * (60 * 1024 * 1024))  # 60 MB

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

        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        session_file = project_dir / "session-one.jsonl"
        session_file.write_text("")  # Create empty file first

        # Multiple records with same cwd
        for i in range(3):
            record = {
                "cwd": str(repo_root),
                "message": {"role": "user", "text": f"message {i}"},
                "timestamp": f"2026-01-01T{i:02d}:00:00Z",
            }
            session_file.write_text(
                session_file.read_text() + json.dumps(record) + "\n"
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

        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        session_file = project_dir / "session-one.jsonl"
        # Record without cwd
        record = {
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
            # No cwd
        }
        session_file.write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # Should be rejected since no matching cwd found
        assert len(transcripts) == 0


class TestDeterministicOrdering:
    """Test deterministic file and directory ordering."""

    def test_files_ordered_deterministically(self, tmp_path: Path) -> None:
        """Test that files are discovered in deterministic sorted order."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir()

        # Create files in non-alphabetical order
        record = {
            "cwd": str(repo_root),
            "message": {"role": "user", "text": "hello"},
            "timestamp": "2026-01-01T00:00:00Z",
        }

        for name in ["zebra", "apple", "middle"]:
            (project_dir / f"{name}.jsonl").write_text(json.dumps(record) + "\n")

        scanner = ChatScanner(projects_dir, repo_root)
        transcripts = list(scanner.scan())

        # Should be in sorted order
        assert len(transcripts) == 3
        session_ids = [t.session_id for t in transcripts]
        assert session_ids == ["apple", "middle", "zebra"]


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
