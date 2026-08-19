"""Integration tests for ingestion transactions against real PostgreSQL.

These tests require:
- RAG_RUN_DB_TESTS=1 environment variable
- Real PostgreSQL database configured via RAG_* environment variables
- Migration 001 applied
"""

import os
import pytest
import uuid
import asyncio
import hashlib
from typing import Optional

from psycopg_pool import ConnectionPool

from app.config import Settings
from app.ingestion.models import ChunkDraft, ChunkPlan, LoadedDocument
from app.ingestion.service import IngestionService


# Check if integration tests are enabled
SKIP_INTEGRATION_TESTS = not os.getenv("RAG_RUN_DB_TESTS", "").lower() in ("1", "true")


def _sha256(value: str) -> str:
    """Compute SHA-256 hash of a string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class FakeEmbeddingClient:
    """Fake embedding client for integration tests."""

    def __init__(self):
        """Initialize fake client."""
        self.call_count = 0

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return fake 1024-dimensional embeddings."""
        self.call_count += 1
        # Return valid 1024-dimensional embeddings
        return [[0.1 + i * 0.001] * 1024 for i in range(len(texts))]


class StaticChunker:
    """Deterministic chunker that returns a pre-configured plan."""

    def __init__(self, plan: ChunkPlan):
        """Initialize with plan to return."""
        self.plan = plan

    def chunk(self, document: LoadedDocument) -> ChunkPlan:
        """Return the static plan, validating document matches."""
        assert document.source_key == self.plan.document.source_key
        return self.plan


@pytest.fixture(scope="module")
def integration_settings():
    """Get settings from environment."""
    return Settings.from_env()


@pytest.fixture(scope="module")
def integration_pool(integration_settings):
    """Create connection pool for integration tests."""
    pool = ConnectionPool(
        integration_settings.database_url,
        min_size=1,
        max_size=1,
        timeout=integration_settings.db_timeout_seconds,
        open=True,
    )
    pool.wait()
    yield pool
    pool.close()


@pytest.fixture
def embedding_client():
    """Create fake embedding client."""
    return FakeEmbeddingClient()


@pytest.fixture
def service(integration_settings, embedding_client, integration_pool):
    """Create ingestion service with real pool."""
    return IngestionService(
        settings=integration_settings,
        embedding_client=embedding_client,
        pool=integration_pool,
    )


def _make_test_source_key() -> str:
    """Generate unique test source key."""
    unique_id = str(uuid.uuid4())[:8]
    return f"integration:step6b:{unique_id}"


def _cleanup_test_sources(pool: ConnectionPool) -> None:
    """Delete all test sources with integration prefix."""
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Delete children first
                cur.execute(
                    """
                    DELETE FROM rag_chunks
                    WHERE source_id IN (
                        SELECT id FROM rag_sources
                        WHERE source_key LIKE 'integration:step6b:%'
                    )
                    """
                )
                child_count = cur.rowcount

                # Delete sources
                cur.execute(
                    """
                    DELETE FROM rag_sources
                    WHERE source_key LIKE 'integration:step6b:%'
                    """
                )
                source_count = cur.rowcount

                conn.commit()
                print(
                    f"Cleaned up {source_count} test sources and {child_count} test chunks"
                )
    except Exception as e:
        print(f"Warning: cleanup failed: {e}")


@pytest.mark.skipif(
    SKIP_INTEGRATION_TESTS,
    reason="Requires RAG_RUN_DB_TESTS=1 and real PostgreSQL",
)
class TestTransactionIntegration:
    """Integration tests with real PostgreSQL."""

    @classmethod
    def setup_class(cls):
        """Clean up any previous test data before running tests."""
        # Get pool from first test's fixture to clean up
        pass

    def setup_method(self):
        """Setup before each test."""
        pass

    def teardown_method(self):
        """Cleanup after each test."""
        pass

    @pytest.mark.asyncio
    async def test_insert_with_jsonb_metadata_and_vector(
        self,
        service,
        integration_pool,
    ):
        """Test that source metadata is stored as JSONB and children have vector(1024)."""
        try:
            source_key = _make_test_source_key()

            content = "This is test content for integration test."
            parent_content = "Parent content"
            child1_content = "Child 1 content"
            child2_content = "Child 2 content"

            doc = LoadedDocument(
                source_key=source_key,
                source_type="project_document",
                title="Test Document",
                source_path="test.txt",
                content=content,
                content_hash=_sha256(content),
                metadata={"test_field": "test_value", "count": 42},
            )

            plan = ChunkPlan(
                document=doc,
                parents=[
                    ChunkDraft(
                        chunk_level="parent",
                        chunk_index=0,
                        content=parent_content,
                        content_hash=_sha256(parent_content),
                        token_count=10,
                        metadata={"parent_field": "parent_value"},
                    ),
                ],
                children=[
                    ChunkDraft(
                        chunk_level="child",
                        chunk_index=0,
                        parent_index=0,
                        content=child1_content,
                        content_hash=_sha256(child1_content),
                        token_count=5,
                        metadata={"child_field": "child_value_1"},
                    ),
                    ChunkDraft(
                        chunk_level="child",
                        chunk_index=1,
                        parent_index=0,
                        content=child2_content,
                        content_hash=_sha256(child2_content),
                        token_count=5,
                        metadata={"child_field": "child_value_2"},
                    ),
                ],
            )

            # Inject plan via StaticChunker
            service.chunker = StaticChunker(plan)

            # Ingest
            result = await service.ingest_sources([doc], dry_run=False)

            # Verify success
            assert result.inserted_sources == 1
            assert result.parent_chunks == 1
            assert result.child_chunks == 2
            assert result.embedded_children == 2

            # Verify in database
            with integration_pool.connection() as conn:
                with conn.cursor() as cur:
                    # Check source metadata
                    cur.execute(
                        "SELECT metadata FROM rag_sources WHERE source_key = %s",
                        (source_key,),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    metadata = row[0]
                    assert metadata["test_field"] == "test_value"
                    assert metadata["count"] == 42

                    # Check children embeddings
                    cur.execute(
                        """
                        SELECT embedding, vector_dims(embedding) AS dims
                        FROM rag_chunks
                        WHERE source_id = (SELECT id FROM rag_sources WHERE source_key = %s)
                        AND chunk_level = 'child'
                        ORDER BY chunk_index
                        """,
                        (source_key,),
                    )
                    rows = cur.fetchall()
                    assert len(rows) == 2
                    for embedding, dimensions in rows:
                        assert embedding is not None
                        assert dimensions == 1024, f"Expected 1024 dims, got {dimensions}"

        finally:
            _cleanup_test_sources(integration_pool)

    @pytest.mark.asyncio
    async def test_confirm_parent_child_state(
        self,
        service,
        integration_pool,
    ):
        """Test that parents have no embeddings, children are ready, no orphans."""
        try:
            source_key = _make_test_source_key()

            content = "Content"
            parent_content = "Parent"
            child_content = "Child"

            doc = LoadedDocument(
                source_key=source_key,
                source_type="project_document",
                title="Test",
                source_path="test.txt",
                content=content,
                content_hash=_sha256(content),
            )

            plan = ChunkPlan(
                document=doc,
                parents=[
                    ChunkDraft(
                        chunk_level="parent",
                        chunk_index=0,
                        content=parent_content,
                        content_hash=_sha256(parent_content),
                        token_count=10,
                    ),
                ],
                children=[
                    ChunkDraft(
                        chunk_level="child",
                        chunk_index=0,
                        parent_index=0,
                        content=child_content,
                        content_hash=_sha256(child_content),
                        token_count=5,
                    ),
                ],
            )

            # Inject plan via StaticChunker
            service.chunker = StaticChunker(plan)

            result = await service.ingest_sources([doc], dry_run=False)
            assert result.inserted_sources == 1

            # Verify state
            with integration_pool.connection() as conn:
                with conn.cursor() as cur:
                    # Check no parent has embedding
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM rag_chunks
                        WHERE source_id = (SELECT id FROM rag_sources WHERE source_key = %s)
                        AND chunk_level = 'parent'
                        AND embedding IS NOT NULL
                        """,
                        (source_key,),
                    )
                    count = cur.fetchone()[0]
                    assert count == 0, "Parent has embedding!"

                    # Check all children are ready
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM rag_chunks
                        WHERE source_id = (SELECT id FROM rag_sources WHERE source_key = %s)
                        AND chunk_level = 'child'
                        AND embedding_status != 'ready'
                        """,
                        (source_key,),
                    )
                    count = cur.fetchone()[0]
                    assert count == 0, "Child not ready!"

                    # Check no orphans
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM rag_chunks
                        WHERE source_id = (SELECT id FROM rag_sources WHERE source_key = %s)
                        AND chunk_level = 'child'
                        AND parent_id IS NULL
                        """,
                        (source_key,),
                    )
                    count = cur.fetchone()[0]
                    assert count == 0, "Orphan children found!"

        finally:
            _cleanup_test_sources(integration_pool)

    @pytest.mark.asyncio
    async def test_version_2_failure_rolls_back(
        self,
        service,
        integration_pool,
    ):
        """Test that version 2 attempt with injected failure rolls back completely."""
        try:
            source_key = _make_test_source_key()

            # Version 1: Insert successfully
            content_v1 = "Version 1 content"
            parent_v1 = "Parent V1"
            child_v1 = "Child V1"

            doc_v1 = LoadedDocument(
                source_key=source_key,
                source_type="project_document",
                title="Test",
                source_path="test.txt",
                content=content_v1,
                content_hash=_sha256(content_v1),
            )

            plan_v1 = ChunkPlan(
                document=doc_v1,
                parents=[
                    ChunkDraft(
                        chunk_level="parent",
                        chunk_index=0,
                        content=parent_v1,
                        content_hash=_sha256(parent_v1),
                        token_count=10,
                    ),
                ],
                children=[
                    ChunkDraft(
                        chunk_level="child",
                        chunk_index=0,
                        parent_index=0,
                        content=child_v1,
                        content_hash=_sha256(child_v1),
                        token_count=5,
                    ),
                ],
            )

            # Inject plan via StaticChunker
            service.chunker = StaticChunker(plan_v1)

            result_v1 = await service.ingest_sources([doc_v1], dry_run=False)
            assert result_v1.inserted_sources == 1

            # Store original state
            with integration_pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT content_hash, raw_content, revision
                        FROM rag_sources
                        WHERE source_key = %s
                        """,
                        (source_key,),
                    )
                    original_state = cur.fetchone()
                    original_hash = original_state[0]
                    original_content = original_state[1]
                    original_revision = original_state[2]

            # Version 2: Attempt with failure injection
            # Mock the repository to fail after first write
            original_insert_parent = service.repository.insert_parent_chunks

            call_count = [0]

            def failing_insert_parent(source_id, parents, cur):
                call_count[0] += 1
                # Call original to insert
                result = original_insert_parent(source_id, parents, cur)
                # Then fail
                raise ValueError("Injected failure for test")

            service.repository.insert_parent_chunks = failing_insert_parent

            content_v2 = "Version 2 content"
            parent_v2 = "Parent V2"
            child_v2 = "Child V2"

            doc_v2 = LoadedDocument(
                source_key=source_key,
                source_type="project_document",
                title="Test",
                source_path="test.txt",
                content=content_v2,
                content_hash=_sha256(content_v2),
            )

            plan_v2 = ChunkPlan(
                document=doc_v2,
                parents=[
                    ChunkDraft(
                        chunk_level="parent",
                        chunk_index=0,
                        content=parent_v2,
                        content_hash=_sha256(parent_v2),
                        token_count=10,
                    ),
                ],
                children=[
                    ChunkDraft(
                        chunk_level="child",
                        chunk_index=0,
                        parent_index=0,
                        content=child_v2,
                        content_hash=_sha256(child_v2),
                        token_count=5,
                    ),
                ],
            )

            # Inject plan_v2 via StaticChunker
            service.chunker = StaticChunker(plan_v2)

            # Attempt should fail
            result_v2 = await service.ingest_sources([doc_v2], dry_run=False)
            assert result_v2.failed_sources == 1

            # Verify database rolled back
            with integration_pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT content_hash, raw_content, revision
                        FROM rag_sources
                        WHERE source_key = %s
                        """,
                        (source_key,),
                    )
                    final_state = cur.fetchone()
                    assert final_state is not None
                    final_hash = final_state[0]
                    final_content = final_state[1]
                    final_revision = final_state[2]

                    # Verify nothing changed
                    assert final_hash == original_hash, (
                        f"Hash changed: {final_hash} != {original_hash}"
                    )
                    assert final_content == original_content, "Content changed!"
                    assert final_revision == original_revision, "Revision changed!"

            # Restore original method
            service.repository.insert_parent_chunks = original_insert_parent

        finally:
            _cleanup_test_sources(integration_pool)

    @pytest.mark.asyncio
    async def test_incomplete_same_hash_source_repair(
        self,
        service,
        integration_pool,
    ):
        """Test that incomplete same-hash source is repaired (rebuilt), not marked unchanged."""
        try:
            source_key = _make_test_source_key()

            # Version 1: Insert with 3 parents, 5 children
            content = "Content for repair test"

            doc_v1 = LoadedDocument(
                source_key=source_key,
                source_type="project_document",
                title="Test",
                source_path="test.txt",
                content=content,
                content_hash=_sha256(content),
            )

            parents_v1 = [
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=i,
                    content=f"Parent {i}",
                    content_hash=_sha256(f"Parent {i}"),
                    token_count=10,
                )
                for i in range(3)
            ]

            children_v1 = [
                ChunkDraft(
                    chunk_level="child",
                    chunk_index=i,
                    parent_index=i // 2,  # Distribute among parents
                    content=f"Child {i}",
                    content_hash=_sha256(f"Child {i}"),
                    token_count=5,
                )
                for i in range(5)
            ]

            plan_v1 = ChunkPlan(
                document=doc_v1,
                parents=parents_v1,
                children=children_v1,
            )

            # Inject plan via StaticChunker
            service.chunker = StaticChunker(plan_v1)

            result_v1 = await service.ingest_sources([doc_v1], dry_run=False)
            assert result_v1.inserted_sources == 1
            assert result_v1.parent_chunks == 3
            assert result_v1.child_chunks == 5

            # Manually delete 1 child from database (simulate incomplete state)
            with integration_pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM rag_chunks
                        WHERE id = (
                            SELECT c.id
                            FROM rag_chunks AS c
                            WHERE c.source_id = (
                                SELECT s.id
                                FROM rag_sources AS s
                                WHERE s.source_key = %s
                            )
                            AND c.chunk_level = 'child'
                            ORDER BY c.chunk_index
                            LIMIT 1
                        )
                        RETURNING id
                        """,
                        (source_key,),
                    )
                    deleted_rows = cur.fetchall()
                    assert len(deleted_rows) == 1, f"Expected RETURNING to produce 1 row, got {len(deleted_rows)}"
                    conn.commit()

            # Verify deletion left 4 children before invoking repair
            with integration_pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM rag_chunks
                        WHERE source_id = (SELECT id FROM rag_sources WHERE source_key = %s)
                        AND chunk_level = 'child'
                        """,
                        (source_key,),
                    )
                    count = cur.fetchone()[0]
                    assert count == 4, f"Expected 4 children after deletion, got {count}"

            # Version 2: Ingest same content (same hash)
            doc_v2 = LoadedDocument(
                source_key=source_key,
                source_type="project_document",
                title="Test",
                source_path="test.txt",
                content=content,  # Same content!
                content_hash=_sha256(content),  # Same hash!
            )

            plan_v2 = ChunkPlan(
                document=doc_v2,
                parents=parents_v1,  # Same structure
                children=children_v1,
            )

            # Inject same plan via StaticChunker
            service.chunker = StaticChunker(plan_v2)

            result_v2 = await service.ingest_sources([doc_v2], dry_run=False)

            # Verify it was marked updated/repaired, not unchanged
            assert result_v2.updated_sources == 1, (
                f"Expected updated=1, got updated={result_v2.updated_sources} "
                f"unchanged={result_v2.unchanged_sources}"
            )
            assert result_v2.unchanged_sources == 0
            assert result_v2.parent_chunks == 3
            assert result_v2.child_chunks == 5

            # Verify all 5 children restored
            with integration_pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM rag_chunks
                        WHERE source_id = (SELECT id FROM rag_sources WHERE source_key = %s)
                        AND chunk_level = 'child'
                        """,
                        (source_key,),
                    )
                    count = cur.fetchone()[0]
                    assert count == 5, f"Expected 5 children, got {count}"

        finally:
            _cleanup_test_sources(integration_pool)
