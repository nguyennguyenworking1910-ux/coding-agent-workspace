#!/usr/bin/env python3
"""CLI tool for checking and managing session-scoped team state.

Can be called from solve.md or other contexts to check if a teammate
is available for reuse or if we need to create a new one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from team_lifecycle import (  # noqa: E402
        get_teammate_status,
        team_state_dir,
    )
else:
    from .team_lifecycle import (
        get_teammate_status,
        team_state_dir,
    )


def check_teammate_available(session_id: str, role: str) -> dict[str, any]:
    """Check if a teammate for a given role exists and is reusable."""
    status = get_teammate_status(session_id, role)

    if status is None:
        return {
            "available": True,
            "status": "DOES_NOT_EXIST",
            "message": f"Role '{role}' not yet created in this session.",
        }

    if status in ("IDLE_REUSABLE", "ACKNOWLEDGED", "REPORT_RECEIVED"):
        return {
            "available": True,
            "status": status,
            "message": f"Teammate for '{role}' is idle and ready for reuse.",
        }

    return {
        "available": False,
        "status": status,
        "message": f"Teammate for '{role}' is busy ({status}); cannot dispatch another instance.",
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: team_state_cli.py <command> [args]"}))
        return 1

    command = sys.argv[1]

    if command == "check":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "check requires session_id and role"}))
            return 1

        session_id = sys.argv[2]
        role = sys.argv[3]

        result = check_teammate_available(session_id, role)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    elif command == "state_dir":
        print(str(team_state_dir()))
        return 0

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
