"""Coordinate authorized Merchant Direct Execute requests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from claude.hooks.merchant_direct_write_state import (
    reserve_merchant_create,
)
from claude.hooks.merchant_reserved_execution import (
    execute_reserved_merchant_create,
)


class DirectCoordinatorError(ValueError):
    """Invalid protected execution request."""


def execute_bound_merchant_create(
    *,
    owner_session_id: str,
    teammate_name: str,
    pane_session_id: str,
    run_id: str,
    task_id: str,
    write_id: str,
    payload: Mapping[str, Any],
    database: str = "runtime",
    repository: Any = None,
) -> dict[str, Any]:
    """Execute a bound Merchant creation.

    Caller identity and write_id must come from trusted
    orchestration state, never from agent-supplied JSON.
    """

    if database not in {"runtime", "test"}:
        raise DirectCoordinatorError(
            "Invalid Merchant database target"
        )

    if not isinstance(payload, Mapping):
        raise DirectCoordinatorError(
            "Merchant payload must be a mapping"
        )

    safe_payload = dict(payload)

    allowed_fields = {
        "merchant_id",
        "code",
        "name",
        "region_code",
        "created_by",
    }

    if set(safe_payload) - allowed_fields:
        raise DirectCoordinatorError(
            "Unexpected Merchant payload fields"
        )

    if repository is None:
        raise DirectCoordinatorError(
            "Trusted repository is required"
        )

    context = {
        "owner_session_id": owner_session_id,
        "teammate_name": teammate_name,
        "pane_session_id": pane_session_id,
        "run_id": run_id,
        "task_id": task_id,
        "write_id": write_id,
        "database": database,
        "payload": safe_payload,
    }

    reserve_merchant_create(**context)

    result = execute_reserved_merchant_create(
        repository=repository,
        **context,
    )

    if (
        not isinstance(result, dict)
        or result.get("success") is not True
        or result.get("mode") != "EXECUTE"
        or result.get("command") != "merchant create"
        or result.get("database") != database
    ):
        raise DirectCoordinatorError(
            "Invalid protected execution result"
        )

    return result
