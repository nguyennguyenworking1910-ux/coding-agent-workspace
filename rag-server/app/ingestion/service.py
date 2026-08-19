"""Idempotent RAG ingestion service with transactional safety."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from psycopg_pool import ConnectionPool
from psycopg.connection import Connection
from psycopg.cursor import Cursor

from .chunker import DocumentChunker
from .embedding_client import EmbeddingClient
from .models import LoadedDocument
from .repository import IngestionRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Immutable snapshot of a source's database state."""

    source_id: str
    content_hash: str
    revision: int
    parent_count: int
    child_count: int
    ready_child_count: int
    pending_or_failed_child_count: int
    parent_embedding_count: int
    invalid_dimension_count: int
    orphan_child_count: int


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Result of ingestion operation."""

    discovered_sources: int
    inserted_sources: int
    updated_sources: int
    unchanged_sources: int
    failed_sources: int
    parent_chunks: int
    child_chunks: int
    embedded_children: int
    elapsed_ms: float
    failures: list[dict] = field(default_factory=list)


class IngestionService:
    """Idempotent ingestion service with transactional safety."""

    def __init__(
        self,
        settings,
        embedding_client: EmbeddingClient,
        pool: ConnectionPool,
    ):
        """Initialize ingestion service.

        Args:
            settings: Settings object with configuration
            embedding_client: Embedding client implementation
            pool: Database connection pool
        """
        self.settings = settings
        self.embedding_client = embedding_client
        self.pool = pool
        self.repository = IngestionRepository(pool)
        self.chunker = DocumentChunker()

    async def ingest_sources(
        self,
        sources: list[LoadedDocument],
        dry_run: bool = False,
    ) -> IngestionResult:
        """Ingest sources idempotently with transactional safety.

        Args:
            sources: List of LoadedDocument objects
            dry_run: If True, perform no writes or embedding calls

        Returns:
            IngestionResult with summary

        Raises:
            Exception: Caught per-source, accumulated in failures
        """
        start_time = time.time()

        # Sort by source_key for deterministic order
        sorted_sources = sorted(sources, key=lambda s: s.source_key)

        result_stats = {
            "discovered": len(sorted_sources),
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "parent_chunks": 0,
            "child_chunks": 0,
            "embedded_children": 0,
            "failures": [],
        }

        for source in sorted_sources:
            try:
                await self._ingest_single_source(
                    source,
                    result_stats,
                    dry_run=dry_run,
                )
            except Exception as e:
                result_stats["failed"] += 1
                error_type = type(e).__name__
                result_stats["failures"].append(
                    {
                        "source_key": source.source_key,
                        "error_type": error_type,
                    }
                )
                logger.error(
                    f"Ingestion failed for {source.source_key}: {error_type}"
                )

        elapsed_ms = (time.time() - start_time) * 1000

        return IngestionResult(
            discovered_sources=result_stats["discovered"],
            inserted_sources=result_stats["inserted"],
            updated_sources=result_stats["updated"],
            unchanged_sources=result_stats["unchanged"],
            failed_sources=result_stats["failed"],
            parent_chunks=result_stats["parent_chunks"],
            child_chunks=result_stats["child_chunks"],
            embedded_children=result_stats["embedded_children"],
            elapsed_ms=elapsed_ms,
            failures=result_stats["failures"],
        )

    async def _ingest_single_source(
        self,
        source: LoadedDocument,
        stats: dict,
        dry_run: bool = False,
    ) -> None:
        """Ingest a single source with hash-based idempotency.

        Args:
            source: LoadedDocument to ingest
            stats: Mutable stats dictionary
            dry_run: If True, perform no writes or embedding calls

        Raises:
            Exception: If ingestion fails
        """
        logger.info(f"Processing source: {source.source_key}")

        # Step 1: Chunk the document
        chunk_plan = self.chunker.chunk(source)

        # Step 2: VALIDATE CHILD LIMIT BEFORE ANY EMBEDDING
        max_children = self.settings.ingest_max_children_per_source
        if len(chunk_plan.children) > max_children:
            logger.error(
                f"Source {source.source_key} has {len(chunk_plan.children)} children, "
                f"exceeds limit of {max_children}"
            )
            raise ValueError(
                f"Source has {len(chunk_plan.children)} children, "
                f"exceeds limit of {max_children}"
            )

        if dry_run:
            # For dry run, skip DB check and embedding, just predict
            logger.info(f"DRY RUN: Would ingest {source.source_key}")
            stats["inserted"] += 1
            stats["parent_chunks"] += len(chunk_plan.parents)
            stats["child_chunks"] += len(chunk_plan.children)
            stats["embedded_children"] += len(chunk_plan.children)
            return

        # Step 3: Fast unchanged check (before embedding)
        existing = self.repository.query_source_by_key(source.source_key)
        if existing:
            source_id, stored_hash = existing
            if stored_hash == source.content_hash:
                # Verify source completeness before skipping embedding
                with self.pool.connection() as conn:
                    with conn.cursor() as cur:
                        snap = self._query_source_snapshot(cur, source.source_key)
                        if snap and self._is_source_complete(snap, chunk_plan):
                            logger.info(f"Source unchanged (fast check): {source.source_key}")
                            stats["unchanged"] += 1
                            return
                # If same hash but incomplete, fall through to embedding and rebuild

        # Step 4: Generate embeddings for all child chunks (only if source changed)
        child_texts = [child.content for child in chunk_plan.children]
        embeddings_dict = {}

        if child_texts:
            logger.info(f"Embedding {len(child_texts)} child chunks")
            embeddings = await self.embedding_client.embed_texts(child_texts)

            # Validate embedding count
            if len(embeddings) != len(child_texts):
                raise ValueError(
                    f"Embedding returned {len(embeddings)} vectors, "
                    f"expected {len(child_texts)}"
                )

            # Map embeddings by global child index
            for idx, embedding in enumerate(embeddings):
                embeddings_dict[idx] = embedding

            logger.info(f"Successfully embedded all {len(child_texts)} children")

        # Step 5-11: Begin transaction with advisory lock
        await self._ingest_with_transaction(
            source,
            chunk_plan,
            embeddings_dict,
            stats,
        )

    async def _ingest_with_transaction(
        self,
        source: LoadedDocument,
        chunk_plan,
        embeddings_dict: dict,
        stats: dict,
    ) -> None:
        """Ingest with transactional safety and advisory lock.

        One connection, one transaction, advisory lock to prevent races.

        Args:
            source: LoadedDocument
            chunk_plan: ChunkPlan with parents and children
            embeddings_dict: Mapping of child index to embedding
            stats: Mutable stats dictionary
        """
        lock_id = self._compute_lock_id(source.source_key)

        with self.pool.connection() as conn:
            try:
                conn.autocommit = False

                with conn.transaction():
                    with conn.cursor() as cur:
                        # Step 5a: Acquire advisory lock
                        cur.execute(
                            "SELECT pg_advisory_xact_lock(%s)",
                            (lock_id,),
                        )

                        # Step 5b: Recheck content_hash inside transaction (race condition prevention)
                        snap = self._query_source_snapshot(
                            cur, source.source_key
                        )
                        if snap:
                            if snap.content_hash == source.content_hash:
                                # Check structure completeness
                                if self._is_source_complete(
                                    snap, chunk_plan
                                ):
                                    logger.info(
                                        f"Source unchanged (locked check): {source.source_key}"
                                    )
                                    stats["unchanged"] += 1
                                    # Transaction will rollback, no writes
                                    return
                                # If same hash but incomplete, fall through to rebuild

                        # Step 6: Insert or update rag_sources
                        upsert_result = self.repository.insert_or_update_source(
                            source, cur
                        )
                        source_id = upsert_result.source_id

                        action_for_stats = upsert_result.action
                        if upsert_result.action == "inserted":
                            pass  # Will increment inserted_sources at end
                        else:
                            # Delete old chunks if updating (including incomplete)
                            self.repository.delete_chunks_for_source(
                                source_id, cur
                            )

                        # Step 7: Insert parent chunks
                        parent_id_map = (
                            self.repository.insert_parent_chunks(
                                source_id,
                                chunk_plan.parents,
                                cur,
                            )
                        )

                        # Step 8: Insert child chunks with embeddings
                        self.repository.insert_child_chunks(
                            source_id,
                            chunk_plan.children,
                            parent_id_map,
                            embeddings_dict,
                            cur,
                            embedding_model=self.settings.embedding_model,
                        )

                        # Step 9: Transaction commits here (end of context)
                        # All writes are now durable

                # Success: increment stats ONLY AFTER commit
                if action_for_stats == "inserted":
                    stats["inserted"] += 1
                else:
                    stats["updated"] += 1

                stats["parent_chunks"] += len(chunk_plan.parents)
                stats["child_chunks"] += len(chunk_plan.children)
                stats["embedded_children"] += len(embeddings_dict)

                logger.info(f"Successfully ingested: {source.source_key}")

            except Exception as e:
                # Transaction already rolled back by context manager
                logger.error(
                    f"Transaction failed for {source.source_key}: {type(e).__name__}: {e}"
                )
                raise

    def _query_source_snapshot(
        self,
        cur: Cursor,
        source_key: str,
    ) -> Optional[SourceSnapshot]:
        """Query database for source snapshot within a transaction.

        Args:
            cur: Database cursor (must be within transaction)
            source_key: Source key to query

        Returns:
            SourceSnapshot if source exists, None otherwise
        """
        # Get source row
        cur.execute(
            """
            SELECT id, content_hash, revision
            FROM rag_sources
            WHERE source_key = %s
            """,
            (source_key,),
        )
        source_row = cur.fetchone()
        if not source_row:
            return None

        source_id, content_hash, revision = source_row

        # Get chunk statistics
        cur.execute(
            """
            SELECT
                SUM(CASE WHEN chunk_level = 'parent' THEN 1 ELSE 0 END) as parent_count,
                SUM(CASE WHEN chunk_level = 'child' THEN 1 ELSE 0 END) as child_count,
                SUM(CASE WHEN chunk_level = 'child' AND embedding_status = 'ready' THEN 1 ELSE 0 END) as ready_child_count,
                SUM(CASE WHEN chunk_level = 'child' AND embedding_status IN ('pending', 'failed') THEN 1 ELSE 0 END) as pending_or_failed_count,
                SUM(CASE WHEN chunk_level = 'parent' AND embedding IS NOT NULL THEN 1 ELSE 0 END) as parent_embedding_count,
                SUM(CASE WHEN chunk_level = 'child' AND (embedding IS NULL OR vector_dims(embedding) != 1024) THEN 1 ELSE 0 END) as invalid_dim_count,
                SUM(CASE WHEN chunk_level = 'child' AND parent_id IS NULL THEN 1 ELSE 0 END) as orphan_count
            FROM rag_chunks
            WHERE source_id = %s
            """,
            (source_id,),
        )
        stats_row = cur.fetchone()
        if not stats_row:
            return None

        (
            parent_count,
            child_count,
            ready_count,
            pending_or_failed_count,
            parent_embedding_count,
            invalid_dim_count,
            orphan_count,
        ) = stats_row

        # Handle None values (no chunks)
        parent_count = parent_count or 0
        child_count = child_count or 0
        ready_count = ready_count or 0
        pending_or_failed_count = pending_or_failed_count or 0
        parent_embedding_count = parent_embedding_count or 0
        invalid_dim_count = invalid_dim_count or 0
        orphan_count = orphan_count or 0

        return SourceSnapshot(
            source_id=str(source_id),
            content_hash=content_hash,
            revision=revision,
            parent_count=parent_count,
            child_count=child_count,
            ready_child_count=ready_count,
            pending_or_failed_child_count=pending_or_failed_count,
            parent_embedding_count=parent_embedding_count,
            invalid_dimension_count=invalid_dim_count,
            orphan_child_count=orphan_count,
        )

    def _is_source_complete(
        self,
        snapshot: SourceSnapshot,
        chunk_plan,
    ) -> bool:
        """Check if source is complete and consistent.

        A source is complete if:
        - Parent count matches chunk_plan
        - Child count matches chunk_plan
        - All children are ready
        - No children are pending/failed
        - No parent has embedding
        - All child embeddings have valid dimensions (1024)
        - No orphan children

        Args:
            snapshot: SourceSnapshot from database
            chunk_plan: ChunkPlan with expected structure

        Returns:
            True if source is complete, False if incomplete or needs repair
        """
        # Check parent count
        if snapshot.parent_count != len(chunk_plan.parents):
            logger.debug(
                f"Parent count mismatch: {snapshot.parent_count} vs {len(chunk_plan.parents)}"
            )
            return False

        # Check child count
        if snapshot.child_count != len(chunk_plan.children):
            logger.debug(
                f"Child count mismatch: {snapshot.child_count} vs {len(chunk_plan.children)}"
            )
            return False

        # Check all children are ready (no pending/failed)
        if snapshot.pending_or_failed_child_count > 0:
            logger.debug(
                f"Children in pending/failed state: {snapshot.pending_or_failed_child_count}"
            )
            return False

        # Check no children are missing ready state
        if snapshot.ready_child_count != snapshot.child_count:
            logger.debug(
                f"Not all children ready: {snapshot.ready_child_count} vs {snapshot.child_count}"
            )
            return False

        # Check parents don't have embeddings
        if snapshot.parent_embedding_count > 0:
            logger.debug(
                f"Parents have embeddings: {snapshot.parent_embedding_count}"
            )
            return False

        # Check all child embeddings have correct dimension
        if snapshot.invalid_dimension_count > 0:
            logger.debug(
                f"Invalid dimension embeddings: {snapshot.invalid_dimension_count}"
            )
            return False

        # Check no orphan children
        if snapshot.orphan_child_count > 0:
            logger.debug(f"Orphan children found: {snapshot.orphan_child_count}")
            return False

        logger.debug(f"Source is complete")
        return True

    @staticmethod
    def _compute_lock_id(source_key: str) -> int:
        """Compute a deterministic lock ID from source key.

        Args:
            source_key: Source key string

        Returns:
            Integer lock ID (within valid pg_advisory_xact_lock range)
        """
        # Use first 8 bytes of SHA256 as integer
        hash_bytes = hashlib.sha256(source_key.encode()).digest()[:8]
        # Convert to signed 64-bit integer
        lock_id = int.from_bytes(hash_bytes, byteorder="big", signed=True)
        return lock_id
