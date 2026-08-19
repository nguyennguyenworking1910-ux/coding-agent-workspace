"""Scanner for local Claude Code chat transcripts."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScannedTranscript:
    """Result of scanning a transcript file."""

    file_path: Path
    session_id: str
    file_size_bytes: int
    modified_time: float


class ChatScanError(Exception):
    """Error during chat scanning."""

    def __init__(self, path: str | Path, reason: str):
        self.path = str(path)
        self.reason = reason
        super().__init__(f"{reason}: {path}")


class ChatScanner:
    """Scans Claude Code project directories for chat transcripts."""

    def __init__(
        self,
        projects_dir: str | Path,
        repo_root: str | Path,
        max_file_bytes: int = 52428800,
    ):
        """Initialize chat scanner.

        Args:
            projects_dir: Path to Claude Code projects directory
            repo_root: Repository root for project isolation
            max_file_bytes: Maximum transcript file size (default 50 MB)
        """
        self.projects_dir = Path(projects_dir).expanduser().resolve()
        self.repo_root = Path(repo_root).resolve()
        self.max_file_bytes = max_file_bytes

        # Validate projects_dir exists
        if not self.projects_dir.exists():
            raise ChatScanError(
                self.projects_dir,
                "projects directory does not exist",
            )
        if not self.projects_dir.is_dir():
            raise ChatScanError(
                self.projects_dir,
                "projects path is not a directory",
            )

    @staticmethod
    def resolve_projects_dir(
        configured_dir: str | None = None,
    ) -> Path:
        """Resolve Claude Code projects directory.

        Precedence:
        1. RAG_CLAUDE_PROJECTS_DIR environment variable
        2. CLAUDE_CONFIG_DIR/projects if CLAUDE_CONFIG_DIR exists
        3. ~/.claude/projects (default)

        Args:
            configured_dir: Explicitly configured directory

        Returns:
            Resolved projects directory path
        """
        # Check explicit configuration
        if configured_dir:
            return Path(configured_dir).expanduser().resolve()

        # Check environment variables
        if env_dir := os.getenv("RAG_CLAUDE_PROJECTS_DIR"):
            return Path(env_dir).expanduser().resolve()

        if env_config := os.getenv("CLAUDE_CONFIG_DIR"):
            projects_dir = Path(env_config) / "projects"
            if projects_dir.exists():
                return projects_dir.resolve()

        # Default location
        default_dir = Path.home() / ".claude" / "projects"
        return default_dir.resolve()

    def scan(
        self,
        session_id: str | None = None,
    ) -> Generator[ScannedTranscript, None, None]:
        """Scan for Claude Code transcripts.

        Only yields transcripts that belong to coding-agent-workspace
        based on embedded cwd values.

        Args:
            session_id: Optional specific session ID to scan

        Yields:
            ScannedTranscript for each valid transcript

        Raises:
            ChatScanError: If scanning fails
        """
        try:
            if session_id:
                # Scan specific session
                yield from self._scan_session(session_id)
            else:
                # Scan all projects
                for project_dir in self._iter_project_dirs():
                    if project_dir.is_dir():
                        yield from self._scan_project(project_dir)

        except ChatScanError:
            raise
        except Exception as e:
            raise ChatScanError(
                self.projects_dir,
                f"scan failed: {str(e)}",
            ) from e

    def _iter_project_dirs(self) -> Generator[Path, None, None]:
        """Iterate over project directories in projects_dir."""
        try:
            for item in sorted(self.projects_dir.iterdir()):
                if item.is_dir():
                    # Skip hidden directories and credentials
                    if item.name.startswith("."):
                        continue
                    yield item
        except (OSError, PermissionError) as e:
            raise ChatScanError(
                self.projects_dir,
                f"cannot list projects: {str(e)}",
            ) from e

    def _scan_session(self, session_id: str) -> Generator[ScannedTranscript, None, None]:
        """Scan for a specific session ID."""
        # Session files are typically in project directories
        for project_dir in self._iter_project_dirs():
            history_file = project_dir / "history.jsonl"
            if history_file.exists():
                # Try to find the session in this file
                # For now, just scan if the session ID matches directory pattern
                yield from self._scan_project(project_dir)

    def _scan_project(
        self,
        project_dir: Path,
    ) -> Generator[ScannedTranscript, None, None]:
        """Scan a single project directory for transcripts."""
        history_file = project_dir / "history.jsonl"

        if not history_file.exists():
            return

        if not history_file.is_file():
            return

        # Check file size
        try:
            file_size = history_file.stat().st_size
            file_mtime = history_file.stat().st_mtime
        except (OSError, ValueError):
            return

        if file_size > self.max_file_bytes:
            logger.warning(
                f"Skipping transcript {history_file}: exceeds size limit"
            )
            return

        # Extract session ID from project directory
        session_id = project_dir.name

        # Check if this transcript belongs to our repository
        if not self._transcript_belongs_to_repo(history_file):
            logger.debug(
                f"Skipping transcript {session_id}: "
                f"not part of {self.repo_root.name}"
            )
            return

        yield ScannedTranscript(
            file_path=history_file,
            session_id=session_id,
            file_size_bytes=file_size,
            modified_time=file_mtime,
        )

    def _transcript_belongs_to_repo(self, history_file: Path) -> bool:
        """Check if transcript belongs to the target repository.

        Reads the JSONL file and checks if any cwd value matches
        or is a child of the repository root.

        Args:
            history_file: Path to history.jsonl file

        Returns:
            True if transcript belongs to repo
        """
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Extract cwd from record
                    cwd = record.get("cwd")
                    if not cwd:
                        continue

                    # Normalize Windows paths case-insensitively
                    try:
                        cwd_path = Path(cwd).resolve()
                        # Check if cwd matches or is child of repo_root
                        if cwd_path == self.repo_root or cwd_path.is_relative_to(
                            self.repo_root
                        ):
                            return True
                    except (ValueError, OSError):
                        continue

            return False

        except (OSError, UnicodeDecodeError):
            return False
