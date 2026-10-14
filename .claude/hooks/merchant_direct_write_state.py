"""Persist exact Direct Merchant write reservations."""

from __future__ import annotations

from typing import Any, Mapping

from claude.clients.merchant.atomic_create import _canonical_hash
from claude.hooks.merchant_direct_binding import (
    DirectExecutionBindingError,
    bind_merchant_execute,
)
from claude.hooks.team_lifecycle import locked_team_state


class DirectWriteReservationError(PermissionError):
    """Write reservation does not match active lifecycle authority."""


def reserve_merchant_create(
    *,
    owner_session_id: str,
    teammate_name: str,
    pane_session_id: str,
    run_id: str,
    task_id: str,
    write_id: str,
    database: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist a stable reservation for one authorized write.

    The caller must be trusted orchestration, never raw agent JSON.
    """

    if database not in {"test", "runtime"}:
        raise DirectWriteReservationError(
            "Invalid database target"
        )

    if not isinstance(payload, Mapping):
        raise DirectWriteReservationError(
            "Invalid Merchant payload"
        )

    allowed = {
        "merchant_id",
        "code",
        "name",
        "region_code",
        "created_by",
    }

    if set(payload) - allowed:
        raise DirectWriteReservationError(
            "Unexpected Merchant payload fields"
        )

    if any(
        not isinstance(payload.get(field), str)
        or not payload[field].strip()
        for field in ("code", "name")
    ):
        raise DirectWriteReservationError(
            "Merchant code and name are required"
        )

    optional = (
        "merchant_id",
        "region_code",
        "created_by",
    )

    if any(
        payload.get(field) is not None
        and (
            not isinstance(payload[field], str)
            or not payload[field].strip()
        )
        for field in optional
    ):
        raise DirectWriteReservationError(
            "Invalid optional Merchant field"
        )

    # Use the exact canonical payload contract of atomic_create.
    canonical_payload = {
        "command": "merchant create",
        "merchant_id": payload.get("merchant_id"),
        "code": payload["code"],
        "name": payload["name"],
        "region_code": payload.get("region_code"),
        "created_by": payload.get("created_by"),
    }

    payload_hash = _canonical_hash(canonical_payload)

    # Initial authentication. A second check occurs below
    # while the team-state lock is held.
    try:
        operation_key = bind_merchant_execute(
            owner_session_id=owner_session_id,
            teammate_name=teammate_name,
            pane_session_id=pane_session_id,
            run_id=run_id,
            task_id=task_id,
            write_id=write_id,
            command="merchant create",
        )
    except DirectExecutionBindingError as exc:
        raise DirectWriteReservationError(
            f"Lifecycle authority denied: {exc}"
        ) from exc

    with locked_team_state(owner_session_id) as state:
        if state is None:
            raise DirectWriteReservationError(
                "Team state unavailable"
            )

        record = state.get("teammates", {}).get(
            teammate_name
        )

        if not isinstance(record, dict):
            raise DirectWriteReservationError(
                "Teammate does not exist"
            )

        expected = {
            "canonical_name": teammate_name,
            "status": "RUNNING",
            "current_run_id": run_id,
            "current_task_id": task_id,
            "trusted_pane_session_id": pane_session_id,
        }

        for field, value in expected.items():
            if record.get(field) != value:
                raise DirectWriteReservationError(
                    f"Lifecycle binding mismatch: {field}"
                )

        if record.get("authorized_operations") != [
            "merchant_execute"
        ]:
            raise DirectWriteReservationError(
                "Merchant execution not authorized"
            )

        if record.get("authorized_selected_agents") != [
            teammate_name
        ]:
            raise DirectWriteReservationError(
                "Teammate authority mismatch"
            )

        if not isinstance(write_id, str) or not write_id.strip():
            raise DirectWriteReservationError(
                "Invalid write identity"
            )

        proposed = {
            "operation_key": operation_key,
            "payload_hash": payload_hash,
            "command": "merchant create",
            "database": database,
            "run_id": run_id,
            "task_id": task_id,
            "write_id": write_id,
            "status": "RESERVED",
        }

        existing_writes = record.get("direct_writes")

        if existing_writes is None:
            existing_writes = {}

        if not isinstance(existing_writes, dict):
            raise DirectWriteReservationError(
                "Invalid stored write state"
            )

        existing = existing_writes.get(write_id)

        if existing is not None:
            if not isinstance(existing, dict):
                raise DirectWriteReservationError(
                    "Invalid existing reservation"
                )

            # A repeated reservation must have the same
            # execution identity and immutable request fields.
            for field in (
                "operation_key",
                "payload_hash",
                "command",
                "database",
                "run_id",
                "task_id",
                "write_id",
            ):
                if existing.get(field) != proposed[field]:
                    raise DirectWriteReservationError(
                        "Conflicting write reservation"
                    )

            if existing.get("status") not in {
                "RESERVED",
                "VERIFIED",
            }:
                raise DirectWriteReservationError(
                    "Unexpected reservation status"
                )

            return dict(existing)

        # Explicitly prevent reusing a write identity that
        # already exists elsewhere in this teammate's record.
        if any(
            isinstance(value, dict)
            and value.get("operation_key") == operation_key
            for value in existing_writes.values()
        ):
            raise DirectWriteReservationError(
                "Duplicate operation identity"
            )

        existing_writes[write_id] = proposed
        record["direct_writes"] = existing_writes

        return dict(proposed)
