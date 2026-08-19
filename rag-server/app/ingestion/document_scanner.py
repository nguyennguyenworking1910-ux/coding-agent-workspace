"""Scanner for local PDF and DOCX documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Generator


@dataclass(frozen=True)
class ScannedDocument:
    """Result of scanning a local document file."""

    file_path: Path
    relative_posix_path: str
    file_size_bytes: int
    file_sha256: str
    extension: str


class DocumentScanError(Exception):
    """Error during document scanning."""

    def __init__(self, path: str | Path, reason: str):
        self.path = str(path)
        self.reason = reason
        super().__init__(f"{reason}: {path}")


class LocalDocumentScanner:
    """Scans a configured local directory for PDF and DOCX documents."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
    MAX_TRAVERSAL_DEPTH = 100

    def __init__(
        self,
        documents_dir: str | Path,
        max_file_bytes: int = 26214400,
    ):
        """Initialize scanner with document directory.

        Args:
            documents_dir: Path to local documents directory
            max_file_bytes: Maximum file size in bytes (default 25 MB)
        """
        self.documents_dir = Path(documents_dir).resolve()
        self.max_file_bytes = max_file_bytes

        # Validate documents_dir exists and is a directory
        if not self.documents_dir.exists():
            raise DocumentScanError(
                self.documents_dir,
                "documents directory does not exist",
            )
        if not self.documents_dir.is_dir():
            raise DocumentScanError(
                self.documents_dir,
                "documents path is not a directory",
            )

    def scan(self) -> Generator[ScannedDocument, None, None]:
        """Scan documents directory in deterministic POSIX order.

        Yields:
            ScannedDocument for each valid PDF/DOCX file

        Raises:
            DocumentScanError: If directory traversal is attempted
        """
        # Collect all files first for deterministic sorting
        files = []

        try:
            for item in self.documents_dir.rglob("*"):
                # Reject symlinks and their parents
                if item.is_symlink():
                    continue

                # Check if any parent is a symlink
                if self._has_symlink_parent(item):
                    continue

                # Only process files
                if not item.is_file():
                    continue

                # Check extension
                if item.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                    continue

                # Check size
                try:
                    file_size = item.stat().st_size
                except (OSError, ValueError):
                    continue

                if file_size > self.max_file_bytes:
                    continue

                # Get relative POSIX path
                try:
                    rel_path = item.relative_to(self.documents_dir)
                except ValueError as e:
                    raise DocumentScanError(
                        item,
                        "path is outside document root",
                    ) from e

                # Reject .. traversal
                posix_path = rel_path.as_posix()
                if ".." in posix_path or posix_path.startswith("/"):
                    raise DocumentScanError(item, "invalid path traversal")

                files.append((item, posix_path, file_size))

        except DocumentScanError:
            raise
        except Exception as e:
            raise DocumentScanError(
                self.documents_dir,
                f"scan failed: {str(e)}",
            ) from e

        # Sort by POSIX path for deterministic order
        files.sort(key=lambda x: x[1])

        # Yield in order
        for file_path, posix_path, file_size in files:
            file_sha256 = self._compute_file_hash(file_path)
            extension = file_path.suffix.lower()

            yield ScannedDocument(
                file_path=file_path,
                relative_posix_path=posix_path,
                file_size_bytes=file_size,
                file_sha256=file_sha256,
                extension=extension,
            )

    def scan_path(self, relative_path: str) -> ScannedDocument:
        """Scan a specific relative path.

        Args:
            relative_path: POSIX-style relative path

        Returns:
            ScannedDocument if valid

        Raises:
            DocumentScanError: If path is invalid or inaccessible
        """
        # Reject absolute paths
        if relative_path.startswith("/"):
            raise DocumentScanError(relative_path, "absolute path rejected")

        # Reject .. traversal
        if ".." in relative_path:
            raise DocumentScanError(relative_path, "traversal rejected")

        # Convert to Path
        file_path = self.documents_dir / relative_path

        # Ensure it's under documents_dir
        try:
            file_path.relative_to(self.documents_dir)
        except ValueError:
            raise DocumentScanError(
                relative_path,
                "path is outside document root",
            )

        # Reject symlinks
        if file_path.is_symlink():
            raise DocumentScanError(relative_path, "symlink rejected")

        # Check if any parent is a symlink
        if self._has_symlink_parent(file_path):
            raise DocumentScanError(relative_path, "parent symlink rejected")

        # Ensure file exists
        if not file_path.exists():
            raise DocumentScanError(relative_path, "file not found")

        if not file_path.is_file():
            raise DocumentScanError(relative_path, "not a file")

        # Check extension
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise DocumentScanError(
                relative_path,
                f"unsupported extension: {file_path.suffix}",
            )

        # Check size
        file_size = file_path.stat().st_size
        if file_size > self.max_file_bytes:
            raise DocumentScanError(relative_path, "file size exceeds limit")

        # Compute hash
        file_sha256 = self._compute_file_hash(file_path)

        return ScannedDocument(
            file_path=file_path,
            relative_posix_path=relative_path,
            file_size_bytes=file_size,
            file_sha256=file_sha256,
            extension=file_path.suffix.lower(),
        )

    @staticmethod
    def _has_symlink_parent(path: Path) -> bool:
        """Check if any parent directory is a symlink."""
        try:
            for parent in path.parents:
                if parent.is_symlink():
                    return True
        except (OSError, ValueError):
            pass
        return False

    @staticmethod
    def _compute_file_hash(file_path: Path) -> str:
        """Compute SHA-256 hash of file contents."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
