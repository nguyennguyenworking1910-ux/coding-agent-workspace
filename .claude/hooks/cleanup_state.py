#!/usr/bin/env python3
"""Stop and SessionEnd hook: manage run and team state cleanup.

Stop hook: clears only the run state so the next `/solve` gets a fresh budget.
SessionEnd hook: clears run state, team state, and the Merchant confirmation
preference when the session ends.

The distinction is important: team state and the Merchant confirmation
preference are session-scoped and persist across multiple `/solve` runs - one
for teammate reuse, the other so a local auto-confirm session does not have to
be re-enabled per run. Run state must be cleared after each run.

Clearing the Merchant confirmation preference at SessionEnd is what makes
MANUAL mode the default of every new session, and it discards any unspent
proposal receipt with it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runtime_state import clear_state  # noqa: E402
    from team_lifecycle import clear_team_state  # noqa: E402
    from merchant_confirmation_preferences import (  # noqa: E402
        clear_preferences,
    )
else:
    from .runtime_state import clear_state
    from .team_lifecycle import clear_team_state
    from .merchant_confirmation_preferences import clear_preferences


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
        clear_preferences(session_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
