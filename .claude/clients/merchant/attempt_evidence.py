"""Durable execution evidence for one Merchant write attempt.

Internal database primitive. It does not authenticate callers or decide
whether a write is authorized; trusted orchestration supplies the identity.

``evidence_bound_repository`` makes the attempt's single read-write
transaction also insert the execution claim and ledger row, and complete
both before commit. The business mutation and its evidence therefore commit
or roll back together, and a second attempt for the same operation key is
refused by the database before any mutation.

``resolve_attempt`` establishes what happened to a finished attempt:

- COMMITTED: the attempt's own completed claim and ledger result exist;
- NOT_COMMITTED: a REVOKED fence now owns the key, so the attempt can never
  commit later (or another identity already owned it);
- UNCERTAIN: anything else, including a fence blocked by an in-flight
  transaction or an unreachable database. Never inferred to have rolled back.

Fence only after the attempt's own connection has closed (the executing call
returned or raised, or its process ended).
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from claude.clients.merchant.execution_claims import (
    acquire_execution_claim,
    complete_execution_claim,
)
from claude.clients.merchant.repository import MerchantRepository


COMMITTED = "COMMITTED"
NOT_COMMITTED = "NOT_COMMITTED"
UNCERTAIN = "UNCERTAIN"

_READ_ONLY_OPTION = "default_transaction_read_only=on"


class EvidenceBindingError(RuntimeError):
    """The attempt cannot be bound to exactly one evidenced transaction."""


@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    operation_key: str
    payload_hash: str
    execution_attempt_id: uuid.UUID
    command: str

    def __post_init__(self) -> None:
        if not isinstance(self.operation_key, str) or not self.operation_key:
            raise ValueError("operation_key is required")

        if not isinstance(self.payload_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.payload_hash
        ):
            raise ValueError("payload_hash must be lowercase SHA-256")

        if not isinstance(self.execution_attempt_id, uuid.UUID):
            raise ValueError("execution_attempt_id must be a UUID")

        if not isinstance(self.command, str) or not self.command:
            raise ValueError("command is required")


class _BoundConnection:
    """Delegating connection whose outer transaction carries evidence."""

    def __init__(
        self,
        connection: Any,
        identity: AttemptIdentity,
        usage: dict[str, bool],
    ) -> None:
        self._connection = connection
        self._identity = identity
        self._usage = usage
        self._depth = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    @contextmanager
    def transaction(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        if self._depth:
            with self._connection.transaction(*args, **kwargs) as nested:
                yield nested
            return

        # One evidenced write transaction per attempt: a second one could
        # commit a partial command after evidence already says COMMITTED.
        if self._usage["used"]:
            raise EvidenceBindingError(
                "A bound attempt allows exactly one write transaction"
            )

        self._usage["used"] = True
        identity = self._identity

        with self._connection.transaction(*args, **kwargs) as outer:
            token = acquire_execution_claim(
                self._connection,
                operation_key=identity.operation_key,
                payload_hash=identity.payload_hash,
                execution_attempt_id=identity.execution_attempt_id,
            )

            with self._connection.cursor() as cursor:
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
                    (identity.operation_key, identity.payload_hash),
                )

                if cursor.fetchone() is None:
                    raise EvidenceBindingError(
                        "Operation already has execution evidence"
                    )

            self._depth += 1
            try:
                yield outer
            finally:
                self._depth -= 1

            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE merchant_ops.merchant_execution_ledger
                    SET result = %s::jsonb
                    WHERE operation_key = %s
                      AND payload_hash = %s
                      AND result IS NULL
                    RETURNING operation_key
                    """,
                    (
                        json.dumps(
                            {
                                "command": identity.command,
                                "execution_attempt_id": str(
                                    identity.execution_attempt_id
                                ),
                            }
                        ),
                        identity.operation_key,
                        identity.payload_hash,
                    ),
                )

                if cursor.fetchone() is None:
                    raise EvidenceBindingError("Ledger row changed")

            complete_execution_claim(self._connection, token=token)


def evidence_bound_repository(
    repository: MerchantRepository,
    identity: AttemptIdentity,
) -> MerchantRepository:
    """Return a repository whose single write transaction is evidenced.

    Read-only connections are untouched.
    """

    if not isinstance(identity, AttemptIdentity):
        raise TypeError("A trusted attempt identity is required")

    base_connect = repository._connect_fn
    usage = {"used": False}

    def connect(**kwargs: Any) -> Any:
        connection = base_connect(**kwargs)

        if _READ_ONLY_OPTION in str(kwargs.get("options") or ""):
            return connection

        return _BoundConnection(connection, identity, usage)

    # A copy keeps the caller's exact configuration and role.
    bound = copy.copy(repository)
    bound._connect_fn = connect

    return bound


def resolve_attempt(
    repository: MerchantRepository,
    identity: AttemptIdentity,
    *,
    fence: bool,
) -> str:
    """Classify a finished attempt from committed database evidence.

    With ``fence`` a missing claim is replaced by a committed REVOKED claim
    under a fresh identity, which makes the attempt's later commit
    impossible. Without it, a missing claim is UNCERTAIN.
    """

    import psycopg

    try:
        with repository.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    if fence:
                        cursor.execute(
                            """
                            INSERT INTO merchant_ops.merchant_execution_claims (
                                operation_key,
                                payload_hash,
                                execution_attempt_id,
                                claim_generation,
                                claim_status
                            )
                            VALUES (%s, %s, %s, 1, 'REVOKED')
                            ON CONFLICT (operation_key) DO NOTHING
                            RETURNING operation_key
                            """,
                            (
                                identity.operation_key,
                                identity.payload_hash,
                                uuid.uuid4(),
                            ),
                        )

                        if cursor.fetchone() is not None:
                            return NOT_COMMITTED

                    cursor.execute(
                        """
                        SELECT
                            claims.payload_hash,
                            claims.execution_attempt_id,
                            claims.claim_status,
                            ledger.payload_hash AS ledger_hash,
                            ledger.result
                        FROM merchant_ops.merchant_execution_claims AS claims
                        LEFT JOIN merchant_ops.merchant_execution_ledger AS ledger
                            ON ledger.operation_key = claims.operation_key
                        WHERE claims.operation_key = %s
                        """,
                        (identity.operation_key,),
                    )

                    row = cursor.fetchone()
    except psycopg.Error:
        return UNCERTAIN

    if row is None:
        return UNCERTAIN

    if isinstance(row, dict):
        values = (
            row["payload_hash"],
            row["execution_attempt_id"],
            row["claim_status"],
            row["ledger_hash"],
            row["result"],
        )
    else:
        values = tuple(row)

    stored_hash, attempt_id, status, ledger_hash, result = values
    own_attempt = str(attempt_id) == str(identity.execution_attempt_id)

    if (
        own_attempt
        and status == "COMPLETED"
        and stored_hash == identity.payload_hash
        and ledger_hash == identity.payload_hash
        and isinstance(result, dict)
        and result.get("execution_attempt_id")
        == str(identity.execution_attempt_id)
    ):
        return COMMITTED

    # A committed fence owns the key, so this attempt's claim insert can
    # never commit. A completed claim under another identity means the
    # operation may have run: that is never reported as not committed.
    if not own_attempt and status == "REVOKED":
        return NOT_COMMITTED

    return UNCERTAIN


STEP_RECEIPT_CONTRACT = "step_update_receipt_v1"


def step_update_receipt(
    repository: MerchantRepository,
    identity: AttemptIdentity,
    step_id: str,
) -> dict[str, Any]:
    """Reconcile one committed Step Update from its three durable records.

    The ledger row, the execution claim and the STEP event are read
    independently. They must name the same attempt, and all three must
    have been written by one PostgreSQL transaction (equal ``xmin``), so
    the receipt never rests on a reported result. Raises
    EvidenceBindingError when they do not reconcile.
    """

    with repository.connection(read_only=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ledger.payload_hash, ledger.result,
                       ledger.xmin::text AS ledger_tx,
                       claims.payload_hash AS claim_hash,
                       claims.execution_attempt_id::text AS claim_attempt,
                       claims.claim_status, claims.xmin::text AS claim_tx
                FROM merchant_ops.merchant_execution_ledger AS ledger
                JOIN merchant_ops.merchant_execution_claims AS claims
                  ON claims.operation_key = ledger.operation_key
                WHERE ledger.operation_key = %s
                """,
                (identity.operation_key,),
            )
            evidence = cursor.fetchone()

            if evidence is None:
                raise EvidenceBindingError("No ledger and claim for the attempt")

            cursor.execute(
                """
                SELECT events.id::text AS event_id,
                       events.merchant_id::text AS merchant_id,
                       events.project_id::text AS project_id,
                       events.entity_id::text AS step_id,
                       events.old_values, events.new_values,
                       steps.sequence_number
                FROM merchant_ops.project_events AS events
                JOIN merchant_ops.project_steps AS steps
                  ON steps.id = events.entity_id
                 AND steps.project_id = events.project_id
                WHERE events.entity_type = 'STEP'
                  AND events.entity_id::text = %s
                  AND events.xmin::text = %s
                """,
                (str(step_id), evidence["ledger_tx"]),
            )
            events = cursor.fetchall()

    attempt = str(identity.execution_attempt_id)
    result = evidence["result"]

    if (
        evidence["payload_hash"] != identity.payload_hash
        or evidence["claim_hash"] != identity.payload_hash
        or evidence["claim_attempt"] != attempt
        or evidence["claim_status"] != "COMPLETED"
        or evidence["claim_tx"] != evidence["ledger_tx"]
        or not isinstance(result, dict)
        or result.get("execution_attempt_id") != attempt
        or result.get("command") != identity.command
    ):
        raise EvidenceBindingError("Ledger and claim do not name this attempt")

    if len(events) != 1:
        raise EvidenceBindingError(
            "The attempt's transaction did not write exactly one STEP event"
        )

    (event,) = events
    old, new = event["old_values"] or {}, event["new_values"] or {}

    if (
        not isinstance(old.get("version"), int)
        or new.get("version") != old["version"] + 1
        or old.get("status") == new.get("status")
    ):
        raise EvidenceBindingError("STEP event is not one transition")

    return {
        "contract": STEP_RECEIPT_CONTRACT,
        "merchant_id": event["merchant_id"],
        "project_id": event["project_id"],
        "step_id": event["step_id"],
        "step_sequence": event["sequence_number"],
        "previous_status": old.get("status"),
        "new_status": new.get("status"),
        "previous_version": old["version"],
        "new_version": new["version"],
        "event_id": event["event_id"],
        "execution_attempt_id": attempt,
        "operation_key": identity.operation_key,
        "payload_hash": identity.payload_hash,
        "claim_status": evidence["claim_status"],
        "ledger_command": result["command"],
        "transaction_id": evidence["ledger_tx"],
    }


def recover_step_update_receipts(
    repository: MerchantRepository,
    step_id: str,
) -> list[dict[str, Any]]:
    """Rebuild every evidenced Step Update receipt of ``step_id`` from PostgreSQL alone.

    Post-commit recovery when local run or team state is lost: each ledger
    row written by the same transaction as a STEP event of the step yields
    its attempt identity, which ``step_update_receipt`` then reconciles in
    full. A transition without execution evidence (written outside Direct
    EXECUTE) yields nothing.
    """

    with repository.connection(read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT ledger.operation_key, ledger.payload_hash, ledger.result
            FROM merchant_ops.merchant_execution_ledger AS ledger
            JOIN merchant_ops.project_events AS events
              ON events.xmin = ledger.xmin
            WHERE events.entity_type = 'STEP'
              AND events.entity_id::text = %s
            ORDER BY events.created_at, ledger.operation_key
            """,
            (str(step_id),),
        ).fetchall()

    receipts = []
    for row in rows:
        result = row["result"] if isinstance(row["result"], dict) else {}
        identity = AttemptIdentity(
            operation_key=row["operation_key"],
            payload_hash=str(row["payload_hash"]),
            execution_attempt_id=uuid.UUID(str(result.get("execution_attempt_id"))),
            command=str(result.get("command")),
        )
        receipts.append(step_update_receipt(repository, identity, step_id))

    return receipts
