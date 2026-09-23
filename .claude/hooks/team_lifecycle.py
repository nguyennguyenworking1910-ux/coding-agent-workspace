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
import tempfile
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock, Timeout

if __package__ in (None, ""):
    from runtime_state import load_state as load_run_state
else:
    from .runtime_state import load_state as load_run_state


STALE_OWNER_TIMEOUT_SECONDS = 3600
CLAUDE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CLAUDE_DIR.parent

DEFAULT_TEAM_STATE_DIR = CLAUDE_DIR / "runtime" / "team_state"

GLOBAL_OWNER_LOCK_NAME = ".global-owner.lock"

# Override for tests
TEAM_STATE_DIR_ENV_VAR = "CLAUDE_TEAM_STATE_DIR"

LOCK_TIMEOUT_SECONDS = 10.0

IS_WINDOWS = os.name == "nt"

# On Windows, os.replace can fail with PermissionError (WinError 5 / 32) while
# an antivirus scanner or an indexer still holds a transient handle on the
# temporary file or the destination. The handle is released within
# milliseconds, so a short bounded retry converts a spurious failure into a
# successful atomic replacement. Other platforms never see this and must fail
# immediately.
REPLACE_RETRY_ATTEMPTS = 5
REPLACE_RETRY_BACKOFF_SECONDS = (0.01, 0.02, 0.04, 0.08)


class TeammateLifecycleStatus(str, Enum):
    """Lifecycle status of a teammate in the session."""
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    REPORT_RECEIVED = "REPORT_RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IDLE_REUSABLE = "IDLE_REUSABLE"
    FAILED = "FAILED"


GLOBAL_OWNER_STATUSES = frozenset(
    {
        TeammateLifecycleStatus.CREATED.value,
        TeammateLifecycleStatus.DISPATCHED.value,
        TeammateLifecycleStatus.RUNNING.value,
        TeammateLifecycleStatus.REPORT_RECEIVED.value,
        TeammateLifecycleStatus.ACKNOWLEDGED.value,
    }
)


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


def global_owner_lock_path() -> Path:
    """Global lock protecting canonical teammate ownership decisions."""
    return (
        team_state_dir()
        / GLOBAL_OWNER_LOCK_NAME
    )


def _touch_transition(
    record: dict[str, Any],
) -> None:
    record["last_transition_at"] = time.time()
    

def _record_is_expired(
    record: dict[str, Any],
    *,
    now: float | None = None,
) -> bool:
    """Return True only for a valid timestamp older than the lease."""

    raw_timestamp = record.get(
        "last_transition_at"
    )

    try:
        timestamp = float(
            raw_timestamp
        )
    except (
        TypeError,
        ValueError,
    ):
        # Missing/malformed timestamp fails closed.
        return False

    current_time = (
        time.time()
        if now is None
        else now
    )

    age = (
        current_time
        - timestamp
    )

    if age < 0:
        return False

    return (
        age
        > STALE_OWNER_TIMEOUT_SECONDS
    )


def _other_session_owns_teammate(
    session_id: Any,
    teammate_name: str,
) -> tuple[bool, str | None]:
    """Return whether another session actively owns this canonical teammate.

    Caller must hold the global ownership lock.

    IDLE_REUSABLE and FAILED are intentionally not global ownership states.
    """

    name = str(
        teammate_name or ""
    ).strip()

    if not name:
        return False, None

    directory = team_state_dir()

    current_state_path = (
        team_state_path(
            session_id
        )
    )

    try:
        paths = list(
            directory.glob("*.json")
        )
    except OSError:
        # Fail closed at the caller if ownership cannot be inspected.
        raise

    for path in paths:
        if path == current_state_path:
            continue

        try:
            candidate = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            continue

        if not isinstance(
            candidate,
            dict,
        ):
            continue

        record = (
            candidate.get(
                "teammates",
                {},
            ).get(
                name
            )
        )

        if not isinstance(
            record,
            dict,
        ):
            continue

        if (
            record.get(
                "canonical_name"
            )
            != name
        ):
            continue

        status = str(
            record.get(
                "status"
            )
            or ""
        )

        if (
            status
            not in GLOBAL_OWNER_STATUSES
        ):
            continue

        owner_session_id = str(
            candidate.get(
                "session_id"
            )
            or ""
        ).strip()

        owner_run_id = str(
            record.get(
                "current_run_id"
            )
            or ""
        ).strip()

        owner_task_id = str(
            record.get(
                "current_task_id"
            )
            or ""
        ).strip()

        # A malformed active ownership record is still unsafe.
        if not owner_session_id:
            return True, None

        if (
            _record_is_expired(
                record
            )
            and _reconcile_stale_owner(
                owner_session_id,
                name,
                expected_run_id=owner_run_id,
                expected_task_id=owner_task_id,
            )
        ):
            # Ownership was safely converted to FAILED.
            # Continue searching in case another legitimate
            # owner exists.
            continue

        return (
            True,
            owner_session_id,
        )

    return False, None


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


def replace_with_retry(temporary: Path, destination: Path) -> None:
    """Atomically replace destination with temporary.

    The replacement stays atomic: the destination is never unlinked first and
    there is no non-atomic fallback write. Only a transient Windows
    PermissionError is retried, a bounded number of times.
    """
    for attempt in range(REPLACE_RETRY_ATTEMPTS):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if not IS_WINDOWS or attempt == REPLACE_RETRY_ATTEMPTS - 1:
                raise

            time.sleep(REPLACE_RETRY_BACKOFF_SECONDS[attempt])


def save_team_state(session_id: Any, state: dict[str, Any]) -> None:
    """Write team state atomically."""
    path = team_state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    # A unique name in the destination directory. A fixed "<session>.json.tmp"
    # lets a retry or a second writer collide on one scratch file, and
    # os.replace is only atomic within a single filesystem.
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    replaced = False

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        replace_with_retry(temporary, path)
        replaced = True
    finally:
        if not replaced:
            # Never mask the failure that brought us here.
            try:
                temporary.unlink()
            except OSError:
                pass


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
        "terminal_recovery_sent": False,
        "last_transition_at": time.time(),
        "authorized_operations": [],
        "authorized_selected_agents": [],
    }


def _reconcile_stale_owner(
    owner_session_id: str,
    teammate_name: str,
    *,
    expected_run_id: str,
    expected_task_id: str,
) -> bool:
    """Fail an expired owner only when its exact run state is gone.

    Caller must hold the global ownership lock.

    Returns True only when the stale ownership was safely reconciled.
    """

    # -------------------------------------------------
    # A matching run state means we do not currently
    # have enough evidence that this owner is abandoned.
    # Keep it BUSY even if the lifecycle transition is old.
    # -------------------------------------------------

    run_state = load_run_state(
        owner_session_id
    )

    if run_state is not None:
        current_run_id = str(
            run_state.get(
                "run_id"
            )
            or ""
        ).strip()

        # Malformed run state does not provide enough evidence
        # for safe reclamation.
        if not current_run_id:
            return False

        # Exact matching run remains authoritative/live.
        if (
            current_run_id
            == expected_run_id
        ):
            return False

        # A different current run does NOT validate the old
        # teammate ownership. Continue with the stale-record
        # checks below.

    with locked_team_state(
        owner_session_id
    ) as state:
        if state is None:
            return False

        record = (
            state.get(
                "teammates",
                {},
            ).get(
                teammate_name
            )
        )

        if not isinstance(
            record,
            dict,
        ):
            return False

        if (
            record.get(
                "canonical_name"
            )
            != teammate_name
        ):
            return False

        status = str(
            record.get(
                "status"
            )
            or ""
        )

        if (
            status
            not in GLOBAL_OWNER_STATUSES
        ):
            return False

        current_run_id = str(
            record.get(
                "current_run_id"
            )
            or ""
        ).strip()

        current_task_id = str(
            record.get(
                "current_task_id"
            )
            or ""
        ).strip()

        # Revalidate exact state after acquiring the
        # per-session lock. Never reclaim a task that
        # changed while we were inspecting it.
        if (
            current_run_id
            != expected_run_id
            or current_task_id
            != expected_task_id
        ):
            return False

        if not _record_is_expired(
            record
        ):
            return False

        record["status"] = (
            TeammateLifecycleStatus.FAILED.value
        )

        record[
            "failure_reason"
        ] = "STALE_GLOBAL_OWNER"

        record[
            "current_run_id"
        ] = None

        record[
            "current_task_id"
        ] = None

        record[
            "authorized_operations"
        ] = []

        record[
            "authorized_selected_agents"
        ] = []

        _touch_transition(
            record
        )

        return True
    

@contextmanager
def locked_team_state(
    session_id: Any,
) -> Iterator[dict[str, Any] | None]:
    """Yield team state under an exclusive lock, persisting any changes.

    Creates a new state document if one doesn't exist yet.
    """
    directory = team_state_dir()
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        lock = FileLock(
            str(team_lock_path(session_id)),
            timeout=LOCK_TIMEOUT_SECONDS,
        )

        with lock:
            state = load_team_state(
                session_id
            )

            if state is None:
                state = new_team_state()

            # Keep the authoritative lead/session owner in the
            # persisted team-state document. This is required for
            # later tmux pane -> lead-session reconciliation.
            state["session_id"] = str(
                session_id or ""
            ).strip()

            yield state

            # IMPORTANT:
            # Persist every lifecycle mutation while the same
            # exclusive lock is still held.
            save_team_state(
                session_id,
                state,
            )

    except Timeout:
        yield None

def clear_team_state(session_id: Any) -> bool:
    """Remove team state while holding its exclusive session lock.

    Keep the lock file as the stable synchronization object for this session.
    Removing its pathname while locked could allow a concurrent process to
    create a second lock and write state after SessionEnd cleanup.
    """
    try:
        team_state_dir().mkdir(parents=True, exist_ok=True)
        lock = FileLock(
            str(team_lock_path(session_id)),
            timeout=LOCK_TIMEOUT_SECONDS,
        )

        with lock:
            try:
                team_state_path(session_id).unlink()
            except FileNotFoundError:
                return False

            return True
    except (Timeout, OSError):
        # Preserve state if exclusive cleanup cannot be established. A later
        # SessionEnd cleanup can safely retry.
        return False


def allocate_teammate(
    session_id: Any,
    role: str,
    canonical_name: str,
) -> tuple[
    TeammateAllocationDecision,
    str,
]:
    """Atomically allocate one canonical teammate.

    Global ownership is checked before local session allocation so two
    concurrent lead sessions cannot both own the same canonical teammate.

    An expired owner may be reconciled by
    `_other_session_owns_teammate()` before this allocation proceeds.

    Returns:
        (decision, teammate_name)

    Decisions:
        CREATE:
            No teammate exists in this session and no other active session
            owns the canonical teammate.

        REUSE:
            This session already has the canonical teammate in
            IDLE_REUSABLE state.

        BUSY:
            Another session actively owns the canonical teammate, or this
            session already has the teammate in a non-reusable state.

        DENIED:
            Ownership/state locking or inspection could not be completed
            safely.
    """

    session_text = str(
        session_id or ""
    ).strip()

    role_text = str(
        role or ""
    ).strip()

    canonical_text = str(
        canonical_name or ""
    ).strip()

    if not (
        session_text
        and role_text
        and canonical_text
    ):
        return (
            TeammateAllocationDecision.DENIED,
            canonical_text,
        )

    directory = team_state_dir()

    try:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError:
        return (
            TeammateAllocationDecision.DENIED,
            canonical_text,
        )

    try:
        global_lock = FileLock(
            str(
                global_owner_lock_path()
            ),
            timeout=LOCK_TIMEOUT_SECONDS,
        )

        with global_lock:
            # --------------------------------------------------
            # Global canonical ownership gate.
            #
            # `_other_session_owns_teammate()` may reconcile an
            # expired owner when:
            #
            # - its lifecycle lease is expired; and
            # - its run state no longer exists; and
            # - its exact run/task binding is unchanged.
            #
            # If ownership remains valid or cannot be safely
            # reclaimed, fail closed as BUSY.
            # --------------------------------------------------

            (
                owned_elsewhere,
                _owner_session_id,
            ) = _other_session_owns_teammate(
                session_text,
                canonical_text,
            )

            if owned_elsewhere:
                return (
                    TeammateAllocationDecision.BUSY,
                    canonical_text,
                )

            # --------------------------------------------------
            # Global ownership is clear.
            # Now inspect/update this session atomically.
            # --------------------------------------------------

            with locked_team_state(
                session_text
            ) as state:
                if state is None:
                    return (
                        TeammateAllocationDecision.DENIED,
                        canonical_text,
                    )

                teammates = state.get(
                    "teammates"
                )

                if not isinstance(
                    teammates,
                    dict,
                ):
                    teammates = {}

                    state[
                        "teammates"
                    ] = teammates

                existing_name = None
                existing_record = None

                # --------------------------------------------------
                # Role-level uniqueness inside one session.
                # --------------------------------------------------

                for (
                    teammate_name,
                    record,
                ) in teammates.items():
                    if not isinstance(
                        record,
                        dict,
                    ):
                        continue

                    if (
                        str(
                            record.get(
                                "role"
                            )
                            or ""
                        ).strip()
                        == role_text
                    ):
                        existing_name = str(
                            teammate_name
                        )

                        existing_record = (
                            record
                        )

                        break

                # --------------------------------------------------
                # No teammate for this role exists in the session.
                #
                # CREATE itself reserves global ownership because
                # CREATED belongs to GLOBAL_OWNER_STATUSES.
                # --------------------------------------------------

                if (
                    existing_record
                    is None
                ):
                    record = (
                        init_teammate_record(
                            role_text,
                            canonical_text,
                        )
                    )

                    teammates[
                        canonical_text
                    ] = record

                    state[
                        "teammates"
                    ] = teammates

                    return (
                        TeammateAllocationDecision.CREATE,
                        canonical_text,
                    )

                # --------------------------------------------------
                # Existing role must use its canonical name.
                # Never silently substitute/suffix another teammate.
                # --------------------------------------------------

                if (
                    existing_name
                    != canonical_text
                ):
                    return (
                        TeammateAllocationDecision.BUSY,
                        existing_name
                        or canonical_text,
                    )

                if (
                    existing_record.get(
                        "canonical_name"
                    )
                    != canonical_text
                ):
                    return (
                        TeammateAllocationDecision.BUSY,
                        canonical_text,
                    )

                status = str(
                    existing_record.get(
                        "status"
                    )
                    or ""
                )

                # --------------------------------------------------
                # Existing completed teammate may be reserved for
                # the next run.
                #
                # This is only the allocation phase. Exact run/task
                # binding is completed later by
                # `reserve_reusable_teammate()`.
                # --------------------------------------------------

                if (
                    status
                    == (
                        TeammateLifecycleStatus
                        .IDLE_REUSABLE
                        .value
                    )
                ):
                    existing_record[
                        "status"
                    ] = (
                        TeammateLifecycleStatus
                        .DISPATCHED
                        .value
                    )

                    existing_record[
                        "current_run_id"
                    ] = None

                    existing_record[
                        "current_task_id"
                    ] = None

                    existing_record[
                        "result_received"
                    ] = False

                    existing_record[
                        "report_source"
                    ] = None

                    existing_record[
                        "terminal_recovery_sent"
                    ] = False

                    existing_record[
                        "authorized_operations"
                    ] = []

                    existing_record[
                        "authorized_selected_agents"
                    ] = []

                    existing_record.pop(
                        "failure_reason",
                        None,
                    )

                    _touch_transition(
                        existing_record
                    )

                    return (
                        TeammateAllocationDecision.REUSE,
                        canonical_text,
                    )

                # --------------------------------------------------
                # Any other local lifecycle state is not reusable.
                #
                # Includes:
                # CREATED
                # DISPATCHED
                # RUNNING
                # REPORT_RECEIVED
                # ACKNOWLEDGED
                # FAILED
                #
                # FAILED deliberately does not automatically become
                # reusable. Recovery requires a separate controlled
                # lifecycle decision.
                # --------------------------------------------------

                return (
                    TeammateAllocationDecision.BUSY,
                    canonical_text,
                )

    except Timeout:
        return (
            TeammateAllocationDecision.DENIED,
            canonical_text,
        )

    except OSError:
        # Ownership/state inspection failure must never create
        # another canonical teammate.
        return (
            TeammateAllocationDecision.DENIED,
            canonical_text,
        )


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
    operations: list[str] | None = None,
    selected_agents: list[str] | None = None,
) -> bool:
    """Mark a teammate as currently running a task.

    This transition also refreshes the global-owner lease timestamp.
    Returns True only when the exact canonical teammate record was updated.
    """

    operations_snapshot = [
        str(operation)
        for operation in (
            operations or []
        )
    ]

    selected_agents_snapshot = [
        str(agent)
        for agent in (
            selected_agents or []
        )
    ]

    with locked_team_state(
        session_id
    ) as state:
        if state is None:
            return False

        teammates = state.get(
            "teammates",
            {},
        )

        record = teammates.get(
            teammate_name
        )

        if not isinstance(
            record,
            dict,
        ):
            return False

        if (
            record.get(
                "canonical_name"
            )
            != teammate_name
        ):
            return False

        record["status"] = (
            TeammateLifecycleStatus.RUNNING.value
        )

        record[
            "current_run_id"
        ] = run_id

        record[
            "current_task_id"
        ] = task_id

        record[
            "result_received"
        ] = False

        record[
            "report_source"
        ] = None

        record[
            "terminal_recovery_sent"
        ] = False

        record[
            "authorized_operations"
        ] = operations_snapshot

        record[
            "authorized_selected_agents"
        ] = selected_agents_snapshot

        record.pop(
            "failure_reason",
            None,
        )

        # Critical for Gate 12B.5:
        # RUNNING is a real lifecycle transition and therefore
        # must refresh the global-owner lease timestamp.
        _touch_transition(
            record
        )

        return True


def reserve_reusable_teammate(
    session_id: Any,
    teammate_name: str,
    run_id: str,
    task_id: str,
    operations: list[str] | None = None,
    selected_agents: list[str] | None = None,
) -> tuple[bool, str]:
    """Atomically reserve an existing idle teammate for a new run."""

    operations_snapshot = [
        str(operation)
        for operation in (
            operations or []
        )
    ]

    selected_agents_snapshot = [
        str(agent)
        for agent in (
            selected_agents or []
        )
    ]

    directory = team_state_dir()
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        global_lock = FileLock(
            str(
                global_owner_lock_path()
            ),
            timeout=LOCK_TIMEOUT_SECONDS,
        )

        with global_lock:
            (
                owned_elsewhere,
                _owner_session_id,
            ) = _other_session_owns_teammate(
                session_id,
                teammate_name,
            )

            if owned_elsewhere:
                return (
                    False,
                    TeammateAllocationDecision.BUSY.value,
                )

            with locked_team_state(
                session_id
            ) as state:
                if state is None:
                    return (
                        False,
                        TeammateAllocationDecision.DENIED.value,
                    )

                record = (
                    state.get(
                        "teammates",
                        {},
                    ).get(
                        teammate_name
                    )
                )

                if not isinstance(
                    record,
                    dict,
                ):
                    return (
                        False,
                        "DOES_NOT_EXIST",
                    )

                if (
                    record.get(
                        "canonical_name"
                    )
                    != teammate_name
                ):
                    return (
                        False,
                        "NON_CANONICAL",
                    )

                prior_status = str(
                    record.get(
                        "status"
                    )
                    or "UNKNOWN"
                )

                current_run_id = str(
                    record.get(
                        "current_run_id"
                    )
                    or ""
                )

                current_task_id = str(
                    record.get(
                        "current_task_id"
                    )
                    or ""
                )

                if (
                    prior_status
                    in (
                        TeammateLifecycleStatus.DISPATCHED.value,
                        TeammateLifecycleStatus.RUNNING.value,
                    )
                    and current_run_id == run_id
                    and current_task_id == task_id
                ):
                    existing_operations = [
                        str(operation)
                        for operation in (
                            record.get(
                                "authorized_operations"
                            )
                            or []
                        )
                    ]

                    existing_selected_agents = [
                        str(agent)
                        for agent in (
                            record.get(
                                "authorized_selected_agents"
                            )
                            or []
                        )
                    ]

                    if (
                        existing_operations
                        != operations_snapshot
                        or existing_selected_agents
                        != selected_agents_snapshot
                    ):
                        return (
                            False,
                            "AUTHORIZATION_MISMATCH",
                        )

                    return (
                        True,
                        prior_status,
                    )

                reusable_statuses = (
                    TeammateLifecycleStatus.IDLE_REUSABLE.value,
                )

                unbound_dispatch = (
                    prior_status
                    == TeammateLifecycleStatus.DISPATCHED.value
                    and not current_run_id
                    and not current_task_id
                )

                if (
                    prior_status
                    not in reusable_statuses
                    and not unbound_dispatch
                ):
                    return (
                        False,
                        prior_status,
                    )

                record["status"] = (TeammateLifecycleStatus.RUNNING.value                )
                record["current_run_id"] = run_id
                record["current_task_id"] = task_id
                record["result_received"] = False
                record["report_source"] = None
                record["terminal_recovery_sent"] = False
                record["authorized_operations"] = operations_snapshot
                record["authorized_selected_agents"] = selected_agents_snapshot

                _touch_transition(
                    record
                )

                return (
                    True,
                    prior_status,
                )

    except Timeout:
        return (
            False,
            TeammateAllocationDecision.DENIED.value,
        )

    except OSError:
        return (
            False,
            TeammateAllocationDecision.DENIED.value,
        )


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


def release_reported_teammate_to_idle(
    session_id: Any,
    teammate_name: str,
) -> tuple[bool, str]:
    """Atomically release one authenticated, reported teammate for reuse.

    The run-state document is intentionally not consulted here. Claude Code
    fires ``Stop`` before ``TeammateIdle`` and the Stop hook clears run state,
    while team state is session-scoped and remains available. Only an exact
    canonical teammate with a bound run/task and a SendMessage-backed report
    may cross this boundary.
    """
    with locked_team_state(session_id) as state:
        if state is None:
            return False, TeammateAllocationDecision.DENIED.value

        record = state.get("teammates", {}).get(teammate_name)

        if not isinstance(record, dict):
            return False, "DOES_NOT_EXIST"

        if record.get("canonical_name") != teammate_name:
            return False, "NON_CANONICAL"

        prior_status = str(record.get("status") or "UNKNOWN")

        if prior_status == TeammateLifecycleStatus.IDLE_REUSABLE.value:
            record["authorized_operations"] = []
            record["authorized_selected_agents"] = []
            return True, prior_status

        if prior_status not in (
            TeammateLifecycleStatus.REPORT_RECEIVED.value,
            TeammateLifecycleStatus.ACKNOWLEDGED.value,
        ):
            return False, prior_status

        if (
            record.get("result_received") is not True
            or record.get("report_source") != "sendmessage"
        ):
            return False, prior_status

        run_id = str(record.get("current_run_id") or "").strip()
        task_id = str(record.get("current_task_id") or "").strip()

        if not (run_id and task_id):
            return False, "UNBOUND_REPORT"

        record["status"] = TeammateLifecycleStatus.IDLE_REUSABLE.value
        record["last_completed_task_id"] = task_id
        record["current_task_id"] = None
        record["current_run_id"] = None
        record["authorized_operations"] = []
        record["authorized_selected_agents"] = []

        _touch_transition(
            record
        )
        
        return True, prior_status


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

        current_task_id = str(record.get("current_task_id") or "").strip()

        record["status"] = TeammateLifecycleStatus.IDLE_REUSABLE.value

        if current_task_id:
            record["last_completed_task_id"] = current_task_id

        record["current_task_id"] = None
        record["current_run_id"] = None
        record["authorized_operations"] = []
        record["authorized_selected_agents"] = []
        return True

def claim_terminal_recovery(
    session_id: Any,
    teammate_name: str,
    run_id: str,
    task_id: str,
) -> tuple[bool, str]:
    """Allow at most one recovery turn for an invalid terminal report.

    This is distinct from result-delivery recovery:

    - result-delivery recovery means no SendMessage was received;
    - terminal recovery means SendMessage was received, but the
      machine-readable terminal contract is invalid or incomplete.

    The claim is bound to the exact canonical teammate, run, and task.
    """

    with locked_team_state(session_id) as state:
        if state is None:
            return False, "STATE_UNAVAILABLE"

        record = (
            state.get("teammates", {})
            .get(teammate_name)
        )

        if not isinstance(record, dict):
            return False, "DOES_NOT_EXIST"

        if (
            record.get("canonical_name")
            != teammate_name
        ):
            return False, "NON_CANONICAL"

        current_run_id = str(
            record.get("current_run_id")
            or ""
        ).strip()

        current_task_id = str(
            record.get("current_task_id")
            or ""
        ).strip()

        if (
            current_run_id != str(run_id).strip()
            or current_task_id != str(task_id).strip()
        ):
            return False, "BINDING_MISMATCH"

        if (
            record.get("result_received")
            is not True
            or record.get("report_source")
            != "sendmessage"
        ):
            return False, "REPORT_NOT_RECEIVED"

        status = str(
            record.get("status")
            or ""
        )

        if status not in (
            TeammateLifecycleStatus.REPORT_RECEIVED.value,
            TeammateLifecycleStatus.ACKNOWLEDGED.value,
        ):
            return False, status or "INVALID_STATUS"

        if record.get(
            "terminal_recovery_sent"
        ):
            return False, "ALREADY_SENT"

        record[
            "terminal_recovery_sent"
        ] = True

        return True, "RECOVERY_CLAIMED"
    

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
        record["authorized_operations"] = []
        record["authorized_selected_agents"] = []
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

def find_unique_active_teammate_owner(
    teammate_name: str,
) -> tuple[str | None, dict[str, Any] | None, str]:
    """Find exactly one lead session currently owning this teammate.

    This is used only for pane-backed teammates whose hook session_id belongs
    to the pane rather than the lead session.

    Returns:
        (session_id, teammate_record, resolution)

    resolution:
        FOUND
        NOT_FOUND
        AMBIGUOUS
    """
    name = str(teammate_name or "").strip()

    if not name:
        return None, None, "NOT_FOUND"

    matches: list[tuple[str, dict[str, Any]]] = []

    directory = team_state_dir()

    try:
        paths = list(directory.glob("*.json"))
    except OSError:
        return None, None, "NOT_FOUND"

    active_statuses = GLOBAL_OWNER_STATUSES

    for path in paths:
        try:
            candidate = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            continue

        if not isinstance(candidate, dict):
            continue

        record = (
            candidate.get("teammates", {})
        ).get(name)

        if not isinstance(record, dict):
            continue

        if record.get("canonical_name") != name:
            continue

        status = str(
            record.get("status") or ""
        )

        if status not in active_statuses:
            continue

        owner_session_id = str(
            candidate.get("session_id") or ""
        ).strip()

        if not owner_session_id:
            continue

        matches.append(
            (
                owner_session_id,
                dict(record),
            )
        )

    if len(matches) == 1:
        session_id, record = matches[0]
        return session_id, record, "FOUND"

    if len(matches) > 1:
        return None, None, "AMBIGUOUS"

    return None, None, "NOT_FOUND"


def mark_bound_report_received(
    session_id: Any,
    teammate_name: str,
    run_id: str,
    task_id: str,
    source: str = "sendmessage",
) -> bool:
    """Mark a report received only when run/task binding still matches."""

    with locked_team_state(session_id) as state:
        if state is None:
            return False

        record = (
            state.get("teammates", {})
        ).get(teammate_name)

        if not isinstance(record, dict):
            return False

        if (
            record.get("canonical_name")
            != teammate_name
        ):
            return False

        prior_status = str(
            record.get("status") or ""
        )

        if prior_status not in {
            TeammateLifecycleStatus.RUNNING.value,
            TeammateLifecycleStatus.REPORT_RECEIVED.value,
            TeammateLifecycleStatus.ACKNOWLEDGED.value,
        }:
            return False

        current_run_id = str(
            record.get("current_run_id") or ""
        )

        current_task_id = str(
            record.get("current_task_id") or ""
        )

        if current_run_id != str(run_id):
            return False

        if current_task_id != str(task_id):
            return False

        # Idempotent duplicate delivery:
        # do not extend the lease again for the same already-recorded report.
        if record.get("result_received") is True:
            return (
                record.get("report_source")
                == source
            )

        record["result_received"] = True

        record["status"] = (
            TeammateLifecycleStatus
            .REPORT_RECEIVED
            .value
        )

        record["report_source"] = source

        # REPORT_RECEIVED is a real lifecycle transition.
        _touch_transition(
            record
        )

        return True