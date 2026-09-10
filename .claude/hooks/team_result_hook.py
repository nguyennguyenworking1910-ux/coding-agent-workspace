#!/usr/bin/env python3
"""PostToolUse and TeammateIdle hooks: idempotent teammate result delivery.

Handles two result delivery paths:
1. PostToolUse: intercepts successful SendMessage tool calls from teammates
2. TeammateIdle: automatic final-answer delivery when a teammate finishes

Uses deduplication key: run_id + task_id + canonical_teammate_name
- If both sources deliver, stores both but processes one logical result
- TaskUpdate (status-only) does not count as a complete result
- Once result_received is true, no recovery request is allowed
- recovery_sent flag prevents multiple recovery requests

Updates both run state (result ledger) and team state (lifecycle status).
When result is received, marks team state REPORT_RECEIVED.
When TeammateIdle fires after result received, marks team state IDLE_REUSABLE.

Stop hook clears run state only.
SessionEnd hook clears run state and session team state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runtime_state import locked_state  # noqa: E402
    from team_lifecycle import (  # noqa: E402
        mark_report_received,
        mark_teammate_idle_reusable,
    )
else:
    from .runtime_state import locked_state
    from .team_lifecycle import (
        mark_report_received,
        mark_teammate_idle_reusable,
    )


HOOK_EVENT_NAMES = ("PostToolUse", "TeammateIdle")


def record_teammate_result(
    state: dict[str, Any],
    teammate_name: str,
    task_id: str,
    source: str = "unknown",
) -> bool:
    """Record a teammate result delivery in the idempotent ledger.

    Deduplication key: run_id + task_id + teammate_name
    Returns True if this is a first result delivery, False if already delivered.
    Multiple delivery sources (automatic + SendMessage) are tracked in the same record.
    """
    run_id = state.get("run_id", "")
    ledger = state.get("result_ledger", {})

    dedup_key = f"{run_id}:{task_id}:{teammate_name}"

    is_new_result = dedup_key not in ledger

    if dedup_key not in ledger:
        ledger[dedup_key] = {
            "teammate_name": teammate_name,
            "task_id": task_id,
            "result_received": True,
            "delivery_sources": [],
            "recovery_sent": False,
        }
    else:
        ledger[dedup_key]["result_received"] = True

    ledger[dedup_key]["delivery_sources"].append(source)
    state["result_ledger"] = ledger

    return is_new_result


def mark_recovery_sent(
    state: dict[str, Any],
    teammate_name: str,
    task_id: str,
) -> bool:
    """Mark that a recovery request was sent. Prevent duplicates.

    Returns True if recovery was NOT previously sent and result not received.
    Returns False if already sent or if result already received.
    """
    run_id = state.get("run_id", "")
    ledger = state.get("result_ledger", {})

    dedup_key = f"{run_id}:{task_id}:{teammate_name}"

    if dedup_key not in ledger:
        ledger[dedup_key] = {
            "teammate_name": teammate_name,
            "task_id": task_id,
            "result_received": False,
            "delivery_sources": [],
            "recovery_sent": False,
        }

    record = ledger[dedup_key]

    if record.get("result_received"):
        return False

    if record.get("recovery_sent"):
        return False

    record["recovery_sent"] = True
    state["result_ledger"] = ledger

    return True


def handle_post_tool_use(
    state: dict[str, Any],
    payload: dict[str, Any],
    session_id: Any = None,
) -> None:
    """Handle PostToolUse: intercept successful SendMessage calls.

    SendMessage is the primary result delivery path. The sender (teammate_name)
    is extracted from the tool input or payload context.

    Updates both run-level result ledger and team lifecycle state.
    """
    tool_name = str(payload.get("tool_name") or "").strip()

    if tool_name != "SendMessage":
        return

    tool_input = payload.get("tool_input")

    if not isinstance(tool_input, dict):
        return

    to_field = str(tool_input.get("to") or "").strip()

    if to_field != "team-lead":
        return

    teammate_name = str(tool_input.get("from_teammate") or "").strip()

    if not teammate_name:
        teammate_name = str(payload.get("teammate_name") or "").strip()

    task_id = str(tool_input.get("task_id") or "")

    if not task_id:
        task_id = payload.get("task_id") or ""

    if teammate_name and task_id:
        record_teammate_result(state, teammate_name, task_id, "sendmessage")

        if session_id:
            mark_report_received(session_id, teammate_name, task_id, "sendmessage")


def handle_teammate_idle(
    state: dict[str, Any],
    payload: dict[str, Any],
    session_id: Any = None,
) -> None:
    """Handle TeammateIdle: automatic final-answer delivery or idle transition.

    When a teammate becomes idle, check if a result was already received.
    - If result was received in this task, mark team state IDLE_REUSABLE for reuse
    - If no result yet, record as automatic delivery (should not happen in normal flow)

    Updates both run-level result ledger and team lifecycle state.
    """
    teammate_name = str(payload.get("teammate_name") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()

    if not (teammate_name and task_id):
        return

    run_id = state.get("run_id", "")
    ledger = state.get("result_ledger", {})
    dedup_key = f"{run_id}:{task_id}:{teammate_name}"

    result_already_received = dedup_key in ledger and ledger[dedup_key].get("result_received")

    if result_already_received:
        if session_id:
            mark_teammate_idle_reusable(session_id, teammate_name)
    else:
        record_teammate_result(state, teammate_name, task_id, "automatic")
        if session_id:
            mark_report_received(session_id, teammate_name, task_id, "automatic")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if not isinstance(payload, dict):
        return 0

    hook_event = str(payload.get("hook_event_name") or "").strip()
    session_id = payload.get("session_id")

    if hook_event not in HOOK_EVENT_NAMES:
        return 0

    with locked_state(session_id) as state:
        if state is None:
            return 0

        if hook_event == "PostToolUse":
            handle_post_tool_use(state, payload, session_id)
        elif hook_event == "TeammateIdle":
            handle_teammate_idle(state, payload, session_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
