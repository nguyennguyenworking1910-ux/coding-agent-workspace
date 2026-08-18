"""Document loaders with UTF-8 decoding and normalization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .filters import FileFilter
from .models import LoadedDocument


class LoaderError(Exception):
    """Raised when a file cannot be loaded."""


class DocumentLoader:
    """Loads and normalizes documents from disk."""

    LOADER_VERSION = "1.0.0"
    REPOSITORY_SCOPE = "coding-agent-workspace"

    @staticmethod
    def _decode_file(file_path: Path) -> str:
        """Decode file as UTF-8, handling optional BOM.

        Args:
            file_path: Path to file to decode

        Returns:
            Decoded string content

        Raises:
            LoaderError: If file cannot be decoded as UTF-8
        """
        try:
            # Try reading with UTF-8 BOM handling
            with open(file_path, "r", encoding="utf-8-sig") as f:
                return f.read()
        except UnicodeDecodeError as e:
            raise LoaderError(
                f"File is not valid UTF-8: {file_path}"
            ) from e
        except OSError as e:
            raise LoaderError(f"Cannot read file: {file_path}") from e

    @staticmethod
    def _normalize_content(content: str) -> str:
        """Normalize content: CRLF → LF, Unicode to NFC.

        Args:
            content: Raw string content

        Returns:
            Normalized content

        Raises:
            LoaderError: If normalized content would be empty
        """
        # Normalize newlines: CRLF → LF
        content = content.replace("\r\n", "\n")
        content = content.replace("\r", "\n")

        # Normalize Unicode to NFC
        content = unicodedata.normalize("NFC", content)

        # Strip leading/trailing whitespace
        content = content.strip()

        # Reject if empty after normalization
        if not content:
            raise LoaderError("Content is empty after normalization")

        return content

    @staticmethod
    def _compute_hash(content: str) -> str:
        """Compute SHA-256 hash of content.

        Args:
            content: Normalized UTF-8 content

        Returns:
            SHA-256 hex digest (64 characters)
        """
        content_bytes = content.encode("utf-8")
        return hashlib.sha256(content_bytes).hexdigest()

    @staticmethod
    def _extract_title(file_path: Path, content: str) -> str:
        """Extract title from filename or first Markdown H1.

        Args:
            file_path: Path to file
            content: File content

        Returns:
            Document title
        """
        # Try to find first Markdown H1
        h1_match = re.search(r"^# +(.+?)$", content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()
            if title:
                return title

        # Fall back to filename without extension
        return file_path.stem

    @staticmethod
    def _get_posix_path(file_path: Path, repository_root: Path) -> str:
        """Get POSIX-style relative path from repository root.

        Args:
            file_path: Absolute path to file
            repository_root: Absolute path to repository root

        Returns:
            POSIX-style relative path (forward slashes)
        """
        try:
            relative = file_path.resolve().relative_to(
                repository_root.resolve()
            )
            # Convert to POSIX format (forward slashes)
            return relative.as_posix()
        except ValueError:
            raise LoaderError(
                f"File is not inside repository: {file_path}"
            )

    @staticmethod
    def load(file_path: Path, repository_root: Path) -> LoadedDocument:
        """Load and normalize a document.

        Args:
            file_path: Absolute path to file
            repository_root: Absolute path to repository root

        Returns:
            LoadedDocument instance

        Raises:
            LoaderError: If file cannot be loaded or normalized
        """
        # Get normalized relative path
        posix_path = DocumentLoader._get_posix_path(
            file_path, repository_root
        )

        # Decode file
        raw_content = DocumentLoader._decode_file(file_path)

        # Normalize content
        content = DocumentLoader._normalize_content(raw_content)

        # Compute hash
        content_hash = DocumentLoader._compute_hash(content)

        # Extract title
        title = DocumentLoader._extract_title(file_path, content)

        # Determine source type
        source_type = FileFilter.get_source_type(file_path)

        # Get file metadata
        try:
            stat = file_path.stat()
            size_bytes = stat.st_size
            modified_time = datetime.fromtimestamp(
                stat.st_mtime
            ).isoformat()
        except OSError as e:
            raise LoaderError(f"Cannot stat file: {file_path}") from e

        # Build metadata
        metadata = {
            "extension": file_path.suffix.lower(),
            "size_bytes": size_bytes,
            "modified_time": modified_time,
            "loader_version": DocumentLoader.LOADER_VERSION,
            "repository_scope": DocumentLoader.REPOSITORY_SCOPE,
        }

        return LoadedDocument(
            source_key=f"workspace:{posix_path}",
            source_type=source_type,
            title=title,
            source_path=posix_path,
            content=content,
            content_hash=content_hash,
            metadata=metadata,
        )
