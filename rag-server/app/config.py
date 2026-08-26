from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE, override=False)


class ConfigurationError(RuntimeError):
    """Raised when required RAG configuration is invalid."""


def _read_int(
    name: str,
    default: int,
    *,
    minimum: int = 1,
) -> int:
    raw_value = os.getenv(name, str(default))

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be an integer"
        ) from exc

    if value < minimum:
        raise ConfigurationError(
            f"{name} must be at least {minimum}"
        )

    return value


@dataclass(frozen=True, slots=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str

    db_password: str | None = field(
        default=None,
        repr=False,
    )
    database_url_override: str | None = field(
        default=None,
        repr=False,
    )

    api_host: str = "127.0.0.1"
    api_port: int = 8200

    pool_min_size: int = 1
    pool_max_size: int = 5
    db_timeout_seconds: int = 5

    service_name: str = "coding-agent-workspace-rag"
    service_version: str = "0.1.0"
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    embedding_dimension: int = 1024
    embedding_max_length: int = 1024
    embedding_batch_size: int = 4
    embedding_max_batch_size: int = 16
    embedding_max_text_chars: int = 8000
    torch_num_threads: int = 4
    model_cache_path: str = "rag-server/.model-cache"

    # RAG API settings for ingestion
    api_base_url: str = "http://127.0.0.1:8200"
    api_timeout_seconds: int = 900
    ingest_max_children_per_source: int = 2000

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            db_host=os.getenv(
                "RAG_DB_HOST",
                "127.0.0.1",
            ),
            db_port=_read_int(
                "RAG_DB_PORT",
                5434,
            ),
            db_name=os.getenv(
                "RAG_DB_NAME",
                "coding_agent_rag",
            ),
            db_user=os.getenv(
                "RAG_DB_USER",
                "rag_user",
            ),
            db_password=os.getenv(
                "RAG_DB_PASSWORD"
            ),
            database_url_override=os.getenv(
                "RAG_DATABASE_URL"
            ),
            api_host=os.getenv(
                "RAG_API_HOST",
                "127.0.0.1",
            ),
            api_port=_read_int(
                "RAG_API_PORT",
                8200,
            ),
            pool_min_size=_read_int(
                "RAG_DB_POOL_MIN_SIZE",
                1,
            ),
            pool_max_size=_read_int(
                "RAG_DB_POOL_MAX_SIZE",
                5,
            ),
            db_timeout_seconds=_read_int(
                "RAG_DB_TIMEOUT_SECONDS",
                5,
            ),
            embedding_model=os.getenv(
                "RAG_EMBEDDING_MODEL",
                "BAAI/bge-m3",
            ),
            embedding_device=os.getenv(
                "RAG_EMBEDDING_DEVICE",
                "cpu",
            ),
            embedding_dimension=_read_int(
                "RAG_EMBEDDING_DIMENSION",
                1024,
            ),
            embedding_max_length=_read_int(
                "RAG_EMBEDDING_MAX_LENGTH",
                1024,
            ),
            embedding_batch_size=_read_int(
                "RAG_EMBEDDING_BATCH_SIZE",
                4,
            ),
            embedding_max_batch_size=_read_int(
                "RAG_EMBEDDING_MAX_BATCH_SIZE",
                16,
            ),
            embedding_max_text_chars=_read_int(
                "RAG_EMBEDDING_MAX_TEXT_CHARS",
                8000,
            ),
            torch_num_threads=_read_int(
                "RAG_TORCH_NUM_THREADS",
                4,
            ),
            model_cache_path=os.getenv(
                "RAG_MODEL_CACHE",
                "rag-server/.model-cache",
            ),
            api_base_url=os.getenv(
                "RAG_API_BASE_URL",
                "http://127.0.0.1:8200",
            ),
            api_timeout_seconds=_read_int(
                "RAG_INGEST_API_TIMEOUT_SECONDS",
                900,
            ),
            ingest_max_children_per_source=_read_int(
                "RAG_INGEST_MAX_CHILDREN_PER_SOURCE",
                2000,
            ),
        )

        if (
            settings.pool_max_size
            < settings.pool_min_size
        ):
            raise ConfigurationError(
                "RAG_DB_POOL_MAX_SIZE must be greater "
                "than or equal to RAG_DB_POOL_MIN_SIZE"
            )

        if (
            not settings.database_url_override
            and not settings.db_password
        ):
            raise ConfigurationError(
                "RAG_DB_PASSWORD is required when "
                "RAG_DATABASE_URL is not configured"
            )

        if settings.embedding_dimension != 1024:
            raise ConfigurationError(
                "RAG_EMBEDDING_DIMENSION must be 1024 "
                "because rag_chunks.embedding is vector(1024)"
            )

        if (
            settings.embedding_batch_size
            > settings.embedding_max_batch_size
        ):
            raise ConfigurationError(
                "RAG_EMBEDDING_BATCH_SIZE cannot exceed "
                "RAG_EMBEDDING_MAX_BATCH_SIZE"
            )

        if settings.embedding_max_batch_size > 32:
            raise ConfigurationError(
                "RAG_EMBEDDING_MAX_BATCH_SIZE cannot exceed 32"
            )

        return settings

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override

        if not self.db_password:
            raise ConfigurationError(
                "RAG_DB_PASSWORD is not configured"
            )

        user = quote(self.db_user, safe="")
        password = quote(
            self.db_password,
            safe="",
        )
        database = quote(
            self.db_name,
            safe="",
        )

        return (
            f"postgresql://{user}:{password}"
            f"@{self.db_host}:{self.db_port}"
            f"/{database}"
        )

    @property
    def model_cache_dir(self) -> Path:
        configured_path = Path(
            self.model_cache_path
        )

        if not configured_path.is_absolute():
            configured_path = (
                PROJECT_ROOT / configured_path
            )

        return configured_path.resolve()