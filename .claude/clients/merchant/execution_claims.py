"""Transaction-scoped Merchant execution claims.

Internal database primitive. This module does not authenticate callers,
authorize takeover, commit transactions, or execute Merchant commands.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any


class ExecutionClaimConflictError(RuntimeError):
    """Claim is owned by another attempt or is not active."""


@dataclass(frozen=True, slots=True)
class ExecutionClaimToken:
    operation_key: str
    payload_hash: str
    execution_attempt_id: uuid.UUID
    claim_generation: int


def _validate_identity(
    operation_key: str,
    payload_hash: str,
    execution_attempt_id: uuid.UUID,
) -> None:
    if not isinstance(operation_key, str) or not operation_key.strip():
        raise ValueError("operation_key must be non-empty")

    if not isinstance(payload_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", payload_hash
    ):
        raise ValueError("payload_hash must be lowercase SHA-256")

    if not isinstance(execution_attempt_id, uuid.UUID):
        raise ValueError("execution_attempt_id must be a UUID")


def _fields(row: Any, *names: str) -> tuple[Any, ...]:
    if isinstance(row, dict):
        return tuple(row[name] for name in names)
    return tuple(row)


def acquire_execution_claim(
    connection: Any,
    *,
    operation_key: str,
    payload_hash: str,
    execution_attempt_id: uuid.UUID,
) -> ExecutionClaimToken:
    """Acquire a new claim or recognize the identical active attempt.

    Requires a caller-owned transaction. Never performs takeover.
    The claim row remains locked until that transaction ends.
    """
    _validate_identity(
        operation_key, payload_hash, execution_attempt_id
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO merchant_ops.merchant_execution_claims (
                operation_key,
                payload_hash,
                execution_attempt_id,
                claim_generation,
                claim_status
            )
            VALUES (%s, %s, %s, 1, 'ACTIVE')
            ON CONFLICT (operation_key) DO NOTHING
            """,
            (operation_key, payload_hash, execution_attempt_id),
        )

        cursor.execute(
            """
            SELECT
                payload_hash,
                execution_attempt_id,
                claim_generation,
                claim_status
            FROM merchant_ops.merchant_execution_claims
            WHERE operation_key = %s
            FOR UPDATE
            """,
            (operation_key,),
        )

        row = cursor.fetchone()
        if row is None:
            raise ExecutionClaimConflictError(
                "Execution claim disappeared"
            )

        stored_hash, stored_attempt, generation, status = _fields(
            row,
            "payload_hash",
            "execution_attempt_id",
            "claim_generation",
            "claim_status",
        )

        if (
            stored_hash != payload_hash
            or str(stored_attempt) != str(execution_attempt_id)
            or status != "ACTIVE"
            or type(generation) is not int
            or generation < 1
        ):
            raise ExecutionClaimConflictError(
                "Execution claim is not owned by this active attempt"
            )

        return ExecutionClaimToken(
            operation_key=operation_key,
            payload_hash=payload_hash,
            execution_attempt_id=execution_attempt_id,
            claim_generation=generation,
        )


def complete_execution_claim(
    connection: Any,
    *,
    token: ExecutionClaimToken,
) -> None:
    """Complete only the exact active attempt and generation.

    The caller must verify domain execution and ledger result before
    calling this function, using the same database transaction.
    """
    if not isinstance(token, ExecutionClaimToken):
        raise TypeError("A trusted execution claim token is required")

    _validate_identity(
        token.operation_key,
        token.payload_hash,
        token.execution_attempt_id,
    )

    if (
        type(token.claim_generation) is not int
        or token.claim_generation < 1
    ):
        raise ValueError("Invalid claim generation")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE merchant_ops.merchant_execution_claims
            SET claim_status = 'COMPLETED',
                updated_at = NOW()
            WHERE operation_key = %s
              AND payload_hash = %s
              AND execution_attempt_id = %s
              AND claim_generation = %s
              AND claim_status = 'ACTIVE'
            RETURNING operation_key
            """,
            (
                token.operation_key,
                token.payload_hash,
                token.execution_attempt_id,
                token.claim_generation,
            ),
        )

        if cursor.fetchone() is None:
            raise ExecutionClaimConflictError(
                "Stale, revoked, or completed execution claim"
            )