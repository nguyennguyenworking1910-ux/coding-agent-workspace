import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_independent_of_database(
    client: TestClient,
) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "coding-agent-workspace-rag",
        "version": "0.1.0",
    }


def test_ready_checks_database_and_schema(
    client: TestClient,
) -> None:
    response = client.get("/ready")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "ok"

    database = payload["database"]

    assert database["database"] == (
        "coding_agent_rag"
    )
    assert database["database_user"] == (
        "rag_user"
    )
    assert database["vector_version"] == "0.8.6"
    assert database["sources_table"] is True
    assert database["chunks_table"] is True
    assert database["migrations_table"] is True