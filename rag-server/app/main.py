from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import (
    ConfigurationError,
    Settings,
)
from .database import (
    DatabasePool,
    check_database,
    create_pool,
)
from .schemas import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingStatusResponse,
    HealthResponse,
    ReadinessResponse,
)
from .embedding import (
    EmbeddingInputError,
    EmbeddingService,
)
from .retrieval import router as retrieval_router


LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:
    pool: DatabasePool | None = None

    app.state.settings = None
    app.state.db_pool = None
    app.state.configuration_error = None
    app.state.embedding_service = None

    try:
        settings = Settings.from_env()
        embedding_service = EmbeddingService(
            settings
        )
        app.state.embedding_service = (
            embedding_service
        )
        pool = create_pool(settings)

        # Start background pool workers without making
        # API startup depend on database availability.
        pool.open()

        app.state.settings = settings
        app.state.db_pool = pool
    except ConfigurationError as exc:
        app.state.configuration_error = str(exc)
        LOGGER.error(
            "RAG configuration is invalid: %s",
            exc,
        )

    try:
        yield
    finally:
        if pool is not None:
            pool.close()


app = FastAPI(
    title="Coding Agent Workspace RAG",
    version="0.1.0",
    description=(
        "Private local RAG service for "
        "coding-agent-workspace."
    ),
    lifespan=lifespan,
)

app.include_router(retrieval_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "coding-agent-workspace-rag",
        "endpoints": {
            "health": "/health",
            "ready": "/ready",
            "docs": "/docs",
        },
    }


@app.get(
    "/health",
    response_model=HealthResponse,
)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="coding-agent-workspace-rag",
        version="0.1.0",
    )


@app.get(
    "/ready",
    response_model=None,
)
def ready(
    request: Request,
) -> ReadinessResponse | JSONResponse:
    configuration_error = getattr(
        request.app.state,
        "configuration_error",
        None,
    )

    if configuration_error:
        return JSONResponse(
            status_code=503,
            content={
                "status": "service_down",
                "component": "configuration",
                "message": (
                    "RAG configuration is invalid"
                ),
            },
        )

    settings: Settings | None = getattr(
        request.app.state,
        "settings",
        None,
    )
    pool: DatabasePool | None = getattr(
        request.app.state,
        "db_pool",
        None,
    )

    if settings is None or pool is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "service_down",
                "component": "database",
                "message": (
                    "Database pool is unavailable"
                ),
            },
        )

    try:
        database_status = check_database(
            pool,
            timeout_seconds=(
                settings.db_timeout_seconds
            ),
        )
    except Exception as exc:
        LOGGER.warning(
            "Database readiness check failed: %s",
            type(exc).__name__,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "service_down",
                "component": "database",
                "message": (
                    "Database readiness check failed"
                ),
            },
        )

    required_checks = (
        database_status["vector_version"],
        database_status["sources_table"],
        database_status["chunks_table"],
        database_status["migrations_table"],
    )

    if not all(required_checks):
        return JSONResponse(
            status_code=503,
            content={
                "status": "service_down",
                "component": "database_schema",
                "message": (
                    "Required RAG schema is incomplete"
                ),
            },
        )

    return ReadinessResponse(
        status="ok",
        service=settings.service_name,
        database=database_status,
    )

@app.get(
    "/v1/embeddings/status",
    response_model=EmbeddingStatusResponse,
)
def embedding_status(
    request: Request,
) -> EmbeddingStatusResponse | JSONResponse:
    service: EmbeddingService | None = getattr(
        request.app.state,
        "embedding_service",
        None,
    )

    if service is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "service_down",
                "component": "embedding_model",
                "message": (
                    "Embedding service is unavailable"
                ),
            },
        )

    return EmbeddingStatusResponse(
        **service.describe()
    )


@app.post(
    "/v1/embeddings",
    response_model=None,
)
def create_embeddings(
    payload: EmbeddingRequest,
    request: Request,
) -> EmbeddingResponse | JSONResponse:
    service: EmbeddingService | None = getattr(
        request.app.state,
        "embedding_service",
        None,
    )

    if service is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "service_down",
                "component": "embedding_model",
                "message": (
                    "Embedding service is unavailable"
                ),
            },
        )

    try:
        result = service.encode(
            payload.texts
        )
    except EmbeddingInputError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "status": "invalid_request",
                "message": str(exc),
            },
        )
    except Exception as exc:
        LOGGER.warning(
            "Embedding generation failed: %s",
            type(exc).__name__,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "service_down",
                "component": "embedding_model",
                "message": (
                    "Embedding generation failed"
                ),
            },
        )

    return EmbeddingResponse(
        status="ok",
        model=result.model,
        dimensions=result.dimensions,
        count=len(result.embeddings),
        normalized=True,
        elapsed_ms=result.elapsed_ms,
        embeddings=result.embeddings,
    )