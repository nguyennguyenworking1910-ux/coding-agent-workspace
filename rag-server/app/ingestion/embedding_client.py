"""HTTP embedding client for RAG documents."""

from __future__ import annotations

import asyncio
import httpx
import json
import logging
import math
from dataclasses import dataclass
from typing import Protocol

from ..config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    """Response from embedding API."""

    model: str
    dimensions: int
    embeddings: list[list[float]]


class EmbeddingClient(Protocol):
    """Protocol for embedding clients."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings (one per text)

        Raises:
            ValueError: If embedding fails
        """
        ...


class HttpEmbeddingClient:
    """HTTP client for embedding texts via RAG API."""

    def __init__(
        self,
        api_base_url: str,
        api_timeout_seconds: int,
        embedding_batch_size: int,
        settings: Settings | None = None,
    ):
        """Initialize HTTP embedding client.

        Args:
            api_base_url: Base URL of embedding API (e.g., http://127.0.0.1:8200)
            api_timeout_seconds: Timeout for API requests in seconds
            embedding_batch_size: Maximum batch size for embeddings
            settings: Optional Settings object for embedding model and dimension
        """
        self.api_base_url = api_base_url.rstrip("/")
        self.api_timeout_seconds = api_timeout_seconds
        self.embedding_batch_size = embedding_batch_size
        self.settings = settings or Settings.from_env()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts by batching requests to API.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings (one per text, in order)

        Raises:
            ValueError: If API call fails or response is invalid
        """
        if not texts:
            return []

        # Log request at INFO level (safe)
        logger.info(
            f"Embedding {len(texts)} texts in batches of {self.embedding_batch_size}"
        )

        # Split into batches
        batches = self._split_into_batches(texts, self.embedding_batch_size)
        all_embeddings = []

        # Process each batch
        for batch_idx, batch in enumerate(batches):
            logger.info(
                f"Processing batch {batch_idx + 1}/{len(batches)} with {len(batch)} texts"
            )
            try:
                batch_embeddings = await self._embed_batch(batch)
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                logger.warning(
                    f"Embedding failed for batch {batch_idx + 1}: "
                    f"{type(e).__name__} (batch_size={len(batch)})"
                )
                raise

        logger.info(f"Successfully embedded all {len(texts)} texts")
        return all_embeddings

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch of texts.

        Args:
            texts: List of texts (should be <= batch_size)

        Returns:
            List of embeddings

        Raises:
            ValueError: If API call fails or response is invalid
        """
        url = f"{self.api_base_url}/v1/embeddings"

        async with httpx.AsyncClient(timeout=self.api_timeout_seconds) as client:
            try:
                response = await client.post(
                    url,
                    json={"texts": texts},
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise ValueError(f"HTTP request failed: {e}") from e

        # Parse response
        try:
            data = response.json()
        except Exception as e:
            raise ValueError(f"Failed to parse API response: {e}") from e

        # Validate response structure
        embedding_response = self._validate_response(data, len(texts))

        return embedding_response.embeddings

    def _validate_response(
        self,
        data: dict,
        expected_count: int,
    ) -> EmbeddingResponse:
        """Validate embedding API response.

        Args:
            data: Response JSON data
            expected_count: Expected number of embeddings

        Returns:
            Validated EmbeddingResponse

        Raises:
            ValueError: If response is invalid
        """
        # Check required fields
        try:
            model = data.get("model")
            dimensions = data.get("dimensions")
            embeddings = data.get("embeddings")

            if model is None or dimensions is None or embeddings is None:
                raise ValueError("Missing required fields (model, dimensions, embeddings)")

            # Validate model matches settings
            if model != self.settings.embedding_model:
                raise ValueError(
                    f"Invalid model '{model}': expected '{self.settings.embedding_model}'"
                )

            # Validate dimensions matches settings
            if dimensions != self.settings.embedding_dimension:
                raise ValueError(
                    f"Invalid dimensions {dimensions}: expected {self.settings.embedding_dimension}"
                )

            # Validate embedding count
            if len(embeddings) != expected_count:
                raise ValueError(
                    f"Received {len(embeddings)} embeddings, "
                    f"expected {expected_count}"
                )

            # Validate each embedding
            self._validate_embeddings(embeddings, self.settings.embedding_dimension)

            logger.info(
                f"Validated response: model={model}, "
                f"dimensions={dimensions}, count={len(embeddings)}"
            )

            return EmbeddingResponse(
                model=model,
                dimensions=dimensions,
                embeddings=embeddings,
            )

        except (KeyError, TypeError) as e:
            raise ValueError(f"Invalid response structure: {e}") from e

    @staticmethod
    def _validate_embeddings(embeddings: list, expected_dimension: int = 1024) -> None:
        """Validate embedding vectors.

        Args:
            embeddings: List of embedding vectors
            expected_dimension: Expected number of dimensions per embedding

        Raises:
            ValueError: If any embedding is invalid
        """
        for idx, embedding in enumerate(embeddings):
            if not isinstance(embedding, (list, tuple)):
                raise ValueError(
                    f"Embedding {idx} is not a list/tuple"
                )

            if len(embedding) != expected_dimension:
                raise ValueError(
                    f"Embedding {idx} has {len(embedding)} dimensions, "
                    f"expected {expected_dimension}"
                )

            for val_idx, val in enumerate(embedding):
                if not isinstance(val, (int, float)):
                    raise ValueError(
                        f"Embedding {idx}[{val_idx}] is not numeric"
                    )

                # Check for NaN or infinity
                if math.isnan(float(val)) or math.isinf(float(val)):
                    raise ValueError(
                        f"Embedding {idx}[{val_idx}] is NaN or inf"
                    )

    @staticmethod
    def _split_into_batches(
        texts: list[str],
        batch_size: int,
    ) -> list[list[str]]:
        """Split texts into batches.

        Args:
            texts: List of texts
            batch_size: Maximum batch size

        Returns:
            List of batches
        """
        batches = []
        for i in range(0, len(texts), batch_size):
            batches.append(texts[i : i + batch_size])
        return batches
