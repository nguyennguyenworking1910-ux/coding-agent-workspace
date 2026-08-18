from fastapi.testclient import TestClient

from app.embedding import EmbeddingResult
from app.main import app


class FakeEmbeddingService:
    def describe(self):
        return {
            "status": "loaded",
            "model": "BAAI/bge-m3",
            "device": "cpu",
            "dimensions": 1024,
            "max_length": 1024,
        }

    def encode(
        self,
        texts: list[str],
    ) -> EmbeddingResult:
        vector = [1.0] + [0.0] * 1023

        return EmbeddingResult(
            model="BAAI/bge-m3",
            dimensions=1024,
            embeddings=[
                vector
                for _ in texts
            ],
            elapsed_ms=1.0,
        )


def test_embedding_api_contract() -> None:
    with TestClient(app) as client:
        original_service = (
            app.state.embedding_service
        )

        app.state.embedding_service = (
            FakeEmbeddingService()
        )

        try:
            status_response = client.get(
                "/v1/embeddings/status"
            )

            assert status_response.status_code == 200
            assert (
                status_response.json()["status"]
                == "loaded"
            )

            response = client.post(
                "/v1/embeddings",
                json={
                    "texts": [
                        "RAG lưu lịch sử chat tiếng Việt."
                    ]
                },
            )

            assert response.status_code == 200

            payload = response.json()

            assert payload["status"] == "ok"
            assert payload["dimensions"] == 1024
            assert payload["count"] == 1
            assert payload["normalized"] is True
            assert (
                len(payload["embeddings"][0])
                == 1024
            )

            invalid_response = client.post(
                "/v1/embeddings",
                json={
                    "texts": ["   "]
                },
            )

            assert (
                invalid_response.status_code
                == 422
            )

        finally:
            app.state.embedding_service = (
                original_service
            )