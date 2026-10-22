"""Exact identity snapshots for verified Merchant direct writes.

Pure validation utilities. This module does not authenticate callers,
verify PostgreSQL evidence, or grant lifecycle authority.
"""

from __future__ import annotations

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
