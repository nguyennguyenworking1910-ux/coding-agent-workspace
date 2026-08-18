"""Idempotent RAG ingestion service with transactional safety."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field

from psycopg_pool import ConnectionPool

from .chunker import DocumentChunker
from .embedding_client import EmbeddingClient
from .models import LoadedDocument
from .repository import IngestionRepository

logger = logging.getLogger(__name__)


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

        # Step 1: Check if source exists
        existing = self.repository.query_source_by_key(source.source_key)

        # Step 2: Chunk the document
        chunk_plan = self.chunker.chunk(source)

        # Step 3: Hash check (outside transaction)
        if existing:
            source_id, stored_hash = existing
            if stored_hash == source.content_hash:
                logger.info(f"Source unchanged: {source.source_key}")
                stats["unchanged"] += 1
                return

        # Step 4: Generate embeddings for all child chunks (outside transaction)
        child_texts = [child.content for child in chunk_plan.children]
        embeddings_dict = {}

        if child_texts and not dry_run:
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

        # Step 5: Validate child count limit
        max_children = self.settings.ingest_max_children_per_source
        if len(chunk_plan.children) > max_children:
            raise ValueError(
                f"Source has {len(chunk_plan.children)} children, "
                f"exceeds limit of {max_children}"
            )

        if dry_run:
            logger.info(f"DRY RUN: Would ingest {source.source_key}")
            stats["inserted"] += 1
            stats["parent_chunks"] += len(chunk_plan.parents)
            stats["child_chunks"] += len(chunk_plan.children)
            stats["embedded_children"] += len(embeddings_dict)
            return

        # Step 6-11: Begin transaction with advisory lock
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

        Args:
            source: LoadedDocument
            chunk_plan: ChunkPlan with parents and children
            embeddings_dict: Mapping of child index to embedding
            stats: Mutable stats dictionary
        """
        # Use hash of source_key for advisory lock (consistent, deterministic)
        lock_id = self._compute_lock_id(source.source_key)

        try:
            with self.pool.connection() as conn:
                conn.autocommit = False
                with conn.cursor() as cur:
                    # Step 6: Acquire advisory lock
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(%s)",
                        (lock_id,),
                    )

                    # Step 6b: Recheck content_hash (race condition prevention)
                    existing = self.repository.query_source_by_key(
                        source.source_key
                    )
                    if existing:
                        source_id, stored_hash = existing
                        if stored_hash == source.content_hash:
                            logger.info(
                                f"Source unchanged after lock: {source.source_key}"
                            )
                            stats["unchanged"] += 1
                            conn.rollback()
                            return

                    # Step 7: Insert or update rag_sources
                    upsert_result = self.repository.insert_or_update_source(source)
                    source_id = upsert_result.source_id

                    if upsert_result.action == "inserted":
                        stats["inserted"] += 1
                    else:
                        stats["updated"] += 1
                        # Delete old chunks if updating
                        self.repository.delete_chunks_for_source(source_id)

                    # Step 8: Insert parent chunks
                    parent_id_map = self.repository.insert_parent_chunks(
                        source_id,
                        chunk_plan.parents,
                    )
                    stats["parent_chunks"] += len(chunk_plan.parents)

                    # Step 9: Insert child chunks with embeddings
                    self.repository.insert_child_chunks(
                        source_id,
                        chunk_plan.children,
                        parent_id_map,
                        embeddings_dict,
                    )
                    stats["child_chunks"] += len(chunk_plan.children)
                    stats["embedded_children"] += len(embeddings_dict)

                    # Step 10: Commit (implicit on context exit)
                    conn.commit()
                    logger.info(f"Successfully ingested: {source.source_key}")

        except Exception as e:
            logger.error(
                f"Transaction failed for {source.source_key}: {type(e).__name__}"
            )
            raise

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
