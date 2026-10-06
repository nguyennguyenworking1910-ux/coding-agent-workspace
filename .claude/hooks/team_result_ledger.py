"""Generic teammate result-ledger helpers.

This module owns idempotent teammate result delivery bookkeeping only.
It performs no lifecycle transition, Merchant authorization, runtime apply,
or external side effect.
"""

from __future__ import annotations

from typing import Any


def record_teammate_result(
    state: dict[str, Any],
    teammate_name: str,
    task_id: str,
    source: str = "unknown",
) -> bool:
    """Record a teammate result delivery in the idempotent ledger.

    Deduplication key: run_id + task_id + teammate_name.
    Returns True for a first result delivery, False when already delivered.
    """

    run_id = state.get(
        "run_id",
        "",
    )

    ledger = state.get(
        "result_ledger",
        {},
    )

    dedup_key = (
        f"{run_id}:"
        f"{task_id}:"
        f"{teammate_name}"
    )

    is_new_result = (
        dedup_key not in ledger
    )

    if dedup_key not in ledger:
        ledger[dedup_key] = {
            "teammate_name": teammate_name,
            "task_id": task_id,
            "result_received": True,
            "delivery_sources": [],
            "recovery_sent": False,
        }
    else:
        ledger[
            dedup_key
        ][
            "result_received"
        ] = True

    if (
        source
        not in ledger[
            dedup_key
        ][
            "delivery_sources"
        ]
    ):
        ledger[
            dedup_key
        ][
            "delivery_sources"
        ].append(
            source
        )

    state[
        "result_ledger"
    ] = ledger

    return is_new_result


def mark_recovery_sent(
    state: dict[str, Any],
    teammate_name: str,
    task_id: str,
) -> bool:
    """Mark that delivery recovery was requested and suppress duplicates."""

    run_id = state.get(
        "run_id",
        "",
    )

    ledger = state.get(
        "result_ledger",
        {},
    )

    dedup_key = (
        f"{run_id}:"
        f"{task_id}:"
        f"{teammate_name}"
    )

    if dedup_key not in ledger:
        ledger[dedup_key] = {
            "teammate_name": teammate_name,
            "task_id": task_id,
            "result_received": False,
            "delivery_sources": [],
            "recovery_sent": False,
        }

    record = ledger[
        dedup_key
    ]

    if record.get(
        "result_received"
    ):
        return False

    if record.get(
        "recovery_sent"
    ):
        return False

    record[
        "recovery_sent"
    ] = True

    state[
        "result_ledger"
    ] = ledger

    return True
