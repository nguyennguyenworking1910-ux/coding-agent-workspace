"""File filtering and security checks for RAG ingestion."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple


class FilterResult(NamedTuple):
    """Result of filtering a file path."""

    allowed: bool
    reason: str | None = None


# Directories to exclude from scanning (case-insensitive matching)
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".model-cache",
    "dist",
    "build",
    ".agent-workspace",
    "agent-memory-local",
    "secrets",  # Generic secrets directory
}

# Secret files that should never be loaded
SECRET_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
}

# Secret file patterns (case-insensitive)
SECRET_PATTERNS = [
    r"\.env\..*(?<!example)$",  # .env.* except .env.*.example
    r".*\.pem$",
    r".*\.key$",
    r"^id_rsa$",
    r"^service-account.*\.json$",
]

# Files explicitly allowed by name (safe example files)
ALLOWED_EXAMPLE_FILES = {
    ".env.example",
    ".env.rag.example",
}

# Extensions for documents
DOCUMENT_EXTENSIONS = {".md", ".mdx", ".txt", ".rst"}

# Extensions for code/config files
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    ".sh",
    ".ps1",
    ".bat",
}

# Files that are allowed by name (no extension)
ALLOWED_BY_NAME = {"Dockerfile", "Makefile"}

# Size limit: 2 MiB
MAX_FILE_SIZE = 2097152


class FileFilter:
    """Filters files for RAG ingestion based on security and content rules."""

    @staticmethod
    def is_secret_file(path: Path) -> bool:
        """Check if file matches any secret file pattern (case-insensitive).

        Returns True if the file is a secret that should not be loaded,
        False if it's a safe example file or not a secret.
        """
        name = path.name
        name_lower = name.lower()

        # Check if it's an explicitly allowed example file (case-insensitive)
        if name_lower in {f.lower() for f in ALLOWED_EXAMPLE_FILES}:
            return False

        # Check against secret files (case-insensitive)
        if name_lower in {f.lower() for f in SECRET_FILES}:
            return True

        # Check patterns (case-insensitive)
        for pattern in SECRET_PATTERNS:
            if re.match(pattern, name_lower):
                return True

        # Check for 'secrets' directory in path (case-insensitive)
        if any(part.lower() == "secrets" for part in path.parts):
            return True

        return False

    @staticmethod
    def is_excluded_dir(path: Path) -> bool:
        """Check if directory should be excluded from scanning (case-insensitive)."""
        return any(
            part.lower() in {d.lower() for d in EXCLUDE_DIRS}
            for part in path.parts
        )

    @staticmethod
    def is_supported_file(path: Path) -> bool:
        """Check if file extension is supported."""
        if path.name in ALLOWED_BY_NAME:
            return True

        suffix = path.suffix.lower()
        return suffix in DOCUMENT_EXTENSIONS or suffix in CODE_EXTENSIONS

    @staticmethod
    def get_source_type(path: Path) -> str:
        """Determine source_type based on file extension."""
        suffix = path.suffix.lower()
        if suffix in DOCUMENT_EXTENSIONS:
            return "project_document"
        return "source_code"

    @staticmethod
    def is_binary(content: bytes) -> bool:
        """Check if content contains binary data (NUL bytes)."""
        return b"\x00" in content

    @staticmethod
    def filter_path(
        path: Path,
        repository_root: Path,
    ) -> FilterResult:
        """Filter a single file path.

        Args:
            path: File path to filter
            repository_root: Repository root path

        Returns:
            FilterResult with allowed=True/False and optional reason

        Checks (in order):
        - Path is not absolute (relative path required)
        - No symlinks in the file or any parent directory
        - File is inside repository root (after resolve)
        - File is not a directory
        - File exists and is accessible
        - File is not in excluded directory
        - File is not a secret
        - File is not too large
        - File is not binary
        - File has supported extension
        """
        try:
            # Resolve paths for comparison
            # Handle both absolute and relative paths
            if path.is_absolute():
                resolved = path.resolve()
            else:
                resolved = (repository_root / path).resolve()

            root_resolved = repository_root.resolve()

            # Check for symlinks in parent directories
            # Walk up the path checking each component
            current_check = resolved.parent
            while current_check != current_check.parent:  # Stop at root
                if os.path.islink(str(current_check)):
                    return FilterResult(False, "symlink_in_path")
                current_check = current_check.parent

            # Check if resolved path is within repository root
            try:
                resolved.relative_to(root_resolved)
            except ValueError:
                return FilterResult(False, "outside_repository")

            # Check if path exists
            if not resolved.exists():
                return FilterResult(False, "file_not_found")

            # Check if it's a directory
            if resolved.is_dir():
                return FilterResult(False, "directory")

            # Check for symlinks at the resolved path
            if os.path.islink(str(resolved)):
                return FilterResult(False, "symlink")

            # Check for excluded directories in path (case-insensitive)
            if FileFilter.is_excluded_dir(resolved):
                return FilterResult(False, "excluded_directory")

            # Check for secret files (case-insensitive)
            if FileFilter.is_secret_file(resolved):
                return FilterResult(False, "secret_file")

            # Check file size
            try:
                size = resolved.stat().st_size
                if size > MAX_FILE_SIZE:
                    return FilterResult(False, "file_too_large")
            except (OSError, FileNotFoundError):
                return FilterResult(False, "inaccessible")

            # Check supported extensions BEFORE reading content (performance)
            if not FileFilter.is_supported_file(resolved):
                return FilterResult(False, "unsupported_extension")

            # Check for binary content (NUL bytes) by sampling first bytes
            try:
                # Read first 65536 bytes to check for NUL bytes
                with open(resolved, "rb") as f:
                    sample = f.read(65536)
                    if FileFilter.is_binary(sample):
                        return FilterResult(False, "binary_file")
            except (OSError, FileNotFoundError):
                return FilterResult(False, "inaccessible")

            return FilterResult(True)

        except Exception as e:
            return FilterResult(False, "error")
