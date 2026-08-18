from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings


DatabasePool = ConnectionPool


def create_pool(
    settings: Settings,
) -> DatabasePool:
    return ConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        timeout=settings.db_timeout_seconds,
        open=False,
        kwargs={
            "autocommit": True,
            "connect_timeout": (
                settings.db_timeout_seconds
            ),
            "application_name": (
                settings.service_name
            ),
        },
    )


def check_database(
    pool: DatabasePool,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    query = """
        SELECT
            current_database() AS database,
            current_user AS database_user,

            (
                SELECT extversion
                FROM pg_extension
                WHERE extname = 'vector'
            ) AS vector_version,

            to_regclass(
                'public.rag_sources'
            ) IS NOT NULL AS sources_table,

            to_regclass(
                'public.rag_chunks'
            ) IS NOT NULL AS chunks_table,

            to_regclass(
                'public.rag_schema_migrations'
            ) IS NOT NULL AS migrations_table
    """

    with pool.connection(
        timeout=timeout_seconds
    ) as connection:
        with connection.cursor(
            row_factory=dict_row
        ) as cursor:
            cursor.execute(query)
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Database readiness query returned no row"
        )

    return dict(row)