"""Tests for ingestion repository layer."""

import json
import math
import pytest
from unittest.mock import MagicMock, patch

from app.ingestion.models import ChunkDraft, LoadedDocument
from app.ingestion.repository import IngestionRepository, SourceUpsertResult


@pytest.fixture
def mock_pool():
    """Create a mock connection pool."""
    return MagicMock()


@pytest.fixture
def repository(mock_pool):
    """Create a repository with mock pool."""
    return IngestionRepository(mock_pool)


@pytest.fixture
def sample_document():
    """Create a sample document."""
    return LoadedDocument(
        source_key="workspace:README.md",
        source_type="project_document",
        title="README",
        source_path="README.md",
        content="# README\n\nThis is a test document.",
        content_hash="a" * 64,
        metadata={"extension": ".md", "size_bytes": 100},
    )


@pytest.fixture
def sample_parent_chunks():
    """Create sample parent chunks."""
    return [
        ChunkDraft(
            chunk_level="parent",
            chunk_index=0,
            content="Parent chunk 1",
            content_hash="b" * 64,
            token_count=5,
            metadata={"token_count_method": "estimated"},
        ),
        ChunkDraft(
            chunk_level="parent",
            chunk_index=1,
            content="Parent chunk 2",
            content_hash="c" * 64,
            token_count=5,
            metadata={"token_count_method": "estimated"},
        ),
    ]


@pytest.fixture
def sample_child_chunks():
    """Create sample child chunks."""
    return [
        ChunkDraft(
            chunk_level="child",
            chunk_index=0,
            parent_index=0,
            content="Child 1 of parent 0",
            content_hash="d" * 64,
            token_count=5,
            metadata={"token_count_method": "estimated"},
        ),
        ChunkDraft(
            chunk_level="child",
            chunk_index=1,
            parent_index=0,
            content="Child 2 of parent 0",
            content_hash="e" * 64,
            token_count=5,
            metadata={"token_count_method": "estimated"},
        ),
    ]


class TestQuerySourceByKey:
    """Tests for query_source_by_key."""

    def test_source_found(self, repository, mock_pool):
        """Test finding an existing source."""
        # Setup mock
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (
            "source-id-123",
            "hash1234567890" * 4,
        )

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool.connection.return_value.__enter__.return_value = mock_conn

        # Execute
        result = repository.query_source_by_key("workspace:README.md")

        # Verify
        assert result is not None
        assert result[0] == "source-id-123"
        assert len(result[1]) == 64

    def test_source_not_found(self, repository, mock_pool):
        """Test when source does not exist."""
        # Setup mock
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool.connection.return_value.__enter__.return_value = mock_conn

        # Execute
        result = repository.query_source_by_key("workspace:nonexistent.md")

        # Verify
        assert result is None


class TestInsertOrUpdateSource:
    """Tests for insert_or_update_source."""

    def test_insert_new_source(self, repository, mock_pool, sample_document):
        """Test inserting a new source."""
        # Setup mock
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("new-source-id", sample_document.content_hash),
            (1,),  # revision check
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool.connection.return_value.__enter__.return_value = mock_conn

        # Execute
        result = repository.insert_or_update_source(sample_document)

        # Verify
        assert result.source_id == "new-source-id"
        assert result.action == "inserted"
        assert result.new_hash == sample_document.content_hash

    def test_update_existing_source(self, repository, mock_pool, sample_document):
        """Test updating an existing source."""
        # Setup mock
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("existing-id", sample_document.content_hash),
            (2,),  # revision check (updated)
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool.connection.return_value.__enter__.return_value = mock_conn

        # Execute
        result = repository.insert_or_update_source(sample_document)

        # Verify
        assert result.source_id == "existing-id"
        assert result.action == "updated"


class TestParentChunkInsertion:
    """Tests for insert_parent_chunks."""

    def test_insert_multiple_parents(
        self,
        repository,
        mock_pool,
        sample_parent_chunks,
    ):
        """Test inserting multiple parent chunks."""
        # Setup mock
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("parent-id-0",),
            ("parent-id-1",),
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool.connection.return_value.__enter__.return_value = mock_conn

        # Execute
        result = repository.insert_parent_chunks(
            "source-123",
            sample_parent_chunks,
        )

        # Verify
        assert result[0] == "parent-id-0"
        assert result[1] == "parent-id-1"
        assert len(result) == 2


class TestChildChunkInsertion:
    """Tests for insert_child_chunks."""

    def test_insert_child_chunks_with_valid_embeddings(
        self,
        repository,
        mock_pool,
        sample_child_chunks,
    ):
        """Test inserting child chunks with valid embeddings."""
        # Setup mock
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("child-id-0",),
            ("child-id-1",),
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool.connection.return_value.__enter__.return_value = mock_conn

        # Create valid embeddings (1024 dimensions)
        embeddings = {
            0: [0.1] * 1024,
            1: [0.2] * 1024,
        }

        parent_id_map = {0: "parent-id-0"}

        # Execute
        repository.insert_child_chunks(
            "source-123",
            sample_child_chunks,
            parent_id_map,
            embeddings,
        )

        # Verify - should not raise exception
        assert mock_cursor.execute.called

    def test_invalid_embedding_shape_raises_error(
        self,
        repository,
        sample_child_chunks,
    ):
        """Test that invalid embedding shape raises error."""
        # Create invalid embeddings (wrong dimension)
        embeddings = {
            0: [0.1] * 512,  # Wrong: should be 1024
        }

        parent_id_map = {0: "parent-id-0"}

        # Execute & Verify
        with pytest.raises(Exception):  # RepositoryError
            repository.insert_child_chunks(
                "source-123",
                sample_child_chunks,
                parent_id_map,
                embeddings,
            )


class TestDeleteChunksForSource:
    """Tests for delete_chunks_for_source."""

    def test_delete_chunks(self, repository, mock_pool):
        """Test deleting all chunks for a source."""
        # Setup mock
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool.connection.return_value.__enter__.return_value = mock_conn

        # Execute
        repository.delete_chunks_for_source("source-123")

        # Verify - should execute without error
        assert mock_cursor.execute.called
