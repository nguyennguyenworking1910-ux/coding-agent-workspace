#!/usr/bin/env python3
"""Stop and SessionEnd hook: manage run and team state cleanup.

Stop hook: clears only the run state so the next `/solve` gets a fresh budget.
SessionEnd hook: clears both run state and team state when the session ends.

The distinction is important: team state is session-scoped and persists across
multiple `/solve` runs for teammate reuse, but run state must be cleared after
each run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runtime_state import clear_state  # noqa: E402
    from team_lifecycle import clear_team_state  # noqa: E402
else:
    from .runtime_state import clear_state
    from .team_lifecycle import clear_team_state


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if not isinstance(payload, dict):
        return 0

    session_id = payload.get("session_id")
    hook_event = payload.get("hook_event_name", "").lower()

    clear_state(session_id)

    if hook_event == "sessionend":
        clear_team_state(session_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
