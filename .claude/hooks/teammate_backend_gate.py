#!/usr/bin/env python3
"""PostToolUse(Agent) hook: a /solve teammate must run in its own psmux pane.

The policy gate binds a dispatch to the run before the harness spawns the
teammate, but only the harness decides the backend. After the spawn, this hook
accepts the teammate only if the harness team config records a tmux backend
and pane for it and the operating system shows that pane under the lead's
psmux server (see team_lifecycle.verify_spawned_teammate_backend). Otherwise
the task ends FAILED, so it cannot deliver a result or be reused, and the lead
is told to stop the teammate. In-process teammates are never accepted.

Fails closed: any error still blocks with instructions to stop the teammate.
Agent calls outside a /solve run are ignored.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runtime_state import (  # noqa: E402
        configure_utf8_output,
        load_state,
        read_hook_payload,
    )
    from team_lifecycle import verify_spawned_teammate_backend  # noqa: E402
else:
    from .runtime_state import configure_utf8_output, load_state, read_hook_payload
    from .team_lifecycle import verify_spawned_teammate_backend

AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})


def _block(reason: str) -> None:
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": reason,
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": reason,
                },
            }
        )
    )


def _rejected(teammate: str, reason: str, *, ended: bool = True) -> str:
    outcome = (
        "Its task has ended FAILED and its result will not be accepted."
        if ended
        else "Do not use any result from it."
    )
    return (
        f"Blocked: teammate '{teammate or '?'}' is not running in its own "
        f"verified psmux pane of this session ({reason}). /solve forbids "
        f"in-process or unverified teammates. {outcome} Stop it now with "
        "TaskStop, report this failure to the user, and do not dispatch a "
        "replacement."
    )


def _main() -> int:
    try:
        payload = read_hook_payload()
    except (UnicodeDecodeError, ValueError):
        _block(_rejected("", "hook input unreadable", ended=False))
        return 0

    if not isinstance(payload, dict) or payload.get("tool_name") not in AGENT_TOOL_NAMES:
        return 0

    session_id = payload.get("session_id")
    state = load_state(session_id)

    if not isinstance(state, dict) or not state.get("run_id"):
        return 0  # not a /solve run

    tool_input = payload.get("tool_input")
    teammate = str(
        (tool_input.get("name") if isinstance(tool_input, dict) else None) or ""
    ).strip()
    response = payload.get("tool_response")
    response = response if isinstance(response, dict) else {}

    verified, reason = verify_spawned_teammate_backend(
        session_id,
        teammate,
        str(state.get("run_id")),
        reported_pane=response.get("tmux_pane_id"),
        reported_splitpane=response.get("is_splitpane"),
    )

    if not verified:
        _block(
            _rejected(
                teammate,
                reason,
                ended=reason not in ("STATE_UNAVAILABLE", "UNTRACKED_TEAMMATE"),
            )
        )

    return 0


def main() -> int:
    configure_utf8_output()

    try:
        return _main()
    except Exception as exc:  # fail closed: never accept on an error
        traceback.print_exc(file=sys.stderr)
        _block(
            _rejected("", f"backend check failed: {type(exc).__name__}", ended=False)
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
