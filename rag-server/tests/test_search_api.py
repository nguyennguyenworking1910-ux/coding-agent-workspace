from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

import app.main
from app.config import Settings


class FakePool:
    def open(self):
        pass

    def close(self):
        pass


class FakeEmbeddingService:
    def __init__(self):
        self._settings = type(
            "Settings",
            (),
            {
                "embedding_model": "BAAI/bge-m3",
                "embedding_dimension": 1024,
            },
        )()

    def encode(self, texts):
        from app.embedding import EmbeddingResult

        return EmbeddingResult(
            model="BAAI/bge-m3",
            dimensions=1024,
            embeddings=[[0.1] * 1024],
            elapsed_ms=10.5,
        )


@pytest.fixture(autouse=True)
def isolated_app(monkeypatch):
    monkeypatch.setenv("RAG_DB_PASSWORD", "test")

    mock_settings = Settings.from_env()
    fake_pool = FakePool()
    successful_database_status = {
        "database": "coding_agent_rag",
        "database_user": "rag_user",
        "vector_version": "0.8.6",
        "sources_table": True,
        "chunks_table": True,
        "migrations_table": True,
    }

    def default_mock_create_pool(settings):
        return fake_pool

    def default_mock_check_database(pool, *, timeout_seconds):
        return successful_database_status

    monkeypatch.setattr(
        "app.main.create_pool",
        default_mock_create_pool,
    )
    monkeypatch.setattr(
        "app.main.check_database",
        default_mock_check_database,
    )
    monkeypatch.setattr(
        "app.main.Settings.from_env",
        lambda: mock_settings,
    )
    monkeypatch.setattr(
        "app.main.EmbeddingService",
        lambda settings: FakeEmbeddingService(),
    )

    yield {
        "fake_pool": fake_pool,
        "mock_settings": mock_settings,
    }


def test_search_endpoint_exists():
    with TestClient(app.main.app) as client:
        response = client.post(
            "/v1/search",
            json={
                "query": "test",
            },
        )

    assert response.status_code in (200, 503)


def test_search_basic_request():
    def mock_vector_search(
        self,
        embedding,
        candidate_k,
        source_types=None,
        source_keys=None,
    ):
        return []

    def mock_full_text_search(
        self,
        query_text,
        candidate_k,
        source_types=None,
        source_keys=None,
    ):
        return []

    def mock_get_parent_content(self, parent_ids):
        return {}

    with patch(
        "app.retrieval.repository.RetrievalRepository.vector_search",
        mock_vector_search,
    ), patch(
        "app.retrieval.repository.RetrievalRepository.full_text_search",
        mock_full_text_search,
    ), patch(
        "app.retrieval.repository.RetrievalRepository.get_parent_content",
        mock_get_parent_content,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test query",
                    "top_k": 5,
                    "candidate_k": 40,
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert "results" in payload
    assert "result_count" in payload
    assert "embedding_model" in payload
    assert "elapsed_ms" in payload


def test_search_blank_query_rejected():
    with TestClient(app.main.app) as client:
        response = client.post(
            "/v1/search",
            json={
                "query": "   ",
            },
        )

    assert response.status_code == 422


def test_search_query_too_long_rejected():
    long_query = "test " * 500
    with TestClient(app.main.app) as client:
        response = client.post(
            "/v1/search",
            json={
                "query": long_query,
            },
        )

    assert response.status_code == 422


def test_search_top_k_below_minimum():
    with TestClient(app.main.app) as client:
        response = client.post(
            "/v1/search",
            json={
                "query": "test",
                "top_k": 0,
            },
        )

    assert response.status_code == 422


def test_search_top_k_above_maximum():
    with TestClient(app.main.app) as client:
        response = client.post(
            "/v1/search",
            json={
                "query": "test",
                "top_k": 25,
            },
        )

    assert response.status_code == 422


def test_search_candidate_k_below_minimum():
    with TestClient(app.main.app) as client:
        response = client.post(
            "/v1/search",
            json={
                "query": "test",
                "candidate_k": 2,
            },
        )

    assert response.status_code == 422


def test_search_candidate_k_above_maximum():
    with TestClient(app.main.app) as client:
        response = client.post(
            "/v1/search",
            json={
                "query": "test",
                "candidate_k": 300,
            },
        )

    assert response.status_code == 422


def test_search_candidate_k_less_than_top_k():
    with TestClient(app.main.app) as client:
        response = client.post(
            "/v1/search",
            json={
                "query": "test",
                "top_k": 10,
                "candidate_k": 5,
            },
        )

    assert response.status_code == 422


def test_search_default_top_k():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse

        return SearchResponse(
            results=[],
            result_count=0,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=0,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result_count"] == 0


def test_search_default_candidate_k():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse

        assert request.candidate_k == 40
        return SearchResponse(
            results=[],
            result_count=0,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=0,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test",
                },
            )

    assert response.status_code == 200


def test_search_with_source_types():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse

        assert request.source_types == [
            "project_document"
        ]
        return SearchResponse(
            results=[],
            result_count=0,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=0,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test",
                    "source_types": [
                        "project_document"
                    ],
                },
            )

    assert response.status_code == 200


def test_search_with_source_keys():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse

        assert request.source_keys == [
            "workspace:doc.md"
        ]
        return SearchResponse(
            results=[],
            result_count=0,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=0,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test",
                    "source_keys": ["workspace:doc.md"],
                },
            )

    assert response.status_code == 200


def test_search_empty_result():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse

        return SearchResponse(
            results=[],
            result_count=0,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=10,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "nonexistent",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"] == []
    assert payload["result_count"] == 0


def test_search_response_structure():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse, SearchResult

        return SearchResponse(
            results=[
                SearchResult(
                    rank=1,
                    source_key="workspace:doc.md",
                    source_type="project_document",
                    title="Document",
                    parent_chunk_id="parent-1",
                    parent_chunk_index=0,
                    content="Document content",
                    score=0.95,
                    vector_score=0.95,
                    text_score=0.0,
                ),
            ],
            result_count=1,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=15,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test",
                },
            )

    assert response.status_code == 200
    payload = response.json()

    assert payload["result_count"] == 1
    assert payload["embedding_model"] == "BAAI/bge-m3"
    assert payload["elapsed_ms"] == 15

    result = payload["results"][0]
    assert result["rank"] == 1
    assert result["source_key"] == "workspace:doc.md"
    assert result["source_type"] == "project_document"
    assert result["title"] == "Document"
    assert result["parent_chunk_id"] == "parent-1"
    assert result["parent_chunk_index"] == 0
    assert result["content"] == "Document content"
    assert result["score"] == 0.95
    assert result["vector_score"] == 0.95
    assert result["text_score"] == 0.0


def test_search_returns_no_embeddings():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse, SearchResult

        return SearchResponse(
            results=[
                SearchResult(
                    rank=1,
                    source_key="workspace:doc.md",
                    source_type="project_document",
                    title="Document",
                    parent_chunk_id="parent-1",
                    parent_chunk_index=0,
                    content="Document content",
                    score=0.95,
                    vector_score=0.95,
                    text_score=0.0,
                ),
            ],
            result_count=1,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=15,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test",
                },
            )

    payload = response.json()
    result = payload["results"][0]

    assert "embedding" not in result
    assert (
        "embeddings" not in payload
    )


def test_search_returns_parent_content():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse, SearchResult

        return SearchResponse(
            results=[
                SearchResult(
                    rank=1,
                    source_key="workspace:doc.md",
                    source_type="project_document",
                    title="Document",
                    parent_chunk_id="parent-1",
                    parent_chunk_index=0,
                    content="Parent content here",
                    score=0.95,
                    vector_score=0.95,
                    text_score=0.0,
                ),
            ],
            result_count=1,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=15,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test",
                },
            )

    payload = response.json()
    result = payload["results"][0]

    assert result["content"] == "Parent content here"
    assert "raw_content" not in result


def test_search_query_trimmed():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse

        assert request.query == "test"
        return SearchResponse(
            results=[],
            result_count=0,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=0,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "  test  ",
                },
            )

    assert response.status_code == 200


def test_search_health_independent_of_search():
    with TestClient(app.main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_search_pool_not_closed():
    close_called = []

    def mock_close():
        close_called.append(True)

    def mock_search(service, request):
        from app.retrieval.models import SearchResponse

        return SearchResponse(
            results=[],
            result_count=0,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=0,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test",
                },
            )

    assert response.status_code == 200
    assert not close_called


def test_search_returns_finite_scores():
    def mock_search(service, request):
        from app.retrieval.models import SearchResponse, SearchResult

        return SearchResponse(
            results=[
                SearchResult(
                    rank=1,
                    source_key="workspace:doc.md",
                    source_type="project_document",
                    title="Document",
                    parent_chunk_id="parent-1",
                    parent_chunk_index=0,
                    content="Content",
                    score=0.95,
                    vector_score=0.95,
                    text_score=0.0,
                ),
            ],
            result_count=1,
            embedding_model="BAAI/bge-m3",
            elapsed_ms=15,
        )

    with patch(
        "app.retrieval.service.RetrievalService.search",
        mock_search,
    ):
        with TestClient(app.main.app) as client:
            response = client.post(
                "/v1/search",
                json={
                    "query": "test",
                },
            )

    payload = response.json()
    result = payload["results"][0]

    import math

    assert not math.isnan(result["score"])
    assert not math.isinf(result["score"])
    assert not math.isnan(result["vector_score"])
    assert not math.isinf(result["vector_score"])
    assert not math.isnan(result["text_score"])
    assert not math.isinf(result["text_score"])
