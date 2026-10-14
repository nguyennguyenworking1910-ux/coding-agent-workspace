import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import psycopg
import pytest

from claude.clients.merchant.execution_ledger import (
    ExecutionConflictError,
    execute_once,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def connect():
    if os.environ.get("MERCHANT_TEST_DB_NAME") != (
        "coding_agent_merchant_test"
    ):
        pytest.skip("Test database not explicitly configured")

    password = os.environ.get("MERCHANT_TEST_PASSWORD")

    if not password:
        pytest.skip("Test database password missing")

    return psycopg.connect(
        host="127.0.0.1",
        port=5434,
        dbname="coding_agent_merchant_test",
        user="merchant_test",
        password=password,
        connect_timeout=5,
        options="-c lock_timeout=5000",
    )


def operation_key():
    return "pytest:direct:" + str(uuid.uuid4())


def cleanup(key):
    with connect() as conn:
        with conn.transaction():
            conn.execute(
                """
                DELETE FROM merchant_ops.merchant_execution_ledger
                WHERE operation_key = %s
                """,
                (key,),
            )


def test_postgres_commit_and_replay():
    key = operation_key()
    calls = []

    try:
        with connect() as conn:
            with conn.transaction():
                first, replayed = execute_once(
                    conn,
                    operation_key=key,
                    payload_hash=HASH_A,
                    execute=lambda: calls.append("write") or {
                        "success": True,
                        "merchant_id": "merchant-test-1",
                    },
                )

        assert replayed is False

        with connect() as conn:
            with conn.transaction():
                second, replayed = execute_once(
                    conn,
                    operation_key=key,
                    payload_hash=HASH_A,
                    execute=lambda: pytest.fail(
                        "Duplicate execution"
                    ),
                )

        assert replayed is True
        assert second == first
        assert calls == ["write"]
    finally:
        cleanup(key)


def test_postgres_payload_conflict():
    key = operation_key()

    try:
        with connect() as conn:
            with conn.transaction():
                execute_once(
                    conn,
                    operation_key=key,
                    payload_hash=HASH_A,
                    execute=lambda: {"success": True},
                )

        with pytest.raises(ExecutionConflictError):
            with connect() as conn:
                with conn.transaction():
                    execute_once(
                        conn,
                        operation_key=key,
                        payload_hash=HASH_B,
                        execute=lambda: pytest.fail(
                            "Conflicting write executed"
                        ),
                    )
    finally:
        cleanup(key)


def test_postgres_rollback_removes_ledger():
    key = operation_key()

    try:
        with pytest.raises(RuntimeError):
            with connect() as conn:
                with conn.transaction():
                    execute_once(
                        conn,
                        operation_key=key,
                        payload_hash=HASH_A,
                        execute=lambda: {"success": True},
                    )

                    raise RuntimeError("Rollback requested")

        with connect() as conn:
            row = conn.execute(
                """
                SELECT count(*)
                FROM merchant_ops.merchant_execution_ledger
                WHERE operation_key = %s
                """,
                (key,),
            ).fetchone()

        assert row[0] == 0
    finally:
        cleanup(key)


def test_postgres_concurrent_same_key():
    key = operation_key()
    start = Event()

    def worker(number):
        start.wait(timeout=5)

        with connect() as conn:
            with conn.transaction():
                return execute_once(
                    conn,
                    operation_key=key,
                    payload_hash=HASH_A,
                    execute=lambda: {
                        "success": True,
                        "writer": number,
                    },
                )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(worker, 1),
                executor.submit(worker, 2),
            ]

            start.set()

            results = [
                future.result(timeout=20)
                for future in futures
            ]

        assert sorted(
            replayed for _, replayed in results
        ) == [False, True]

        assert results[0][0] == results[1][0]
    finally:
        cleanup(key)
