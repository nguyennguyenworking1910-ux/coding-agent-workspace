"""Database persistence layer for RAG documents."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from psycopg_pool import ConnectionPool

from .models import ChunkDraft, LoadedDocument

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SourceUpsertResult:
    """Result of upserting a source document."""

    source_id: str
    action: Literal["inserted", "updated", "unchanged"]
    prev_hash: str | None = None
    new_hash: str | None = None


class RepositoryError(Exception):
    """Raised when database operation fails."""


class IngestionRepository:
    """Repository for RAG document persistence."""

    def __init__(self, pool: ConnectionPool):
        """Initialize repository with connection pool.

        Args:
            pool: psycopg connection pool
        """
        self.pool = pool

    def query_source_by_key(
        self,
        source_key: str,
    ) -> tuple[str, str] | None:
        """Query existing source by key.

        Args:
            source_key: Source key to search for

        Returns:
            Tuple of (source_id, content_hash) or None if not found

        Raises:
            RepositoryError: If query fails
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, content_hash
                        FROM rag_sources
                        WHERE source_key = %s
                        """,
                        (source_key,),
                    )
                    row = cur.fetchone()
                    if row:
                        return (str(row[0]), str(row[1]))
                    return None
        except Exception as e:
            raise RepositoryError(f"Failed to query source: {e}") from e

    def insert_or_update_source(
        self,
        source: LoadedDocument,
    ) -> SourceUpsertResult:
        """Insert new source or update existing one.

        Args:
            source: LoadedDocument to insert or update

        Returns:
            SourceUpsertResult with action and hash info

        Raises:
            RepositoryError: If operation fails
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO rag_sources (
                            source_key,
                            source_type,
                            title,
                            source_path,
                            content_hash,
                            raw_content,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_key) DO UPDATE SET
                            raw_content = EXCLUDED.raw_content,
                            title = EXCLUDED.title,
                            source_path = EXCLUDED.source_path,
                            content_hash = EXCLUDED.content_hash,
                            metadata = EXCLUDED.metadata,
                            revision = rag_sources.revision + 1
                        RETURNING id, content_hash
                        """,
                        (
                            source.source_key,
                            source.source_type,
                            source.title,
                            source.source_path,
                            source.content_hash,
                            source.content,
                            source.metadata,
                        ),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise RepositoryError("Insert/update returned no row")

                    source_id = str(row[0])
                    new_hash = str(row[1])

                    # Determine action by checking if we just created or updated
                    # We need to do a separate query to check the revision
                    cur.execute(
                        "SELECT revision FROM rag_sources WHERE id = %s",
                        (source_id,),
                    )
                    revision_row = cur.fetchone()
                    if not revision_row:
                        raise RepositoryError("Could not fetch revision")

                    revision = revision_row[0]
                    action = "inserted" if revision == 1 else "updated"

                    logger.info(
                        f"Source {action}: {source.source_key} "
                        f"(id={source_id})"
                    )

                    return SourceUpsertResult(
                        source_id=source_id,
                        action=action,
                        new_hash=new_hash,
                    )

        except RepositoryError:
            raise
        except Exception as e:
            raise RepositoryError(f"Failed to insert/update source: {e}") from e

    def delete_chunks_for_source(self, source_id: str) -> None:
        """Delete all chunks for a source.

        Args:
            source_id: Source ID

        Raises:
            RepositoryError: If operation fails
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    # Delete children first (they have parent_id)
                    cur.execute(
                        """
                        DELETE FROM rag_chunks
                        WHERE source_id = %s AND chunk_level = 'child'
                        """,
                        (source_id,),
                    )
                    child_count = cur.rowcount

                    # Delete parents
                    cur.execute(
                        """
                        DELETE FROM rag_chunks
                        WHERE source_id = %s AND chunk_level = 'parent'
                        """,
                        (source_id,),
                    )
                    parent_count = cur.rowcount

                    logger.info(
                        f"Deleted {parent_count} parents and {child_count} children "
                        f"for source {source_id}"
                    )
        except Exception as e:
            raise RepositoryError(f"Failed to delete chunks: {e}") from e

    def insert_parent_chunks(
        self,
        source_id: str,
        parents: list[ChunkDraft],
    ) -> dict[int, str]:
        """Insert parent chunks and return mapping of index to ID.

        Args:
            source_id: Source ID
            parents: List of parent ChunkDraft objects

        Returns:
            Dict mapping parent_index -> chunk_id

        Raises:
            RepositoryError: If operation fails
        """
        parent_id_map = {}

        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    for parent in parents:
                        # Build metadata without embedding fields
                        metadata = dict(parent.metadata) if parent.metadata else {}

                        cur.execute(
                            """
                            INSERT INTO rag_chunks (
                                source_id,
                                chunk_level,
                                chunk_index,
                                content,
                                content_hash,
                                token_count,
                                metadata
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                source_id,
                                "parent",
                                parent.chunk_index,
                                parent.content,
                                parent.content_hash,
                                parent.token_count,
                                metadata,
                            ),
                        )
                        row = cur.fetchone()
                        if not row:
                            raise RepositoryError(
                                f"Parent insert returned no row for index {parent.chunk_index}"
                            )

                        chunk_id = str(row[0])
                        parent_id_map[parent.chunk_index] = chunk_id

                    logger.info(f"Inserted {len(parents)} parent chunks for source {source_id}")

        except RepositoryError:
            raise
        except Exception as e:
            raise RepositoryError(f"Failed to insert parent chunks: {e}") from e

        return parent_id_map

    def insert_child_chunks(
        self,
        source_id: str,
        children: list[ChunkDraft],
        parent_id_map: dict[int, str],
        embeddings: dict[int, list[float]],
    ) -> None:
        """Insert child chunks with embeddings.

        Args:
            source_id: Source ID
            children: List of child ChunkDraft objects
            parent_id_map: Mapping of parent_index -> parent_id
            embeddings: Mapping of global_child_index -> embedding vector

        Raises:
            RepositoryError: If operation fails
        """
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    for global_child_idx, child in enumerate(children):
                        if child.parent_index is None:
                            raise RepositoryError(
                                f"Child chunk {global_child_idx} has no parent_index"
                            )

                        parent_id = parent_id_map.get(child.parent_index)
                        if not parent_id:
                            raise RepositoryError(
                                f"No parent found for index {child.parent_index}"
                            )

                        embedding = embeddings.get(global_child_idx)
                        if embedding is None:
                            raise RepositoryError(
                                f"No embedding found for child {global_child_idx}"
                            )

                        # Validate embedding length
                        if len(embedding) != 1024:
                            raise RepositoryError(
                                f"Embedding for child {global_child_idx} "
                                f"has {len(embedding)} dims, expected 1024"
                            )

                        # Build metadata without embedding fields
                        metadata = dict(child.metadata) if child.metadata else {}

                        # Insert with embedding as vector
                        cur.execute(
                            """
                            INSERT INTO rag_chunks (
                                source_id,
                                parent_id,
                                chunk_level,
                                chunk_index,
                                content,
                                content_hash,
                                token_count,
                                embedding,
                                embedding_status,
                                embedding_model,
                                metadata
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                source_id,
                                parent_id,
                                "child",
                                child.chunk_index,
                                child.content,
                                child.content_hash,
                                child.token_count,
                                embedding,
                                "ready",
                                "BAAI/bge-m3",
                                metadata,
                            ),
                        )
                        row = cur.fetchone()
                        if not row:
                            raise RepositoryError(
                                f"Child insert returned no row for index {child.chunk_index}"
                            )

                    logger.info(
                        f"Inserted {len(children)} child chunks with embeddings "
                        f"for source {source_id}"
                    )

        except RepositoryError:
            raise
        except Exception as e:
            raise RepositoryError(f"Failed to insert child chunks: {e}") from e
