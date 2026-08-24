import pytest
from unittest.mock import Mock, MagicMock
from psycopg.rows import dict_row

from app.retrieval.repository import RetrievalRepository


class FakeCursor:
    def __init__(
        self,
        results=None,
    ):
        self.results = results or []
        self._row_factory = dict_row

    def execute(self, query, params=None):
        pass

    def fetchall(self):
        return self.results

    def fetchone(self):
        return self.results[0] if self.results else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class FakeConnection:
    def __init__(
        self,
        cursor_results=None,
    ):
        self.cursor_results = (
            cursor_results or []
        )
        self._current_cursor_index = 0

    def cursor(self, row_factory=None):
        cursor = FakeCursor(
            self.cursor_results
        )
        if self._current_cursor_index > 0:
            cursor.results = []
        self._current_cursor_index += 1
        return cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class FakePool:
    def __init__(self, results=None):
        self.results = results or []

    def connection(self, **kwargs):
        return FakeConnection(self.results)


def test_vector_search_returns_candidates():
    results = [
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

    fake_pool = FakePool(results)
    repo = RetrievalRepository(fake_pool)

    embedding = [0.1] * 1024
    candidates = repo.vector_search(
        embedding,
        candidate_k=40,
    )

    assert len(candidates) == 2
    assert candidates[0]["child_id"] == "child-1"
    assert candidates[1]["child_id"] == "child-2"


def test_vector_search_with_source_type_filter():
    results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "similarity": 0.95,
            "vector_rank": 1,
        },
    ]

    fake_pool = FakePool(results)
    repo = RetrievalRepository(fake_pool)

    embedding = [0.1] * 1024
    candidates = repo.vector_search(
        embedding,
        candidate_k=40,
        source_types=["project_document"],
    )

    assert len(candidates) == 1


def test_vector_search_with_source_key_filter():
    results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "similarity": 0.95,
            "vector_rank": 1,
        },
    ]

    fake_pool = FakePool(results)
    repo = RetrievalRepository(fake_pool)

    embedding = [0.1] * 1024
    candidates = repo.vector_search(
        embedding,
        candidate_k=40,
        source_keys=["workspace:.claude/documents/ARCHITECTURE.md"],
    )

    assert len(candidates) == 1


def test_vector_search_empty_result():
    fake_pool = FakePool([])
    repo = RetrievalRepository(fake_pool)

    embedding = [0.1] * 1024
    candidates = repo.vector_search(
        embedding,
        candidate_k=40,
    )

    assert candidates == []


def test_full_text_search_returns_candidates():
    results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "text_rank": 0.5,
            "text_rank_position": 1,
        },
        {
            "child_id": "child-2",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "text_rank": 0.3,
            "text_rank_position": 2,
        },
    ]

    fake_pool = FakePool(results)
    repo = RetrievalRepository(fake_pool)

    candidates = repo.full_text_search(
        "intent gate",
        candidate_k=40,
    )

    assert len(candidates) == 2
    assert candidates[0]["child_id"] == "child-1"
    assert candidates[1]["child_id"] == "child-2"


def test_full_text_search_with_filter():
    results = [
        {
            "child_id": "child-1",
            "parent_id": "parent-1",
            "source_id": "source-1",
            "text_rank": 0.5,
            "text_rank_position": 1,
        },
    ]

    fake_pool = FakePool(results)
    repo = RetrievalRepository(fake_pool)

    candidates = repo.full_text_search(
        "intent",
        candidate_k=40,
        source_types=["project_document"],
    )

    assert len(candidates) == 1


def test_get_parent_content_returns_parents():
    results = [
        {
            "parent_id": "parent-1",
            "parent_chunk_index": 0,
            "content": "Parent content 1",
            "source_key": "workspace:doc.md",
            "source_type": "project_document",
            "title": "Architecture",
            "source_id": "source-1",
        },
    ]

    fake_pool = FakePool(results)
    repo = RetrievalRepository(fake_pool)

    parent_map = repo.get_parent_content(
        ["parent-1"]
    )

    assert "parent-1" in parent_map
    assert (
        parent_map["parent-1"]["content"]
        == "Parent content 1"
    )


def test_get_parent_content_empty_parents():
    fake_pool = FakePool([])
    repo = RetrievalRepository(fake_pool)

    parent_map = repo.get_parent_content([])

    assert parent_map == {}


def test_verify_parent_source_valid():
    results = [
        (True,),
    ]

    fake_pool = FakePool(results)
    repo = RetrievalRepository(fake_pool)

    is_valid = repo.verify_parent_source(
        "child-1",
        "parent-1",
    )

    assert is_valid is True


def test_verify_parent_source_invalid():
    fake_pool = FakePool([(False,)])
    repo = RetrievalRepository(fake_pool)

    is_valid = repo.verify_parent_source(
        "child-1",
        "parent-1",
    )

    assert is_valid is False


def test_verify_parent_source_no_result():
    fake_pool = FakePool([])
    repo = RetrievalRepository(fake_pool)

    is_valid = repo.verify_parent_source(
        "child-1",
        "parent-1",
    )

    assert is_valid is False
