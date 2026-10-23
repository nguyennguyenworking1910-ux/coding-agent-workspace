"""Reconcile every bound Direct Merchant write before report delivery."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from claude.hooks.team_lifecycle import (
    load_team_state,
    locked_team_state,
    has_unresolved_direct_writes,
)
from claude.hooks.merchant_completion_receipt import (
    build_completion_receipt,
    receipt_matches_state,
)
from claude.hooks.merchant_direct_recovery import (
    reconcile_committed_merchant_create,
)
from claude.hooks.merchant_diagnostics import (
    build_diagnostic_event,
    emit_diagnostic_event,
)


class DirectCompletionError(RuntimeError):
    """Direct write completion cannot be established safely."""


def reconcile_all_direct_writes(
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    repository_factory: Callable[[str], Any],
    diagnostic_sink: Any = None,
) -> bool:
    """Return True only after every bound write has verified DB evidence.

    False indicates incomplete evidence or stale lifecycle authority.
    Never executes a business write.
    """

    state = load_team_state(owner_session_id)

    if not isinstance(state, dict):
        return False

    record = state.get("teammates", {}).get(teammate_name)

    if not isinstance(record, dict):
        return False

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
        return False

    writes = record.get("direct_writes")

    if not isinstance(writes, dict) or not writes:
        return False

    # Validate the entire collection before contacting PostgreSQL.
    # Never ignore malformed or cross-task entries.
    for write_id, write in writes.items():
        if not isinstance(write_id, str) or not write_id:
            return False

        if not isinstance(write, dict):
            return False

        if (
            write.get("write_id") != write_id
            or write.get("run_id") != run_id
            or write.get("task_id") != task_id
            or write.get("command") != "merchant create"
            or write.get("database") not in {"test", "runtime"}
            or write.get("status")
            not in {"RESERVED", "EXECUTING", "VERIFIED"}
        ):
            return False

        if (
            not isinstance(write.get("operation_key"), str)
            or not isinstance(write.get("payload_hash"), str)
        ):
            return False

    # An existing generation is immutable. A missing generation
    # may be bootstrapped only through committed-evidence recovery.
    for write in writes.values():
        generation = write.get("claim_generation")

        if generation is not None and (
            type(generation) is not int or generation < 1
        ):
            return False

    # Preserve the original trusted reservation identity.
    # A shallow copy is insufficient because reservation fields
    # may be mutated during the reconciliation process.
    original_writes = deepcopy(writes)

    # Reconciliation reads PostgreSQL evidence and persists VERIFIED
    # under the trusted team-state lock. It does not run CREATE.
    for write_id, write in sorted(original_writes.items()):
        try:
            repository = repository_factory(write["database"])

            result = reconcile_committed_merchant_create(
                repository,
                owner_session_id=owner_session_id,
                teammate_name=teammate_name,
                run_id=run_id,
                task_id=task_id,
                write_id=write_id,
                database=write["database"],
            )
        except Exception as exc:
            raise DirectCompletionError(
                "Direct write reconciliation failed"
            ) from exc

        if (
            not isinstance(result, dict)
            or result.get("status") != "VERIFIED"
        ):
            return False

    # Verify the current lifecycle and every write again using a
    # fresh state read. The later mark_bound_report_received call
    # performs its own locked run/task/status check.
    final_state = load_team_state(owner_session_id)

    if not isinstance(final_state, dict):
        return False

    final_record = final_state.get(
        "teammates", {}
    ).get(teammate_name)

    if not isinstance(final_record, dict):
        return False

    if (
        final_record.get("status") != "RUNNING"
        or final_record.get("current_run_id") != run_id
        or final_record.get("current_task_id") != task_id
    ):
        return False

    final_writes = final_record.get("direct_writes")

    if not isinstance(final_writes, dict):
        return False

    if set(final_writes) != set(original_writes):
        return False

    if has_unresolved_direct_writes(final_record):
        return False

    for write_id, original in original_writes.items():
        current = final_writes.get(write_id)

        if not isinstance(current, dict):
            return False

        for field in (
            "write_id",
            "run_id",
            "task_id",
            "database",
            "command",
            "operation_key",
            "payload_hash",
            "execution_attempt_id",
        ):
            if current.get(field) != original.get(field):
                return False

        original_generation = original.get("claim_generation")
        current_generation = current.get("claim_generation")

        if (
            type(current_generation) is not int
            or current_generation < 1
        ):
            return False

        # A bound generation must not change during reconciliation.
        # None -> positive int is the permitted bootstrap transition.
        if (
            original_generation is not None
            and current_generation != original_generation
        ):
            return False

        if current.get("status") != "VERIFIED":
            return False

    # Snapshot identities after successful database reconciliation.
    # A later locked read must still match these exact values.
    expected_receipt = build_completion_receipt(final_record)

    if expected_receipt is None:
        return False

    with locked_team_state(owner_session_id) as locked_state:
        if not isinstance(locked_state, dict):
            return False

        locked_record = locked_state.get(
            "teammates", {}
        ).get(teammate_name)

        if not isinstance(locked_record, dict):
            return False

        if (
            locked_record.get("canonical_name") != teammate_name
            or locked_record.get("status") != "RUNNING"
            or locked_record.get("current_run_id") != run_id
            or locked_record.get("current_task_id") != task_id
            or locked_record.get("authorized_operations")
            != ["merchant_execute"]
            or locked_record.get("authorized_selected_agents")
            != [teammate_name]
            or locked_record.get("result_received") is True
        ):
            return False

        # Detect changes between the last unlocked state read
        # and this final trusted persistence boundary.
        if not receipt_matches_state(
            locked_record, expected_receipt
        ):
            return False

        # Preserve the original reservation identities too.
        # Never allow reconciliation to silently replace a
        # previously bound execution attempt or generation.
        locked_writes = locked_record.get("direct_writes")

        if not isinstance(locked_writes, dict):
            return False

        if set(locked_writes) != set(original_writes):
            return False

        for write_id, original in original_writes.items():
            current = locked_writes.get(write_id)

            if not isinstance(current, dict):
                return False

            for field in (
                "write_id",
                "run_id",
                "task_id",
                "database",
                "command",
                "operation_key",
                "payload_hash",
                "execution_attempt_id",
            ):
                if current.get(field) != original.get(field):
                    return False

            original_generation = original.get(
                "claim_generation"
            )
            current_generation = current.get(
                "claim_generation"
            )

            if (
                type(current_generation) is not int
                or current_generation < 1
            ):
                return False

            if (
                original_generation is not None
                and current_generation != original_generation
            ):
                return False

        existing_receipt = locked_record.get(
            "direct_completion_receipt"
        )

        # Do not overwrite conflicting or malformed receipts.
        if (
            existing_receipt is not None
            and existing_receipt != expected_receipt
        ):
            return False

        locked_record["direct_completion_receipt"] = (
            expected_receipt
        )

        # Snapshot only trusted, validated write identities.
        diagnostic_writes = tuple(
            (
                write_id,
                locked_writes[write_id]["claim_generation"],
            )
            for write_id in sorted(locked_writes)
        )

    # The lock has exited: the receipt is durably persisted.
    # Telemetry must never change the completion result.
    if diagnostic_sink is not None:
        for write_id, generation in diagnostic_writes:
            try:
                event = build_diagnostic_event(
                    event_type="merchant.completion",
                    stage="completion_receipt",
                    outcome="completed",
                    run_id=run_id,
                    task_id=task_id,
                    write_id=write_id,
                    claim_generation=generation,
                )
                emit_diagnostic_event(event, diagnostic_sink)
            except Exception:
                pass

    return True
