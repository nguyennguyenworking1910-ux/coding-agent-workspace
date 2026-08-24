from __future__ import annotations

import logging
import time
from typing import Any

from ..database import DatabasePool
from ..embedding import EmbeddingService
from .models import SearchRequest, SearchResponse, SearchResult
from .repository import RetrievalRepository

LOGGER = logging.getLogger(__name__)

RRF_CONSTANT = 60


class RetrievalService:
    def __init__(
        self,
        pool: DatabasePool,
        embedding_service: EmbeddingService,
    ) -> None:
        self._pool = pool
        self._embedding_service = embedding_service
        self._repo = RetrievalRepository(pool)

    def search(
        self,
        request: SearchRequest,
    ) -> SearchResponse:
        started_at = time.perf_counter()

        try:
            embedding_result = (
                self._embedding_service.encode(
                    [request.query]
                )
            )
            query_embedding = (
                embedding_result.embeddings[0]
            )

            if (
                len(query_embedding)
                != self._embedding_service._settings.embedding_dimension
            ):
                LOGGER.warning(
                    "Embedding dimension mismatch: %d",
                    len(query_embedding),
                )
                return SearchResponse(
                    results=[],
                    result_count=0,
                    embedding_model=(
                        embedding_result.model
                    ),
                    elapsed_ms=int(
                        (
                            time.perf_counter()
                            - started_at
                        )
                        * 1000
                    ),
                )
        except Exception as exc:
            LOGGER.error(
                "Search failed: phase=embedding error=%s",
                type(exc).__name__,
                exc_info=False,
            )
            return SearchResponse(
                results=[],
                result_count=0,
                embedding_model=(
                    self._embedding_service._settings.embedding_model
                ),
                elapsed_ms=int(
                    (
                        time.perf_counter()
                        - started_at
                    )
                    * 1000
                ),
            )

        try:
            vector_candidates = (
                self._repo.vector_search(
                    query_embedding,
                    request.candidate_k,
                    request.source_types or None,
                    request.source_keys or None,
                )
            )
        except Exception as exc:
            LOGGER.error(
                "Search failed: phase=vector_search error=%s",
                type(exc).__name__,
                exc_info=False,
            )
            raise

        try:
            text_candidates = (
                self._repo.full_text_search(
                    request.query,
                    request.candidate_k,
                    request.source_types or None,
                    request.source_keys or None,
                )
            )
        except Exception as exc:
            LOGGER.error(
                "Search failed: phase=text_search error=%s",
                type(exc).__name__,
                exc_info=False,
            )
            raise

        vector_candidate_count = len(
            vector_candidates
        )
        text_candidate_count = len(
            text_candidates
        )

        LOGGER.debug(
            "Search candidates: "
            "vector_count=%d text_count=%d",
            vector_candidate_count,
            text_candidate_count,
        )

        try:
            fused_scores = self._fuse_candidates(
                vector_candidates,
                text_candidates,
            )
        except Exception as exc:
            LOGGER.error(
                "Search failed: phase=fusion error=%s",
                type(exc).__name__,
                exc_info=False,
            )
            raise

        fused_child_count = len(fused_scores)

        LOGGER.debug(
            "Search fusion: fused_child_count=%d",
            fused_child_count,
        )

        try:
            unique_parents = self._get_unique_parents(
                fused_scores,
                request.top_k,
            )

            fused_parent_count = len(
                unique_parents
            )

            LOGGER.debug(
                "Search parents before hydration: "
                "fused_parent_count=%d",
                fused_parent_count,
            )

            parent_ids = [
                parent_id for parent_id, _ in (
                    unique_parents
                )
            ]

            parent_map = self._repo.get_parent_content(
                parent_ids
            )

            hydrated_parent_count = len(
                parent_map
            )

            LOGGER.debug(
                "Search parents after hydration: "
                "requested=%d hydrated=%d",
                len(parent_ids),
                hydrated_parent_count,
            )
        except Exception as exc:
            LOGGER.error(
                "Search failed: phase=parent_hydration error=%s",
                type(exc).__name__,
                exc_info=False,
            )
            raise

        try:
            results = []
            for rank, (
                parent_id,
                score_info,
            ) in enumerate(
                unique_parents,
                start=1,
            ):
                parent = parent_map.get(parent_id)
                if parent is None:
                    LOGGER.debug(
                        "Skipping missing parent: "
                        "parent_id_type=%s",
                        type(parent_id).__name__,
                    )
                    continue

                if (
                    parent["source_id"]
                    != score_info["source_id"]
                ):
                    LOGGER.debug(
                        "Skipping parent with mismatched source"
                    )
                    continue

                result = SearchResult(
                    rank=rank,
                    source_key=(
                        parent["source_key"]
                    ),
                    source_type=(
                        parent["source_type"]
                    ),
                    title=parent["title"],
                    parent_chunk_id=parent_id,
                    parent_chunk_index=(
                        parent["parent_chunk_index"]
                    ),
                    content=parent["content"],
                    score=float(
                        score_info["combined_score"]
                    ),
                    vector_score=float(
                        score_info[
                            "vector_contribution"
                        ]
                    ),
                    text_score=float(
                        score_info[
                            "text_contribution"
                        ]
                    ),
                )
                results.append(result)

            response_result_count = len(results)

            LOGGER.debug(
                "Search results: count=%d",
                response_result_count,
            )
        except Exception as exc:
            LOGGER.error(
                "Search failed: phase=response_mapping error=%s",
                type(exc).__name__,
                exc_info=False,
            )
            raise

        elapsed_ms = int(
            (
                time.perf_counter() - started_at
            )
            * 1000
        )

        return SearchResponse(
            results=results,
            result_count=len(results),
            embedding_model=(
                embedding_result.model
            ),
            elapsed_ms=elapsed_ms,
        )

    def _fuse_candidates(
        self,
        vector_candidates: list[dict[str, Any]],
        text_candidates: list[dict[str, Any]],
    ) -> dict[str, tuple[str, dict[str, float]]]:
        candidate_scores: dict[
            str, dict[str, Any]
        ] = {}

        for candidate in vector_candidates:
            child_id = candidate["child_id"]
            vector_rank = candidate["vector_rank"]
            vector_contribution = (
                1.0 / (RRF_CONSTANT + vector_rank)
            )

            if child_id not in candidate_scores:
                candidate_scores[child_id] = {
                    "parent_id": candidate[
                        "parent_id"
                    ],
                    "source_id": candidate[
                        "source_id"
                    ],
                    "vector_contribution": (
                        vector_contribution
                    ),
                    "text_contribution": 0.0,
                }
            else:
                candidate_scores[child_id][
                    "vector_contribution"
                ] = vector_contribution

        for candidate in text_candidates:
            child_id = candidate["child_id"]
            text_rank_position = candidate[
                "text_rank_position"
            ]
            text_contribution = (
                1.0 / (RRF_CONSTANT + text_rank_position)
            )

            if child_id not in candidate_scores:
                candidate_scores[child_id] = {
                    "parent_id": candidate[
                        "parent_id"
                    ],
                    "source_id": candidate[
                        "source_id"
                    ],
                    "vector_contribution": 0.0,
                    "text_contribution": (
                        text_contribution
                    ),
                }
            else:
                candidate_scores[child_id][
                    "text_contribution"
                ] = text_contribution

        parent_scores: dict[
            str, dict[str, Any]
        ] = {}

        for child_id, child_score in (
            candidate_scores.items()
        ):
            parent_id = child_score["parent_id"]
            source_id = child_score["source_id"]
            combined = (
                child_score["vector_contribution"]
                + child_score["text_contribution"]
            )

            if parent_id not in parent_scores:
                parent_scores[parent_id] = {
                    "source_id": source_id,
                    "combined_score": combined,
                    "vector_contribution": child_score[
                        "vector_contribution"
                    ],
                    "text_contribution": child_score[
                        "text_contribution"
                    ],
                }
            else:
                if (
                    combined
                    > parent_scores[parent_id][
                        "combined_score"
                    ]
                ):
                    parent_scores[parent_id][
                        "combined_score"
                    ] = combined
                    parent_scores[parent_id][
                        "vector_contribution"
                    ] = child_score[
                        "vector_contribution"
                    ]
                    parent_scores[parent_id][
                        "text_contribution"
                    ] = child_score[
                        "text_contribution"
                    ]

        sorted_parents = sorted(
            parent_scores.items(),
            key=lambda x: (
                -x[1]["combined_score"],
                x[0],
            ),
        )

        return dict(sorted_parents)

    def _get_unique_parents(
        self,
        fused_scores: dict[
            str,
            dict[str, Any],
        ],
        top_k: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        return list(
            fused_scores.items()
        )[:top_k]
