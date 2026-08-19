"""PDF document loader using pypdf."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .models import LoadedDocument


logger = logging.getLogger(__name__)

PDF_SIGNATURE = b"%PDF"
LOADER_VERSION = "1.0.0"


@dataclass(frozen=True)
class PageSpan:
    """Metadata for a single page's character span."""

    page_number: int
    char_start: int
    char_end: int


class PdfLoadError(Exception):
    """Error loading PDF document."""

    def __init__(self, path: str | Path, reason: str, detail: str = ""):
        self.path = str(path)
        self.reason = reason
        self.detail = detail
        msg = f"{reason}: {path}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)


class PdfLoader:
    """Loads PDF documents and extracts text."""

    def __init__(
        self,
        max_file_bytes: int = 26214400,
        max_pages: int = 500,
    ):
        """Initialize PDF loader.

        Args:
            max_file_bytes: Maximum file size in bytes (default 25 MB)
            max_pages: Maximum number of pages (default 500)
        """
        self.max_file_bytes = max_file_bytes
        self.max_pages = max_pages

    def load(
        self,
        file_path: Path,
        relative_path: str,
        file_sha256: str,
        repository_scope: str = "coding-agent-workspace",
    ) -> LoadedDocument:
        """Load and extract text from PDF file.

        Args:
            file_path: Absolute path to PDF file
            relative_path: POSIX-relative path for source_key
            file_sha256: SHA-256 hash of file contents
            repository_scope: Repository scope identifier

        Returns:
            LoadedDocument with extracted text

        Raises:
            PdfLoadError: If PDF cannot be loaded or has no text
        """
        # Validate file size
        try:
            file_size = file_path.stat().st_size
        except (OSError, ValueError) as e:
            raise PdfLoadError(file_path, "file not found", str(e))

        if file_size > self.max_file_bytes:
            raise PdfLoadError(
                file_path,
                "file size exceeds limit",
                f"{file_size} > {self.max_file_bytes}",
            )

        # Validate PDF signature
        try:
            with open(file_path, "rb") as f:
                header = f.read(4)
        except (OSError, ValueError) as e:
            raise PdfLoadError(file_path, "cannot read file", str(e))

        if header != PDF_SIGNATURE:
            raise PdfLoadError(file_path, "invalid PDF signature")

        # Parse PDF
        try:
            pdf_reader = PdfReader(file_path)
        except PdfReadError as e:
            raise PdfLoadError(file_path, "malformed PDF", str(e))
        except Exception as e:
            raise PdfLoadError(file_path, "malformed PDF", str(e))

        # Check if encrypted
        if pdf_reader.is_encrypted:
            raise PdfLoadError(file_path, "encrypted_document")

        # Get page count
        page_count = len(pdf_reader.pages)
        if page_count == 0:
            raise PdfLoadError(file_path, "empty PDF")

        # Enforce page limit
        if page_count > self.max_pages:
            raise PdfLoadError(
                file_path,
                "page limit exceeded",
                f"{page_count} > {self.max_pages}",
            )

        # Extract text from all pages
        extracted_text = ""
        page_spans: list[PageSpan] = []
        pages_without_text = []
        pages_with_text = []

        for page_num, page in enumerate(pdf_reader.pages):
            page_start = len(extracted_text)

            # Extract text from page
            page_text = page.extract_text()

            # Handle None or empty text
            if not page_text:
                pages_without_text.append(page_num)
                # Don't insert "None" or markers
                page_end = page_start
            else:
                # Normalize line endings
                page_text = page_text.replace("\r\n", "\n").replace("\r", "\n")

                extracted_text += page_text
                if not extracted_text.endswith("\n"):
                    extracted_text += "\n"

                pages_with_text.append(page_num)
                page_end = len(extracted_text)

                page_spans.append(
                    PageSpan(
                        page_number=page_num,
                        char_start=page_start,
                        char_end=page_end,
                    )
                )

        # Check if any text was extracted
        if not extracted_text.strip():
            raise PdfLoadError(file_path, "ocr_required")

        # Normalize final text
        extracted_text = extracted_text.strip()

        # Compute content hash
        content_hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()

        # Compute extracted text hash
        extracted_text_sha256 = hashlib.sha256(
            extracted_text.encode("utf-8")
        ).hexdigest()

        # Build metadata
        metadata = {
            "origin": "local_documents",
            "repository_scope": repository_scope,
            "document_format": "pdf",
            "loader_version": LOADER_VERSION,
            "file_size_bytes": file_size,
            "file_sha256": file_sha256,
            "extracted_text_sha256": extracted_text_sha256,
            "page_count": page_count,
            "pages_with_text": pages_with_text,
            "pages_without_text": pages_without_text,
            "page_spans": [
                {
                    "page_number": span.page_number,
                    "char_start": span.char_start,
                    "char_end": span.char_end,
                }
                for span in page_spans
            ],
        }

        # Extract title from filename
        title = file_path.stem

        return LoadedDocument(
            source_key=f"document:{relative_path}",
            source_type="project_document",
            title=title,
            source_path=relative_path,
            content=extracted_text,
            content_hash=content_hash,
            metadata=metadata,
        )
