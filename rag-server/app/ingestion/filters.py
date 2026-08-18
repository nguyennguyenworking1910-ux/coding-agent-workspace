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


# Directories to exclude from scanning
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
}

# Secret files that should never be loaded
SECRET_FILES = {
    ".env",
    "credentials.json",
}

# Secret file patterns
SECRET_PATTERNS = [
    r"\.env\..*(?<!example)$",  # .env.* except .env.*.example
    r".*\.pem$",
    r".*\.key$",
    r"^id_rsa$",
    r"^service-account.*\.json$",
]

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
        """Check if file matches any secret file pattern."""
        name = path.name

        if name in SECRET_FILES:
            return True

        # Special case: .env.rag.example is allowed
        if name == ".env.rag.example":
            return False

        # Check patterns
        for pattern in SECRET_PATTERNS:
            if re.match(pattern, name):
                return True

        # Check for 'secrets' directory in path
        if "secrets" in path.parts:
            return True

        return False

    @staticmethod
    def is_excluded_dir(path: Path) -> bool:
        """Check if directory should be excluded from scanning."""
        return any(part in EXCLUDE_DIRS for part in path.parts)

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
        """Filter a single file path. Returns (allowed, reason)."""
        try:
            # Resolve to absolute path
            resolved = path.resolve()
            root_resolved = repository_root.resolve()

            # Check if path is within repository root
            try:
                resolved.relative_to(root_resolved)
            except ValueError:
                return FilterResult(False, "outside_repository")

            # Check if it's a directory
            if resolved.is_dir():
                return FilterResult(False, "directory")

            # Check for symlinks (if supported on platform)
            if os.path.islink(str(resolved)):
                return FilterResult(False, "symlink")

            # Check for excluded directories in path
            if FileFilter.is_excluded_dir(resolved):
                return FilterResult(False, "excluded_directory")

            # Check file size
            try:
                size = resolved.stat().st_size
                if size > MAX_FILE_SIZE:
                    return FilterResult(False, "file_too_large")
            except (OSError, FileNotFoundError):
                return FilterResult(False, "inaccessible")

            # Check for secret files
            if FileFilter.is_secret_file(resolved):
                return FilterResult(False, "secret_file")

            # Check supported extensions
            if not FileFilter.is_supported_file(resolved):
                return FilterResult(False, "unsupported_extension")

            return FilterResult(True)

        except Exception as e:
            return FilterResult(False, f"error: {type(e).__name__}")
