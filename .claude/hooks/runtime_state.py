#!/usr/bin/env python3
"""Per-session state shared by the enforcement hooks.

The hooks are separate processes that fire at different lifecycle points, so the
only thing tying a controlled run together is this file. One JSON document per
session under `.claude/runtime/`, guarded by a `filelock` because a tool batch
fires several PreToolUse hooks concurrently and a lost update means a budget that
silently stops being enforced.

**Never write credentials here.** The stored request is the user's own prompt
text, which can contain a pasted key by accident, so it goes through
``redact_secrets`` on the way in. Nothing else about the environment is copied.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock, Timeout

CLAUDE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CLAUDE_DIR.parent

DEFAULT_STATE_DIR = CLAUDE_DIR / "runtime"

# Tests point this at a temporary directory so a test run never touches the
# state of the live session that is executing it.
STATE_DIR_ENV_VAR = "CLAUDE_RUNTIME_STATE_DIR"

# Seconds to wait for the lock. Long enough for a concurrent hook to finish its
# read-modify-write, short enough that a stale lock cannot hang a tool call.
LOCK_TIMEOUT_SECONDS = 10.0

# A session id reaches us from the harness and is used to build a file name, so
# everything outside this set is replaced rather than trusted.
_UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9_-]")

_MAX_SESSION_ID_LENGTH = 64

_SECRET_PLACEHOLDER = "[redacted]"

# Targeted rather than clever: each pattern matches a credential shape, not
# "anything long". A false negative leaves a secret in a local file; a false
# positive corrupts the request the run is classified from.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{16,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret|password"
        r"|passwd|credential)s?\b\s*[:=]\s*\S+"
    ),
)


def redact_secrets(text: str) -> str:
    """Mask credential-shaped substrings before anything is persisted."""
    redacted = text

    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_SECRET_PLACEHOLDER, redacted)

    return redacted


def state_dir() -> Path:
    """Directory holding the per-session documents."""
    override = os.environ.get(STATE_DIR_ENV_VAR)

    return Path(override) if override else DEFAULT_STATE_DIR


def sanitize_session_id(session_id: Any) -> str:
    """Turn a session id into a safe file stem.

    Anything unusable collapses to a hash of the original so two different ids
    can never share a file, and a missing id still yields a usable name instead
    of raising inside a hook.
    """
    text = str(session_id or "").strip()

    if not text:
        return "unknown-session"

    safe = _UNSAFE_CHARACTERS.sub("-", text)

    if len(safe) > _MAX_SESSION_ID_LENGTH:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        safe = f"{safe[:_MAX_SESSION_ID_LENGTH - 17]}-{digest}"

    return safe.strip("-") or "unknown-session"


def state_path(session_id: Any) -> Path:
    return state_dir() / f"{sanitize_session_id(session_id)}.json"


def lock_path(session_id: Any) -> Path:
    return state_dir() / f"{sanitize_session_id(session_id)}.json.lock"


def new_state(
    *,
    request: str,
    task_class: str,
    risk_level: str,
    selected_agents: list[str],
    limits: dict[str, Any],
    confirmed: bool,
) -> dict[str, Any]:
    """Build the state document for a freshly classified run.

    ``members_used`` is the list of distinct agent ids already dispatched, not a
    bare count: ``max_members`` caps distinct members, so re-dispatching the same
    agent must not consume budget twice.
    """
    return {
        "request": redact_secrets(request),
        "task_class": task_class,
        "risk_level": risk_level,
        "selected_agents": list(selected_agents),
        "limits": dict(limits),
        "confirmed": bool(confirmed),
        "members_used": [],
        "total_tool_calls": 0,
        "agent_rounds": 0,
    }


def load_state(session_id: Any) -> dict[str, Any] | None:
    """Read the state, or None when this session is not a controlled run.

    A corrupt document is treated as absent rather than raised: a hook that
    crashes on malformed JSON would block every tool call in the session.
    """
    path = state_path(session_id)

    try:
        with path.open("r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    return state if isinstance(state, dict) else None


def save_state(session_id: Any, state: dict[str, Any]) -> None:
    """Write the state atomically, so a killed hook cannot truncate it."""
    path = state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(".json.tmp")

    with temporary.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, ensure_ascii=False, indent=2)

    os.replace(temporary, path)


@contextmanager
def locked_state(session_id: Any) -> Iterator[dict[str, Any] | None]:
    """Yield the state under an exclusive lock and persist any mutation.

    Yields None when there is no state, in which case nothing is written — that
    is the "not a controlled run" case, and creating a file there would make
    every later hook believe a run is active.

    A lock timeout also yields None: failing to acquire it must not wedge the
    session, and the caller treats a missing state as "no decision".
    """
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)

    try:
        lock = FileLock(str(lock_path(session_id)), timeout=LOCK_TIMEOUT_SECONDS)

        with lock:
            state = load_state(session_id)

            if state is None:
                yield None
                return

            yield state

            save_state(session_id, state)
    except Timeout:
        yield None


def clear_state(session_id: Any) -> bool:
    """Remove the state and its lock. A missing file is not an error."""
    removed = False

    for path in (state_path(session_id), lock_path(session_id)):
        try:
            path.unlink()
            removed = removed or path.name.endswith(".json")
        except FileNotFoundError:
            continue
        except OSError:
            # A lock file still held on Windows is not worth failing over; the
            # state document is what makes a run "active", and it is gone.
            continue

    return removed
