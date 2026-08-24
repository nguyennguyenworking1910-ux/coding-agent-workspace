"""Tests for chat ingestion CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ingestion.chat_scanner import ChatScanner, ChatScanError
from app.ingestion.claude_transcript_loader import ClaudeTranscriptLoader


class TestChatIngestionBasics:
    """Test basic chat ingestion functionality."""

    def test_ingest_chats_requires_mode(self, tmp_path: Path) -> None:
        """Test that ingest_chats requires either --dry-run or --apply flag."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "--dry-run or --apply is required" in result.stderr

    def test_ingest_chats_dry_run_with_no_transcripts(self, tmp_path: Path) -> None:
        """Test dry-run with no transcripts."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create empty projects directory
        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["mode"] == "dry_run"
        assert data["discovered_transcripts"] == 0
        assert data["database_writes"] == 0
        assert data["embedding_requests"] == 0
        # Success marker goes to stderr in JSON mode
        assert "STEP6D_CHAT_DRY_RUN_OK" in result.stderr

    def test_ingest_chats_processes_single_transcript(self, tmp_path: Path) -> None:
        """Test processing a single valid transcript."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create projects directory with a transcript
        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create a simple transcript
        transcript_file = project_dir / "test-session.jsonl"
        transcript_file.write_text("")  # Create empty file first

        records = [
            {
                "uuid": "user-1",
                "message": {"role": "user", "content": "Fix the test"},
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "uuid": "asst-1",
                "message": {"role": "assistant", "content": "I'll fix it"},
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
        ]
        for record in records:
            transcript_file.write_text(
                transcript_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--since-days",
                "30",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["mode"] == "dry_run"
        assert data["discovered_transcripts"] == 1
        assert data["planned_sources"] == 1
        assert data["total_messages"] == 2
        assert data["user_messages"] == 1
        assert data["assistant_messages"] == 1
        assert data["database_writes"] == 0
        assert data["embedding_requests"] == 0
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["session_id"] == "test-session"

    def test_ingest_chats_no_content_in_output(self, tmp_path: Path) -> None:
        """Test that chunk content is never in output."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create projects directory with a transcript
        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create a transcript with specific content
        transcript_file = project_dir / "test-session.jsonl"
        unique_text = "this_is_unique_content_should_not_appear"
        record = {
            "uuid": "user-1",
            "message": {"role": "user", "content": unique_text},
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

        time.sleep(0.1)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        # Content should never appear in output
        assert unique_text not in result.stdout
        assert unique_text not in result.stderr

    def test_ingest_chats_no_paths_in_output(self, tmp_path: Path) -> None:
        """Test that absolute paths never appear in output."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create projects directory with a transcript
        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create a transcript
        transcript_file = project_dir / "test-session.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        time.sleep(0.1)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        # Absolute paths should not appear
        assert str(repo_root) not in result.stdout
        assert str(projects_dir) not in result.stdout
        assert str(transcript_file) not in result.stdout


class TestChatIngestionSecrets:
    """Test secret handling in CLI output."""

    def test_ingest_chats_no_secrets_in_output(self, tmp_path: Path) -> None:
        """Test that secrets are not in output."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create projects directory
        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create transcript with fake secret
        transcript_file = project_dir / "test-session.jsonl"
        record = {
            "role": "user",
            "text": "Use API key sk-ant-v1-abcdefghijklmnopqrstuv",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        # Secret should not appear anywhere
        assert "sk-ant-" not in result.stdout
        assert "abcdefgh" not in result.stdout


class TestChatIngestionFiltering:
    """Test transcript filtering logic."""

    def test_ingest_chats_filters_by_session_id(self, tmp_path: Path) -> None:
        """Test that --session-id filters to specific session."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Create projects with multiple sessions
        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create two sessions
        for session_name in ["session-one", "session-two"]:
            transcript_file = project_dir / f"{session_name}.jsonl"
            record = {
                "role": "user",
                "text": f"Message from {session_name}",
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            }
            transcript_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)

        # Request only session-one
        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--session-id",
                "session-one",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["discovered_transcripts"] == 1
        assert data["sessions"][0]["session_id"] == "session-one"

    def test_ingest_chats_missing_session_fails(self, tmp_path: Path) -> None:
        """Test that missing explicit session returns non-zero."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--session-id",
                "nonexistent",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
            },
        )

        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_ingest_chats_negative_since_days_rejected(self, tmp_path: Path) -> None:
        """Test that negative --since-days is rejected."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--since-days",
                "-1",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "non-negative" in result.stderr

    def test_ingest_chats_skips_old_transcripts(self, tmp_path: Path) -> None:
        """Test that old transcripts are skipped."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create old transcript (by manipulating mtime)
        transcript_file = project_dir / "old-session.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        # Set mtime to 100 days ago
        old_time = time.time() - (100 * 86400)
        transcript_file.touch()
        Path(transcript_file).stat()
        import os
        os.utime(transcript_file, (old_time, old_time))

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--since-days",
                "30",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["discovered_transcripts"] == 1
        assert data["skipped_sessions"] == 1
        assert "too_old" in data["skip_reasons"]


class TestChatIngestionRepository:
    """Test repository isolation."""

    def test_ingest_chats_excludes_other_repository(self, tmp_path: Path) -> None:
        """Test that transcripts from other repositories are excluded."""
        repo_root = tmp_path / "repo1"
        repo_root.mkdir()

        other_repo = tmp_path / "repo2"
        other_repo.mkdir()

        # Create projects with transcript from other repo
        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        transcript_file = project_dir / "test-session.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(other_repo),  # Different repo!
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),  # We're scanning repo1
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        # Transcript should be skipped (not found)
        assert data["planned_sources"] == 0


class TestChatIngestionNoDatabaseCalls:
    """Test that no database operations occur."""

    def test_ingest_chats_never_creates_pool(self, tmp_path: Path, monkeypatch) -> None:
        """Test that create_pool is never called during dry-run."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create a transcript
        transcript_file = project_dir / "test-session.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)

        # Mock create_pool to fail if called
        from app import database as db_module

        original_create = db_module.create_pool
        create_pool_called = []

        def mock_create(*args, **kwargs):
            create_pool_called.append(True)
            raise AssertionError("create_pool should not be called during dry-run")

        monkeypatch.setattr(db_module, "create_pool", mock_create)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
            },
        )

        # Should succeed without calling create_pool
        assert result.returncode == 0
        assert "STEP6D_CHAT_DRY_RUN_OK" in result.stdout

    def test_ingest_chats_never_creates_http_embedding_client(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Test that HttpEmbeddingClient is never instantiated during dry-run."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create a transcript
        transcript_file = project_dir / "test-session.jsonl"
        record = {
            "role": "user",
            "text": "Message",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(repo_root),
        }
        transcript_file.write_text(json.dumps(record) + "\n")

        time.sleep(0.1)

        # Mock HttpEmbeddingClient to fail if instantiated
        from app.ingestion import embedding_client as ec_module

        http_client_created = []

        original_http_client = ec_module.HttpEmbeddingClient

        class MockHttpClient:
            def __init__(self, *args, **kwargs):
                http_client_created.append(True)
                raise AssertionError(
                    "HttpEmbeddingClient should not be instantiated during dry-run"
                )

        monkeypatch.setattr(ec_module, "HttpEmbeddingClient", MockHttpClient)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
            },
        )

        # Should succeed without instantiating HttpEmbeddingClient
        assert result.returncode == 0
        assert "STEP6D_CHAT_DRY_RUN_OK" in result.stdout


class TestChatIngestionChunking:
    """Test chunking behavior."""

    def test_ingest_chats_produces_chunks(self, tmp_path: Path) -> None:
        """Test that transcripts are chunked correctly."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create transcript with enough content to produce multiple chunks
        transcript_file = project_dir / "test-session.jsonl"
        transcript_file.write_text("")  # Initialize empty file

        records = [
            {
                "uuid": f"user-{i}",
                "message": {
                    "role": "user",
                    "content": "This is a long message. " * 100,
                },
                "timestamp": f"2026-01-01T00:{i:02d}:00Z",
                "cwd": str(repo_root),
            }
            for i in range(5)
        ]
        for record in records:
            transcript_file.write_text(
                transcript_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["parent_chunks"] > 0
        assert data["child_chunks"] > 0
        assert data["would_embed_children"] == data["child_chunks"]


class TestChatIngestionStats:
    """Test statistics reporting."""

    def test_ingest_chats_reports_correct_stats(self, tmp_path: Path) -> None:
        """Test that statistics are reported accurately."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        projects_dir = tmp_path / ".claude" / "projects"
        project_dir = projects_dir / "encoded-project"
        project_dir.mkdir(parents=True)

        # Create transcript with mixed content
        transcript_file = project_dir / "test-session.jsonl"
        transcript_file.write_text("")  # Initialize empty file

        records = [
            {
                "uuid": "user-1",
                "message": {"role": "user", "content": "First message"},
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(repo_root),
            },
            {
                "uuid": "asst-1",
                "message": {"role": "assistant", "content": "Response"},
                "timestamp": "2026-01-01T00:00:01Z",
                "cwd": str(repo_root),
            },
            {
                "uuid": "user-2",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Second message"}],
                },
                "timestamp": "2026-01-01T00:00:02Z",
                "cwd": str(repo_root),
            },
        ]
        for record in records:
            transcript_file.write_text(
                transcript_file.read_text() + json.dumps(record) + "\n"
            )

        time.sleep(0.1)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
                "RAG_CHAT_QUIET_PERIOD_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_messages"] == 3
        assert data["user_messages"] == 2
        assert data["assistant_messages"] == 1
        assert data["database_writes"] == 0
        assert data["embedding_requests"] == 0
        assert data["elapsed_ms"] >= 0


class TestChatIngestionApplyMode:
    """Test apply mode for production ingestion."""

    def test_dry_run_and_apply_mutually_exclusive(self, tmp_path: Path) -> None:
        """Test that --dry-run and --apply cannot both be specified."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--dry-run",
                "--apply",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "mutually exclusive" in result.stderr

    def test_apply_with_no_sources_succeeds(self, tmp_path: Path) -> None:
        """Test that apply mode with no sources succeeds without DB init."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--apply",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
            },
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["mode"] == "apply"
        assert data["planned_sources"] == 0
        assert data["inserted_sources"] == 0
        assert data["updated_sources"] == 0
        assert data["unchanged_sources"] == 0

    def test_apply_mode_requires_valid_session_before_db(self, tmp_path: Path) -> None:
        """Test that apply mode fails with missing session before DB init."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--session-id",
                "nonexistent",
                "--apply",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
            },
        )

        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_apply_mode_json_output_format(self, tmp_path: Path) -> None:
        """Test that apply mode produces correct JSON output."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)

        result = subprocess.run(
            [
                sys.executable,
                "rag-server/scripts/ingest_chats.py",
                "--root",
                str(repo_root),
                "--apply",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                **dict(subprocess.os.environ),
                "RAG_CLAUDE_PROJECTS_DIR": str(projects_dir),
            },
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["mode"] == "apply"
        assert "discovered_transcripts" in data
        assert "planned_sources" in data
        assert "inserted_sources" in data
        assert "updated_sources" in data
        assert "unchanged_sources" in data
        assert "failed_sources" in data
        assert "parent_chunks" in data
        assert "child_chunks" in data
        assert "embedded_children" in data
        assert "elapsed_ms" in data
        assert "failures" in data
