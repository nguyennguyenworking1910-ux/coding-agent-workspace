"""Shared helpers for team_result_hook staging functions.

Consolidates ~400 lines of duplicate context validation across 6 staging functions:
- Extract pane, role, sender, owner context
- Validate authorization and task binding
- Return validated context or False
"""

from __future__ import annotations

from typing import Any


def validate_merchant_manager_context(
    payload: dict[str, Any],
    session_id: Any,
) -> tuple[str, str, str, str, str] | None:
    """Validate and extract Merchant Manager staging context.

    Returns (pane_session_id, owner_session_id, owner_run_id, owner_task_id, tool_use_id)
    or None if validation fails.
    """
    from .team_result_hook import (
        MERCHANT_MANAGER_AGENT,
        find_unique_active_teammate_owner,
        trusted_post_tool_sender,
    )

    pane_session_id = str(session_id or "").strip()
    if not pane_session_id:
        return None

    role_hint = str(payload.get("agent_type") or "").strip()
    if role_hint != MERCHANT_MANAGER_AGENT:
        return None

    authenticated_sender = trusted_post_tool_sender(payload)
    if authenticated_sender and authenticated_sender != MERCHANT_MANAGER_AGENT:
        return None

    owner_session_id, owner_record, owner_resolution = (
        find_unique_active_teammate_owner(MERCHANT_MANAGER_AGENT)
    )

    if (
        owner_resolution != "FOUND"
        or not owner_session_id
        or not isinstance(owner_record, dict)
    ):
        return None

    owner_run_id = str(owner_record.get("current_run_id") or "").strip()
    owner_task_id = str(owner_record.get("current_task_id") or "").strip()

    if not (owner_run_id and owner_task_id):
        return None

    tool_use_id = str(payload.get("tool_use_id") or "").strip()

    return (pane_session_id, owner_session_id, owner_run_id, owner_task_id, tool_use_id)
