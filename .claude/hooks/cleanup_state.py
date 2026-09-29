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
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(
        0,
        str(
            Path(__file__).resolve().parent
        ),
    )

    from runtime_state import (  # noqa: E402
        clear_state,
        load_state,
    )

    from team_lifecycle import (  # noqa: E402
        GLOBAL_OWNER_STATUSES,
        clear_team_state,
        load_team_state,
    )

    from merchant_confirmation_preferences import (  # noqa: E402
        clear_preferences,
    )

else:
    from .runtime_state import (
        clear_state,
        load_state,
    )

    from .team_lifecycle import (
        GLOBAL_OWNER_STATUSES,
        clear_team_state,
        load_team_state,
    )

    from .merchant_confirmation_preferences import (
        clear_preferences,
    )

def active_teammate_owns_run(
    session_id: Any,
    run_id: Any,
) -> bool:
    """Return True while this exact run still owns an active teammate."""

    run_id_text = str(
        run_id
        or ""
    ).strip()

    if not run_id_text:
        return False

    team_state = load_team_state(
        session_id
    )

    if not isinstance(
        team_state,
        dict,
    ):
        return False

    teammates = team_state.get(
        "teammates",
        {},
    )

    if not isinstance(
        teammates,
        dict,
    ):
        return False

    for record in teammates.values():
        if not isinstance(
            record,
            dict,
        ):
            continue

        teammate_run_id = str(
            record.get(
                "current_run_id"
            )
            or ""
        ).strip()

        status = str(
            record.get(
                "status"
            )
            or ""
        ).strip()

        if (
            teammate_run_id
            == run_id_text
            and status
            in GLOBAL_OWNER_STATUSES
        ):
            return True

    return False


def main() -> int:
    try:
        payload = json.load(
            sys.stdin
        )
    except (
        json.JSONDecodeError,
        ValueError,
    ):
        return 0

    if not isinstance(
        payload,
        dict,
    ):
        return 0

    session_id = payload.get(
        "session_id"
    )

    hook_event = str(
        payload.get(
            "hook_event_name"
        )
        or ""
    ).strip().lower()

    # SessionEnd is authoritative final cleanup.
    if hook_event == "sessionend":
        clear_state(
            session_id
        )

        clear_team_state(
            session_id
        )

        clear_preferences(
            session_id
        )

        return 0

    if hook_event != "stop":
        return 0

    # A lead Stop may fire while an Agent Team teammate is still
    # performing the current run. Gate 7.4 still requires this
    # exact persisted run-state document.
    #
    # Never clear it while an exact teammate ownership binding for
    # this run remains active.
    run_state = load_state(
        session_id
    )

    if not isinstance(
        run_state,
        dict,
    ):
        return 0

    run_id = str(
        run_state.get(
            "run_id"
        )
        or ""
    ).strip()

    if (
        run_id
        and active_teammate_owns_run(
            session_id,
            run_id,
        )
    ):
        return 0

    clear_state(
        session_id
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
