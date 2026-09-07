#!/usr/bin/env python3
"""PostToolBatch hook: count how many dispatch rounds a run has spent.

`limits.max_tool_rounds` bounds rounds, not calls, so something has to decide
where one round ends. A round is one top-level batch that contained at least one
Agent dispatch: three agents sent concurrently in a single message is one round,
and the tools those agents then run are theirs, not a new round of the leader's.

Only batches with an Agent call are counted, and only when the batch belongs to
the main session. A subagent's own batch would otherwise inflate the leader's
round count and strand the run early.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runtime_state import locked_state  # noqa: E402
else:
    from .runtime_state import locked_state

AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})

# Keys a batch payload may use for its list of calls. Checked in order; the first
# one present wins.
BATCH_LIST_KEYS = (
    "tool_calls",
    "tool_uses",
    "tools",
    "batch",
    "calls",
    "tool_inputs",
    "tool_results",
)

# Any of these being set means the batch came from inside a subagent rather than
# the main session. Treated as a family because the payload only needs to carry
# one of them for the distinction to hold.
SUBAGENT_MARKER_KEYS = (
    "agent_id",
    "subagent_id",
    "subagent_type",
    "parent_tool_use_id",
    "parent_session_id",
    "is_subagent",
    "is_nested",
    "nested",
)


def batch_tool_names(payload: dict[str, Any]) -> list[str]:
    """Best-effort extraction of the tool names in a batch payload."""
    for key in BATCH_LIST_KEYS:
        entries = payload.get(key)

        if not isinstance(entries, list):
            continue

        names: list[str] = []

        for entry in entries:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                name = entry.get("tool_name") or entry.get("name") or entry.get("tool")

                if isinstance(name, str):
                    names.append(name)

        if names:
            return names

    # Some payloads describe a single call rather than a list.
    single = payload.get("tool_name")

    return [single] if isinstance(single, str) else []


def is_top_level_batch(payload: dict[str, Any]) -> bool:
    """False when the batch was produced inside a subagent."""
    return not any(payload.get(key) for key in SUBAGENT_MARKER_KEYS)


def contains_agent_dispatch(payload: dict[str, Any]) -> bool:
    return any(name in AGENT_TOOL_NAMES for name in batch_tool_names(payload))


def should_count(payload: dict[str, Any]) -> bool:
    return is_top_level_batch(payload) and contains_agent_dispatch(payload)


def record_round(session_id: Any) -> int | None:
    """Increment agent_rounds under the lock. Returns the new value, or None."""
    with locked_state(session_id) as state:
        if state is None:
            return None

        state["agent_rounds"] = int(state.get("agent_rounds", 0)) + 1

        return state["agent_rounds"]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if not isinstance(payload, dict):
        return 0

    if should_count(payload):
        record_round(payload.get("session_id"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
