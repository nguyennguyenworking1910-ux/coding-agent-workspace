"""Reconcile a reserved Merchant write against committed DB evidence."""

from __future__ import annotations

import uuid
from typing import Any

from claude.hooks.team_lifecycle import locked_team_state
from claude.hooks.merchant_execution_evidence import (
    verify_committed_merchant_create,
)


class DirectRecoveryError(RuntimeError):
    """The reservation is unavailable or no longer authoritative."""


def _matching_record(
    state: dict[str, Any] | None,
    teammate_name: str,
    run_id: str,
    task_id: str,
    write_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(state, dict):
        raise DirectRecoveryError("State unavailable")

    record = state.get("teammates", {}).get(teammate_name)

    if not isinstance(record, dict):
        raise DirectRecoveryError("Teammate missing")

    if (
        record.get("canonical_name") != teammate_name
        or record.get("status") != "RUNNING"
        or record.get("current_run_id") != run_id
        or record.get("current_task_id") != task_id
        or record.get("authorized_operations")
        != ["merchant_execute"]
        or record.get("authorized_selected_agents")
        != [teammate_name]
    ):
        raise DirectRecoveryError("Lifecycle no longer matches")

    writes = record.get("direct_writes")

    if not isinstance(writes, dict):
        raise DirectRecoveryError("Write state missing")

    reservation = writes.get(write_id)

    if not isinstance(reservation, dict):
        raise DirectRecoveryError("Reservation missing")

    if (
        reservation.get("write_id") != write_id
        or reservation.get("run_id") != run_id
        or reservation.get("task_id") != task_id
        or reservation.get("command") != "merchant create"
        or reservation.get("status")
        not in {"RESERVED", "EXECUTING", "VERIFIED"}
    ):
        raise DirectRecoveryError("Reservation mismatch")

    return record, reservation


def reconcile_committed_merchant_create(
    repository: Any,
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    write_id: str,
    database: str,
) -> dict[str, Any] | None:
    """Verify a previously reserved write without executing it.

    None means committed evidence is not established. It does NOT
    authorize issuing a new write.
    """

    if database not in {"test", "runtime"}:
        raise DirectRecoveryError("Invalid database")

    if getattr(
        getattr(repository, "config", None),
        "database",
        None,
    ) != {
        "test": "coding_agent_merchant_test",
        "runtime": "coding_agent_merchant",
    }[database]:
        raise DirectRecoveryError("Repository database mismatch")

    # Snapshot under the real team-state lock.
    with locked_team_state(owner_session_id) as state:
        _, reservation = _matching_record(
            state, teammate_name, run_id, task_id, write_id
        )

        if reservation.get("database") != database:
            raise DirectRecoveryError("Reservation database mismatch")

        key = reservation.get("operation_key")
        expected_hash = reservation.get("payload_hash")
        expected_status = reservation.get("status")
        expected_attempt_id = reservation.get("execution_attempt_id")

        # A RESERVED write has not been claimed for execution.
        # Recovery never treats unbound evidence as authorization.
        if expected_status == "RESERVED":
            return None

        if expected_status in {"EXECUTING", "VERIFIED"}:
            if not isinstance(expected_attempt_id, str):
                raise DirectRecoveryError(
                    "Execution-bound reservation missing attempt identity"
                )

        if expected_attempt_id is not None:
            if not isinstance(expected_attempt_id, str):
                raise DirectRecoveryError(
                    "Invalid execution attempt identity"
                )
            try:
                parsed_attempt_id = uuid.UUID(expected_attempt_id)
            except (ValueError, AttributeError):
                raise DirectRecoveryError(
                    "Invalid execution attempt identity"
                ) from None

            if str(parsed_attempt_id) != expected_attempt_id:
                raise DirectRecoveryError(
                    "Non-canonical execution attempt identity"
                )
        else:
            parsed_attempt_id = None

        if not isinstance(key, str) or not key:
            raise DirectRecoveryError("Operation key missing")

        if not isinstance(expected_hash, str):
            raise DirectRecoveryError("Payload hash missing")

    # Read committed evidence outside the state lock.
    # An executing reservation always requires an attempt-bound claim.
    verify_kwargs = {
        "operation_key": key,
        "payload_hash": expected_hash,
    }
    if parsed_attempt_id is not None:
        verify_kwargs["execution_attempt_id"] = parsed_attempt_id

    evidence = verify_committed_merchant_create(
        repository,
        **verify_kwargs,
    )

    if evidence is None:
        return None

    # Reacquire lock: never apply stale evidence to a reassigned task.
    with locked_team_state(owner_session_id) as state:
        record, current = _matching_record(
            state, teammate_name, run_id, task_id, write_id
        )

        if (
            current.get("database") != database
            or current.get("operation_key") != key
            or current.get("payload_hash") != expected_hash
            or current.get("status") != expected_status
            or current.get("execution_attempt_id") != expected_attempt_id
        ):
            raise DirectRecoveryError(
                "Reservation changed during verification"
            )

        current["status"] = "VERIFIED"
        current["merchant_id"] = evidence["merchant_id"]

        # Do not mark REPORT_RECEIVED or release the teammate here.
        return dict(current)
