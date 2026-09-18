#!/usr/bin/env python3
"""Temporary SendMessage receipts for pane-backed Agent Team members."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout


CLAUDE_DIR = Path(__file__).resolve().parents[1]

DEFAULT_PENDING_RESULT_DIR = (
    CLAUDE_DIR
    / "runtime"
    / "pending_team_results"
)

PENDING_RESULT_DIR_ENV_VAR = (
    "CLAUDE_PENDING_TEAM_RESULT_DIR"
)

LOCK_TIMEOUT_SECONDS = 10.0

# A receipt should be consumed almost immediately by TeammateIdle.
# Reject abandoned receipts instead of allowing them into a later run.
MAX_RECEIPT_AGE_SECONDS = 3600


def pending_result_dir() -> Path:
    override = os.environ.get(
        PENDING_RESULT_DIR_ENV_VAR
    )

    if override:
        return Path(override)

    return DEFAULT_PENDING_RESULT_DIR


def _session_key(session_id: Any) -> str:
    value = str(session_id or "").strip()

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def pending_result_path(
    session_id: Any,
) -> Path:
    return (
        pending_result_dir()
        / f"{_session_key(session_id)}.json"
    )


def pending_result_lock_path(
    session_id: Any,
) -> Path:
    return (
        pending_result_dir()
        / f"{_session_key(session_id)}.lock"
    )


def stage_pending_result(
    *,
    session_id: Any,
    message: str,
    tool_use_id: str = "",
    owner_session_id: Any,
    teammate_name: str,
    run_id: str,
    task_id: str,
    operations: list[str] | None = None,
    selected_agents: list[str] | None = None,
) -> bool:
    """Stage one exactly-bound tmux SendMessage receipt.

    agent_type may be used by the caller only to locate a unique
    active owner. It is not sufficient by itself to authenticate
    completion. TeammateIdle later confirms the canonical teammate.
    """

    pane_session_id = str(
        session_id or ""
    ).strip()

    report = str(message or "").strip()

    bound_owner_session_id = str(
        owner_session_id or ""
    ).strip()

    bound_teammate_name = str(
        teammate_name or ""
    ).strip()

    bound_run_id = str(
        run_id or ""
    ).strip()

    bound_task_id = str(
        task_id or ""
    ).strip()

    if not (
        pane_session_id
        and report
        and bound_owner_session_id
        and bound_teammate_name
        and bound_run_id
        and bound_task_id
    ):
        return False

    directory = pending_result_dir()
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = pending_result_path(
        pane_session_id
    )

    lock = FileLock(
        str(
            pending_result_lock_path(
                pane_session_id
            )
        ),
        timeout=LOCK_TIMEOUT_SECONDS,
    )

    bound_operations = [
        str(operation)
        for operation in (operations or [])
    ]

    bound_selected_agents = [
        str(agent)
        for agent in (selected_agents or [])
    ]

    payload = {
        "pane_session_id": pane_session_id,
        "recipient": "team-lead",
        "message": report,
        "tool_use_id": str(
            tool_use_id or ""
        ).strip(),

        # Exact lifecycle binding captured at SendMessage time.
        "owner_session_id": bound_owner_session_id,
        "teammate_name": bound_teammate_name,
        "run_id": bound_run_id,
        "task_id": bound_task_id,

        "created_at": time.time(),
        "operations": bound_operations,
        "selected_agents": bound_selected_agents,
    }

    temporary: Path | None = None

    try:
        with lock:
            descriptor, temporary_name = (
                tempfile.mkstemp(
                    prefix=(
                        destination.name
                        + "."
                    ),
                    suffix=".tmp",
                    dir=str(directory),
                )
            )

            temporary = Path(
                temporary_name
            )

            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(
                    handle.fileno()
                )

            os.replace(
                temporary,
                destination,
            )

            temporary = None
            return True

    except (Timeout, OSError):
        return False

    finally:
        if (
            temporary is not None
            and temporary.exists()
        ):
            try:
                temporary.unlink()
            except OSError:
                pass


def load_pending_result(
    session_id: Any,
) -> dict[str, Any] | None:
    pane_session_id = str(
        session_id or ""
    ).strip()

    if not pane_session_id:
        return None

    path = pending_result_path(
        pane_session_id
    )

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(payload, dict):
        return None

    if (
        payload.get("pane_session_id")
        != pane_session_id
    ):
        return None

    created_at = payload.get(
        "created_at"
    )

    try:
        age = (
            time.time()
            - float(created_at)
        )
    except (TypeError, ValueError):
        return None

    if age < 0 or age > MAX_RECEIPT_AGE_SECONDS:
        return None

    if (
        payload.get("recipient")
        != "team-lead"
    ):
        return None

    if not str(
        payload.get("message") or ""
    ).strip():
        return None

    binding_fields = (
        "owner_session_id",
        "teammate_name",
        "run_id",
        "task_id",
    )

    for field in binding_fields:
        if not str(
            payload.get(field) or ""
        ).strip():
            return None

    operations = payload.get(
        "operations"
    )

    selected_agents = payload.get(
        "selected_agents"
    )

    if not isinstance(
        operations,
        list,
    ):
        return None

    if not isinstance(
        selected_agents,
        list,
    ):
        return None

    if any(
        not isinstance(
            operation,
            str,
        )
        for operation in operations
    ):
        return None

    if any(
        not isinstance(
            agent,
            str,
        )
        for agent in selected_agents
    ):
        return None

    return payload


def clear_pending_result(
    session_id: Any,
) -> bool:
    pane_session_id = str(
        session_id or ""
    ).strip()

    if not pane_session_id:
        return False

    try:
        pending_result_path(
            pane_session_id
        ).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False