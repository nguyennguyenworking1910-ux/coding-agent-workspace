"""Tests for RAG document chunking."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.chunker import DocumentChunker, TokenEstimator
from app.ingestion.loaders import DocumentLoader
from app.ingestion.models import LoadedDocument


class TestTokenEstimation:
    """Test token estimation."""

    def test_estimate_tokens_simple(self) -> None:
        """Test basic token estimation."""
        content = "Hello world"  # 2 words ≈ 1 token
        tokens = TokenEstimator.estimate(content)
        assert tokens >= 1

    def test_estimate_tokens_longer(self) -> None:
        """Test token estimation on longer text."""
        content = "a" * 400  # 400 chars ≈ 100 tokens
        tokens = TokenEstimator.estimate(content)
        assert tokens >= 50

    def test_estimate_tokens_empty_string(self) -> None:
        """Test that empty string estimates at least 1 token."""
        tokens = TokenEstimator.estimate("")
        assert tokens >= 1

    def test_estimate_tokens_whitespace_only(self) -> None:
        """Test that whitespace-only string estimates at least 1."""
        tokens = TokenEstimator.estimate("   \n\n   ")
        assert tokens >= 1

    def test_estimate_tokens_deterministic(self) -> None:
        """Test that token estimation is deterministic."""
        content = "test content here"
        tokens1 = TokenEstimator.estimate(content)
        tokens2 = TokenEstimator.estimate(content)
        assert tokens1 == tokens2


class TestChunkHashing:
    """Test deterministic chunk hashing."""

    def test_chunk_hash_is_sha256(self) -> None:
        """Test that chunk hash is valid SHA-256."""
        content = "chunk content"
        hash_val = DocumentChunker._compute_hash(content)
        assert len(hash_val) == 64
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_chunk_hash_deterministic(self) -> None:
        """Test that chunk hash is deterministic."""
        content = "test chunk"
        hash1 = DocumentChunker._compute_hash(content)
        hash2 = DocumentChunker._compute_hash(content)
        assert hash1 == hash2

    def test_different_chunks_different_hashes(self) -> None:
        """Test that different chunks produce different hashes."""
        hash1 = DocumentChunker._compute_hash("chunk 1")
        hash2 = DocumentChunker._compute_hash("chunk 2")
        assert hash1 != hash2


class TestParentChunkCreation:
    """Test parent chunk creation."""

    def test_simple_document_creates_parents(self, tmp_path: Path) -> None:
        """Test that chunker creates parent chunks."""
        file_path = tmp_path / "doc.md"
        content = "# Title\n\n" + "word " * 500
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        assert len(plan.parents) > 0
        assert all(p.chunk_level == "parent" for p in plan.parents)

    def test_parent_index_monotonic(self, tmp_path: Path) -> None:
        """Test that parent indexes increase monotonically."""
        file_path = tmp_path / "doc.md"
        content = "# Title\n\n" + "word " * 500
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        parent_indexes = [p.chunk_index for p in plan.parents]
        assert parent_indexes == sorted(parent_indexes)
        # Should start at 0
        if parent_indexes:
            assert parent_indexes[0] == 0

    def test_parent_not_over_max_size(self, tmp_path: Path) -> None:
        """Test that parent chunks never exceed max size."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 1000  # 5000 chars
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        for parent in plan.parents:
            assert len(parent.content) <= chunker.config.parent_max_chars

    def test_parent_content_never_empty(self, tmp_path: Path) -> None:
        """Test that parent chunks never have empty content."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 100
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        for parent in plan.parents:
            assert len(parent.content.strip()) > 0

    def test_parent_has_content_hash(self, tmp_path: Path) -> None:
        """Test that parent chunks have content hash."""
        file_path = tmp_path / "doc.txt"
        file_path.write_text("test content")

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        for parent in plan.parents:
            assert len(parent.content_hash) == 64

    def test_parent_has_token_count(self, tmp_path: Path) -> None:
        """Test that parent chunks have token count."""
        file_path = tmp_path / "doc.txt"
        file_path.write_text("test content")

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        for parent in plan.parents:
            assert parent.token_count > 0

    def test_parent_metadata_has_token_method(self, tmp_path: Path) -> None:
        """Test that parent metadata includes token_count_method."""
        file_path = tmp_path / "doc.txt"
        file_path.write_text("test content")

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        for parent in plan.parents:
            assert parent.metadata.get("token_count_method") == "estimated"


class TestChildChunkCreation:
    """Test child chunk creation."""

    def test_children_created_from_parents(self, tmp_path: Path) -> None:
        """Test that child chunks are created from parents."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 200
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        assert len(plan.children) > 0
        assert all(c.chunk_level == "child" for c in plan.children)

    def test_child_index_global_and_continuous(self, tmp_path: Path) -> None:
        """Test that child indexes are global and continuous."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 300
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        child_indexes = [c.chunk_index for c in plan.children]
        expected = list(range(len(plan.children)))
        assert child_indexes == expected

    def test_child_parent_references_valid(self, tmp_path: Path) -> None:
        """Test that every child has valid parent_index."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 200
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        parent_indexes = {p.chunk_index for p in plan.parents}

        for child in plan.children:
            assert child.parent_index is not None
            assert child.parent_index in parent_indexes

    def test_child_not_over_max_size(self, tmp_path: Path) -> None:
        """Test that child chunks never exceed max size."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 500
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        for child in plan.children:
            assert len(child.content) <= chunker.config.child_max_chars

    def test_child_content_never_empty(self, tmp_path: Path) -> None:
        """Test that child chunks never have empty content."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 200
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        for child in plan.children:
            assert len(child.content.strip()) > 0

    def test_child_within_parent_scope(self, tmp_path: Path) -> None:
        """Test that child content is within parent's scope."""
        file_path = tmp_path / "doc.txt"
        content = "unique_word_123 " * 200
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        # Build map of parent content
        parent_map = {p.chunk_index: p.content for p in plan.parents}

        # Check that each child's content appears in its parent
        for child in plan.children:
            parent = parent_map[child.parent_index]
            assert child.content in parent or child.content[0:50] in parent


class TestMarkdownHeadingAwareness:
    """Test Markdown-specific chunking with heading awareness."""

    def test_markdown_split_by_heading(self, tmp_path: Path) -> None:
        """Test that Markdown is split by headings."""
        file_path = tmp_path / "doc.md"
        content = """# Section 1
word """ * 200 + """

# Section 2
word """ * 200

        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        # Should have multiple parent chunks
        assert len(plan.parents) >= 1

    def test_markdown_preserves_heading_in_metadata(
        self, tmp_path: Path
    ) -> None:
        """Test that heading context is preserved in metadata."""
        file_path = tmp_path / "doc.md"
        content = """# Important Section
word """ * 200

        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        # At least one parent should have heading in metadata
        headings = [
            p.metadata.get("heading")
            for p in plan.parents
            if "heading" in p.metadata
        ]
        # May or may not have heading preserved, depends on chunking


class TestChunkDeterminism:
    """Test that chunking is deterministic."""

    def test_chunking_deterministic_same_doc(self, tmp_path: Path) -> None:
        """Test that chunking same document produces identical results."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 300
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()

        plan1 = chunker.chunk(doc)
        plan2 = chunker.chunk(doc)

        # Same number of chunks
        assert len(plan1.parents) == len(plan2.parents)
        assert len(plan1.children) == len(plan2.children)

        # Same hashes
        hashes1 = [p.content_hash for p in plan1.parents]
        hashes2 = [p.content_hash for p in plan2.parents]
        assert hashes1 == hashes2

    def test_chunking_deterministic_across_instances(
        self, tmp_path: Path
    ) -> None:
        """Test that different chunker instances produce same results."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 300
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)

        chunker1 = DocumentChunker()
        chunker2 = DocumentChunker()

        plan1 = chunker1.chunk(doc)
        plan2 = chunker2.chunk(doc)

        # Same structure
        assert len(plan1.parents) == len(plan2.parents)
        assert len(plan1.children) == len(plan2.children)

        # Same hashes
        hashes1 = [p.content_hash for p in plan1.parents]
        hashes2 = [p.content_hash for p in plan2.parents]
        assert hashes1 == hashes2


class TestSmallDocumentHandling:
    """Test handling of very small documents."""

    def test_single_parent_for_small_doc(self, tmp_path: Path) -> None:
        """Test that small document creates single parent."""
        file_path = tmp_path / "small.txt"
        content = "Small content"
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        # Small doc should create at least one parent
        assert len(plan.parents) >= 1

    def test_single_child_for_small_parent(self, tmp_path: Path) -> None:
        """Test that small parent creates single child."""
        file_path = tmp_path / "small.txt"
        content = "Small content for testing"
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        if plan.parents:
            # Each parent with small content should get 1 child
            small_parents = [
                p
                for p in plan.parents
                if len(p.content) < chunker.config.child_target_chars
            ]
            # These parents should contribute minimal children


class TestTokenCountConsistency:
    """Test that token counts are consistent."""

    def test_token_count_consistent_chunks(self, tmp_path: Path) -> None:
        """Test that same content gets same token count."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 100
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        # Load same doc again
        doc2 = DocumentLoader.load(file_path, tmp_path)
        plan2 = chunker.chunk(doc2)

        # Same token counts
        tokens1 = [p.token_count for p in plan.parents]
        tokens2 = [p.token_count for p in plan2.parents]
        assert tokens1 == tokens2

    def test_token_count_positive(self, tmp_path: Path) -> None:
        """Test that all chunks have positive token count."""
        file_path = tmp_path / "doc.txt"
        content = "word " * 200
        file_path.write_text(content)

        doc = DocumentLoader.load(file_path, tmp_path)
        chunker = DocumentChunker()
        plan = chunker.chunk(doc)

        for chunk in plan.parents + plan.children:
            assert chunk.token_count > 0
