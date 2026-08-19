"""Tests for PDF document loader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.ingestion.pdf_loader import PdfLoadError, PdfLoader


class TestPdfValidation:
    """Test PDF signature and format validation."""

    def test_invalid_pdf_signature(self, tmp_path: Path) -> None:
        """Test rejection of invalid PDF signature."""
        loader = PdfLoader()

        # Create file with wrong signature
        pdf_file = tmp_path / "invalid.pdf"
        pdf_file.write_bytes(b"NOT_PDF\ntest")

        with pytest.raises(PdfLoadError) as exc_info:
            loader.load(pdf_file, "invalid.pdf", "fake_hash")
        assert "invalid PDF signature" in str(exc_info.value)

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Test handling of missing file."""
        loader = PdfLoader()

        nonexistent = tmp_path / "nonexistent.pdf"

        with pytest.raises(PdfLoadError) as exc_info:
            loader.load(nonexistent, "nonexistent.pdf", "fake_hash")
        assert "file not found" in str(exc_info.value)

    def test_encrypted_pdf_rejected(self, tmp_path: Path) -> None:
        """Test rejection of encrypted PDFs."""
        loader = PdfLoader()

        pdf_file = tmp_path / "encrypted.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        # Mock PdfReader to return encrypted state
        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            reader_instance = MagicMock()
            reader_instance.is_encrypted = True
            reader_instance.pages = []
            mock_reader.return_value = reader_instance

            with pytest.raises(PdfLoadError) as exc_info:
                loader.load(pdf_file, "encrypted.pdf", "fake_hash")
            assert "encrypted_document" in str(exc_info.value)


class TestPdfPageExtraction:
    """Test text extraction from PDF pages."""

    def test_multi_page_extraction_preserves_order(self, tmp_path: Path) -> None:
        """Test that pages are extracted in order."""
        loader = PdfLoader()

        pdf_file = tmp_path / "multipage.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            reader_instance = MagicMock()
            reader_instance.is_encrypted = False

            # Create mock pages
            pages = []
            for i in range(3):
                page = MagicMock()
                page.extract_text.return_value = f"Page {i} content"
                pages.append(page)

            reader_instance.pages = pages
            mock_reader.return_value = reader_instance

            doc = loader.load(pdf_file, "multipage.pdf", "fake_hash")

            # Check content order
            assert "Page 0 content" in doc.content
            assert "Page 1 content" in doc.content
            assert "Page 2 content" in doc.content

    def test_handles_none_page_text(self, tmp_path: Path) -> None:
        """Test that None page text is handled without inserting markers."""
        loader = PdfLoader()

        pdf_file = tmp_path / "blank_page.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            reader_instance = MagicMock()
            reader_instance.is_encrypted = False

            # Create pages: text, None, text
            pages = []
            page1 = MagicMock()
            page1.extract_text.return_value = "Page 1 text"
            pages.append(page1)

            page2 = MagicMock()
            page2.extract_text.return_value = None  # Blank page
            pages.append(page2)

            page3 = MagicMock()
            page3.extract_text.return_value = "Page 3 text"
            pages.append(page3)

            reader_instance.pages = pages
            mock_reader.return_value = reader_instance

            doc = loader.load(pdf_file, "blank_page.pdf", "fake_hash")

            # Check that "None" is not in content
            assert "None" not in doc.content
            assert doc.content.count("Page") == 2  # Only 2 pages with text

    def test_partly_blank_pdf_recorded(self, tmp_path: Path) -> None:
        """Test that partly blank PDFs are recorded with blank page numbers."""
        loader = PdfLoader()

        pdf_file = tmp_path / "partial.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            reader_instance = MagicMock()
            reader_instance.is_encrypted = False

            pages = []
            page1 = MagicMock()
            page1.extract_text.return_value = "Content"
            pages.append(page1)

            page2 = MagicMock()
            page2.extract_text.return_value = None
            pages.append(page2)

            reader_instance.pages = pages
            mock_reader.return_value = reader_instance

            doc = loader.load(pdf_file, "partial.pdf", "fake_hash")

            assert doc.metadata["pages_without_text"] == [1]
            assert doc.metadata["pages_with_text"] == [0]

    def test_ocr_required_for_image_only_pdf(self, tmp_path: Path) -> None:
        """Test rejection of image-only PDF with ocr_required."""
        loader = PdfLoader()

        pdf_file = tmp_path / "image_only.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            reader_instance = MagicMock()
            reader_instance.is_encrypted = False

            # All pages return None (no extractable text)
            pages = []
            for _ in range(3):
                page = MagicMock()
                page.extract_text.return_value = None
                pages.append(page)

            reader_instance.pages = pages
            mock_reader.return_value = reader_instance

            with pytest.raises(PdfLoadError) as exc_info:
                loader.load(pdf_file, "image_only.pdf", "fake_hash")
            assert "ocr_required" in str(exc_info.value)


class TestPdfPageLimit:
    """Test page limit enforcement."""

    def test_enforce_max_pages(self, tmp_path: Path) -> None:
        """Test that maximum page count is enforced."""
        loader = PdfLoader(max_pages=5)

        pdf_file = tmp_path / "large.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            reader_instance = MagicMock()
            reader_instance.is_encrypted = False

            # Create 10 pages (exceeds limit of 5)
            pages = []
            for i in range(10):
                page = MagicMock()
                page.extract_text.return_value = f"Page {i}"
                pages.append(page)

            reader_instance.pages = pages
            mock_reader.return_value = reader_instance

            with pytest.raises(PdfLoadError) as exc_info:
                loader.load(pdf_file, "large.pdf", "fake_hash")
            assert "page limit exceeded" in str(exc_info.value)


class TestPdfSizeLimit:
    """Test file size enforcement."""

    def test_enforce_max_file_bytes(self, tmp_path: Path) -> None:
        """Test that maximum file size is enforced."""
        loader = PdfLoader(max_file_bytes=1024)

        # Create oversized file
        pdf_file = tmp_path / "large.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n" + b"x" * 2048)

        with pytest.raises(PdfLoadError) as exc_info:
            loader.load(pdf_file, "large.pdf", "fake_hash")
        assert "exceeds limit" in str(exc_info.value)


class TestPdfMetadata:
    """Test PDF metadata extraction."""

    def test_page_spans_recorded(self, tmp_path: Path) -> None:
        """Test that page spans are recorded."""
        loader = PdfLoader()

        pdf_file = tmp_path / "pages.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            reader_instance = MagicMock()
            reader_instance.is_encrypted = False

            pages = []
            page1 = MagicMock()
            page1.extract_text.return_value = "Page 1 text"
            pages.append(page1)

            page2 = MagicMock()
            page2.extract_text.return_value = "Page 2 text"
            pages.append(page2)

            reader_instance.pages = pages
            mock_reader.return_value = reader_instance

            doc = loader.load(pdf_file, "pages.pdf", "fake_hash")

            # Check page spans
            spans = doc.metadata["page_spans"]
            assert len(spans) == 2
            assert spans[0]["page_number"] == 0
            assert spans[1]["page_number"] == 1
            assert spans[0]["char_start"] >= 0
            assert spans[0]["char_end"] > spans[0]["char_start"]

    def test_metadata_includes_file_hash(self, tmp_path: Path) -> None:
        """Test that file SHA-256 is recorded in metadata."""
        loader = PdfLoader()

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\ntest")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            reader_instance = MagicMock()
            reader_instance.is_encrypted = False

            page = MagicMock()
            page.extract_text.return_value = "Content"
            reader_instance.pages = [page]
            mock_reader.return_value = reader_instance

            test_hash = "abc123def456"
            doc = loader.load(pdf_file, "test.pdf", test_hash)

            assert doc.metadata["file_sha256"] == test_hash


class TestPdfLineNormalization:
    """Test line ending normalization."""

    def test_crlf_normalized_to_lf(self, tmp_path: Path) -> None:
        """Test that CRLF is normalized to LF."""
        loader = PdfLoader()

        pdf_file = tmp_path / "crlf.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            reader_instance = MagicMock()
            reader_instance.is_encrypted = False

            page = MagicMock()
            page.extract_text.return_value = "Line 1\r\nLine 2\r\nLine 3"
            reader_instance.pages = [page]
            mock_reader.return_value = reader_instance

            doc = loader.load(pdf_file, "crlf.pdf", "hash")

            # Check that only LF is present
            assert "\r\n" not in doc.content
            assert "\r" not in doc.content
            assert "Line 1\nLine 2\nLine 3" in doc.content


class TestPdfErrorHandling:
    """Test PDF error handling."""

    def test_malformed_pdf_rejected(self, tmp_path: Path) -> None:
        """Test rejection of malformed PDFs."""
        loader = PdfLoader()

        pdf_file = tmp_path / "malformed.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            mock_reader.side_effect = PdfReadError("Malformed PDF")

            with pytest.raises(PdfLoadError) as exc_info:
                loader.load(pdf_file, "malformed.pdf", "hash")
            assert "malformed PDF" in str(exc_info.value)

    def test_error_does_not_expose_text(self, tmp_path: Path) -> None:
        """Test that errors don't expose extracted text in detail."""
        loader = PdfLoader()

        pdf_file = tmp_path / "error.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")

        with patch("app.ingestion.pdf_loader.PdfReader") as mock_reader:
            # Simulate a malformed PDF error
            mock_reader.side_effect = PdfReadError("Malformed stream")

            with pytest.raises(PdfLoadError) as exc_info:
                loader.load(pdf_file, "error.pdf", "hash")

            # Error message should include file path but not raw PDF data
            error_msg = str(exc_info.value)
            assert "error.pdf" in error_msg
            # Should not contain raw binary markers or extracted content
            assert "%PDF" not in error_msg
