"""Generic teammate-result context and terminal-recovery helpers.

This module provides task lookup, bounded hook context output, and generic
terminal-result recovery behavior. It contains no Merchant-domain logic.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from team_lifecycle import (
        claim_terminal_recovery,
        load_team_state,
        mark_teammate_failed,
    )
    from tmux_result_receipt import (
        clear_pending_result,
    )
except ModuleNotFoundError:
    from .team_lifecycle import (
        claim_terminal_recovery,
        load_team_state,
        mark_teammate_failed,
    )
    from .tmux_result_receipt import (
        clear_pending_result,
    )


MISSING_RESULT_FEEDBACK = (
    "Your result was not delivered to the lead. Send your complete existing "
    "report now through SendMessage to team-lead; do not redo the task. "
    "After SendMessage succeeds, finish with only: RESULT_DELIVERED."
)

INVALID_TERMINAL_RESULT_FEEDBACK = (
    "Your report was delivered, but its machine-readable terminal "
    "result is invalid or incomplete. Do not redo the task. Send the "
    "same result once more through SendMessage to team-lead with exactly "
    "one valid TEAM_RESULT_JSON block describing the actual outcome, then "
    "finish with only: RESULT_DELIVERED."
)

PENDING_RESULT_FEEDBACK = (
    "Result delivery is still incomplete. Send the existing report once "
    "through SendMessage to team-lead; do not repeat the task."
)


def active_task_id(
    session_id: Any,
    teammate_name: str,
) -> str:
    """Resolve the current task because TeammateIdle may omit task_id."""

    team_state = load_team_state(
        session_id
    )

    if not isinstance(
        team_state,
        dict,
    ):
        return ""

    record = (
        team_state.get(
            "teammates"
        )
        or {}
    ).get(
        teammate_name
    )

    if not isinstance(
        record,
        dict,
    ):
        return ""

    if (
        record.get(
            "canonical_name"
        )
        != teammate_name
    ):
        return ""

    return str(
        record.get(
            "current_task_id"
        )
        or ""
    ).strip()


def emit_post_tool_context(
    feedback: str,
) -> None:
    """Return bounded PostToolUse feedback without polluting tool stdout."""

    document = {
        "hookSpecificOutput": {
            "hookEventName": (
                "PostToolUse"
            ),
            "additionalContext": (
                feedback
            ),
        }
    }

    print(
        json.dumps(
            document,
            ensure_ascii=False,
        )
    )


def bounded_terminal_result_failure(
    *,
    owner_session_id: Any,
    pane_session_id: Any,
    teammate_name: str,
    run_id: str,
    task_id: str,
    reason: str,
) -> str:
    """Give an invalid terminal result exactly one correction turn."""

    recovery_claimed, recovery_status = (
        claim_terminal_recovery(
            owner_session_id,
            teammate_name,
            run_id,
            task_id,
        )
    )

    if recovery_claimed:
        return (
            INVALID_TERMINAL_RESULT_FEEDBACK
        )

    if recovery_status == "ALREADY_SENT":
        mark_teammate_failed(
            owner_session_id,
            teammate_name,
            reason=reason,
        )

        if pane_session_id:
            clear_pending_result(
                pane_session_id
            )

        return ""

    # Unexpected lifecycle/binding failures remain fail-closed.
    return PENDING_RESULT_FEEDBACK
