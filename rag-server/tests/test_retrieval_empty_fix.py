import pytest
from unittest.mock import Mock
import uuid

from app.retrieval.repository import RetrievalRepository
from app.retrieval.service import RetrievalService
from app.retrieval.models import SearchRequest
from app.embedding import EmbeddingResult


class TestUUIDNormalization:
    """Verify UUID handling consistency throughout pipeline."""

    def test_vector_search_normalizes_uuids_to_string(
        self,
    ):
        """Vector search returns UUIDs as strings, not uuid.UUID objects."""
        test_uuid = str(uuid.uuid4())
        parent_uuid = str(uuid.uuid4())
        source_uuid = str(uuid.uuid4())

        mock_pool = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()

        mock_pool.connection.return_value.__enter__ = (
            Mock(return_value=mock_connection)
        )
        mock_pool.connection.return_value.__exit__ = (
            Mock(return_value=None)
        )
        mock_connection.cursor.return_value.__enter__ = (
            Mock(return_value=mock_cursor)
        )
        mock_connection.cursor.return_value.__exit__ = (
            Mock(return_value=None)
        )

        from psycopg.rows import dict_row

        mock_cursor.fetchall.return_value = [
            {
                "child_id": uuid.UUID(test_uuid),
                "parent_id": uuid.UUID(parent_uuid),
                "source_id": uuid.UUID(source_uuid),
                "similarity": 0.95,
                "vector_rank": 1,
            }
        ]

        repo = RetrievalRepository(mock_pool)
        results = repo.vector_search(
            [0.1] * 1024,
            candidate_k=40,
        )

        assert len(results) == 1
        assert isinstance(results[0]["child_id"], str)
        assert isinstance(results[0]["parent_id"], str)
        assert isinstance(results[0]["source_id"], str)
        assert results[0]["child_id"] == test_uuid
        assert results[0]["parent_id"] == parent_uuid
        assert results[0]["source_id"] == source_uuid

    def test_full_text_search_normalizes_uuids_to_string(
        self,
    ):
        """Full-text search returns UUIDs as strings."""
        test_uuid = str(uuid.uuid4())
        parent_uuid = str(uuid.uuid4())
        source_uuid = str(uuid.uuid4())

        mock_pool = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()

        mock_pool.connection.return_value.__enter__ = (
            Mock(return_value=mock_connection)
        )
        mock_pool.connection.return_value.__exit__ = (
            Mock(return_value=None)
        )
        mock_connection.cursor.return_value.__enter__ = (
            Mock(return_value=mock_cursor)
        )
        mock_connection.cursor.return_value.__exit__ = (
            Mock(return_value=None)
        )

        mock_cursor.fetchall.return_value = [
            {
                "child_id": uuid.UUID(test_uuid),
                "parent_id": uuid.UUID(parent_uuid),
                "source_id": uuid.UUID(source_uuid),
                "text_rank": 0.5,
                "text_rank_position": 1,
            }
        ]

        repo = RetrievalRepository(mock_pool)
        results = repo.full_text_search(
            "test",
            candidate_k=40,
        )

        assert len(results) == 1
        assert isinstance(results[0]["child_id"], str)
        assert isinstance(results[0]["parent_id"], str)
        assert isinstance(results[0]["source_id"], str)

    def test_parent_hydration_normalizes_uuids(self):
        """Parent hydration returns UUIDs as strings in both keys and values."""
        parent_uuid = str(uuid.uuid4())
        source_uuid = str(uuid.uuid4())

        mock_pool = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()

        mock_pool.connection.return_value.__enter__ = (
            Mock(return_value=mock_connection)
        )
        mock_pool.connection.return_value.__exit__ = (
            Mock(return_value=None)
        )
        mock_connection.cursor.return_value.__enter__ = (
            Mock(return_value=mock_cursor)
        )
        mock_connection.cursor.return_value.__exit__ = (
            Mock(return_value=None)
        )

        mock_cursor.fetchall.return_value = [
            {
                "parent_id": uuid.UUID(parent_uuid),
                "parent_chunk_index": 0,
                "content": "Test content",
                "source_key": "workspace:test.md",
                "source_type": "project_document",
                "title": "Test",
                "source_id": uuid.UUID(source_uuid),
            }
        ]

        repo = RetrievalRepository(mock_pool)
        result_map = repo.get_parent_content(
            [parent_uuid]
        )

        assert len(result_map) == 1
        assert parent_uuid in result_map
        parent = result_map[parent_uuid]
        assert isinstance(parent["parent_id"], str)
        assert isinstance(parent["source_id"], str)
        assert parent["parent_id"] == parent_uuid
        assert parent["source_id"] == source_uuid


class TestExceptionHandling:
    """Verify exceptions propagate instead of returning empty results."""

    def test_vector_search_raises_on_database_error(
        self,
    ):
        """Vector search raises exception on database error."""
        mock_pool = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()

        mock_pool.connection.return_value.__enter__ = (
            Mock(return_value=mock_connection)
        )
        mock_pool.connection.return_value.__exit__ = (
            Mock(return_value=None)
        )
        mock_connection.cursor.return_value.__enter__ = (
            Mock(return_value=mock_cursor)
        )
        mock_connection.cursor.return_value.__exit__ = (
            Mock(return_value=None)
        )

        mock_cursor.execute.side_effect = (
            RuntimeError("Database error")
        )

        repo = RetrievalRepository(mock_pool)

        with pytest.raises(RuntimeError):
            repo.vector_search(
                [0.1] * 1024,
                candidate_k=40,
            )

    def test_full_text_search_raises_on_database_error(
        self,
    ):
        """Full-text search raises exception on database error."""
        mock_pool = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()

        mock_pool.connection.return_value.__enter__ = (
            Mock(return_value=mock_connection)
        )
        mock_pool.connection.return_value.__exit__ = (
            Mock(return_value=None)
        )
        mock_connection.cursor.return_value.__enter__ = (
            Mock(return_value=mock_cursor)
        )
        mock_connection.cursor.return_value.__exit__ = (
            Mock(return_value=None)
        )

        mock_cursor.execute.side_effect = (
            RuntimeError("Database error")
        )

        repo = RetrievalRepository(mock_pool)

        with pytest.raises(RuntimeError):
            repo.full_text_search(
                "test",
                candidate_k=40,
            )

    def test_parent_hydration_raises_on_database_error(
        self,
    ):
        """Parent hydration raises exception on database error."""
        mock_pool = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()

        mock_pool.connection.return_value.__enter__ = (
            Mock(return_value=mock_connection)
        )
        mock_pool.connection.return_value.__exit__ = (
            Mock(return_value=None)
        )
        mock_connection.cursor.return_value.__enter__ = (
            Mock(return_value=mock_cursor)
        )
        mock_connection.cursor.return_value.__exit__ = (
            Mock(return_value=None)
        )

        mock_cursor.execute.side_effect = (
            RuntimeError("Database error")
        )

        repo = RetrievalRepository(mock_pool)

        with pytest.raises(RuntimeError):
            repo.get_parent_content(
                ["id-1"]
            )


class TestPipelineDataPreservation:
    """Verify data is not lost through pipeline."""

    def test_candidates_preserved_through_fusion(
        self,
    ):
        """All candidates are preserved through RRF fusion."""
        parent_uuid = str(uuid.uuid4())
        source_uuid = str(uuid.uuid4())

        mock_pool = Mock()
        mock_embedding_service = Mock()

        embedding_result = Mock()
        embedding_result.embeddings = [[0.1] * 1024]
        embedding_result.model = "BAAI/bge-m3"
        embedding_result.elapsed_ms = 10.5

        mock_embedding_service.encode.return_value = (
            embedding_result
        )
        mock_embedding_service._settings = Mock()
        mock_embedding_service._settings.embedding_model = (
            "BAAI/bge-m3"
        )
        mock_embedding_service._settings.embedding_dimension = (
            1024
        )

        vector_candidates = [
            {
                "child_id": str(uuid.uuid4()),
                "parent_id": parent_uuid,
                "source_id": source_uuid,
                "similarity": 0.95,
                "vector_rank": 1,
            }
        ]

        text_candidates = [
            {
                "child_id": str(uuid.uuid4()),
                "parent_id": parent_uuid,
                "source_id": source_uuid,
                "text_rank": 0.5,
                "text_rank_position": 1,
            }
        ]

        repo = Mock()
        repo.vector_search.return_value = (
            vector_candidates
        )
        repo.full_text_search.return_value = (
            text_candidates
        )
        repo.get_parent_content.return_value = {
            parent_uuid: {
                "parent_id": parent_uuid,
                "parent_chunk_index": 0,
                "content": "Test",
                "source_key": "workspace:test.md",
                "source_type": "project_document",
                "title": "Test",
                "source_id": source_uuid,
            }
        }

        service = RetrievalService(
            mock_pool,
            mock_embedding_service,
        )
        service._repo = repo

        request = SearchRequest(
            query="test",
            top_k=5,
        )

        response = service.search(request)

        assert response.result_count > 0
        assert len(response.results) > 0


@pytest.mark.skipif(
    not __import__("os").getenv(
        "RAG_RUN_INTEGRATION_TESTS"
    ),
    reason="Integration tests skipped by default. Set RAG_RUN_INTEGRATION_TESTS=1 to run.",
)
class TestLiveEmptyFixValidation:
    """Live integration test for empty result fix."""

    def test_search_returns_results_for_intent_gate(
        self,
    ):
        """Live test: search returns results for 'intent gate' query."""
        from app.config import Settings
        from app.database import create_pool
        from app.embedding import EmbeddingService

        settings = Settings.from_env()
        pool = create_pool(settings)
        pool.open()

        try:
            embedding_service = EmbeddingService(
                settings
            )
            repo = RetrievalRepository(pool)

            embedding_result = (
                embedding_service.encode(
                    ["intent gate"]
                )
            )

            vector_candidates = repo.vector_search(
                embedding_result.embeddings[0],
                candidate_k=40,
            )

            text_candidates = repo.full_text_search(
                "intent gate",
                candidate_k=40,
            )

            assert (
                len(vector_candidates) > 0
                or len(text_candidates) > 0
            ), (
                f"No candidates found: "
                f"vector={len(vector_candidates)} "
                f"text={len(text_candidates)}"
            )

            service = RetrievalService(
                pool,
                embedding_service,
            )

            request = SearchRequest(
                query="intent gate",
                top_k=5,
                candidate_k=40,
            )

            response = service.search(request)

            assert response.result_count > 0, (
                f"No results returned: "
                f"vector_candidates={len(vector_candidates)} "
                f"text_candidates={len(text_candidates)}"
            )

        finally:
            pool.close()

    def test_search_with_source_key_filter_returns_results(
        self,
    ):
        """Live test: search with source_keys filter returns results."""
        from app.config import Settings
        from app.database import create_pool
        from app.embedding import EmbeddingService

        settings = Settings.from_env()
        pool = create_pool(settings)
        pool.open()

        try:
            embedding_service = EmbeddingService(
                settings
            )
            repo = RetrievalRepository(pool)

            embedding_result = (
                embedding_service.encode(
                    ["intent gate"]
                )
            )

            vector_candidates = repo.vector_search(
                embedding_result.embeddings[0],
                candidate_k=40,
                source_keys=[
                    "workspace:CLAUDE.md"
                ],
            )

            text_candidates = repo.full_text_search(
                "intent gate",
                candidate_k=40,
                source_keys=[
                    "workspace:CLAUDE.md"
                ],
            )

            assert (
                len(vector_candidates) > 0
                or len(text_candidates) > 0
            ), (
                f"No candidates for source_keys filter: "
                f"vector={len(vector_candidates)} "
                f"text={len(text_candidates)}"
            )

            service = RetrievalService(
                pool,
                embedding_service,
            )

            request = SearchRequest(
                query="intent gate",
                top_k=5,
                candidate_k=40,
                source_keys=[
                    "workspace:CLAUDE.md"
                ],
            )

            response = service.search(request)

            assert response.result_count > 0, (
                f"No results with source_keys filter: "
                f"vector_candidates={len(vector_candidates)} "
                f"text_candidates={len(text_candidates)}"
            )

            for result in response.results:
                assert (
                    result.source_key
                    == "workspace:CLAUDE.md"
                )

        finally:
            pool.close()
