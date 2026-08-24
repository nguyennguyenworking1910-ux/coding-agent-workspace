from __future__ import annotations

import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..database import DatabasePool
from ..embedding import EmbeddingService
from .models import SearchRequest, SearchResponse
from .service import RetrievalService

LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1",
    tags=["search"],
)


@router.post(
    "/search",
    response_model=None,
)
def search(
    payload: SearchRequest,
    request: Request,
) -> SearchResponse | JSONResponse:
    pool: DatabasePool | None = getattr(
        request.app.state,
        "db_pool",
        None,
    )
    embedding_service: EmbeddingService | None = (
        getattr(
            request.app.state,
            "embedding_service",
            None,
        )
    )

    if pool is None or embedding_service is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "service_down",
                "component": "retrieval",
                "message": (
                    "Retrieval service is unavailable"
                ),
            },
        )

    try:
        service = RetrievalService(
            pool,
            embedding_service,
        )
        result = service.search(payload)
        return result
    except Exception as exc:
        LOGGER.error(
            "Search failed in endpoint: phase=%s error=%s",
            getattr(exc, "phase", "unknown"),
            type(exc).__name__,
            exc_info=False,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "service_down",
                "component": "search",
                "message": "Search operation failed",
            },
        )
