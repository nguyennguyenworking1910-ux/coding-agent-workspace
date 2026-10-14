"""Transactional idempotency for Merchant direct writes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ExecutionConflictError(ValueError):
    """The same operation key was used for a different request."""


class ExecutionLedgerError(RuntimeError):
    """Execution ledger contract was violated."""


def execute_once(
    connection: Any,
    *,
    operation_key: str,
    payload_hash: str,
    execute: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """
    Execute once within the caller-owned PostgreSQL transaction.

    Returns (result, replayed).

    The caller must own transaction commit/rollback.
    The execute callback must use this same connection.
    """

    if not isinstance(operation_key, str) or not operation_key.strip():
        raise ValueError("operation_key is required")

    if not isinstance(payload_hash, str) or len(payload_hash) != 64:
        raise ValueError("payload_hash must be a SHA-256 hex digest")

    try:
        int(payload_hash, 16)
    except ValueError as error:
        raise ValueError("Invalid payload_hash") from error

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO merchant_ops.merchant_execution_ledger (
                operation_key,
                payload_hash,
                result
            )
            VALUES (%s, %s, NULL)
            ON CONFLICT (operation_key) DO NOTHING
            RETURNING operation_key
            """,
            (operation_key, payload_hash),
        )

        claimed = cursor.fetchone() is not None

        cursor.execute(
            """
            SELECT payload_hash, result
            FROM merchant_ops.merchant_execution_ledger
            WHERE operation_key = %s
            FOR UPDATE
            """,
            (operation_key,),
        )

        existing = cursor.fetchone()

        if existing is None:
            raise ExecutionLedgerError(
                "Execution ledger claim disappeared"
            )

        if isinstance(existing, dict):
            stored_hash = existing["payload_hash"]
            stored_result = existing["result"]
        else:
            stored_hash, stored_result = existing

        if stored_hash != payload_hash:
            raise ExecutionConflictError(
                "Operation key already belongs to another payload"
            )

        if not claimed:
            if not isinstance(stored_result, dict):
                raise ExecutionLedgerError(
                    "Existing execution has no committed result"
                )

            return stored_result, True

        result = execute()

        if not isinstance(result, dict):
            raise ExecutionLedgerError(
                "Execution result must be a dictionary"
            )

        cursor.execute(
            """
            UPDATE merchant_ops.merchant_execution_ledger
            SET result = %s::jsonb
            WHERE operation_key = %s
            """,
            (
                __import__("json").dumps(result),
                operation_key,
            ),
        )

        return result, False
