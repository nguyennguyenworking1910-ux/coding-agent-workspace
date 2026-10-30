"""Exact identity snapshots for verified Merchant direct writes.

Also validates the no-write terminal marker for clean direct tasks.

Pure validation utilities. This module does not authenticate callers,
verify PostgreSQL evidence, or grant lifecycle authority.
"""

from __future__ import annotations

import uuid
from typing import Any


IDENTITY_FIELDS = (
    "write_id",
    "run_id",
    "task_id",
    "database",
    "command",
    "operation_key",
    "payload_hash",
    "execution_attempt_id",
    "claim_generation",
    "merchant_id",
)



def valid_historical_receipt(receipt: Any) -> bool:
    """Validate persisted history structure without granting authority."""
    from uuid import UUID

    if not isinstance(receipt, dict):
        return False

    if set(receipt) != {"version", "run_id", "task_id", "writes"}:
        return False

    if type(receipt["version"]) is not int or receipt["version"] != 1:
        return False

    run_id = receipt["run_id"]
    task_id = receipt["task_id"]
    writes = receipt["writes"]

    if (
        not isinstance(run_id, str) or not run_id
        or not isinstance(task_id, str) or not task_id
        or not isinstance(writes, dict) or not writes
    ):
        return False

    for write_id, write in writes.items():
        if not isinstance(write_id, str) or not write_id:
            return False

        if not isinstance(write, dict):
            return False

        if set(write) != set(IDENTITY_FIELDS):
            return False

        if (
            write.get("write_id") != write_id
            or write.get("run_id") != run_id
            or write.get("task_id") != task_id
            or write.get("database") not in {"test", "runtime"}
            or write.get("command") != "merchant create"
        ):
            return False

        generation = write.get("claim_generation")
        if type(generation) is not int or generation < 1:
            return False

        for field in IDENTITY_FIELDS:
            if field == "claim_generation":
                continue

            value = write.get(field)
            if not isinstance(value, str) or not value:
                return False

        for field in ("execution_attempt_id", "merchant_id"):
            value = write[field]
            try:
                if str(UUID(value)) != value:
                    return False
            except (ValueError, TypeError, AttributeError):
                return False

    return True



def build_completion_receipt(
    record: dict[str, Any],
) -> dict[str, Any] | None:
    """Create a value snapshot, or None if state is incomplete."""
    if not isinstance(record, dict):
        return None

    run_id = record.get("current_run_id")
    task_id = record.get("current_task_id")
    writes = record.get("direct_writes")

    if (
        not isinstance(run_id, str)
        or not run_id
        or not isinstance(task_id, str)
        or not task_id
        or not isinstance(writes, dict)
        or not writes
    ):
        return None

    snapshot = {}

    for write_id, write in writes.items():
        if not isinstance(write_id, str) or not write_id:
            return None

        if not isinstance(write, dict):
            return None

        if (
            write.get("status") != "VERIFIED"
            or write.get("write_id") != write_id
            or write.get("run_id") != run_id
            or write.get("task_id") != task_id
            or write.get("database") not in {"test", "runtime"}
            or write.get("command") != "merchant create"
        ):
            return None

        generation = write.get("claim_generation")

        if type(generation) is not int or generation < 1:
            return None

        for field in IDENTITY_FIELDS:
            value = write.get(field)

            if field == "claim_generation":
                continue

            if not isinstance(value, str) or not value:
                return None

        snapshot[write_id] = {
            field: write[field]
            for field in IDENTITY_FIELDS
        }

    return {
        "version": 1,
        "run_id": run_id,
        "task_id": task_id,
        "writes": snapshot,
    }


def receipt_matches_state(
    record: dict[str, Any],
    receipt: dict[str, Any] | None,
) -> bool:
    """Require exact equality with the recorded write identities."""
    if not isinstance(receipt, dict):
        return False

    if receipt.get("version") != 1:
        return False

    current = build_completion_receipt(record)

    return current is not None and current == receipt


# Non-success outcomes that may finalize a task without a write.
NO_WRITE_TERMINAL_OUTCOMES = frozenset(
    {
        "REQUIRES_CLARIFICATION",
        "BLOCKED",
        "FAILED",
    }
)

NO_WRITE_TERMINAL_FIELDS = frozenset(
    {"version", "run_id", "task_id", "outcome"}
)


def has_direct_write_footprint(record: dict[str, Any]) -> bool:
    """True unless trusted state proves no write exists for this task.

    Reservations are the only path to a PostgreSQL claim, and they are
    persisted before execution. Any reservation, receipt, or archived
    history for the current run/task is therefore a write footprint.
    Malformed state is treated as a footprint (fail closed).
    """
    if not isinstance(record, dict):
        return True

    if "direct_writes" in record and record["direct_writes"] != {}:
        return True

    if record.get("direct_completion_receipt") is not None:
        return True

    # A scoped execution record exists from before authorization is spent.
    if "direct_scope_execution" in record:
        return True

    current = (
        record.get("current_run_id"),
        record.get("current_task_id"),
    )

    history = record.get("completed_direct_write_history", [])

    if not isinstance(history, list):
        return True

    for item in history:
        if not valid_historical_receipt(item):
            return True

        if (item["run_id"], item["task_id"]) == current:
            return True

    scope_history = record.get("completed_scope_execution_history", [])

    if not isinstance(scope_history, list):
        return True

    for item in scope_history:
        if (
            not valid_scope_execution(item)
            or item["status"] != SCOPE_EXECUTION_SUCCEEDED
        ):
            return True

        if (item["run_id"], item["task_id"]) == current:
            return True

    return False


# Scoped Direct EXECUTE of a non-Create command. Persisted EXECUTING in
# trusted team state before the one-use runtime authorization is spent.
SCOPE_EXECUTION_EXECUTING = "EXECUTING"
SCOPE_EXECUTION_SUCCEEDED = "SUCCEEDED"
SCOPE_EXECUTION_FAILED = "FAILED"
SCOPE_EXECUTION_UNCERTAIN = "UNCERTAIN"

SCOPE_EXECUTION_STATUSES = frozenset(
    {
        SCOPE_EXECUTION_EXECUTING,
        SCOPE_EXECUTION_SUCCEEDED,
        SCOPE_EXECUTION_FAILED,
        SCOPE_EXECUTION_UNCERTAIN,
    }
)

SCOPE_EXECUTION_FIELDS = frozenset(
    {
        "version",
        "run_id",
        "task_id",
        "command",
        "scope_hash",
        "confirmation_hash",
        "execution_attempt_id",
        "status",
    }
)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def valid_scope_execution(value: Any) -> bool:
    """Validate a scoped execution record without granting authority."""
    if not isinstance(value, dict) or set(value) != SCOPE_EXECUTION_FIELDS:
        return False

    try:
        attempt = str(uuid.UUID(str(value["execution_attempt_id"])))
    except (ValueError, AttributeError, TypeError):
        return False

    return (
        type(value["version"]) is int
        and value["version"] == 1
        and all(
            isinstance(value[field], str) and value[field]
            for field in ("run_id", "task_id", "command")
        )
        and value["command"] != "merchant create"
        and _is_sha256(value["scope_hash"])
        and _is_sha256(value["confirmation_hash"])
        and attempt == value["execution_attempt_id"]
        and value["status"] in SCOPE_EXECUTION_STATUSES
    )


def scope_execution_succeeded(record: dict[str, Any]) -> bool:
    """Require an exact SUCCEEDED scoped execution for the current task."""
    if not isinstance(record, dict):
        return False

    execution = record.get("direct_scope_execution")

    if (
        not valid_scope_execution(execution)
        or execution["status"] != SCOPE_EXECUTION_SUCCEEDED
        or execution["run_id"] != record.get("current_run_id")
        or execution["task_id"] != record.get("current_task_id")
        or record.get("authorized_operations") != ["merchant_execute"]
    ):
        return False

    # A scoped execution never coexists with Create or no-write evidence.
    return (
        record.get("direct_writes", {}) == {}
        and record.get("direct_completion_receipt") is None
        and "direct_no_write_terminal" not in record
    )


def no_write_terminal_matches_state(record: dict[str, Any]) -> bool:
    """Require an exact no-write marker for the current clean task."""
    if not isinstance(record, dict):
        return False

    marker = record.get("direct_no_write_terminal")

    if (
        not isinstance(marker, dict)
        or set(marker) != NO_WRITE_TERMINAL_FIELDS
        or type(marker["version"]) is not int
        or marker["version"] != 1
        or marker["outcome"] not in NO_WRITE_TERMINAL_OUTCOMES
    ):
        return False

    run_id = record.get("current_run_id")
    task_id = record.get("current_task_id")

    if (
        not isinstance(run_id, str)
        or not run_id
        or not isinstance(task_id, str)
        or not task_id
        or marker["run_id"] != run_id
        or marker["task_id"] != task_id
    ):
        return False

    if record.get("authorized_operations") != ["merchant_execute"]:
        return False

    return not has_direct_write_footprint(record)
