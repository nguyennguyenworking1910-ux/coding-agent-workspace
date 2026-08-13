#!/usr/bin/env python3
"""Stop and SessionEnd hook: drop the run state.

State outliving its run is worse than no state: the next `/solve` in the same
session would inherit spent budget, and a leftover document makes an ordinary
session look like a controlled run to the policy gate.

Registered on both events on purpose. Stop covers the normal end of a turn
(including clear, resume, and compact); SessionEnd covers the session going away
without a Stop. Removing state twice is harmless — a missing file is not an error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_state import clear_state  # noqa: E402  (path shim must run first)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if not isinstance(payload, dict):
        return 0

    clear_state(payload.get("session_id"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
