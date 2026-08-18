"""Data models for RAG ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    """Represents a successfully loaded document ready for chunking.

    source_key: Unique identifier in format "workspace:" + POSIX relative path
    source_type: One of "project_document" or "source_code"
    title: Document title (filename or first Markdown H1)
    source_path: POSIX-style relative path from repository root
    content: Normalized UTF-8 content
    content_hash: SHA-256 hex digest (64 characters)
    metadata: Dict with extension, size_bytes, modified_time, loader_version, repository_scope
    """

    source_key: str
    source_type: str
    title: str
    source_path: str
    content: str
    content_hash: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """Represents a single chunk (parent or child) before database insertion.

    chunk_level: "parent" or "child"
    chunk_index: Global index for children, per-parent for parents
    parent_index: None for parents, parent's index for children
    content: Non-empty chunk text
    content_hash: SHA-256 hex digest (64 characters)
    token_count: Estimated token count
    metadata: Dict that includes token_count_method="estimated"
    """

    chunk_level: Literal["parent", "child"]
    chunk_index: int
    content: str
    content_hash: str
    token_count: int
    metadata: dict = field(default_factory=dict)
    parent_index: int | None = None


@dataclass(frozen=True, slots=True)
class ChunkPlan:
    """Complete chunking plan for a single document.

    document: The loaded document
    parents: List of parent-level chunks
    children: List of child-level chunks
    """

    document: LoadedDocument
    parents: list[ChunkDraft] = field(default_factory=list)
    children: list[ChunkDraft] = field(default_factory=list)
