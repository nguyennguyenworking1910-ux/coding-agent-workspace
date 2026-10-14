"""Execute only an existing trusted Merchant write reservation."""

from __future__ import annotations

from typing import Any, Mapping

from claude.clients.merchant.atomic_create import _canonical_hash
from claude.agents.tools.merchant.write_adapters import (
    execute_protected_merchant_create,
)
from claude.hooks.team_lifecycle import locked_team_state


class ReservedExecutionError(PermissionError):
    """Protected Merchant execution lacks a valid reservation."""


DATABASE_NAMES = {
    "test": "coding_agent_merchant_test",
    "runtime": "coding_agent_merchant",
}


def execute_reserved_merchant_create(
    *,
    repository: Any,
    owner_session_id: str,
    teammate_name: str,
    pane_session_id: str,
    run_id: str,
    task_id: str,
    write_id: str,
    database: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute one already-reserved Merchant creation.

    All identity inputs must originate from trusted orchestration.
    This function is not an agent-facing API.
    """

    if database not in DATABASE_NAMES:
        raise ReservedExecutionError("Invalid database target")

    config = getattr(repository, "config", None)

    if getattr(config, "database", None) != DATABASE_NAMES[database]:
        raise ReservedExecutionError("Repository database mismatch")

    if not isinstance(payload, Mapping):
        raise ReservedExecutionError("Invalid payload")

    allowed = {
        "merchant_id",
        "code",
        "name",
        "region_code",
        "created_by",
    }

    if set(payload) - allowed:
        raise ReservedExecutionError("Unexpected payload fields")

    if any(
        not isinstance(payload.get(field), str)
        or not payload[field].strip()
        for field in ("code", "name")
    ):
        raise ReservedExecutionError("Invalid Merchant identity")

    for field in ("merchant_id", "region_code", "created_by"):
        value = payload.get(field)
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            raise ReservedExecutionError("Invalid optional field")

    canonical = {
        "command": "merchant create",
        "merchant_id": payload.get("merchant_id"),
        "code": payload["code"],
        "name": payload["name"],
        "region_code": payload.get("region_code"),
        "created_by": payload.get("created_by"),
    }

    actual_hash = _canonical_hash(canonical)

    with locked_team_state(owner_session_id) as state:
        if not isinstance(state, dict):
            raise ReservedExecutionError("Team state unavailable")

        record = state.get("teammates", {}).get(teammate_name)

        if not isinstance(record, dict):
            raise ReservedExecutionError("Teammate missing")

        expected = {
            "canonical_name": teammate_name,
            "status": "RUNNING",
            "current_run_id": run_id,
            "current_task_id": task_id,
            "trusted_pane_session_id": pane_session_id,
        }

        if any(
            record.get(field) != value
            for field, value in expected.items()
        ):
            raise ReservedExecutionError("Lifecycle binding mismatch")

        if (
            record.get("authorized_operations")
            != ["merchant_execute"]
            or record.get("authorized_selected_agents")
            != [teammate_name]
        ):
            raise ReservedExecutionError("Operation not authorized")

        writes = record.get("direct_writes")

        if not isinstance(writes, dict):
            raise ReservedExecutionError("Write reservation missing")

        reservation = writes.get(write_id)

        if not isinstance(reservation, dict):
            raise ReservedExecutionError("Write not reserved")

        expected_write = {
            "write_id": write_id,
            "run_id": run_id,
            "task_id": task_id,
            "database": database,
            "command": "merchant create",
            "payload_hash": actual_hash,
            "status": "RESERVED",
        }

        if any(
            reservation.get(field) != value
            for field, value in expected_write.items()
        ):
            raise ReservedExecutionError("Reservation mismatch")

        operation_key = reservation.get("operation_key")

        if (
            not isinstance(operation_key, str)
            or not operation_key.startswith("merchant-direct:v1:")
            or len(operation_key) != len("merchant-direct:v1:") + 64
            or any(
                char not in "0123456789abcdef"
                for char in operation_key[len("merchant-direct:v1:"):]
            )
        ):
            raise ReservedExecutionError("Invalid reserved operation key")

        # Atomic claim under the same exclusive team-state lock.
        # All lifecycle ownership mutations must honor EXECUTING.
        # The enclosing locked_team_state context persists this
        # mutation before PostgreSQL execution begins.
        reservation["status"] = "EXECUTING"

    # Persist EXECUTING before entering PostgreSQL execution.
    # Lifecycle mutations must reject in-flight direct writes.
    result = execute_protected_merchant_create(
        database=database,
        operation_key=operation_key,
        payload=dict(payload),
        repository=repository,
    )

    if (
        not isinstance(result, dict)
        or result.get("success") is not True
        or result.get("mode") != "EXECUTE"
        or result.get("command") != "merchant create"
        or result.get("database") != database
    ):
        raise ReservedExecutionError("Invalid execution result")

    return result
