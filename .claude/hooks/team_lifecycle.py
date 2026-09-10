#!/usr/bin/env python3
"""Session-scoped Agent Team lifecycle management.

Maintains a persistent record of which teammates exist in the current session,
their lifecycle status, and whether they can be reused. This is separate from
run state, which is cleared after each `/solve` run completes.

A session has one Agent Team, and each role (reviewer, coder, etc.) can have at most
one canonical teammate unless the envelope explicitly authorizes multiple instances
(future feature).

Team state is:
- Created on first teammate dispatch
- Persisted for the session's lifetime
- Cleared when the session ends (SessionEnd hook)
- Checked before each new dispatch to enable reuse

Allocation decisions are explicit:
- CREATE: no teammate exists yet; ready to create one
- REUSE: canonical teammate exists and is idle; ready to reuse
- BUSY: canonical teammate exists but is currently active; cannot dispatch
- DENIED: lock timeout; unable to acquire team state; fail closed
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock, Timeout

CLAUDE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CLAUDE_DIR.parent

DEFAULT_TEAM_STATE_DIR = CLAUDE_DIR / "runtime" / "team_state"

# Override for tests
TEAM_STATE_DIR_ENV_VAR = "CLAUDE_TEAM_STATE_DIR"

LOCK_TIMEOUT_SECONDS = 10.0


class TeammateLifecycleStatus(str, Enum):
    """Lifecycle status of a teammate in the session."""
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    REPORT_RECEIVED = "REPORT_RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IDLE_REUSABLE = "IDLE_REUSABLE"
    FAILED = "FAILED"


class TeammateAllocationDecision(str, Enum):
    """Decision for allocating a teammate: create, reuse, busy, or denied."""
    CREATE = "CREATE"
    REUSE = "REUSE"
    BUSY = "BUSY"
    DENIED = "DENIED"


def team_state_dir() -> Path:
    """Directory holding the per-session team state documents."""
    override = os.environ.get(TEAM_STATE_DIR_ENV_VAR)
    return Path(override) if override else DEFAULT_TEAM_STATE_DIR


def team_state_path(session_id: Any) -> Path:
    """Path to the team state document for a session."""
    safe_id = _sanitize_session_id(session_id)
    return team_state_dir() / f"{safe_id}.json"


def team_lock_path(session_id: Any) -> Path:
    """Path to the lock file for a team state document."""
    safe_id = _sanitize_session_id(session_id)
    return team_state_dir() / f"{safe_id}.json.lock"


def _sanitize_session_id(session_id: Any) -> str:
    """Convert session_id to a safe filename."""
    import hashlib
    import re

    text = str(session_id or "").strip()
    if not text:
        return "unknown-session"

    safe = re.sub(r"[^A-Za-z0-9_-]", "-", text)

    if len(safe) > 64:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        safe = f"{safe[:47]}-{digest}"

    return safe.strip("-") or "unknown-session"


def load_team_state(session_id: Any) -> dict[str, Any] | None:
    """Load team state for a session, or None if not yet created."""
    path = team_state_path(session_id)

    try:
        with path.open("r", encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    return state if isinstance(state, dict) else None


def save_team_state(session_id: Any, state: dict[str, Any]) -> None:
    """Write team state atomically."""
    path = team_state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(".json.tmp")

    with temporary.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    os.replace(temporary, path)


def new_team_state() -> dict[str, Any]:
    """Create an empty team state document."""
    return {
        "teammates": {}
    }


def init_teammate_record(
    role: str,
    teammate_name: str,
) -> dict[str, Any]:
    """Create a new teammate record for a given role."""
    return {
        "role": role,
        "canonical_name": teammate_name,
        "status": TeammateLifecycleStatus.CREATED.value,
        "current_run_id": None,
        "current_task_id": None,
        "last_completed_task_id": None,
        "report_source": None,
        "result_received": False,
    }


@contextmanager
def locked_team_state(session_id: Any) -> Iterator[dict[str, Any] | None]:
    """Yield team state under an exclusive lock, persisting any changes.

    Creates a new state document if one doesn't exist yet.
    """
    directory = team_state_dir()
    directory.mkdir(parents=True, exist_ok=True)

    try:
        lock = FileLock(str(team_lock_path(session_id)), timeout=LOCK_TIMEOUT_SECONDS)

        with lock:
            state = load_team_state(session_id)

            if state is None:
                state = new_team_state()

            yield state
            save_team_state(session_id, state)
    except Timeout:
        yield None


def clear_team_state(session_id: Any) -> bool:
    """Remove team state and its lock. Returns True if team state was removed."""
    removed = False

    for path in (team_state_path(session_id), team_lock_path(session_id)):
        try:
            path.unlink()
            removed = removed or path.name.endswith(".json")
        except FileNotFoundError:
            continue
        except OSError:
            continue

    return removed


def allocate_teammate(
    session_id: Any,
    role: str,
    canonical_name: str,
) -> tuple[TeammateAllocationDecision, str]:
    """
    Allocate a teammate for a role with explicit decision.

    Returns (decision, teammate_name).
    - CREATE: no teammate exists; ready to create one
    - REUSE: canonical teammate exists and is idle; ready to reuse
    - BUSY: canonical teammate exists but is currently active
    - DENIED: lock timeout; unable to acquire team state; fail closed

    The teammate_name is always returned for reference, even when BUSY or DENIED.
    """
    with locked_team_state(session_id) as state:
        if state is None:
            # Lock timeout, unable to acquire state
            return TeammateAllocationDecision.DENIED, canonical_name

        teammates = state.get("teammates", {})
        existing = None

        for name, record in teammates.items():
            if record.get("role") == role:
                existing = (name, record)
                break

        if existing is None:
            # No teammate for this role exists, create one
            record = init_teammate_record(role, canonical_name)
            teammates[canonical_name] = record
            state["teammates"] = teammates
            return TeammateAllocationDecision.CREATE, canonical_name

        name, record = existing
        status = record.get("status", "")

        if status in (
            TeammateLifecycleStatus.IDLE_REUSABLE.value,
            TeammateLifecycleStatus.ACKNOWLEDGED.value,
            TeammateLifecycleStatus.REPORT_RECEIVED.value,
        ):
            # Teammate is idle/reusable, mark as reused
            record["status"] = TeammateLifecycleStatus.DISPATCHED.value
            record["current_run_id"] = None
            record["current_task_id"] = None
            record["result_received"] = False
            record["report_source"] = None
            return TeammateAllocationDecision.REUSE, name

        # Teammate exists but is busy or failed
        return TeammateAllocationDecision.BUSY, name


def get_or_create_teammate(
    session_id: Any,
    role: str,
    preferred_name: str,
) -> tuple[str, bool]:
    """
    Get or create a teammate record for a role (backward-compatible wrapper).

    Returns (teammate_name, is_new).
    - If a teammate for this role exists and is idle/reusable, returns its name and False
    - If no teammate exists, creates one, returns its name and True
    - If a teammate exists but is busy, returns the canonical name and False
      (caller should treat as "role busy")
    - On lock timeout, returns (preferred_name, False)

    For new code, prefer allocate_teammate() which returns explicit decisions.
    """
    decision, name = allocate_teammate(session_id, role, preferred_name)
    is_new = decision == TeammateAllocationDecision.CREATE
    return name, is_new


def mark_teammate_running(
    session_id: Any,
    teammate_name: str,
    run_id: str,
    task_id: str,
) -> bool:
    """Mark a teammate as currently running a task. Returns success."""
    with locked_team_state(session_id) as state:
        if state is None:
            return False

        teammates = state.get("teammates", {})
        record = teammates.get(teammate_name)

        if record is None:
            return False

        record["status"] = TeammateLifecycleStatus.RUNNING.value
        record["current_run_id"] = run_id
        record["current_task_id"] = task_id
        return True


def mark_report_received(
    session_id: Any,
    teammate_name: str,
    task_id: str,
    source: str = "sendmessage",
) -> bool:
    """
    Mark that a report was received from a teammate.

    source can be "sendmessage", "automatic", or "taskapdate"
    Returns success (or False if already received from same or different source)
    """
    with locked_team_state(session_id) as state:
        if state is None:
            return False

        teammates = state.get("teammates", {})
        record = teammates.get(teammate_name)

        if record is None:
            return False

        if record.get("result_received"):
            # Already received, treat as duplicate (idempotent)
            return True

        record["result_received"] = True
        record["status"] = TeammateLifecycleStatus.REPORT_RECEIVED.value
        record["report_source"] = source
        record["current_task_id"] = task_id
        return True


def mark_teammate_acknowledged(
    session_id: Any,
    teammate_name: str,
) -> bool:
    """Mark a teammate as acknowledged and ready for reuse."""
    with locked_team_state(session_id) as state:
        if state is None:
            return False

        teammates = state.get("teammates", {})
        record = teammates.get(teammate_name)

        if record is None:
            return False

        record["status"] = TeammateLifecycleStatus.ACKNOWLEDGED.value
        record["current_task_id"] = None
        return True


def mark_teammate_idle_reusable(
    session_id: Any,
    teammate_name: str,
) -> bool:
    """Mark a teammate as idle and available for reuse."""
    with locked_team_state(session_id) as state:
        if state is None:
            return False

        teammates = state.get("teammates", {})
        record = teammates.get(teammate_name)

        if record is None:
            return False

        record["status"] = TeammateLifecycleStatus.IDLE_REUSABLE.value
        record["current_task_id"] = None
        record["current_run_id"] = None
        return True


def mark_teammate_failed(
    session_id: Any,
    teammate_name: str,
    reason: str = "",
) -> bool:
    """Mark a teammate as permanently failed."""
    with locked_team_state(session_id) as state:
        if state is None:
            return False

        teammates = state.get("teammates", {})
        record = teammates.get(teammate_name)

        if record is None:
            return False

        record["status"] = TeammateLifecycleStatus.FAILED.value
        if reason:
            record["failure_reason"] = reason
        record["current_task_id"] = None
        record["current_run_id"] = None
        return True


def get_teammate_status(
    session_id: Any,
    teammate_name: str,
) -> str | None:
    """Get the current status of a teammate, or None if not found."""
    state = load_team_state(session_id)
    if state is None:
        return None

    teammates = state.get("teammates", {})
    record = teammates.get(teammate_name)

    if record is None:
        return None

    return record.get("status")


def check_role_in_selected_agents(
    role: str,
    selected_agents: list[str],
) -> bool:
    """Check whether a role is authorized in the current run."""
    return role in selected_agents
