import os
from unittest.mock import Mock

import pytest
from psycopg.rows import dict_row

from app.retrieval.repository import RetrievalRepository


def make_mock_database(
    *,
    fetchall_result=None,
    fetchone_result=None,
):
    """Create a pool, connection, and cursor mock."""
    mock_pool = Mock()
    mock_connection = Mock()
    mock_cursor = Mock()

    mock_pool.connection.return_value.__enter__ = Mock(
        return_value=mock_connection
    )
    mock_pool.connection.return_value.__exit__ = Mock(
        return_value=None
    )
    mock_connection.cursor.return_value.__enter__ = Mock(
        return_value=mock_cursor
    )
    mock_connection.cursor.return_value.__exit__ = Mock(
        return_value=None
    )
    mock_cursor.fetchall.return_value = (
        [] if fetchall_result is None else fetchall_result
    )
    mock_cursor.fetchone.return_value = fetchone_result

    return mock_pool, mock_connection, mock_cursor


def capture_queries(mock_cursor):
    """Capture SQL and parameters passed to cursor.execute."""
    executed_queries = []

    def capture_execute(query, params=None):
        executed_queries.append(
            {
                "query": query,
                "params": params,
            }
        )

    mock_cursor.execute.side_effect = capture_execute
    return executed_queries


class TestRowFactoryUsage:
    """Verify that repository explicitly uses dict_row factory."""

    def test_vector_search_uses_dict_row_factory(self):
        """Regression: vector_search must request dict_row."""
        mock_pool, mock_connection, _ = make_mock_database()

        repo = RetrievalRepository(mock_pool)
        repo.vector_search(
            [0.1] * 1024,
            candidate_k=40,
        )

        mock_connection.cursor.assert_called()
        call_args = mock_connection.cursor.call_args

        assert call_args is not None
        assert "row_factory" in call_args.kwargs
        assert call_args.kwargs["row_factory"] == dict_row

    def test_full_text_search_uses_dict_row_factory(self):
        """Regression: full_text_search must request dict_row."""
        mock_pool, mock_connection, _ = make_mock_database()

        repo = RetrievalRepository(mock_pool)
        repo.full_text_search(
            "test",
            candidate_k=40,
        )

        mock_connection.cursor.assert_called()
        call_args = mock_connection.cursor.call_args

        assert call_args is not None
        assert "row_factory" in call_args.kwargs
        assert call_args.kwargs["row_factory"] == dict_row

    def test_get_parent_content_uses_dict_row_factory(self):
        """Regression: get_parent_content must request dict_row."""
        mock_pool, mock_connection, _ = make_mock_database()

        repo = RetrievalRepository(mock_pool)
        repo.get_parent_content(["id-1"])

        mock_connection.cursor.assert_called()
        call_args = mock_connection.cursor.call_args

        assert call_args is not None
        assert "row_factory" in call_args.kwargs
        assert call_args.kwargs["row_factory"] == dict_row


class TestParameterization:
    """Verify that all queries use Psycopg parameterization."""

    def test_vector_search_parameterizes_embedding(self):
        """Verify embedding and limit are not interpolated."""
        mock_pool, _, mock_cursor = make_mock_database()
        executed_queries = capture_queries(mock_cursor)

        repo = RetrievalRepository(mock_pool)
        repo.vector_search(
            [0.1] * 1024,
            candidate_k=40,
        )

        assert executed_queries
        query = executed_queries[0]["query"]
        params = executed_queries[0]["params"]

        assert "%(embedding)s::vector" in query
        assert "LIMIT %(candidate_k)s" in query
        assert "$1" not in query
        assert isinstance(params, dict)
        assert "embedding" in params
        assert params["candidate_k"] == 40

    def test_source_types_uses_array_parameter(self):
        """Verify source_types uses a named array parameter."""
        mock_pool, _, mock_cursor = make_mock_database()
        executed_queries = capture_queries(mock_cursor)

        repo = RetrievalRepository(mock_pool)
        repo.vector_search(
            [0.1] * 1024,
            candidate_k=40,
            source_types=["project_document"],
        )

        assert executed_queries
        query = executed_queries[0]["query"]
        params = executed_queries[0]["params"]

        assert "%(source_types)s::text[]" in query
        assert "$" not in query
        assert isinstance(params, dict)
        assert params["source_types"] == [
            "project_document"
        ]

    def test_source_keys_uses_array_parameter(self):
        """Verify source_keys uses a named array parameter."""
        mock_pool, _, mock_cursor = make_mock_database()
        executed_queries = capture_queries(mock_cursor)

        repo = RetrievalRepository(mock_pool)
        repo.vector_search(
            [0.1] * 1024,
            candidate_k=40,
            source_keys=["workspace:doc.md"],
        )

        assert executed_queries
        query = executed_queries[0]["query"]
        params = executed_queries[0]["params"]

        assert "%(source_keys)s::text[]" in query
        assert "$" not in query
        assert isinstance(params, dict)
        assert params["source_keys"] == [
            "workspace:doc.md"
        ]

    def test_full_text_search_parameterizes_query(self):
        """Verify full-text query and limit use named parameters."""
        mock_pool, _, mock_cursor = make_mock_database()
        executed_queries = capture_queries(mock_cursor)

        repo = RetrievalRepository(mock_pool)
        repo.full_text_search(
            "intent gate",
            candidate_k=10,
        )

        assert executed_queries
        query = executed_queries[0]["query"]
        params = executed_queries[0]["params"]

        assert "%(query_text)s" in query
        assert "LIMIT %(candidate_k)s" in query
        assert "$1" not in query
        assert isinstance(params, dict)
        assert params == {
            "query_text": "intent gate",
            "candidate_k": 10,
        }

    def test_get_parent_content_parameterizes_parent_ids(self):
        """Verify parent IDs use a named UUID array parameter."""
        mock_pool, _, mock_cursor = make_mock_database()
        executed_queries = capture_queries(mock_cursor)
        parent_ids = [
            "00000000-0000-0000-0000-000000000001"
        ]

        repo = RetrievalRepository(mock_pool)
        repo.get_parent_content(parent_ids)

        assert executed_queries
        query = executed_queries[0]["query"]
        params = executed_queries[0]["params"]

        assert "%(parent_ids)s::uuid[]" in query
        assert "$1" not in query
        assert params == {"parent_ids": parent_ids}

    def test_verify_parent_source_parameterizes_ids(self):
        """Verify child and parent IDs use named parameters."""
        mock_pool, _, mock_cursor = make_mock_database(
            fetchone_result=(True,)
        )
        executed_queries = capture_queries(mock_cursor)

        repo = RetrievalRepository(mock_pool)
        result = repo.verify_parent_source(
            child_id="child-id",
            parent_id="parent-id",
        )

        assert result is True
        assert executed_queries
        query = executed_queries[0]["query"]
        params = executed_queries[0]["params"]

        assert "%(parent_id)s" in query
        assert "%(child_id)s" in query
        assert "$1" not in query
        assert "$2" not in query
        assert params == {
            "parent_id": "parent-id",
            "child_id": "child-id",
        }


class TestResponseMapping:
    """Verify response values are properly formatted."""

    def test_scores_converted_to_float(self):
        """Verify score fields are converted to float."""
        from app.retrieval.models import SearchRequest
        from app.retrieval.service import RetrievalService

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
        from app.retrieval.models import SearchRequest
        from app.retrieval.service import RetrievalService

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
    reason=(
        "Integration tests skipped by default. Set "
        "RAG_RUN_INTEGRATION_TESTS=1 to run."
    ),
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
            if results:
                result = results[0]
                assert "child_id" in result
                assert "parent_id" in result
                assert "source_id" in result

        finally:
            pool.close()

    def test_live_full_text_search_returns_results(self):
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
            if results:
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

            if text_results:
                parent_ids = [
                    result["parent_id"]
                    for result in text_results
                ]
                parent_map = repo.get_parent_content(
                    parent_ids
                )

                assert isinstance(parent_map, dict)
                if parent_map:
                    parent = next(iter(parent_map.values()))
                    assert "parent_id" in parent
                    assert "content" in parent
                    assert "source_key" in parent
                    assert "title" in parent

        finally:
            pool.close()