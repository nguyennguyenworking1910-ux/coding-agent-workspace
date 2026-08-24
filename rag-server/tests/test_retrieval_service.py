import pytest
from unittest.mock import Mock, MagicMock, patch

from app.retrieval.service import RetrievalService, RRF_CONSTANT
from app.retrieval.models import SearchRequest
from app.embedding import EmbeddingResult


class FakeEmbeddingService:
    def __init__(
        self,
        model="BAAI/bge-m3",
    ):
        self._settings = Mock()
        self._settings.embedding_model = model
        self._settings.embedding_dimension = 1024

    def encode(self, texts):
        embedding = [0.1] * 1024
        return EmbeddingResult(
            model=self._settings.embedding_model,
            dimensions=1024,
            embeddings=[embedding],
            elapsed_ms=10.5,
        )


class FakeRepository:
    def __init__(
        self,
        vector_results=None,
        text_results=None,
        parent_map=None,
    ):
        self.vector_results = (
            vector_results or []
        )
        self.text_results = (
            text_results or []
        )
        self.parent_map = parent_map or {}

    def vector_search(
        self,
        embedding,
        candidate_k,
        source_types=None,
        source_keys=None,
    ):
        return self.vector_results

    def full_text_search(
        self,
        query_text,
        candidate_k,
        source_types=None,
        source_keys=None,
    ):
        return self.text_results

    def get_parent_content(self, parent_ids):
        return {
            pid: self.parent_map[pid]
            for pid in parent_ids
            if pid in self.parent_map
        }

    def verify_parent_source(self, child_id, parent_id):
        return True


class FakePool:
    pass


def test_search_basic():
    pool = FakePool()
    embedding_service = FakeEmbeddingService()

    vector_results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "similarity": 0.95,
            "vector_rank": 1,
        },
    ]

    parent_map = {
        "parent-1": {
            "parent_id": "parent-1",
            "parent_chunk_index": 0,
            "content": "Architecture content",
            "source_key": "workspace:.claude/documents/ARCHITECTURE.md",
            "source_type": "project_document",
            "title": "Architecture",
            "source_id": "source-1",
        },
    }

    repo = FakeRepository(
        vector_results=vector_results,
        parent_map=parent_map,
    )

    service = RetrievalService(pool, embedding_service)
    service._repo = repo

    request = SearchRequest(
        query="architecture",
        top_k=5,
    )

    response = service.search(request)

    assert response.result_count == 1
    assert response.results[0].rank == 1
    assert (
        response.results[0].parent_chunk_id
        == "parent-1"
    )
    assert (
        response.results[0].source_key
        == "workspace:.claude/documents/ARCHITECTURE.md"
    )


def test_search_hybrid_fusion():
    pool = FakePool()
    embedding_service = FakeEmbeddingService()

    vector_results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "similarity": 0.95,
            "vector_rank": 1,
        },
    ]

    text_results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "text_rank": 0.5,
            "text_rank_position": 1,
        },
    ]

    parent_map = {
        "parent-1": {
            "parent_id": "parent-1",
            "parent_chunk_index": 0,
            "content": "Content",
            "source_key": "workspace:doc.md",
            "source_type": "project_document",
            "title": "Doc",
            "source_id": "source-1",
        },
    }

    repo = FakeRepository(
        vector_results=vector_results,
        text_results=text_results,
        parent_map=parent_map,
    )

    service = RetrievalService(pool, embedding_service)
    service._repo = repo

    request = SearchRequest(
        query="test",
        top_k=5,
    )

    response = service.search(request)

    assert response.result_count == 1
    result = response.results[0]
    assert result.vector_score > 0
    assert result.text_score > 0
    assert result.score > 0


def test_search_rrf_calculation():
    pool = FakePool()
    embedding_service = FakeEmbeddingService()

    vector_results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "similarity": 0.95,
            "vector_rank": 1,
        },
        {
            "child_id": "child-2",
            "parent_id": "parent-2",
            "source_id": "source-1",
            "similarity": 0.85,
            "vector_rank": 2,
        },
    ]

    text_results = [
        {
            "child_id": "child-2",
            "parent_id": "parent-2",
            "source_id": "source-1",
            "text_rank": 0.4,
            "text_rank_position": 1,
        },
    ]

    parent_map = {
        "parent-1": {
            "parent_id": "parent-1",
            "parent_chunk_index": 0,
            "content": "Content 1",
            "source_key": "workspace:doc1.md",
            "source_type": "project_document",
            "title": "Doc 1",
            "source_id": "source-1",
        },
        "parent-2": {
            "parent_id": "parent-2",
            "parent_chunk_index": 0,
            "content": "Content 2",
            "source_key": "workspace:doc2.md",
            "source_type": "project_document",
            "title": "Doc 2",
            "source_id": "source-1",
        },
    }

    repo = FakeRepository(
        vector_results=vector_results,
        text_results=text_results,
        parent_map=parent_map,
    )

    service = RetrievalService(pool, embedding_service)
    service._repo = repo

    request = SearchRequest(query="test", top_k=5)

    response = service.search(request)

    assert response.result_count == 2

    first_result_score = response.results[0].score
    second_result_score = response.results[1].score

    vector_contrib_parent1 = (
        1.0 / (RRF_CONSTANT + 1)
    )
    vector_contrib_parent2 = (
        1.0 / (RRF_CONSTANT + 2)
    )
    text_contrib_parent2 = (
        1.0 / (RRF_CONSTANT + 1)
    )

    parent1_score = vector_contrib_parent1
    parent2_score = (
        vector_contrib_parent2 + text_contrib_parent2
    )

    assert abs(
        first_result_score - parent2_score
    ) < 0.0001
    assert abs(
        second_result_score - parent1_score
    ) < 0.0001


def test_search_parent_deduplication():
    pool = FakePool()
    embedding_service = FakeEmbeddingService()

    vector_results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "similarity": 0.95,
            "vector_rank": 1,
        },
        {
            "child_id": "child-2",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "similarity": 0.90,
            "vector_rank": 2,
        },
    ]

    parent_map = {
        "parent-1": {
            "parent_id": "parent-1",
            "parent_chunk_index": 0,
            "content": "Parent content",
            "source_key": "workspace:doc.md",
            "source_type": "project_document",
            "title": "Doc",
            "source_id": "source-1",
        },
    }

    repo = FakeRepository(
        vector_results=vector_results,
        parent_map=parent_map,
    )

    service = RetrievalService(pool, embedding_service)
    service._repo = repo

    request = SearchRequest(query="test", top_k=5)

    response = service.search(request)

    assert response.result_count == 1
    assert (
        response.results[0].parent_chunk_id
        == "parent-1"
    )


def test_search_top_k_limit():
    pool = FakePool()
    embedding_service = FakeEmbeddingService()

    vector_results = [
        {
            "child_id": f"child-{i}",
            "parent_id": f"parent-{i}",
            "source_id": "source-1",
            "similarity": 0.95 - (i * 0.01),
            "vector_rank": i + 1,
        }
        for i in range(10)
    ]

    parent_map = {
        f"parent-{i}": {
            "parent_id": f"parent-{i}",
            "parent_chunk_index": i,
            "content": f"Content {i}",
            "source_key": f"workspace:doc{i}.md",
            "source_type": "project_document",
            "title": f"Doc {i}",
            "source_id": "source-1",
        }
        for i in range(10)
    }

    repo = FakeRepository(
        vector_results=vector_results,
        parent_map=parent_map,
    )

    service = RetrievalService(pool, embedding_service)
    service._repo = repo

    request = SearchRequest(
        query="test",
        top_k=3,
    )

    response = service.search(request)

    assert response.result_count == 3


def test_search_deterministic_tie_breaking():
    pool = FakePool()
    embedding_service = FakeEmbeddingService()

    vector_results = [
        {
            "child_id": "child-a",
            "parent_id": "parent-a",
            "source_id": "source-1",
            "similarity": 0.90,
            "vector_rank": 1,
        },
        {
            "child_id": "child-b",
            "parent_id": "parent-b",
            "source_id": "source-1",
            "similarity": 0.90,
            "vector_rank": 2,
        },
    ]

    parent_map = {
        "parent-a": {
            "parent_id": "parent-a",
            "parent_chunk_index": 0,
            "content": "Content A",
            "source_key": "workspace:a.md",
            "source_type": "project_document",
            "title": "A",
            "source_id": "source-1",
        },
        "parent-b": {
            "parent_id": "parent-b",
            "parent_chunk_index": 0,
            "content": "Content B",
            "source_key": "workspace:b.md",
            "source_type": "project_document",
            "title": "B",
            "source_id": "source-1",
        },
    }

    repo = FakeRepository(
        vector_results=vector_results,
        parent_map=parent_map,
    )

    service = RetrievalService(pool, embedding_service)
    service._repo = repo

    request = SearchRequest(query="test", top_k=2)

    response = service.search(request)

    assert response.result_count == 2
    assert (
        response.results[0].parent_chunk_id
        == "parent-a"
    )
    assert (
        response.results[1].parent_chunk_id
        == "parent-b"
    )


def test_search_embedding_failure():
    pool = FakePool()
    embedding_service = Mock()
    embedding_service._settings = Mock()
    embedding_service._settings.embedding_model = (
        "BAAI/bge-m3"
    )
    embedding_service.encode.side_effect = (
        Exception("Model error")
    )

    service = RetrievalService(pool, embedding_service)

    request = SearchRequest(query="test")

    response = service.search(request)

    assert response.result_count == 0
    assert response.results == []


def test_search_embedding_dimension_mismatch():
    pool = FakePool()
    embedding_service = Mock()
    embedding_service._settings = Mock()
    embedding_service._settings.embedding_model = (
        "BAAI/bge-m3"
    )
    embedding_service._settings.embedding_dimension = (
        1024
    )

    wrong_embedding = EmbeddingResult(
        model="BAAI/bge-m3",
        dimensions=512,
        embeddings=[[0.1] * 512],
        elapsed_ms=10.0,
    )

    embedding_service.encode.return_value = (
        wrong_embedding
    )

    service = RetrievalService(pool, embedding_service)

    request = SearchRequest(query="test")

    response = service.search(request)

    assert response.result_count == 0


def test_search_respects_source_type_filter():
    pool = FakePool()
    embedding_service = FakeEmbeddingService()

    vector_results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "similarity": 0.95,
            "vector_rank": 1,
        },
    ]

    parent_map = {
        "parent-1": {
            "parent_id": "parent-1",
            "parent_chunk_index": 0,
            "content": "Content",
            "source_key": "workspace:doc.md",
            "source_type": "project_document",
            "title": "Doc",
            "source_id": "source-1",
        },
    }

    call_args = []

    def mock_vector_search(
        embedding,
        candidate_k,
        source_types=None,
        source_keys=None,
    ):
        call_args.append(
            {
                "source_types": source_types,
                "source_keys": source_keys,
            }
        )
        return vector_results

    repo = FakeRepository(
        vector_results=vector_results,
        parent_map=parent_map,
    )
    repo.vector_search = mock_vector_search

    service = RetrievalService(pool, embedding_service)
    service._repo = repo

    request = SearchRequest(
        query="test",
        source_types=["project_document"],
    )

    response = service.search(request)

    assert len(call_args) > 0
    assert (
        call_args[0]["source_types"]
        == ["project_document"]
    )


def test_search_response_contains_scores():
    pool = FakePool()
    embedding_service = FakeEmbeddingService()

    vector_results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "similarity": 0.95,
            "vector_rank": 1,
        },
    ]

    parent_map = {
        "parent-1": {
            "parent_id": "parent-1",
            "parent_chunk_index": 0,
            "content": "Content",
            "source_key": "workspace:doc.md",
            "source_type": "project_document",
            "title": "Doc",
            "source_id": "source-1",
        },
    }

    repo = FakeRepository(
        vector_results=vector_results,
        parent_map=parent_map,
    )

    service = RetrievalService(pool, embedding_service)
    service._repo = repo

    request = SearchRequest(query="test")

    response = service.search(request)

    result = response.results[0]
    assert hasattr(result, "score")
    assert hasattr(result, "vector_score")
    assert hasattr(result, "text_score")
    assert isinstance(result.score, float)
    assert isinstance(result.vector_score, float)
    assert isinstance(result.text_score, float)
