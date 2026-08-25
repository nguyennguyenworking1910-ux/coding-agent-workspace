"""Tools for searching the private local RAG knowledge base."""

from .search import (
    RAG_TOOLS,
    get_rag_client,
    ready,
    search,
)


__all__ = [
    "RAG_TOOLS",
    "get_rag_client",
    "ready",
    "search",
]
