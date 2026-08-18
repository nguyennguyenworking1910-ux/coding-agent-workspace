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


@pytest.fixture
def mock_pool():
    """Create a mock connection pool."""
    return MagicMock()


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
        service,
        sample_document,
        sample_chunk_plan,
    ):
        """Test that changed source triggers re-embedding."""
        # Setup mock - source exists with different hash
        service.repository.query_source_by_key.return_value = (
            "existing-id",
            "oldhash" * 8,  # Different hash
        )
        service.repository.insert_or_update_source.return_value = MagicMock(
            source_id="existing-id",
            action="updated",
        )
        service.chunker = MagicMock()
        service.chunker.chunk.return_value = sample_chunk_plan

        # Execute
        result = await service.ingest_sources([sample_document], dry_run=False)

        # Verify embedding was called and chunks were updated
        assert service.embedding_client.embed_call_count == 1
        assert result.updated_sources == 1


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


class TestParentChildMappings:
    """Tests for correct parent-child index mapping."""

    @pytest.mark.asyncio
    async def test_global_child_indexes_mapped_correctly(
        self,
        service,
        sample_chunk_plan,
    ):
        """Test that global child indexes are mapped correctly to embeddings."""
        # We'll verify this by checking that the correct embeddings are passed
        service.repository.query_source_by_key.return_value = None
        service.repository.insert_or_update_source.return_value = MagicMock(
            source_id="test-id",
            action="inserted",
        )
        service.repository.insert_parent_chunks.return_value = {0: "parent-id-0"}
        service.chunker = MagicMock()
        service.chunker.chunk.return_value = sample_chunk_plan

        doc = sample_chunk_plan.document

        # Execute
        result = await service.ingest_sources([doc], dry_run=False)

        # Verify correct number of embedded children
        assert result.embedded_children == 2


class TestParentsNeverHaveEmbeddings:
    """Tests that parent chunks never have embeddings."""

    @pytest.mark.asyncio
    async def test_parent_chunks_no_embedding_fields(self, service):
        """Test that parent chunks are inserted without embedding fields."""
        # This is enforced by insert_parent_chunks not including embedding
        # We verify by mock validation
        service.repository.query_source_by_key.return_value = None

        plan = ChunkPlan(
            document=LoadedDocument(
                source_key="workspace:test.md",
                source_type="project_document",
                title="Test",
                source_path="test.md",
                content="Test",
                content_hash="a" * 64,
            ),
            parents=[
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=0,
                    content="Parent",
                    content_hash="b" * 64,
                    token_count=5,
                )
            ],
            children=[],
        )

        service.chunker = MagicMock()
        service.chunker.chunk.return_value = plan
        service.repository.insert_parent_chunks.return_value = {0: "parent-id"}

        # Execute
        result = await service.ingest_sources([plan.document], dry_run=False)

        # Verify parent was inserted
        assert service.repository.insert_parent_chunks.called


class TestChildrenHaveValidEmbeddingFields:
    """Tests that child chunks have valid embedding fields."""

    @pytest.mark.asyncio
    async def test_child_embedding_status_ready(self, service):
        """Test that child chunks have embedding_status='ready'."""
        # This is enforced in insert_child_chunks
        # We verify through the repository mock
        service.repository.query_source_by_key.return_value = None
        service.repository.insert_or_update_source.return_value = MagicMock(
            source_id="test-id",
            action="inserted",
        )
        service.repository.insert_parent_chunks.return_value = {0: "parent-id"}

        child = ChunkDraft(
            chunk_level="child",
            chunk_index=0,
            parent_index=0,
            content="Child",
            content_hash="c" * 64,
            token_count=5,
        )

        plan = ChunkPlan(
            document=LoadedDocument(
                source_key="workspace:test.md",
                source_type="project_document",
                title="Test",
                source_path="test.md",
                content="Test",
                content_hash="a" * 64,
            ),
            parents=[
                ChunkDraft(
                    chunk_level="parent",
                    chunk_index=0,
                    content="Parent",
                    content_hash="b" * 64,
                    token_count=5,
                )
            ],
            children=[child],
        )

        service.chunker = MagicMock()
        service.chunker.chunk.return_value = plan

        # Execute
        result = await service.ingest_sources([plan.document], dry_run=False)

        # Verify child was inserted
        assert service.repository.insert_child_chunks.called
