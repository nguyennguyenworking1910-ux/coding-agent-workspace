"""Shared trusted context for resolution staging.

This module normalizes and validates the common owner/pane/task binding used
before Project, Document Revision, and Step resolution staging.

It performs no receipt loading, no resolution staging, no CLI parsing,
and no state mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RESOLUTION_OPERATIONS = frozenset(
    {
        "merchant_read",
        "merchant_propose",
        "merchant_apply",
    }
)

RESOLUTION_TEAMMATE = "merchant-manager"


@dataclass(frozen=True)
class ResolutionStageContext:
    pane_session_id: str
    owner_session_id: str
    teammate_name: str
    run_id: str
    task_id: str
    operation: str


def resolution_stage_context(
    *,
    payload: Any,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    authorized_operations: Any,
) -> ResolutionStageContext | None:
    """Return one normalized trusted staging context or fail closed."""

    if not isinstance(
        payload,
        dict,
    ):
        return None

    pane_id = str(
        pane_session_id
        or ""
    ).strip()

    owner_id = str(
        owner_session_id
        or ""
    ).strip()

    teammate = str(
        teammate_name
        or ""
    ).strip()

    owner_run_id = str(
        run_id
        or ""
    ).strip()

    owner_task_id = str(
        task_id
        or ""
    ).strip()

    if not (
        pane_id
        and owner_id
        and teammate
        and owner_run_id
        and owner_task_id
    ):
        return None

    if (
        teammate
        != RESOLUTION_TEAMMATE
    ):
        return None

    operations = [
        str(
            operation
        ).strip()
        for operation
        in (
            authorized_operations
            or []
        )
        if str(
            operation
        ).strip()
    ]

    if len(
        operations
    ) != 1:
        return None

    operation = operations[0]

    if (
        operation
        not in RESOLUTION_OPERATIONS
    ):
        return None

    return ResolutionStageContext(
        pane_session_id=pane_id,
        owner_session_id=owner_id,
        teammate_name=teammate,
        run_id=owner_run_id,
        task_id=owner_task_id,
        operation=operation,
    )
