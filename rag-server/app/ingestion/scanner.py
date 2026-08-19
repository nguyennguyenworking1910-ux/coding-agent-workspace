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
        tracked and untracked files. NUL-separated output supports paths
        with spaces and Unicode characters.

        Returns:
            List of absolute paths to files in the repository, sorted in
            deterministic POSIX order

        Raises:
            RuntimeError: If git command fails (fail-closed)
        """
        try:
            # Use git ls-files with NUL-separated output for correct handling
            # of paths with spaces and Unicode characters
            # -z: NUL-separated output
            # --cached: tracked files
            # --others: untracked files
            # --exclude-standard: apply .gitignore, .git/info/exclude, etc.
            result = subprocess.run(
                [
                    "git",
                    "ls-files",
                    "-z",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                ],
                cwd=str(self.repository_root),
                capture_output=True,
                text=False,  # Binary output for NUL handling
                check=True,
            )

            files = []
            # Split by NUL byte, decode each path as UTF-8
            for relative_path_bytes in result.stdout.split(b"\x00"):
                if relative_path_bytes:  # Skip empty entries
                    try:
                        relative_path = relative_path_bytes.decode("utf-8")
                        # Paths from git ls-files are relative to repository root
                        file_path = (self.repository_root / relative_path).resolve()
                        files.append(file_path)
                    except UnicodeDecodeError as e:
                        raise RuntimeError(
                            f"Failed to decode file path as UTF-8: {relative_path_bytes}"
                        ) from e

            # Return in sorted (deterministic) order
            return sorted(files)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to discover files with git (exit code {e.returncode}): "
                f"{e.stderr.decode('utf-8', errors='replace') if e.stderr else 'unknown error'}"
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
