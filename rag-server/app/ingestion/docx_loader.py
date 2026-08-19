"""DOCX document loader using python-docx."""

from __future__ import annotations

import hashlib
import logging
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .models import LoadedDocument


logger = logging.getLogger(__name__)

LOADER_VERSION = "1.0.0"


class DocxLoadError(Exception):
    """Error loading DOCX document."""

    def __init__(self, path: str | Path, reason: str, detail: str = ""):
        self.path = str(path)
        self.reason = reason
        self.detail = detail
        msg = f"{reason}: {path}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)


class DocxLoader:
    """Loads DOCX documents and extracts text."""

    VALID_HEADING_STYLES = {
        "Heading 1",
        "Heading 2",
        "Heading 3",
        "Heading 4",
        "Heading 5",
        "Heading 6",
    }

    def __init__(
        self,
        max_file_bytes: int = 26214400,
        max_uncompressed_bytes: int = 104857600,
        max_entries: int = 2000,
    ):
        """Initialize DOCX loader.

        Args:
            max_file_bytes: Maximum file size in bytes (default 25 MB)
            max_uncompressed_bytes: Maximum uncompressed size (default 100 MB)
            max_entries: Maximum ZIP entries (default 2000)
        """
        self.max_file_bytes = max_file_bytes
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_entries = max_entries

    def load(
        self,
        file_path: Path,
        relative_path: str,
        file_sha256: str,
        repository_scope: str = "coding-agent-workspace",
    ) -> LoadedDocument:
        """Load and extract text from DOCX file.

        Args:
            file_path: Absolute path to DOCX file
            relative_path: POSIX-relative path for source_key
            file_sha256: SHA-256 hash of file contents
            repository_scope: Repository scope identifier

        Returns:
            LoadedDocument with extracted text

        Raises:
            DocxLoadError: If DOCX cannot be loaded or is invalid
        """
        # Validate file size
        try:
            file_size = file_path.stat().st_size
        except (OSError, ValueError) as e:
            raise DocxLoadError(file_path, "file not found", str(e))

        if file_size > self.max_file_bytes:
            raise DocxLoadError(
                file_path,
                "file size exceeds limit",
                f"{file_size} > {self.max_file_bytes}",
            )

        # Validate ZIP container before opening with python-docx
        try:
            self._validate_zip_container(file_path)
        except DocxLoadError:
            raise

        # Load document
        try:
            doc = Document(file_path)
        except Exception as e:
            raise DocxLoadError(
                file_path,
                "invalid DOCX",
                str(e),
            )

        # Extract content
        extracted_text = ""
        paragraph_count = 0
        table_count = 0

        for element in doc.element.body:
            # Process paragraphs
            if element.tag.endswith("p"):
                para = Paragraph(element, doc)
                para_text = self._extract_paragraph_text(para)

                if para_text:
                    extracted_text += para_text
                    if not extracted_text.endswith("\n"):
                        extracted_text += "\n"
                    paragraph_count += 1

            # Process tables
            elif element.tag.endswith("tbl"):
                table = Table(element, doc)
                table_text = self._extract_table_text(table)

                if table_text:
                    extracted_text += table_text
                    if not extracted_text.endswith("\n"):
                        extracted_text += "\n"
                    table_count += 1

        # Check if any text was extracted
        if not extracted_text.strip():
            raise DocxLoadError(file_path, "empty_document")

        # Normalize and collapse excessive blank lines
        extracted_text = extracted_text.strip()
        extracted_text = re.sub(r"\n\n\n+", "\n\n", extracted_text)

        # Compute content hash
        content_hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()

        # Compute extracted text hash
        extracted_text_sha256 = hashlib.sha256(
            extracted_text.encode("utf-8")
        ).hexdigest()

        # Get title from core properties or filename
        title = file_path.stem
        if hasattr(doc.core_properties, "title") and doc.core_properties.title:
            title = doc.core_properties.title

        # Build metadata
        metadata = {
            "origin": "local_documents",
            "repository_scope": repository_scope,
            "document_format": "docx",
            "loader_version": LOADER_VERSION,
            "file_size_bytes": file_size,
            "file_sha256": file_sha256,
            "extracted_text_sha256": extracted_text_sha256,
            "paragraph_count": paragraph_count,
            "table_count": table_count,
            "inline_shape_count": len(doc.inline_shapes),
            "images_extracted": False,
        }

        return LoadedDocument(
            source_key=f"document:{relative_path}",
            source_type="project_document",
            title=title,
            source_path=relative_path,
            content=extracted_text,
            content_hash=content_hash,
            metadata=metadata,
        )

    def _validate_zip_container(self, file_path: Path) -> None:
        """Validate DOCX ZIP container structure.

        Args:
            file_path: Path to DOCX file

        Raises:
            DocxLoadError: If ZIP is invalid
        """
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                # Check for valid ZIP signature
                # (ZipFile constructor already validates)

                # Get list of files
                file_list = zf.namelist()

                # Check entry count
                if len(file_list) > self.max_entries:
                    raise DocxLoadError(
                        file_path,
                        "too many ZIP entries",
                        f"{len(file_list)} > {self.max_entries}",
                    )

                # Check for required files
                if "[Content_Types].xml" not in file_list:
                    raise DocxLoadError(
                        file_path,
                        "missing [Content_Types].xml",
                    )

                if "word/document.xml" not in file_list:
                    raise DocxLoadError(
                        file_path,
                        "missing word/document.xml",
                    )

                # Check for absolute paths and traversal
                for entry in file_list:
                    if entry.startswith("/"):
                        raise DocxLoadError(
                            file_path,
                            "absolute archive path rejected",
                            entry,
                        )

                    if ".." in entry:
                        raise DocxLoadError(
                            file_path,
                            "archive traversal rejected",
                            entry,
                        )

                # Check for encrypted entries
                info = zf.infolist()
                for item in info:
                    if item.flag_bits & 0x1:  # Encryption flag
                        raise DocxLoadError(
                            file_path,
                            "encrypted archive entry",
                            item.filename,
                        )

                # Check for .docm (macro-enabled)
                if "[Content_Types].xml" in file_list:
                    content_types = zf.read("[Content_Types].xml").decode("utf-8")
                    if "macro" in content_types.lower():
                        raise DocxLoadError(
                            file_path,
                            "macro-enabled DOCM rejected",
                        )

                # Check for legacy .doc
                if "word/document.xml" not in file_list:
                    raise DocxLoadError(
                        file_path,
                        "legacy DOC format not supported",
                    )

                # Check uncompressed size
                total_uncompressed = sum(item.file_size for item in info)
                if total_uncompressed > self.max_uncompressed_bytes:
                    raise DocxLoadError(
                        file_path,
                        "uncompressed size exceeds limit",
                        f"{total_uncompressed} > {self.max_uncompressed_bytes}",
                    )

        except zipfile.BadZipFile as e:
            raise DocxLoadError(file_path, "invalid ZIP", str(e))
        except DocxLoadError:
            raise
        except Exception as e:
            raise DocxLoadError(file_path, "ZIP validation failed", str(e))

    def _extract_paragraph_text(self, para: Paragraph) -> str:
        """Extract text from a paragraph with heading awareness.

        Args:
            para: Paragraph object

        Returns:
            Formatted paragraph text (empty string if no text)
        """
        text = para.text.strip()
        if not text:
            return ""

        # Check if paragraph is a heading
        style = para.style.name if para.style else ""
        if style in self.VALID_HEADING_STYLES:
            level = int(style.split()[-1])
            return "#" * level + " " + text

        # Check for list level
        pPr = para._element.pPr
        if pPr is not None:
            numPr = pPr.find(qn("w:numPr"))
            if numPr is not None:
                ilvl = numPr.find(qn("w:ilvl"))
                numId = numPr.find(qn("w:numId"))

                if ilvl is not None and numId is not None:
                    level = int(ilvl.get(qn("w:val"), "0"))
                    indent = "  " * level

                    # Try to determine if numbered or bulleted
                    # (simplified; actual logic depends on numbering.xml)
                    return f"{indent}- {text}"

        return text

    def _extract_table_text(self, table: Table) -> str:
        """Extract table as Markdown.

        Args:
            table: Table object

        Returns:
            Markdown-formatted table text
        """
        rows = table.rows
        if len(rows) == 0:
            return ""

        # Extract table data
        table_data = []
        for row in rows:
            row_data = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                # Escape pipe characters
                cell_text = cell_text.replace("|", "\\|")
                row_data.append(cell_text)
            table_data.append(row_data)

        if not table_data:
            return ""

        # Build Markdown table
        lines = []

        # Header row
        header = "| " + " | ".join(table_data[0]) + " |"
        lines.append(header)

        # Separator
        separator = "|" + "|".join(["---"] * len(table_data[0])) + "|"
        lines.append(separator)

        # Data rows
        for row in table_data[1:]:
            row_text = "| " + " | ".join(row) + " |"
            lines.append(row_text)

        return "\n".join(lines)
