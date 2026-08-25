import json
import sys
import types
from pathlib import Path
from urllib.error import URLError

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PROJECT_ROOT / ".claude"


def load_claude_package() -> None:
    """Expose `.claude` through its importable package name."""
    if "claude" in sys.modules:
        return

    package = types.ModuleType("claude")
    package.__path__ = [str(CLAUDE_DIR)]
    package.__package__ = "claude"
    sys.modules["claude"] = package


load_claude_package()

from claude.clients.rag_client import (  # noqa: E402
    RagClient,
    RagClientError,
)


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class RecordingOpener:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append(
            {
                "request": request,
                "timeout": timeout,
            }
        )
        return FakeResponse(self.payload)


def valid_search_response():
    return {
        "results": [
            {
                "rank": 1,
                "source_key": "workspace:CLAUDE.md",
                "source_type": "project_document",
                "title": "Coding Agent Workspace",
                "parent_chunk_id": "parent-1",
                "parent_chunk_index": 0,
                "content": "Intent gate documentation",
                "score": 0.03,
                "vector_score": 0.015,
                "text_score": 0.015,
            }
        ],
        "result_count": 1,
        "embedding_model": "BAAI/bge-m3",
        "elapsed_ms": 120,
    }


def test_ready_calls_ready_endpoint():
    opener = RecordingOpener(
        {
            "status": "ok",
            "service": "coding-agent-workspace-rag",
        }
    )
    client = RagClient(
        base_url="http://127.0.0.1:8200/",
        timeout_seconds=3,
        opener=opener,
    )

    response = client.ready()

    assert response["status"] == "ok"
    assert len(opener.calls) == 1
    call = opener.calls[0]
    assert call["request"].full_url == (
        "http://127.0.0.1:8200/ready"
    )
    assert call["request"].method == "GET"
    assert call["timeout"] == 3


def test_search_sends_expected_payload():
    opener = RecordingOpener(valid_search_response())
    client = RagClient(
        base_url="http://127.0.0.1:8200",
        timeout_seconds=5,
        opener=opener,
    )

    response = client.search(
        "  intent gate  ",
        top_k=5,
        candidate_k=40,
        source_types=["project_document"],
        source_keys=["workspace:CLAUDE.md"],
    )

    assert response["result_count"] == 1
    assert len(opener.calls) == 1

    request = opener.calls[0]["request"]
    payload = json.loads(request.data.decode("utf-8"))

    assert request.method == "POST"
    assert request.full_url == (
        "http://127.0.0.1:8200/v1/search"
    )
    assert payload == {
        "query": "intent gate",
        "top_k": 5,
        "candidate_k": 40,
        "source_types": ["project_document"],
        "source_keys": ["workspace:CLAUDE.md"],
    }


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"query": "   "}, "query cannot be blank"),
        (
            {"query": "test", "top_k": 0},
            "top_k must be between 1 and 20",
        ),
        (
            {"query": "test", "candidate_k": 4},
            "candidate_k must be between 5 and 200",
        ),
        (
            {
                "query": "test",
                "top_k": 10,
                "candidate_k": 5,
            },
            "candidate_k must be greater than or equal to top_k",
        ),
    ],
)
def test_search_rejects_invalid_arguments(arguments, message):
    opener = RecordingOpener(valid_search_response())
    client = RagClient(opener=opener)

    with pytest.raises(ValueError, match=message):
        client.search(**arguments)

    assert opener.calls == []


def test_search_rejects_invalid_response_shape():
    opener = RecordingOpener(
        {
            "results": [],
            "result_count": 1,
            "embedding_model": "BAAI/bge-m3",
            "elapsed_ms": 100,
        }
    )
    client = RagClient(opener=opener)

    with pytest.raises(
        RagClientError,
        match="result_count does not match results",
    ):
        client.search("intent gate")


def test_connection_error_has_startup_guidance():
    def failing_opener(request, timeout):
        raise URLError("connection refused")

    client = RagClient(
        base_url="http://127.0.0.1:8200",
        opener=failing_opener,
    )

    with pytest.raises(
        RagClientError,
        match="Start the RAG server",
    ):
        client.ready()