from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

import app.main
from app.config import Settings


class FakePool:
    """Lightweight fake database pool for testing."""

    def open(self):
        """Simulate pool opening without creating connections."""
        pass

    def close(self):
        """Simulate pool closing."""
        pass


@pytest.fixture(autouse=True)
def isolated_app(monkeypatch):
    """
    Isolation fixture that patches all database dependencies BEFORE TestClient
    enters the app lifespan. This prevents any real database connections.

    Applied automatically to all tests in this module (autouse=True).
    Individual tests can override the check_database behavior by using
    monkeypatch within the fixture's context.
    """
    # Mock environment to avoid ConfigurationError
    monkeypatch.setenv("RAG_DB_PASSWORD", "test_password")

    # Create mock settings
    mock_settings = Settings.from_env()

    # Create fake pool
    fake_pool = FakePool()

    # Default successful check_database result
    successful_database_status = {
        "database": "coding_agent_rag",
        "database_user": "rag_user",
        "vector_version": "0.8.6",
        "sources_table": True,
        "chunks_table": True,
        "migrations_table": True,
    }

    def default_mock_create_pool(settings):
        return fake_pool

    def default_mock_check_database(pool, *, timeout_seconds):
        return successful_database_status

    # Patch BEFORE any test runs (autouse fixture)
    monkeypatch.setattr(
        "app.main.create_pool",
        default_mock_create_pool,
    )
    monkeypatch.setattr(
        "app.main.check_database",
        default_mock_check_database,
    )
    monkeypatch.setattr(
        "app.main.Settings.from_env",
        lambda: mock_settings,
    )
    monkeypatch.setattr(
        "app.main.EmbeddingService",
        lambda settings: None,
    )

    # Yield to allow test to run with patches in place
    yield {
        "fake_pool": fake_pool,
        "mock_settings": mock_settings,
        "successful_database_status": successful_database_status,
    }


def test_health_is_independent_of_database() -> None:
    """Test /health endpoint is independent of database."""
    with TestClient(app.main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "coding-agent-workspace-rag",
        "version": "0.1.0",
    }


def test_ready_checks_database_and_schema() -> None:
    """Test /ready endpoint returns 200 when database is healthy."""
    with TestClient(app.main.app) as client:
        response = client.get("/ready")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["service"] == "coding-agent-workspace-rag"

    database = payload["database"]

    assert database["database"] == "coding_agent_rag"
    assert database["database_user"] == "rag_user"
    assert database["vector_version"] == "0.8.6"
    assert database["sources_table"] is True
    assert database["chunks_table"] is True
    assert database["migrations_table"] is True


def test_ready_returns_503_when_database_check_fails(monkeypatch) -> None:
    """Test /ready returns 503 when database check raises an exception."""
    def mock_check_database_error(pool, *, timeout_seconds):
        raise Exception("Connection timeout")

    monkeypatch.setattr(
        "app.main.check_database",
        mock_check_database_error,
    )

    with TestClient(app.main.app) as client:
        response = client.get("/ready")

    assert response.status_code == 503

    payload = response.json()

    assert payload["status"] == "service_down"
    assert payload["component"] == "database"
    assert "failed" in payload["message"].lower()


def test_ready_returns_503_when_schema_incomplete(monkeypatch) -> None:
    """Test /ready returns 503 when required schema is missing."""
    # Mock database status with missing vector_version
    incomplete_database_status = {
        "database": "coding_agent_rag",
        "database_user": "rag_user",
        "vector_version": None,  # Missing pgvector
        "sources_table": True,
        "chunks_table": True,
        "migrations_table": True,
    }

    def mock_check_database(pool, *, timeout_seconds):
        return incomplete_database_status

    monkeypatch.setattr(
        "app.main.check_database",
        mock_check_database,
    )

    with TestClient(app.main.app) as client:
        response = client.get("/ready")

    assert response.status_code == 503

    payload = response.json()

    assert payload["status"] == "service_down"
    assert payload["component"] == "database_schema"
    assert "incomplete" in payload["message"].lower()


def test_ready_returns_503_when_sources_table_missing(monkeypatch) -> None:
    """Test /ready returns 503 when rag_sources table is missing."""
    # Mock database status with missing sources table
    missing_table_status = {
        "database": "coding_agent_rag",
        "database_user": "rag_user",
        "vector_version": "0.8.6",
        "sources_table": False,  # Missing table
        "chunks_table": True,
        "migrations_table": True,
    }

    def mock_check_database(pool, *, timeout_seconds):
        return missing_table_status

    monkeypatch.setattr(
        "app.main.check_database",
        mock_check_database,
    )

    with TestClient(app.main.app) as client:
        response = client.get("/ready")

    assert response.status_code == 503

    payload = response.json()

    assert payload["status"] == "service_down"
    assert payload["component"] == "database_schema"