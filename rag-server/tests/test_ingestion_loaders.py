"""Tests for RAG document loaders."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.loaders import DocumentLoader, LoaderError


class TestUTF8Decoding:
    """Test UTF-8 decoding with various encodings."""

    def test_decode_utf8_file(self, tmp_path: Path) -> None:
        """Test decoding plain UTF-8 file."""
        file_path = tmp_path / "test.txt"
        content = "Hello, world!"
        file_path.write_text(content, encoding="utf-8")

        result = DocumentLoader._decode_file(file_path)
        assert result == content

    def test_decode_utf8_with_bom(self, tmp_path: Path) -> None:
        """Test decoding UTF-8 file with BOM."""
        file_path = tmp_path / "test.txt"
        content = "Hello, world!"
        # Write with UTF-8 BOM
        file_path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

        result = DocumentLoader._decode_file(file_path)
        assert result == content

    def test_decode_vietnamese_content(self, tmp_path: Path) -> None:
        """Test decoding Vietnamese Unicode content."""
        file_path = tmp_path / "vietnamese.txt"
        content = "Xin chào, thế giới!"
        file_path.write_text(content, encoding="utf-8")

        result = DocumentLoader._decode_file(file_path)
        assert result == content
        assert "Xin chào" in result

    def test_decode_invalid_utf8_fails(self, tmp_path: Path) -> None:
        """Test that invalid UTF-8 raises LoaderError."""
        file_path = tmp_path / "invalid.txt"
        # Write invalid UTF-8
        file_path.write_bytes(b"\x80\x81\x82\x83")

        with pytest.raises(LoaderError):
            DocumentLoader._decode_file(file_path)

    def test_nonexistent_file_fails(self, tmp_path: Path) -> None:
        """Test that reading nonexistent file raises LoaderError."""
        file_path = tmp_path / "nonexistent.txt"

        with pytest.raises(LoaderError):
            DocumentLoader._decode_file(file_path)


class TestContentNormalization:
    """Test content normalization."""

    def test_crlf_normalized_to_lf(self) -> None:
        """Test that CRLF is normalized to LF."""
        content = "line1\r\nline2\r\nline3"
        result = DocumentLoader._normalize_content(content)
        assert result == "line1\nline2\nline3"

    def test_cr_normalized_to_lf(self) -> None:
        """Test that CR is normalized to LF."""
        content = "line1\rline2\rline3"
        result = DocumentLoader._normalize_content(content)
        assert result == "line1\nline2\nline3"

    def test_unicode_nfc_normalization(self) -> None:
        """Test Unicode NFC normalization."""
        # Using combining characters
        content = "café"  # e + combining acute accent
        result = DocumentLoader._normalize_content(content)
        # Should be in NFC form
        assert result == "café"  # single precomposed character

    def test_leading_trailing_whitespace_stripped(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        content = "  \n\n  text here  \n\n  "
        result = DocumentLoader._normalize_content(content)
        assert result == "text here"

    def test_empty_content_rejected(self) -> None:
        """Test that empty content after normalization is rejected."""
        with pytest.raises(LoaderError):
            DocumentLoader._normalize_content("   \n\n   ")

    def test_whitespace_only_rejected(self) -> None:
        """Test that whitespace-only content is rejected."""
        with pytest.raises(LoaderError):
            DocumentLoader._normalize_content("\t\t\n\n")


class TestContentHashing:
    """Test deterministic content hashing."""

    def test_hash_is_sha256(self) -> None:
        """Test that hash is 64-character SHA-256 hex."""
        content = "test content"
        hash_val = DocumentLoader._compute_hash(content)
        assert len(hash_val) == 64
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_hash_deterministic(self) -> None:
        """Test that same content produces same hash."""
        content = "test content"
        hash1 = DocumentLoader._compute_hash(content)
        hash2 = DocumentLoader._compute_hash(content)
        assert hash1 == hash2

    def test_hash_different_for_different_content(self) -> None:
        """Test that different content produces different hash."""
        hash1 = DocumentLoader._compute_hash("content1")
        hash2 = DocumentLoader._compute_hash("content2")
        assert hash1 != hash2

    def test_hash_utf8_consistent(self) -> None:
        """Test that UTF-8 encoding is consistent."""
        content = "Xin chào, thế giới!"
        hash1 = DocumentLoader._compute_hash(content)
        # Hash of UTF-8 encoded bytes
        hash2 = DocumentLoader._compute_hash(content)
        assert hash1 == hash2


class TestTitleExtraction:
    """Test title extraction from documents."""

    def test_h1_from_markdown(self) -> None:
        """Test extracting title from Markdown H1."""
        content = "# My Document Title\n\nContent here"
        path = Path("/repo/file.md")
        title = DocumentLoader._extract_title(path, content)
        assert title == "My Document Title"

    def test_h1_with_extra_spaces(self) -> None:
        """Test extracting H1 with extra spaces."""
        content = "#   Padded Title   \n\nContent"
        path = Path("/repo/file.md")
        title = DocumentLoader._extract_title(path, content)
        assert title == "Padded Title"

    def test_fallback_to_filename(self) -> None:
        """Test fallback to filename when no H1."""
        content = "Just some content without a heading"
        path = Path("/repo/myfile.md")
        title = DocumentLoader._extract_title(path, content)
        assert title == "myfile"

    def test_h1_not_at_start(self) -> None:
        """Test extracting H1 that appears later in document."""
        content = "Some intro\n\n# Real Title\n\nContent"
        path = Path("/repo/file.md")
        title = DocumentLoader._extract_title(path, content)
        assert title == "Real Title"

    def test_empty_h1_fallback_to_filename(self) -> None:
        """Test that empty H1 falls back to filename."""
        content = "#   \n\nContent"
        path = Path("/repo/document.md")
        title = DocumentLoader._extract_title(path, content)
        assert title == "document"


class TestSourceKeyGeneration:
    """Test source key generation."""

    def test_source_key_format(self, tmp_path: Path) -> None:
        """Test that source key has workspace: prefix."""
        file_path = tmp_path / "document.md"
        file_path.write_text("# Title\n\nContent")

        result = DocumentLoader.load(file_path, tmp_path)
        assert result.source_key.startswith("workspace:")

    def test_source_key_posix_path(self, tmp_path: Path) -> None:
        """Test that source key uses POSIX path."""
        subdir = tmp_path / "src" / "docs"
        subdir.mkdir(parents=True)
        file_path = subdir / "guide.md"
        file_path.write_text("# Guide\n\nContent")

        result = DocumentLoader.load(file_path, tmp_path)
        # Should use forward slashes
        assert "src/docs/guide.md" in result.source_key

    def test_source_key_no_backslashes(self, tmp_path: Path) -> None:
        """Test that source key never uses backslashes."""
        subdir = tmp_path / "deep" / "nested" / "path"
        subdir.mkdir(parents=True)
        file_path = subdir / "file.py"
        file_path.write_text("print('hello')")

        result = DocumentLoader.load(file_path, tmp_path)
        assert "\\" not in result.source_key


class TestMetadata:
    """Test metadata generation."""

    def test_metadata_includes_extension(self, tmp_path: Path) -> None:
        """Test that metadata includes file extension."""
        file_path = tmp_path / "file.py"
        file_path.write_text("code here")

        result = DocumentLoader.load(file_path, tmp_path)
        assert result.metadata["extension"] == ".py"

    def test_metadata_includes_size(self, tmp_path: Path) -> None:
        """Test that metadata includes file size."""
        file_path = tmp_path / "file.txt"
        content = "test content"
        file_path.write_text(content)

        result = DocumentLoader.load(file_path, tmp_path)
        assert result.metadata["size_bytes"] > 0

    def test_metadata_includes_modified_time(self, tmp_path: Path) -> None:
        """Test that metadata includes modification time."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        result = DocumentLoader.load(file_path, tmp_path)
        assert "modified_time" in result.metadata
        # Should be ISO format
        assert "T" in result.metadata["modified_time"]

    def test_metadata_includes_loader_version(self, tmp_path: Path) -> None:
        """Test that metadata includes loader version."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        result = DocumentLoader.load(file_path, tmp_path)
        assert result.metadata["loader_version"] == "1.0.0"

    def test_metadata_includes_repository_scope(self, tmp_path: Path) -> None:
        """Test that metadata includes repository scope."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        result = DocumentLoader.load(file_path, tmp_path)
        assert (
            result.metadata["repository_scope"]
            == "coding-agent-workspace"
        )


class TestIndentationPreservation:
    """Test that code indentation is preserved."""

    def test_indentation_preserved_in_python(self, tmp_path: Path) -> None:
        """Test that Python indentation is preserved."""
        file_path = tmp_path / "code.py"
        content = """def function():
    if True:
        print('indented')
        return 42"""

        file_path.write_text(content)
        result = DocumentLoader.load(file_path, tmp_path)

        # Indentation should be preserved
        assert "    if True:" in result.content
        assert "        print" in result.content

    def test_indentation_preserved_in_json(self, tmp_path: Path) -> None:
        """Test that JSON indentation is preserved."""
        file_path = tmp_path / "config.json"
        content = """{
  "name": "test",
  "nested": {
    "key": "value"
  }
}"""

        file_path.write_text(content)
        result = DocumentLoader.load(file_path, tmp_path)

        # Indentation should be preserved
        assert "  " in result.content


class TestLoadedDocumentImmutability:
    """Test that LoadedDocument is immutable."""

    def test_loaded_document_frozen(self, tmp_path: Path) -> None:
        """Test that LoadedDocument is frozen (immutable)."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        doc = DocumentLoader.load(file_path, tmp_path)

        with pytest.raises(AttributeError):
            doc.title = "new title"  # type: ignore
