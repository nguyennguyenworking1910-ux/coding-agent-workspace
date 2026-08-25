"""RAG knowledge-search tools.

This module is the tool layer between agents and `RagClient`. It must not
connect to PostgreSQL or import the RAG server's embedding implementation.
"""

from __future__ import annotations

from typing import Any

from ....clients import RagClient


_rag_client: RagClient | None = None


def get_rag_client() -> RagClient:
    """Get or create the process-local RAG client."""
    global _rag_client

    if _rag_client is None:
        _rag_client = RagClient()

    return _rag_client


def ready() -> dict[str, Any]:
    """Check whether the local RAG service is ready."""
    return get_rag_client().ready()


def search(
    query: str,
    *,
    top_k: int = 5,
    candidate_k: int = 40,
    source_types: list[str] | None = None,
    source_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Search indexed workspace documents and Claude conversations."""
    return get_rag_client().search(
        query,
        top_k=top_k,
        candidate_k=candidate_k,
        source_types=source_types,
        source_keys=source_keys,
    )


RAG_TOOLS = {
    "ready": ready,
    "search": search,
}