from __future__ import annotations

import time
from dataclasses import dataclass
from threading import RLock
from typing import Any

import torch
from sentence_transformers import SentenceTransformer

from .config import Settings


class EmbeddingInputError(ValueError):
    """Raised when embedding input is invalid."""


class EmbeddingModelError(RuntimeError):
    """Raised when the model output is invalid."""


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    model: str
    dimensions: int
    embeddings: list[list[float]]
    elapsed_ms: float


class EmbeddingService:
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self._settings = settings
        self._model: SentenceTransformer | None = None
        self._lock = RLock()

        torch.set_num_threads(
            settings.torch_num_threads
        )

    def describe(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": (
                    "loaded"
                    if self._model is not None
                    else "not_loaded"
                ),
                "model": (
                    self._settings.embedding_model
                ),
                "device": (
                    self._settings.embedding_device
                ),
                "dimensions": (
                    self._settings.embedding_dimension
                ),
                "max_length": (
                    self._settings.embedding_max_length
                ),
            }

    def _load_model(
        self,
    ) -> SentenceTransformer:
        if self._model is not None:
            return self._model

        self._settings.model_cache_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        model = SentenceTransformer(
            self._settings.embedding_model,
            device=self._settings.embedding_device,
            cache_folder=str(
                self._settings.model_cache_dir
            ),
        )

        model.max_seq_length = (
            self._settings.embedding_max_length
        )

        actual_dimension = (
            model.get_sentence_embedding_dimension()
        )

        if (
            actual_dimension
            != self._settings.embedding_dimension
        ):
            raise EmbeddingModelError(
                "Embedding dimension mismatch: "
                f"expected "
                f"{self._settings.embedding_dimension}, "
                f"received {actual_dimension}"
            )

        self._model = model
        return model

    def _validate_texts(
        self,
        texts: list[str],
    ) -> None:
        if not texts:
            raise EmbeddingInputError(
                "At least one text is required"
            )

        if (
            len(texts)
            > self._settings.embedding_max_batch_size
        ):
            raise EmbeddingInputError(
                "Embedding batch exceeds maximum "
                f"{self._settings.embedding_max_batch_size}"
            )

        for index, text in enumerate(texts):
            if not isinstance(text, str):
                raise EmbeddingInputError(
                    f"texts[{index}] must be a string"
                )

            if not text.strip():
                raise EmbeddingInputError(
                    f"texts[{index}] cannot be empty"
                )

            if (
                len(text)
                > self._settings.embedding_max_text_chars
            ):
                raise EmbeddingInputError(
                    f"texts[{index}] exceeds maximum "
                    f"{self._settings.embedding_max_text_chars} "
                    "characters"
                )

    def encode(
        self,
        texts: list[str],
    ) -> EmbeddingResult:
        self._validate_texts(texts)

        started_at = time.perf_counter()

        # Serialize CPU inference to avoid multiple
        # concurrent requests exhausting system memory.
        with self._lock:
            model = self._load_model()

            vectors = model.encode(
                texts,
                batch_size=(
                    self._settings.embedding_batch_size
                ),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

        if vectors.ndim != 2:
            raise EmbeddingModelError(
                "Embedding model returned invalid shape"
            )

        if (
            vectors.shape[1]
            != self._settings.embedding_dimension
        ):
            raise EmbeddingModelError(
                "Embedding model returned unexpected "
                f"dimension {vectors.shape[1]}"
            )

        elapsed_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return EmbeddingResult(
            model=self._settings.embedding_model,
            dimensions=vectors.shape[1],
            embeddings=vectors.astype(
                float
            ).tolist(),
            elapsed_ms=round(elapsed_ms, 2),
        )