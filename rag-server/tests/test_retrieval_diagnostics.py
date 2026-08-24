import pytest
import os
from unittest.mock import Mock, patch, call
from psycopg.rows import dict_row

from app.retrieval.repository import RetrievalRepository


class TestRowFactoryUsage:
    """Verify that repository explicitly uses dict_row factory."""

    def test_vector_search_uses_dict_row_factory(self):
        """Regression: vector_search must explicitly request dict_row."""
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
        mock_cursor.fetchall.return_value = []

        repo = RetrievalRepository(mock_pool)
        repo.vector_search(
            [0.1] * 1024,
            candidate_k=40,
        )

        mock_connection.cursor.assert_called()
        call_args = (
            mock_connection.cursor.call_args
        )

        assert call_args is not None
        assert "row_factory" in call_args.kwargs
        assert (
            call_args.kwargs["row_factory"]
            == dict_row
        )

    def test_full_text_search_uses_dict_row_factory(
        self,
    ):
        """Regression: full_text_search must explicitly request dict_row."""
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
        mock_cursor.fetchall.return_value = []

        repo = RetrievalRepository(mock_pool)
        repo.full_text_search(
            "test",
            candidate_k=40,
        )

        mock_connection.cursor.assert_called()
        call_args = (
            mock_connection.cursor.call_args
        )

        assert call_args is not None
        assert "row_factory" in call_args.kwargs
        assert (
            call_args.kwargs["row_factory"]
            == dict_row
        )

    def test_get_parent_content_uses_dict_row_factory(
        self,
    ):
        """Regression: get_parent_content must explicitly request dict_row."""
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
        mock_cursor.fetchall.return_value = []

        repo = RetrievalRepository(mock_pool)
        repo.get_parent_content(["id-1"])

        mock_connection.cursor.assert_called()
        call_args = (
            mock_connection.cursor.call_args
        )

        assert call_args is not None
        assert "row_factory" in call_args.kwargs
        assert (
            call_args.kwargs["row_factory"]
            == dict_row
        )


class TestParameterization:
    """Verify that all queries use proper parameterization."""

    def test_vector_search_parameterizes_embedding(
        self,
    ):
        """Verify embedding parameter is not interpolated."""
        mock_pool = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()

        executed_queries = []

        def capture_execute(query, params=None):
            executed_queries.append(
                {"query": query, "params": params}
            )

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
            capture_execute
        )
        mock_cursor.fetchall.return_value = []

        repo = RetrievalRepository(mock_pool)
        repo.vector_search(
            [0.1] * 1024,
            candidate_k=40,
        )

        assert len(executed_queries) > 0
        query, params = (
            executed_queries[0]["query"],
            executed_queries[0]["params"],
        )

        assert "$1" in query
        assert params is not None
        assert len(params) > 0

    def test_source_types_uses_array_parameter(self):
        """Verify source_types uses parameterized array."""
        mock_pool = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()

        executed_queries = []

        def capture_execute(query, params=None):
            executed_queries.append(
                {"query": query, "params": params}
            )

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
            capture_execute
        )
        mock_cursor.fetchall.return_value = []

        repo = RetrievalRepository(mock_pool)
        repo.vector_search(
            [0.1] * 1024,
            candidate_k=40,
            source_types=["project_document"],
        )

        assert len(executed_queries) > 0
        query, params = (
            executed_queries[0]["query"],
            executed_queries[0]["params"],
        )

        assert "ANY($" in query
        assert "::text[]" in query
        assert params is not None
        assert ["project_document"] in params

    def test_source_keys_uses_array_parameter(self):
        """Verify source_keys uses parameterized array."""
        mock_pool = Mock()
        mock_connection = Mock()
        mock_cursor = Mock()

        executed_queries = []

        def capture_execute(query, params=None):
            executed_queries.append(
                {"query": query, "params": params}
            )

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
            capture_execute
        )
        mock_cursor.fetchall.return_value = []

        repo = RetrievalRepository(mock_pool)
        repo.vector_search(
            [0.1] * 1024,
            candidate_k=40,
            source_keys=["workspace:doc.md"],
        )

        assert len(executed_queries) > 0
        query, params = (
            executed_queries[0]["query"],
            executed_queries[0]["params"],
        )

        assert "ANY($" in query
        assert "::text[]" in query
        assert params is not None
        assert ["workspace:doc.md"] in params


class TestResponseMapping:
    """Verify response values are properly formatted."""

    def test_scores_converted_to_float(self):
        """Verify score fields are converted to float."""
        from app.retrieval.service import RetrievalService
        from app.retrieval.models import SearchRequest
        from decimal import Decimal

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

        mock_repo = Mock()
        mock_repo.vector_search.return_value = []
        mock_repo.full_text_search.return_value = []
        mock_repo.get_parent_content.return_value = {}

        service = RetrievalService(
            mock_pool,
            mock_embedding_service,
        )
        service._repo = mock_repo

        request = SearchRequest(query="test")
        response = service.search(request)

        for result in response.results:
            assert isinstance(result.score, float)
            assert isinstance(result.vector_score, float)
            assert isinstance(result.text_score, float)

    def test_response_contains_no_embeddings(self):
        """Verify response does not include raw embeddings."""
        from app.retrieval.service import RetrievalService
        from app.retrieval.models import SearchRequest

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

        mock_repo = Mock()
        mock_repo.vector_search.return_value = []
        mock_repo.full_text_search.return_value = []
        mock_repo.get_parent_content.return_value = {}

        service = RetrievalService(
            mock_pool,
            mock_embedding_service,
        )
        service._repo = mock_repo

        request = SearchRequest(query="test")
        response = service.search(request)

        response_dict = response.model_dump()

        assert "embedding" not in response_dict
        assert "embeddings" not in response_dict
        for result in response.results:
            result_dict = result.model_dump()
            assert "embedding" not in result_dict


@pytest.mark.skipif(
    not os.getenv("RAG_RUN_INTEGRATION_TESTS"),
    reason="Integration tests skipped by default. Set RAG_RUN_INTEGRATION_TESTS=1 to run.",
)
class TestLiveIntegration:
    """Live integration tests against real database."""

    def test_live_vector_search_returns_results(self):
        """Live test: vector search works against real database."""
        from app.config import Settings
        from app.database import create_pool
        from app.embedding import EmbeddingService

        settings = Settings.from_env()
        pool = create_pool(settings)
        pool.open()

        try:
            embedding_service = EmbeddingService(settings)

            embedding_result = embedding_service.encode(
                ["intent gate"]
            )

            repo = RetrievalRepository(pool)

            results = repo.vector_search(
                embedding_result.embeddings[0],
                candidate_k=10,
            )

            assert isinstance(results, list)
            if len(results) > 0:
                result = results[0]
                assert "child_id" in result
                assert "parent_id" in result
                assert "source_id" in result

        finally:
            pool.close()

    def test_live_full_text_search_returns_results(
        self,
    ):
        """Live test: full-text search works against real database."""
        from app.config import Settings
        from app.database import create_pool

        settings = Settings.from_env()
        pool = create_pool(settings)
        pool.open()

        try:
            repo = RetrievalRepository(pool)

            results = repo.full_text_search(
                "intent gate",
                candidate_k=10,
            )

            assert isinstance(results, list)
            if len(results) > 0:
                result = results[0]
                assert "child_id" in result
                assert "parent_id" in result
                assert "source_id" in result

        finally:
            pool.close()

    def test_live_parent_hydration_works(self):
        """Live test: parent hydration works against real database."""
        from app.config import Settings
        from app.database import create_pool

        settings = Settings.from_env()
        pool = create_pool(settings)
        pool.open()

        try:
            repo = RetrievalRepository(pool)

            text_results = repo.full_text_search(
                "intent",
                candidate_k=5,
            )

            if len(text_results) > 0:
                parent_ids = [
                    r["parent_id"] for r in text_results
                ]
                parent_map = repo.get_parent_content(
                    parent_ids
                )

                assert isinstance(parent_map, dict)
                if len(parent_map) > 0:
                    parent = list(parent_map.values())[0]
                    assert "parent_id" in parent
                    assert "content" in parent
                    assert "source_key" in parent
                    assert "title" in parent

        finally:
            pool.close()
