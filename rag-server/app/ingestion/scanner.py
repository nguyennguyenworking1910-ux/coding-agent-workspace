"""Repository scanner for discovering files to ingest."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import NamedTuple

from .filters import FileFilter, FilterResult


class ScanResult(NamedTuple):
    """Result of scanning a file."""

    path: Path
    filter_result: FilterResult


class RepositoryScanner:
    """Scans a git repository for files to ingest."""

    def __init__(self, repository_root: Path):
        """Initialize scanner with repository root.

        Args:
            repository_root: Absolute path to git repository root

        Raises:
            ValueError: If repository_root is not a valid directory
        """
        self.repository_root = repository_root.resolve()
        if not self.repository_root.is_dir():
            raise ValueError(
                f"Repository root is not a directory: "
                f"{self.repository_root}"
            )

    def discover_files(self) -> list[Path]:
        """Discover all files tracked by git or present in working tree.

        Respects .gitignore rules. Uses git ls-files to discover both
        tracked and untracked files.

        Returns:
            List of absolute paths to files in the repository

        Raises:
            subprocess.CalledProcessError: If git command fails
        """
        try:
            # Use git ls-files to discover all files (tracked and untracked)
            # --cached: tracked files
            # --others: untracked files
            # --exclude-standard: apply .gitignore, .git/info/exclude, etc.
            result = subprocess.run(
                [
                    "git",
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                ],
                cwd=str(self.repository_root),
                capture_output=True,
                text=True,
                check=True,
            )

            files = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    # Paths from git ls-files are relative
                    file_path = (self.repository_root / line).resolve()
                    files.append(file_path)

            return files

        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to discover files with git: {e.stderr}"
            ) from e

    def scan(self) -> tuple[list[Path], dict[str, int]]:
        """Scan repository and filter files.

        Returns:
            Tuple of (list of allowed paths, dict of skip reasons with counts)

        Raises:
            RuntimeError: If git discovery fails
        """
        allowed_files = []
        skip_reasons: dict[str, int] = {}

        files = self.discover_files()

        for file_path in files:
            # Check if path is a directory (can happen with git ls-files)
            if file_path.is_dir():
                continue

            result = FileFilter.filter_path(
                file_path,
                self.repository_root,
            )

            if result.allowed:
                allowed_files.append(file_path)
            else:
                reason = result.reason or "unknown"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

        return allowed_files, skip_reasons
