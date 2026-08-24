from __future__ import annotations

import logging
from typing import Any

from psycopg.rows import dict_row

from ..database import DatabasePool

LOGGER = logging.getLogger(__name__)


class RetrievalRepository:
    def __init__(self, pool: DatabasePool) -> None:
        self._pool = pool

    def vector_search(
        self,
        embedding: list[float],
        candidate_k: int,
        source_types: list[str] | None = None,
        source_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            from pgvector.psycopg import Vector
            query_vector = Vector(embedding)
        except ImportError:
            LOGGER.debug(
                "pgvector not available, using fallback"
            )
            query_vector = embedding

        query = """
            SELECT
                c.id AS child_id,
                c.parent_id,
                c.source_id,
                1.0 - (c.embedding <=> $1::vector) AS similarity,
                ROW_NUMBER() OVER (
                    ORDER BY c.embedding <=> $1::vector ASC
                ) AS vector_rank
            FROM rag_chunks c
            INNER JOIN rag_sources s ON c.source_id = s.id
            WHERE
                c.chunk_level = 'child'
                AND c.embedding IS NOT NULL
                AND c.embedding_status = 'ready'
        """

        params: list[Any] = [query_vector]
        param_count = 1

        if source_types:
            param_count += 1
            params.append(source_types)
            query += f"\n                AND s.source_type = ANY(${param_count}::text[])"

        if source_keys:
            param_count += 1
            params.append(source_keys)
            query += f"\n                AND s.source_key = ANY(${param_count}::text[])"

        query += f"""
            ORDER BY c.embedding <=> $1::vector ASC
            LIMIT {candidate_k}
        """

        with self._pool.connection() as connection:
            with connection.cursor(
                row_factory=dict_row
            ) as cursor:
                cursor.execute(query, params)
                results = cursor.fetchall()

        normalized = []
        for row in (results or []):
            normalized.append({
                "child_id": str(row["child_id"]),
                "parent_id": str(row["parent_id"]),
                "source_id": str(row["source_id"]),
                "similarity": row["similarity"],
                "vector_rank": row["vector_rank"],
            })
        return normalized

    def full_text_search(
        self,
        query_text: str,
        candidate_k: int,
        source_types: list[str] | None = None,
        source_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                c.id AS child_id,
                c.parent_id,
                c.source_id,
                ts_rank_cd(c.search_vector, q) AS text_rank,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(c.search_vector, q) DESC
                ) AS text_rank_position
            FROM rag_chunks c
            INNER JOIN rag_sources s ON c.source_id = s.id,
            websearch_to_tsquery('simple', $1) AS q
            WHERE
                c.chunk_level = 'child'
                AND c.embedding_status IN ('ready', 'pending', 'failed')
                AND c.search_vector @@ q
        """

        params: list[Any] = [query_text]
        param_count = 1

        if source_types:
            param_count += 1
            params.append(source_types)
            query += f"\n                AND s.source_type = ANY(${param_count}::text[])"

        if source_keys:
            param_count += 1
            params.append(source_keys)
            query += f"\n                AND s.source_key = ANY(${param_count}::text[])"

        query += f"""
            ORDER BY ts_rank_cd(c.search_vector, q) DESC
            LIMIT {candidate_k}
        """

        with self._pool.connection() as connection:
            with connection.cursor(
                row_factory=dict_row
            ) as cursor:
                cursor.execute(query, params)
                results = cursor.fetchall()

        normalized = []
        for row in (results or []):
            normalized.append({
                "child_id": str(row["child_id"]),
                "parent_id": str(row["parent_id"]),
                "source_id": str(row["source_id"]),
                "text_rank": row["text_rank"],
                "text_rank_position": row[
                    "text_rank_position"
                ],
            })
        return normalized

    def get_parent_content(
        self,
        parent_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not parent_ids:
            return {}

        query = """
            SELECT
                p.id AS parent_id,
                p.chunk_index AS parent_chunk_index,
                p.content,
                s.source_key,
                s.source_type,
                s.title,
                s.id AS source_id
            FROM rag_chunks p
            INNER JOIN rag_sources s ON p.source_id = s.id
            WHERE
                p.id = ANY($1::uuid[])
                AND p.chunk_level = 'parent'
        """

        with self._pool.connection() as connection:
            with connection.cursor(
                row_factory=dict_row
            ) as cursor:
                cursor.execute(query, [parent_ids])
                results = cursor.fetchall()

        result_map = {}
        for row in (results or []):
            parent_id_str = str(row["parent_id"])
            result_map[parent_id_str] = {
                "parent_id": parent_id_str,
                "parent_chunk_index": (
                    row["parent_chunk_index"]
                ),
                "content": row["content"],
                "source_key": row["source_key"],
                "source_type": row["source_type"],
                "title": row["title"],
                "source_id": str(row["source_id"]),
            }
        return result_map

    def verify_parent_source(
        self,
        child_id: str,
        parent_id: str,
    ) -> bool:
        query = """
            SELECT EXISTS(
                SELECT 1
                FROM rag_chunks c
                INNER JOIN rag_chunks p ON (
                    p.id = $1
                    AND c.source_id = p.source_id
                    AND c.parent_id = p.id
                )
                WHERE c.id = $2
            )
        """

        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query,
                    [parent_id, child_id],
                )
                result = cursor.fetchone()

        return bool(result[0]) if result else False
