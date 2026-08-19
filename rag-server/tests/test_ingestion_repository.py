"""Tests for ingestion repository layer."""

import json
import math
import pytest
from unittest.mock import MagicMock, patch, call

from psycopg.types.json import Jsonb
from psycopg.connection import Connection

from app.ingestion.models import ChunkDraft, LoadedDocument
from app.ingestion.repository import IngestionRepository, SourceUpsertResult


@pytest.fixture
def mock_pool():
    """Create a mock connection pool."""
    return MagicMock()


@pytest.fixture
def mock_cursor():
    """Create a mock cursor."""
    return MagicMock()


@pytest.fixture
def mock_connection():
    """Create a mock connection with cursor."""
    cursor = MagicMock()
    conn = MagicMock(spec=Connection)
    conn.cursor.return_value = cursor
    return conn, cursor


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
            "a" * 64,  # 64-character hash
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

    def test_insert_new_source(self, repository, mock_cursor, sample_document):
        """Test inserting a new source."""
        # Setup mock cursor
        mock_cursor.fetchone.side_effect = [
            ("new-source-id", sample_document.content_hash),
            (1,),  # revision check
        ]

        # Execute - pass cursor directly, not connection
        result = repository.insert_or_update_source(sample_document, mock_cursor)

        # Verify
        assert result.source_id == "new-source-id"
        assert result.action == "inserted"
        assert result.new_hash == sample_document.content_hash

        # Verify Jsonb wrapping was used for metadata
        calls = mock_cursor.execute.call_args_list
        first_call_args = calls[0][0]
        # The metadata should be wrapped with Jsonb
        assert isinstance(calls[0][0][1][-1], Jsonb)

    def test_insert_new_source_with_connection(self, repository, mock_connection, sample_document):
        """Test inserting a new source using Connection object."""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.fetchone.side_effect = [
            ("new-source-id", sample_document.content_hash),
            (1,),  # revision check
        ]

        # Execute - pass connection, should extract cursor
        result = repository.insert_or_update_source(sample_document, mock_conn)

        # Verify
        assert result.source_id == "new-source-id"
        assert result.action == "inserted"
        assert mock_conn.cursor.called  # Should have called cursor() method

    def test_update_existing_source(self, repository, mock_cursor, sample_document):
        """Test updating an existing source."""
        # Setup mock
        mock_cursor.fetchone.side_effect = [
            ("existing-id", sample_document.content_hash),
            (2,),  # revision check (updated)
        ]

        # Execute - pass cursor directly
        result = repository.insert_or_update_source(sample_document, mock_cursor)

        # Verify
        assert result.source_id == "existing-id"
        assert result.action == "updated"

    def test_metadata_wrapped_with_jsonb(self, repository, mock_cursor, sample_document):
        """Test that metadata is wrapped with Jsonb."""
        mock_cursor.fetchone.side_effect = [
            ("source-id", sample_document.content_hash),
            (1,),
        ]

        repository.insert_or_update_source(sample_document, mock_cursor)

        # Verify that Jsonb was used
        call_args = mock_cursor.execute.call_args_list[0]
        params = call_args[0][1]  # Get the parameters tuple
        assert isinstance(params[-1], Jsonb)


class TestParentChunkInsertion:
    """Tests for insert_parent_chunks."""

    def test_insert_multiple_parents(
        self,
        repository,
        mock_cursor,
        sample_parent_chunks,
    ):
        """Test inserting multiple parent chunks."""
        # Setup mock
        mock_cursor.fetchone.side_effect = [
            ("parent-id-0",),
            ("parent-id-1",),
        ]

        # Execute - pass cursor directly
        result = repository.insert_parent_chunks(
            "source-123",
            sample_parent_chunks,
            mock_cursor,
        )

        # Verify
        assert result[0] == "parent-id-0"
        assert result[1] == "parent-id-1"
        assert len(result) == 2

        # Verify Jsonb wrapping was used for metadata
        calls = mock_cursor.execute.call_args_list
        for call_obj in calls:
            params = call_obj[0][1]  # Get the parameters tuple
            # The metadata should be wrapped with Jsonb (last parameter)
            assert isinstance(params[-1], Jsonb)

    def test_insert_parents_with_connection(
        self,
        repository,
        mock_connection,
        sample_parent_chunks,
    ):
        """Test inserting parent chunks using Connection object."""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.fetchone.side_effect = [
            ("parent-id-0",),
            ("parent-id-1",),
        ]

        # Execute - pass connection
        result = repository.insert_parent_chunks(
            "source-123",
            sample_parent_chunks,
            mock_conn,
        )

        # Verify
        assert result[0] == "parent-id-0"
        assert mock_conn.cursor.called  # Should have called cursor() method


class TestChildChunkInsertion:
    """Tests for insert_child_chunks."""

    def test_insert_child_chunks_with_valid_embeddings(
        self,
        repository,
        mock_cursor,
        sample_child_chunks,
    ):
        """Test inserting child chunks with valid embeddings."""
        # Setup mock
        mock_cursor.fetchone.side_effect = [
            ("child-id-0",),
            ("child-id-1",),
        ]

        # Create valid embeddings (1024 dimensions)
        embeddings = {
            0: [0.1] * 1024,
            1: [0.2] * 1024,
        }

        parent_id_map = {0: "parent-id-0"}

        # Execute - pass cursor directly
        repository.insert_child_chunks(
            "source-123",
            sample_child_chunks,
            parent_id_map,
            embeddings,
            mock_cursor,
        )

        # Verify - should not raise exception
        assert mock_cursor.execute.called

        # Verify Jsonb wrapping was used for metadata
        calls = mock_cursor.execute.call_args_list
        for call_obj in calls:
            params = call_obj[0][1]  # Get the parameters tuple
            # The metadata should be wrapped with Jsonb (last parameter)
            assert isinstance(params[-1], Jsonb)

    def test_insert_child_chunks_with_connection(
        self,
        repository,
        mock_connection,
        sample_child_chunks,
    ):
        """Test inserting child chunks using Connection object."""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.fetchone.side_effect = [
            ("child-id-0",),
            ("child-id-1",),
        ]

        embeddings = {
            0: [0.1] * 1024,
            1: [0.2] * 1024,
        }

        parent_id_map = {0: "parent-id-0"}

        # Execute - pass connection
        repository.insert_child_chunks(
            "source-123",
            sample_child_chunks,
            parent_id_map,
            embeddings,
            mock_conn,
        )

        # Verify
        assert mock_conn.cursor.called  # Should have called cursor() method

    def test_insert_child_chunks_with_custom_model(
        self,
        repository,
        mock_cursor,
        sample_child_chunks,
    ):
        """Test inserting child chunks with custom embedding model."""
        # Setup mock
        mock_cursor.fetchone.side_effect = [
            ("child-id-0",),
            ("child-id-1",),
        ]

        embeddings = {
            0: [0.1] * 1024,
            1: [0.2] * 1024,
        }

        parent_id_map = {0: "parent-id-0"}

        # Execute with custom model
        repository.insert_child_chunks(
            "source-123",
            sample_child_chunks,
            parent_id_map,
            embeddings,
            mock_cursor,
            embedding_model="custom-model-v1",
        )

        # Verify model was passed correctly
        calls = mock_cursor.execute.call_args_list
        for call_obj in calls:
            params = call_obj[0][1]
            # The embedding_model should be the custom model (10th parameter: model field)
            assert "custom-model-v1" in params

    def test_invalid_embedding_shape_raises_error(
        self,
        repository,
        mock_cursor,
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
                mock_cursor,
            )


class TestDeleteChunksForSource:
    """Tests for delete_chunks_for_source."""

    def test_delete_chunks(self, repository, mock_cursor):
        """Test deleting all chunks for a source."""
        # Setup mock
        mock_cursor.rowcount = 5

        # Execute - pass cursor directly
        repository.delete_chunks_for_source("source-123", mock_cursor)

        # Verify - should execute without error
        assert mock_cursor.execute.called

    def test_delete_chunks_with_connection(self, repository, mock_connection):
        """Test deleting chunks using Connection object."""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.rowcount = 5

        # Execute - pass connection
        repository.delete_chunks_for_source("source-123", mock_conn)

        # Verify
        assert mock_conn.cursor.called  # Should have called cursor() method


class TestTransactionBoundaryGuarantees:
    """Tests verifying transaction boundary refactoring."""

    def test_write_methods_do_not_call_pool_connection(self, repository, mock_pool, mock_cursor):
        """Test that write methods don't obtain their own pool connection."""
        # Create a sample document
        sample_doc = LoadedDocument(
            source_key="test:doc.md",
            source_type="project_document",
            title="Test",
            source_path="doc.md",
            content="Test content",
            content_hash="a" * 64,
            metadata={},
        )

        mock_cursor.fetchone.side_effect = [
            ("source-id", "a" * 64),
            (1,),
        ]

        # Execute
        repository.insert_or_update_source(sample_doc, mock_cursor)

        # Verify pool.connection was NOT called
        mock_pool.connection.assert_not_called()

    def test_all_write_methods_accept_connection_parameter(self, repository, mock_cursor):
        """Test that all write methods require a connection parameter."""
        import inspect

        write_methods = [
            "insert_or_update_source",
            "delete_chunks_for_source",
            "insert_parent_chunks",
            "insert_child_chunks",
        ]

        for method_name in write_methods:
            method = getattr(repository, method_name)
            sig = inspect.signature(method)
            # Verify 'conn' parameter exists
            assert "conn" in sig.parameters, f"{method_name} missing 'conn' parameter"
