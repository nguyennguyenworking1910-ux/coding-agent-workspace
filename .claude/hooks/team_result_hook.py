#!/usr/bin/env python3
"""PostToolUse and TeammateIdle hooks: exact teammate result delivery.

`SendMessage` to `team-lead` is the single machine-verifiable result path.
`TeammateIdle` is only a lifecycle signal: it never invents a result. If a
teammate tries to become idle before sending its report, the hook exits with
code 2 and asks it to send the existing report without repeating the task.

Uses deduplication key: run_id + task_id + canonical_teammate_name.
- Repeated SendMessage delivery is one logical result
- TaskUpdate and TeammateIdle do not count as complete results
- Once result_received is true, no recovery request is allowed
- recovery_sent records that delivery recovery was initiated

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
        find_unique_active_teammate_owner,
        load_team_state,
        mark_bound_report_received,
        mark_report_received,
        release_reported_teammate_to_idle,
    )
    from merchant_confirmation_preferences import (  # noqa: E402
        MERCHANT_MANAGER_AGENT,
        MERCHANT_PROPOSE_OPERATION,
        capture_proposal_receipt,
    )
    from tmux_result_receipt import (
        clear_pending_result,
        load_pending_result,
        stage_pending_result,
    )
else:
    from .runtime_state import locked_state
    from .team_lifecycle import (
        find_unique_active_teammate_owner,
        load_team_state,
        mark_bound_report_received,
        mark_report_received,
        release_reported_teammate_to_idle,
    )
    from .merchant_confirmation_preferences import (
        MERCHANT_MANAGER_AGENT,
        MERCHANT_PROPOSE_OPERATION,
        capture_proposal_receipt,
    )
    from tmux_result_receipt import (
        clear_pending_result,
        load_pending_result,
        stage_pending_result,
    )


HOOK_EVENT_NAMES = ("PostToolUse", "TeammateIdle")

MISSING_RESULT_FEEDBACK = (
    "Your result was not delivered to the lead. Send your complete existing "
    "report now through SendMessage to team-lead; do not redo the task. "
    "After SendMessage succeeds, finish with only: RESULT_DELIVERED."
)
PENDING_RESULT_FEEDBACK = (
    "Result delivery is still incomplete. Send the existing report once "
    "through SendMessage to team-lead; do not repeat the task."
)


def record_teammate_result(
    state: dict[str, Any],
    teammate_name: str,
    task_id: str,
    source: str = "unknown",
) -> bool:
    """Record a teammate result delivery in the idempotent ledger.

    Deduplication key: run_id + task_id + teammate_name
    Returns True if this is a first result delivery, False if already delivered.
    Repeated accepted deliveries are tracked as one logical result.
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

    if source not in ledger[dedup_key]["delivery_sources"]:
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


def _coalesced_text(mapping: dict[str, Any], *fields: str) -> str:
    """Return one unambiguous non-empty text value across alias fields."""
    values = []

    for field in fields:
        value = mapping.get(field)

        if value is None:
            continue

        text = str(value).strip()

        if text:
            values.append(text)

    if not values or any(value != values[0] for value in values[1:]):
        return ""

    return values[0]


def trusted_post_tool_sender(payload: dict[str, Any]) -> str:
    """Return the harness-authenticated sender for a nested tool call.

    PostToolUse identifies a subagent/teammate with agent_id and agent_type.
    Values inside tool_input are agent-controlled and are never sender proof.
    """
    agent_id = str(payload.get("agent_id") or "").strip()
    agent_type = str(payload.get("agent_type") or "").strip()

    if not (agent_id and agent_type):
        return ""

    return agent_type


def active_task_id(session_id: Any, teammate_name: str) -> str:
    """Resolve the current task because TeammateIdle carries no task_id."""
    team_state = load_team_state(session_id)

    if not isinstance(team_state, dict):
        return ""

    record = (team_state.get("teammates") or {}).get(teammate_name)

    if not isinstance(record, dict):
        return ""

    if record.get("canonical_name") != teammate_name:
        return ""

    return str(record.get("current_task_id") or "").strip()


def handle_post_tool_use(
    state: dict[str, Any] | None,
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

    to_field = _coalesced_text(tool_input, "recipient", "to")

    if to_field != "team-lead":
        return

    message = _coalesced_text(
        tool_input,
        "content",
        "message",
    )

    if not message:
        return

    teammate_name = trusted_post_tool_sender(
        payload
    )

    if not teammate_name:
        # tmux/pane-backed teammates currently have no authenticated
        # agent_id/agent_type in PostToolUse. Do NOT trust tool_input
        # for sender identity. Stage the successful SendMessage under
        # this pane session and bind it later through TeammateIdle.
        if session_id:
            stage_pending_result(
                session_id=session_id,
                message=message,
                tool_use_id=str(
                    payload.get(
                        "tool_use_id"
                    )
                    or ""
                ),
                task_id_hint=str(
                    tool_input.get(
                        "task_id"
                    )
                    or payload.get(
                        "task_id"
                    )
                    or ""
                ),
            )

        return

    if not message:
        return

    task_id = str(tool_input.get("task_id") or "")

    if not task_id:
        task_id = str(payload.get("task_id") or "").strip()

    current_task_id = active_task_id(session_id, teammate_name)

    if current_task_id:
        if task_id and task_id != current_task_id:
            return

        task_id = current_task_id

    if teammate_name and task_id:
        if state is not None:
            record_teammate_result(
                state,
                teammate_name,
                task_id,
                "sendmessage",
            )

        if session_id:
            mark_report_received(session_id, teammate_name, task_id, "sendmessage")


def handle_teammate_idle(
    state: dict[str, Any] | None,
    payload: dict[str, Any],
    session_id: Any = None,
) -> str:
    """Handle TeammateIdle as a delivery quality gate.

    Return an empty string when idle is allowed. Return feedback when the
    teammate must remain active and deliver its existing report first. The
    successful path uses session-scoped team state because Stop may already
    have cleared the completed run's state document.
    """
    teammate_name = str(payload.get("teammate_name") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()

    if not teammate_name:
        return ""

    if session_id:
        direct_team_state = load_team_state(session_id)

        if direct_team_state is not None:
            released, _ = release_reported_teammate_to_idle(
                session_id,
                teammate_name,
            )

            if released:
                return ""

        # tmux fallback:
        # TeammateIdle gives us the trusted teammate_name, while its
        # session_id belongs to the pane. Resolve the unique lead session
        # that currently owns this canonical teammate.
        (
            owner_session_id,
            owner_record,
            owner_resolution,
        ) = find_unique_active_teammate_owner(
            teammate_name
        )

        if owner_resolution == "AMBIGUOUS":
            return (
                "Cannot safely reconcile this teammate because more than "
                "one active lead session owns the same canonical teammate. "
                "Do not start new work."
            )

        if (
            owner_resolution == "FOUND"
            and owner_session_id
            and isinstance(
                owner_record,
                dict,
            )
            and str(owner_session_id) != str(session_id)
        ):
            pending_result = (
                load_pending_result(
                    session_id
                )
                if session_id
                else None
            )

            if pending_result is None:
                return MISSING_RESULT_FEEDBACK

            owner_run_id = str(
                owner_record.get(
                    "current_run_id"
                )
                or ""
            ).strip()

            owner_task_id = str(
                owner_record.get(
                    "current_task_id"
                )
                or ""
            ).strip()

            if not (
                owner_run_id
                and owner_task_id
            ):
                return PENDING_RESULT_FEEDBACK

            marked = mark_bound_report_received(
                owner_session_id,
                teammate_name,
                owner_run_id,
                owner_task_id,
                "sendmessage",
            )

            if not marked:
                return PENDING_RESULT_FEEDBACK

            # Update the lead run ledger when it still exists.
            # Stop may already have removed it, in which case team state
            # remains the authoritative completion record.
            if str(owner_session_id) == str(
                session_id
            ):
                if state is not None:
                    record_teammate_result(
                        state,
                        teammate_name,
                        owner_task_id,
                        "sendmessage",
                    )
            else:
                with locked_state(
                    owner_session_id
                ) as owner_state:
                    if owner_state is not None:
                        record_teammate_result(
                            owner_state,
                            teammate_name,
                            owner_task_id,
                            "sendmessage",
                        )

            released, _ = (
                release_reported_teammate_to_idle(
                    owner_session_id,
                    teammate_name,
                )
            )

            if not released:
                return PENDING_RESULT_FEEDBACK

            if session_id:
                clear_pending_result(
                    session_id
                )

            return ""

    current_task_id = active_task_id(session_id, teammate_name)

    if current_task_id:
        if task_id and task_id != current_task_id:
            return ""

        task_id = current_task_id

    if not (teammate_name and task_id):
        return ""

    if state is None:
        return MISSING_RESULT_FEEDBACK

    run_id = state.get("run_id", "")
    ledger = state.get("result_ledger", {})
    dedup_key = f"{run_id}:{task_id}:{teammate_name}"

    result_already_received = dedup_key in ledger and ledger[dedup_key].get("result_received")

    if result_already_received:
        if session_id:
            mark_report_received(
                session_id,
                teammate_name,
                task_id,
                "sendmessage",
            )
            released, _ = release_reported_teammate_to_idle(
                session_id,
                teammate_name,
            )

            if not released:
                team_state = load_team_state(session_id)
                teammate_record = None

                if isinstance(team_state, dict):
                    teammate_record = (
                        team_state.get("teammates", {})
                    ).get(teammate_name)

                if isinstance(teammate_record, dict):
                    return PENDING_RESULT_FEEDBACK

        return ""

    recovery_is_new = mark_recovery_sent(state, teammate_name, task_id)
    return (
        MISSING_RESULT_FEEDBACK
        if recovery_is_new
        else PENDING_RESULT_FEEDBACK
    )


def merchant_report_sender(payload: dict[str, Any]) -> str:
    """Resolve the sender only from harness-authenticated hook fields."""
    return trusted_post_tool_sender(payload)


def embedded_json_objects(text: str) -> list[Any]:
    """Return every JSON object embedded in a teammate report body.

    A report is prose with one or more fenced CLI results inside it, so the
    body is scanned for decodable objects instead of being parsed whole.
    """
    decoder = json.JSONDecoder()
    objects: list[Any] = []
    index = text.find("{")

    while index != -1:
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue

        if isinstance(value, dict):
            objects.append(value)
            index = text.find("{", max(end, index + 1))
        else:  # pragma: no cover - raw_decode at "{" yields a dict
            index = text.find("{", index + 1)

    return objects


def handle_merchant_proposal_receipt(
    state: dict[str, Any],
    payload: dict[str, Any],
    session_id: Any = None,
) -> bool:
    """Capture a proposal receipt from the canonical merchant-manager report.

    This is the only accepted source. Pane text, `TaskUpdate`, idle
    notifications, a non-canonical teammate, an ordinary subagent, a failed
    CLI result, a test-database result, and malformed or inconsistently
    redacted JSON are all refused, and refusal is silent: the later apply
    reports the missing receipt instead.
    """
    if str(payload.get("tool_name") or "").strip() != "SendMessage":
        return False

    tool_input = payload.get("tool_input")

    if not isinstance(tool_input, dict):
        return False

    if _coalesced_text(tool_input, "recipient", "to") != "team-lead":
        return False

    if merchant_report_sender(payload) != MERCHANT_MANAGER_AGENT:
        return False

    # The envelope, not the message, establishes that this session was doing
    # exclusive Merchant proposal work.
    operations = [
        str(operation) for operation in state.get("operations") or []
    ]
    selected_agents = [
        str(agent) for agent in state.get("selected_agents") or []
    ]

    if operations != [MERCHANT_PROPOSE_OPERATION]:
        return False

    if selected_agents != [MERCHANT_MANAGER_AGENT]:
        return False

    message = _coalesced_text(tool_input, "content", "message")

    if not message:
        return False

    candidates = [
        candidate
        for candidate in embedded_json_objects(message)
        if "confirmation_token" in candidate
    ]

    # More than one proposal in a single report is ambiguous about which one
    # a later apply would mean.
    if len(candidates) != 1:
        return False

    return capture_proposal_receipt(session_id, candidates[0]).accepted


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

    idle_feedback = ""

    with locked_state(session_id) as state:
        if hook_event == "PostToolUse":
            handle_post_tool_use(state, payload, session_id)

            if state is not None:
                handle_merchant_proposal_receipt(
                    state,
                    payload,
                    session_id,
                )
        elif hook_event == "TeammateIdle":
            idle_feedback = handle_teammate_idle(
                state,
                payload,
                session_id,
            )

    if idle_feedback:
        print(idle_feedback, file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
