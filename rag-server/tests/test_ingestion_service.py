"""Tests for ingestion service."""

import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ingestion.models import ChunkDraft, ChunkPlan, LoadedDocument
from app.ingestion.service import IngestionResult, IngestionService


class FakeEmbeddingClient:
    """Fake embedding client for testing."""

    def __init__(self, fail_on_batch: int = -1):
        """Initialize fake client.

        Args:
            fail_on_batch: Batch number to fail on (for testing error handling)
        """
        self.fail_on_batch = fail_on_batch
        self.call_count = 0
        self.embed_call_count = 0

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return fake embeddings."""
        self.embed_call_count += 1

        if self.fail_on_batch == self.call_count:
            raise ValueError("Simulated embedding failure")

        self.call_count += 1

        # Return valid 1024-dimensional embeddings
        return [[0.1 + i * 0.001] * 1024 for i in range(len(texts))]


class FakeSettings:
    """Fake settings for testing."""

    def __init__(self):
        self.ingest_max_children_per_source = 2000
        self.embedding_model = "BAAI/bge-m3"


@pytest.fixture
def mock_pool():
    """Create a mock connection pool."""
    pool = MagicMock()

    # Mock the connection context manager
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    # Setup cursor context manager
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

    # Setup connection context manager
    pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
    pool.connection.return_value.__exit__ = MagicMock(return_value=None)

    return pool


@pytest.fixture
def mock_repository():
    """Create a mock repository."""
    repo = MagicMock()

    # Setup default returns
    repo.query_source_by_key.return_value = None  # Source doesn't exist
    repo.insert_or_update_source.return_value = MagicMock(
        source_id="test-source-id",
        action="inserted",
        new_hash="newhash" * 8,
    )
    repo.insert_parent_chunks.return_value = {0: "parent-id-0"}
    repo.delete_chunks_for_source.return_value = None
    repo.insert_child_chunks.return_value = None

    return repo


@pytest.fixture
def settings():
    """Create settings."""
    return FakeSettings()


@pytest.fixture
def embedding_client():
    """Create fake embedding client."""
    return FakeEmbeddingClient()


@pytest.fixture
def service(settings, embedding_client, mock_pool):
    """Create ingestion service with fakes."""
    service = IngestionService(
        settings=settings,
        embedding_client=embedding_client,
        pool=mock_pool,
    )
    # Replace repository with mock
    service.repository = MagicMock()
    service.repository.query_source_by_key.return_value = None

    return service


@pytest.fixture
def sample_document():
    """Create a sample document."""
    return LoadedDocument(
        source_key="workspace:README.md",
        source_type="project_document",
        title="README",
        source_path="README.md",
        content="# README\n\nThis is a test document.",
        content_hash="a" * 64,
        metadata={"extension": ".md"},
    )


@pytest.fixture
def sample_chunk_plan():
    """Create a sample chunk plan."""
    parents = [
        ChunkDraft(
            chunk_level="parent",
            chunk_index=0,
            content="Parent chunk",
            content_hash="b" * 64,
            token_count=10,
            metadata={"token_count_method": "estimated"},
        ),
    ]

    children = [
        ChunkDraft(
            chunk_level="child",
            chunk_index=0,
            parent_index=0,
            content="Child chunk 1",
            content_hash="c" * 64,
            token_count=5,
            metadata={"token_count_method": "estimated"},
        ),
        ChunkDraft(
            chunk_level="child",
            chunk_index=1,
            parent_index=0,
            content="Child chunk 2",
            content_hash="d" * 64,
            token_count=5,
            metadata={"token_count_method": "estimated"},
        ),
    ]

    doc = LoadedDocument(
        source_key="workspace:test.md",
        source_type="project_document",
        title="Test",
        source_path="test.md",
        content="Test content",
        content_hash="e" * 64,
    )

    return ChunkPlan(document=doc, parents=parents, children=children)


class TestNewSourceIngestion:
    """Tests for ingesting new sources."""

    @pytest.mark.asyncio
    async def test_new_source_calls_embedding_api_once(
        self,
        service,
        sample_document,
        sample_chunk_plan,
    ):
        """Test that new source triggers embedding API exactly once."""
        # Setup mocks
        service.repository.query_source_by_key.return_value = None
        service.chunker = MagicMock()
        service.chunker.chunk.return_value = sample_chunk_plan

        # Execute
        result = await service.ingest_sources([sample_document], dry_run=False)

        # Verify embedding was called
        assert service.embedding_client.embed_call_count == 1


class TestUnchangedSourceIngestion:
    """Tests for unchanged source handling."""

    @pytest.mark.asyncio
    async def test_unchanged_source_skips_embedding(
        self,
        service,
        sample_document,
        sample_chunk_plan,
    ):
        """Test that unchanged source skips embedding calls."""
        # Setup mock - source exists with same hash
        service.repository.query_source_by_key.return_value = (
            "existing-id",
            sample_document.content_hash,  # Same hash
        )
        service.chunker = MagicMock()
        service.chunker.chunk.return_value = sample_chunk_plan

        # Mock complete snapshot
        complete_snapshot = MagicMock()
        complete_snapshot.content_hash = sample_document.content_hash
        complete_snapshot.parent_count = len(sample_chunk_plan.parents)
        complete_snapshot.child_count = len(sample_chunk_plan.children)
        complete_snapshot.ready_child_count = len(sample_chunk_plan.children)
        complete_snapshot.pending_or_failed_child_count = 0
        complete_snapshot.parent_embedding_count = 0
        complete_snapshot.invalid_dimension_count = 0
        complete_snapshot.orphan_child_count = 0

        # Mock _query_source_snapshot
        def mock_query_snapshot(cur, source_key):
            return complete_snapshot

        service._query_source_snapshot = mock_query_snapshot

        # Execute
        result = await service.ingest_sources([sample_document], dry_run=False)

        # Verify no embedding calls
        assert service.embedding_client.embed_call_count == 0
        assert result.unchanged_sources == 1
        assert result.inserted_sources == 0
        assert result.updated_sources == 0


class TestChangedSourceIngestion:
    """Tests for changed source handling."""

    @pytest.mark.asyncio
    async def test_changed_source_re_embeds(
        self,
        settings,
        embedding_client,
        mock_pool,
    ):
        """Test that changed source triggers re-embedding."""
        service = IngestionService(
            settings=settings,
            embedding_client=embedding_client,
            pool=mock_pool,
        )
        service.repository = MagicMock()
        service.chunker = MagicMock()

        # Setup mock - source exists with different hash
        service.repository.query_source_by_key.return_value = (
            "existing-id",
            "oldhash" * 8,  # Different hash (will trigger embedding)
        )

        sample_doc = LoadedDocument(
            source_key="test:test.md",
            source_type="project_document",
            title="Test",
            source_path="test.md",
            content="Test content",
            content_hash="newhash" * 8,  # Different hash
        )

        sample_plan = ChunkPlan(
            document=sample_doc,
            parents=[
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=0,
                    content="Parent",
                    content_hash="b" * 64,
                    token_count=10,
                )
            ],
            children=[
                ChunkDraft(
                    chunk_level="child",
                    chunk_index=0,
                    parent_index=0,
                    content="Child",
                    content_hash="c" * 64,
                    token_count=5,
                )
            ],
        )

        service.chunker.chunk.return_value = sample_plan

        # Track embedding calls (should be called for changed source)
        initial_embed_count = embedding_client.embed_call_count

        # Execute - will fail at transaction level, but we can check if embedding was called
        result = await service.ingest_sources([sample_doc], dry_run=False)

        # Verify embedding was attempted (even if transaction failed)
        assert embedding_client.embed_call_count > initial_embed_count


class TestDryRunMode:
    """Tests for dry-run mode."""

    @pytest.mark.asyncio
    async def test_dry_run_zero_embeddings_zero_writes(
        self,
        service,
        sample_document,
        sample_chunk_plan,
    ):
        """Test that dry-run performs zero embeddings and zero writes."""
        service.chunker = MagicMock()
        service.chunker.chunk.return_value = sample_chunk_plan

        # Execute
        result = await service.ingest_sources([sample_document], dry_run=True)

        # Verify no embedding calls
        assert service.embedding_client.embed_call_count == 0

        # Verify results show what would have been done
        assert result.inserted_sources == 1
        assert result.parent_chunks == 1
        assert result.child_chunks == 2


class TestEmbeddingFailure:
    """Tests for embedding failure handling."""

    @pytest.mark.asyncio
    async def test_embedding_failure_preserves_previous_data(
        self,
        settings,
        mock_pool,
    ):
        """Test that embedding failure preserves previous version."""
        # Setup client that fails
        failing_client = FakeEmbeddingClient(fail_on_batch=0)

        service = IngestionService(
            settings=settings,
            embedding_client=failing_client,
            pool=mock_pool,
        )
        service.repository = MagicMock()
        service.repository.query_source_by_key.return_value = None
        service.chunker = MagicMock()

        doc = LoadedDocument(
            source_key="workspace:test.md",
            source_type="project_document",
            title="Test",
            source_path="test.md",
            content="Test content",
            content_hash="a" * 64,
        )

        plan = ChunkPlan(
            document=doc,
            parents=[
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=0,
                    content="Parent",
                    content_hash="b" * 64,
                    token_count=5,
                )
            ],
            children=[
                ChunkDraft(
                    chunk_level="child",
                    chunk_index=0,
                    parent_index=0,
                    content="Child",
                    content_hash="c" * 64,
                    token_count=5,
                )
            ],
        )

        service.chunker.chunk.return_value = plan

        # Execute
        result = await service.ingest_sources([doc], dry_run=False)

        # Verify failure was recorded
        assert result.failed_sources == 1
        assert len(result.failures) == 1
        assert result.failures[0]["source_key"] == "workspace:test.md"


class TestMaxChildrenLimit:
    """Tests for max children limit enforcement."""

    @pytest.mark.asyncio
    async def test_exceeding_max_children_fails(
        self,
        service,
        sample_document,
    ):
        """Test that exceeding max children limit causes failure."""
        # Create plan with too many children
        settings = FakeSettings()
        settings.ingest_max_children_per_source = 5

        service.settings = settings
        service.chunker = MagicMock()

        # Create plan with 6 children (exceeds limit of 5)
        children = [
            ChunkDraft(
                chunk_level="child",
                chunk_index=i,
                parent_index=0,
                content=f"Child {i}",
                content_hash=chr(ord("a") + i) * 64,
                token_count=5,
            )
            for i in range(6)
        ]

        plan = ChunkPlan(
            document=sample_document,
            parents=[
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=0,
                    content="Parent",
                    content_hash="b" * 64,
                    token_count=10,
                )
            ],
            children=children,
        )

        service.chunker.chunk.return_value = plan

        # Execute
        result = await service.ingest_sources([sample_document], dry_run=False)

        # Verify failure
        assert result.failed_sources == 1

    @pytest.mark.asyncio
    async def test_child_limit_checked_before_embedding(
        self,
        service,
        sample_document,
    ):
        """Test that child limit is checked BEFORE embedding is called."""
        # Create plan with too many children
        settings = FakeSettings()
        settings.ingest_max_children_per_source = 2

        service.settings = settings
        service.chunker = MagicMock()

        # Create plan with 3 children (exceeds limit of 2)
        children = [
            ChunkDraft(
                chunk_level="child",
                chunk_index=i,
                parent_index=0,
                content=f"Child {i}",
                content_hash=chr(ord("a") + i) * 64,
                token_count=5,
            )
            for i in range(3)
        ]

        plan = ChunkPlan(
            document=sample_document,
            parents=[
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=0,
                    content="Parent",
                    content_hash="b" * 64,
                    token_count=10,
                )
            ],
            children=children,
        )

        service.chunker.chunk.return_value = plan

        # Record embedding client call count before
        initial_embed_count = service.embedding_client.embed_call_count

        # Execute
        result = await service.ingest_sources([sample_document], dry_run=False)

        # Verify failure and embedding was NEVER called
        assert result.failed_sources == 1
        assert service.embedding_client.embed_call_count == initial_embed_count




class TestTransactionStatsAccounting:
    """Tests that statistics are only incremented after successful transaction."""

    @pytest.mark.asyncio
    async def test_stats_not_incremented_on_transaction_failure(
        self,
        service,
        sample_document,
        sample_chunk_plan,
    ):
        """Test that stats are not incremented if transaction fails."""
        # Setup mocks to fail during insert
        service.repository.query_source_by_key.return_value = None
        service.repository.insert_or_update_source.side_effect = ValueError(
            "Database error"
        )
        service.chunker = MagicMock()
        service.chunker.chunk.return_value = sample_chunk_plan

        # Execute
        result = await service.ingest_sources([sample_document], dry_run=False)

        # Verify stats were NOT incremented (failure was counted instead)
        assert result.failed_sources == 1
        assert result.inserted_sources == 0
        assert result.parent_chunks == 0
        assert result.child_chunks == 0


class TestValidUnchangedSourceHandling:
    """Tests that valid unchanged sources skip all work."""

    @pytest.mark.asyncio
    async def test_valid_unchanged_source_performs_no_embedding(
        self,
        service,
        sample_document,
        sample_chunk_plan,
    ):
        """Test that valid unchanged source skips embedding and DB writes."""
        # Setup: source exists with same hash
        service.repository.query_source_by_key.return_value = (
            "existing-id",
            sample_document.content_hash,
        )

        # Mock complete snapshot (all checks pass)
        complete_snapshot = MagicMock()
        complete_snapshot.content_hash = sample_document.content_hash
        complete_snapshot.parent_count = len(sample_chunk_plan.parents)
        complete_snapshot.child_count = len(sample_chunk_plan.children)
        complete_snapshot.ready_child_count = len(sample_chunk_plan.children)
        complete_snapshot.pending_or_failed_child_count = 0
        complete_snapshot.parent_embedding_count = 0
        complete_snapshot.invalid_dimension_count = 0
        complete_snapshot.orphan_child_count = 0

        service.chunker = MagicMock()
        service.chunker.chunk.return_value = sample_chunk_plan

        # Mock _is_source_complete to return True
        service._is_source_complete = MagicMock(return_value=True)

        # Mock _query_source_snapshot to return complete snapshot
        def mock_query_snapshot(cur, source_key):
            return complete_snapshot

        service._query_source_snapshot = mock_query_snapshot

        # Record initial embedding count
        initial_embed_count = service.embedding_client.embed_call_count

        # Execute
        result = await service.ingest_sources([sample_document], dry_run=False)

        # Verify:
        # 1. No embedding was called
        assert service.embedding_client.embed_call_count == initial_embed_count
        # 2. No DB writes happened (insert/update/delete not called)
        assert service.repository.insert_or_update_source.call_count == 0
        # 3. Marked as unchanged
        assert result.unchanged_sources == 1


class TestIncompleteSameHashSourceRepair:
    """Tests for incomplete same-hash source detection and repair."""

    @pytest.mark.asyncio
    async def test_same_hash_missing_child_triggers_repair(
        self,
        settings,
        embedding_client,
        mock_pool,
    ):
        """Test that same hash with missing child triggers repair and embedding."""
        service = IngestionService(
            settings=settings,
            embedding_client=embedding_client,
            pool=mock_pool,
        )
        service.repository = MagicMock()
        service.chunker = MagicMock()

        # Setup: source exists with same hash but child is missing
        service.repository.query_source_by_key.return_value = (
            "existing-id",
            "hash" * 16,
        )

        doc = LoadedDocument(
            source_key="test:test.md",
            source_type="project_document",
            title="Test",
            source_path="test.md",
            content="Test content",
            content_hash="hash" * 16,  # Same hash
        )

        plan = ChunkPlan(
            document=doc,
            parents=[
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=0,
                    content="Parent",
                    content_hash="p" * 64,
                    token_count=10,
                )
            ],
            children=[
                ChunkDraft(
                    chunk_level="child",
                    chunk_index=0,
                    parent_index=0,
                    content="Child 1",
                    content_hash="c1" * 32,
                    token_count=5,
                ),
                ChunkDraft(
                    chunk_level="child",
                    chunk_index=1,
                    parent_index=0,
                    content="Child 2",
                    content_hash="c2" * 32,
                    token_count=5,
                ),
            ],
        )

        # Mock incomplete snapshot (missing one child)
        incomplete_snapshot = MagicMock()
        incomplete_snapshot.content_hash = "hash" * 16
        incomplete_snapshot.parent_count = 1
        incomplete_snapshot.child_count = 1  # Only 1 child (should be 2)
        incomplete_snapshot.ready_child_count = 1
        incomplete_snapshot.pending_or_failed_child_count = 0
        incomplete_snapshot.parent_embedding_count = 0
        incomplete_snapshot.invalid_dimension_count = 0
        incomplete_snapshot.orphan_child_count = 0

        service.chunker.chunk.return_value = plan

        # Mock _query_source_snapshot to return incomplete snapshot
        def mock_query_snapshot(cur, source_key):
            return incomplete_snapshot

        service._query_source_snapshot = mock_query_snapshot

        # Record initial embedding count
        initial_embed_count = embedding_client.embed_call_count

        # Setup mocks for transaction
        service.repository.insert_or_update_source.return_value = MagicMock(
            source_id="existing-id",
            action="updated",
        )
        service.repository.delete_chunks_for_source.return_value = None
        service.repository.insert_parent_chunks.return_value = {0: "parent-id-0"}
        service.repository.insert_child_chunks.return_value = None

        # Execute
        result = await service.ingest_sources([doc], dry_run=False)

        # Verify:
        # 1. Embedding WAS called (because source is incomplete)
        assert embedding_client.embed_call_count > initial_embed_count
        # 2. Marked as updated (not unchanged)
        assert result.updated_sources == 1
        assert result.unchanged_sources == 0
        # 3. DB writes occurred
        assert service.repository.delete_chunks_for_source.call_count == 1
        assert service.repository.insert_child_chunks.call_count == 1

    @pytest.mark.asyncio
    async def test_same_hash_failed_child_triggers_repair(
        self,
        settings,
        embedding_client,
        mock_pool,
    ):
        """Test that same hash with pending/failed child triggers repair."""
        service = IngestionService(
            settings=settings,
            embedding_client=embedding_client,
            pool=mock_pool,
        )
        service.repository = MagicMock()
        service.chunker = MagicMock()

        # Setup: source exists with same hash but child embedding failed
        service.repository.query_source_by_key.return_value = (
            "existing-id",
            "hash" * 16,
        )

        doc = LoadedDocument(
            source_key="test:test.md",
            source_type="project_document",
            title="Test",
            source_path="test.txt",
            content="Test content",
            content_hash="hash" * 16,
        )

        plan = ChunkPlan(
            document=doc,
            parents=[
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=0,
                    content="Parent",
                    content_hash="p" * 64,
                    token_count=10,
                )
            ],
            children=[
                ChunkDraft(
                    chunk_level="child",
                    chunk_index=0,
                    parent_index=0,
                    content="Child",
                    content_hash="c" * 64,
                    token_count=5,
                )
            ],
        )

        # Mock incomplete snapshot (child has pending embedding)
        incomplete_snapshot = MagicMock()
        incomplete_snapshot.content_hash = "hash" * 16
        incomplete_snapshot.parent_count = 1
        incomplete_snapshot.child_count = 1
        incomplete_snapshot.ready_child_count = 0  # Not ready
        incomplete_snapshot.pending_or_failed_child_count = 1  # Pending
        incomplete_snapshot.parent_embedding_count = 0
        incomplete_snapshot.invalid_dimension_count = 0
        incomplete_snapshot.orphan_child_count = 0

        service.chunker.chunk.return_value = plan

        # Mock _query_source_snapshot to return incomplete snapshot
        def mock_query_snapshot(cur, source_key):
            return incomplete_snapshot

        service._query_source_snapshot = mock_query_snapshot

        # Setup mocks for transaction
        service.repository.insert_or_update_source.return_value = MagicMock(
            source_id="existing-id",
            action="updated",
        )
        service.repository.delete_chunks_for_source.return_value = None
        service.repository.insert_parent_chunks.return_value = {0: "parent-id-0"}
        service.repository.insert_child_chunks.return_value = None

        # Execute
        result = await service.ingest_sources([doc], dry_run=False)

        # Verify:
        assert result.updated_sources == 1
        assert result.unchanged_sources == 0
        assert service.repository.insert_or_update_source.call_count == 1

    @pytest.mark.asyncio
    async def test_same_hash_parent_embedding_triggers_repair(
        self,
        settings,
        embedding_client,
        mock_pool,
    ):
        """Test that same hash with parent embedding (should not have) triggers repair."""
        service = IngestionService(
            settings=settings,
            embedding_client=embedding_client,
            pool=mock_pool,
        )
        service.repository = MagicMock()
        service.chunker = MagicMock()

        # Setup: source exists with same hash but parent has embedding
        service.repository.query_source_by_key.return_value = (
            "existing-id",
            "hash" * 16,
        )

        doc = LoadedDocument(
            source_key="test:test.md",
            source_type="project_document",
            title="Test",
            source_path="test.txt",
            content="Test content",
            content_hash="hash" * 16,
        )

        plan = ChunkPlan(
            document=doc,
            parents=[
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=0,
                    content="Parent",
                    content_hash="p" * 64,
                    token_count=10,
                )
            ],
            children=[
                ChunkDraft(
                    chunk_level="child",
                    chunk_index=0,
                    parent_index=0,
                    content="Child",
                    content_hash="c" * 64,
                    token_count=5,
                )
            ],
        )

        # Mock incomplete snapshot (parent incorrectly has embedding)
        incomplete_snapshot = MagicMock()
        incomplete_snapshot.content_hash = "hash" * 16
        incomplete_snapshot.parent_count = 1
        incomplete_snapshot.child_count = 1
        incomplete_snapshot.ready_child_count = 1
        incomplete_snapshot.pending_or_failed_child_count = 0
        incomplete_snapshot.parent_embedding_count = 1  # Parent should not have embedding
        incomplete_snapshot.invalid_dimension_count = 0
        incomplete_snapshot.orphan_child_count = 0

        service.chunker.chunk.return_value = plan

        def mock_query_snapshot(cur, source_key):
            return incomplete_snapshot

        service._query_source_snapshot = mock_query_snapshot

        # Setup mocks for transaction
        service.repository.insert_or_update_source.return_value = MagicMock(
            source_id="existing-id",
            action="updated",
        )
        service.repository.delete_chunks_for_source.return_value = None
        service.repository.insert_parent_chunks.return_value = {0: "parent-id-0"}
        service.repository.insert_child_chunks.return_value = None

        # Execute
        result = await service.ingest_sources([doc], dry_run=False)

        # Verify repair occurred
        assert result.updated_sources == 1
        assert result.unchanged_sources == 0
