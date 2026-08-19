"""Tests for local document scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.document_scanner import (
    DocumentScanError,
    LocalDocumentScanner,
)


class TestDocumentScannerBasics:
    """Test basic scanner functionality."""

    def test_scanner_requires_existing_directory(self, tmp_path: Path) -> None:
        """Test that scanner requires existing directory."""
        nonexistent = tmp_path / "nonexistent"
        with pytest.raises(DocumentScanError) as exc_info:
            LocalDocumentScanner(nonexistent)
        assert "does not exist" in str(exc_info.value)

    def test_scanner_requires_directory_not_file(self, tmp_path: Path) -> None:
        """Test that scanner rejects file path."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        with pytest.raises(DocumentScanError) as exc_info:
            LocalDocumentScanner(file_path)
        assert "not a directory" in str(exc_info.value)


class TestTraversalRejection:
    """Test traversal attack rejection."""

    def test_reject_dotdot_traversal(self, tmp_path: Path) -> None:
        """Test that .. traversal is rejected."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        scanner = LocalDocumentScanner(docs_dir)

        with pytest.raises(DocumentScanError) as exc_info:
            scanner.scan_path("../../../etc/passwd")
        assert "traversal rejected" in str(exc_info.value)

    def test_scan_rejects_files_outside_root(self, tmp_path: Path) -> None:
        """Test that scan rejects files outside document root."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "test.pdf"
        outside_file.write_text("test")

        scanner = LocalDocumentScanner(docs_dir)

        with pytest.raises(DocumentScanError) as exc_info:
            scanner.scan_path("../outside/test.pdf")
        assert "traversal rejected" in str(exc_info.value)


class TestSymlinkRejection:
    """Test symlink rejection."""

    def test_reject_symlinked_file(self, tmp_path: Path) -> None:
        """Test that symlinked files are rejected."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        # Create a file outside documents
        external_file = tmp_path / "external.pdf"
        external_file.write_text("%PDF-1.4\ntest")

        # Create symlink inside documents
        link = docs_dir / "link.pdf"
        try:
            link.symlink_to(external_file)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this system")

        scanner = LocalDocumentScanner(docs_dir)

        with pytest.raises(DocumentScanError) as exc_info:
            scanner.scan_path("link.pdf")
        assert "symlink rejected" in str(exc_info.value)

    def test_reject_symlinked_parent_directory(self, tmp_path: Path) -> None:
        """Test that symlinked parent directories are rejected."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        # Create external directory with file
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_file = external_dir / "test.pdf"
        external_file.write_text("%PDF-1.4\ntest")

        # Create symlink to external directory
        link_dir = docs_dir / "linkdir"
        try:
            link_dir.symlink_to(external_dir)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this system")

        scanner = LocalDocumentScanner(docs_dir)

        with pytest.raises(DocumentScanError) as exc_info:
            scanner.scan_path("linkdir/test.pdf")
        assert "symlink rejected" in str(exc_info.value)


class TestAbsolutePathRejection:
    """Test absolute path rejection."""

    def test_reject_absolute_path(self, tmp_path: Path) -> None:
        """Test that absolute paths are rejected."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        scanner = LocalDocumentScanner(docs_dir)

        with pytest.raises(DocumentScanError) as exc_info:
            scanner.scan_path("/etc/passwd")
        assert "absolute path rejected" in str(exc_info.value)


class TestUnsupportedExtensionRejection:
    """Test unsupported extension rejection."""

    def test_reject_unsupported_extension(self, tmp_path: Path) -> None:
        """Test that unsupported extensions are rejected."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        # Create file with unsupported extension
        unsupported_file = docs_dir / "document.txt"
        unsupported_file.write_text("test")

        scanner = LocalDocumentScanner(docs_dir)

        with pytest.raises(DocumentScanError) as exc_info:
            scanner.scan_path("document.txt")
        assert "unsupported extension" in str(exc_info.value)

    def test_scan_skips_unsupported_files(self, tmp_path: Path) -> None:
        """Test that scan skips unsupported file types."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        # Create mixed files
        (docs_dir / "document.txt").write_text("text")
        (docs_dir / "image.png").write_text("png")

        scanner = LocalDocumentScanner(docs_dir)
        scanned = list(scanner.scan())

        assert len(scanned) == 0


class TestMaximumSizeEnforcement:
    """Test maximum file size enforcement."""

    def test_enforce_max_file_size(self, tmp_path: Path) -> None:
        """Test that maximum file size is enforced."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        # Create oversized file
        large_file = docs_dir / "large.pdf"
        large_file.write_text("x" * (30 * 1024 * 1024))  # 30 MB

        # Use small max size
        scanner = LocalDocumentScanner(docs_dir, max_file_bytes=1024 * 1024)
        scanned = list(scanner.scan())

        assert len(scanned) == 0

    def test_scan_path_enforces_max_size(self, tmp_path: Path) -> None:
        """Test that scan_path enforces size limit."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        large_file = docs_dir / "large.pdf"
        large_file.write_text("x" * (30 * 1024 * 1024))

        scanner = LocalDocumentScanner(docs_dir, max_file_bytes=1024 * 1024)

        with pytest.raises(DocumentScanError) as exc_info:
            scanner.scan_path("large.pdf")
        assert "exceeds limit" in str(exc_info.value)


class TestDeterministicOrder:
    """Test deterministic scanning order."""

    def test_scan_order_is_deterministic(self, tmp_path: Path) -> None:
        """Test that scan order is deterministic."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        # Create files in non-alphabetical order
        files = ["z.pdf", "a.pdf", "m.pdf", "b.pdf"]
        for filename in files:
            (docs_dir / filename).write_text("%PDF-1.4\n")

        scanner = LocalDocumentScanner(docs_dir)

        # Scan multiple times
        results1 = [s.relative_posix_path for s in scanner.scan()]
        results2 = [s.relative_posix_path for s in scanner.scan()]

        # Should be identical
        assert results1 == results2

        # Should be sorted
        assert results1 == sorted(files)

    def test_scan_nested_files_sorted(self, tmp_path: Path) -> None:
        """Test that nested files are sorted."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        # Create nested files
        (docs_dir / "z.pdf").write_text("%PDF-1.4\n")
        (docs_dir / "a").mkdir()
        (docs_dir / "a" / "z.pdf").write_text("%PDF-1.4\n")
        (docs_dir / "a" / "a.pdf").write_text("%PDF-1.4\n")

        scanner = LocalDocumentScanner(docs_dir)
        results = [s.relative_posix_path for s in scanner.scan()]

        # Should be in POSIX order
        assert results == ["a/a.pdf", "a/z.pdf", "z.pdf"]


class TestFileSHA256Computation:
    """Test SHA-256 hash computation."""

    def test_file_hash_computed(self, tmp_path: Path) -> None:
        """Test that file hash is computed."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        pdf_file = docs_dir / "test.pdf"
        content = b"%PDF-1.4\ntest"
        pdf_file.write_bytes(content)

        scanner = LocalDocumentScanner(docs_dir)
        scanned = list(scanner.scan())

        assert len(scanned) == 1
        assert len(scanned[0].file_sha256) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in scanned[0].file_sha256)

    def test_file_hash_deterministic(self, tmp_path: Path) -> None:
        """Test that file hash is deterministic."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        pdf_file = docs_dir / "test.pdf"
        pdf_file.write_text("%PDF-1.4\ntest")

        scanner = LocalDocumentScanner(docs_dir)
        scanned1 = list(scanner.scan())
        scanned2 = list(scanner.scan())

        assert scanned1[0].file_sha256 == scanned2[0].file_sha256


class TestMissingFileRejection:
    """Test rejection of missing files."""

    def test_scan_path_rejects_missing_file(self, tmp_path: Path) -> None:
        """Test that scan_path rejects missing files."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        scanner = LocalDocumentScanner(docs_dir)

        with pytest.raises(DocumentScanError) as exc_info:
            scanner.scan_path("nonexistent.pdf")
        assert "not found" in str(exc_info.value)

    def test_scan_path_rejects_directory_as_file(self, tmp_path: Path) -> None:
        """Test that scan_path rejects directories."""
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()

        sub_dir = docs_dir / "subdir"
        sub_dir.mkdir()

        scanner = LocalDocumentScanner(docs_dir)

        with pytest.raises(DocumentScanError) as exc_info:
            scanner.scan_path("subdir")
        assert "not a file" in str(exc_info.value)
