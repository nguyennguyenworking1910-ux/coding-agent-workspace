"""Model the trusted state orchestration persists before a scoped write.

Direct EXECUTE authority can be spent only for a staged request with a
durable team-state reservation. Unit tests of the lower-level handoff use
this helper to persist exactly what trusted orchestration would, so they
keep exercising the boundary they pin rather than the reservation check.
"""

from __future__ import annotations

import uuid
from typing import Any

from claude.hooks import harness_team_identity, runtime_state, team_lifecycle
from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_STATE_KEY,
    arguments_hash,
)
from claude.system.merchant_runtime_handoff import (
    completeness_evidence,
    validate_direct_scope,
)


TEAMMATE = "merchant-manager"
TASK_ID = "direct-task"
PANE = "direct-pane"


def isolate_team_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_TEAM_STATE_DIR", str(tmp_path / "team"))


def trust_teammate_pane(monkeypatch, pane: str = "7000:%7") -> None:
    """Every hook process is the teammate's verified pane.

    Only for tests whose subject is not pane identity. Pane identity itself
    is covered against the real harness record in test_cp12h5b_* and
    test_cp12h4_pane_identity.
    """

    monkeypatch.setattr(
        harness_team_identity,
        "verified_teammate_pane",
        lambda owner_session_id, teammate_name: pane,
    )


def reserve_scoped_write(
    session_id: str,
    *,
    task_id: str = TASK_ID,
) -> dict[str, Any]:
    """Persist staging + EXECUTING reservation; return invoke kwargs."""

    attempt_id = str(uuid.uuid4())
    kwargs = {
        "teammate_name": TEAMMATE,
        "task_id": task_id,
        "execution_attempt_id": attempt_id,
    }

    state = runtime_state.load_state(session_id)

    if not isinstance(state, dict):
        return kwargs

    try:
        scope = validate_direct_scope(
            state["merchant_scope"]["argv"],
            state["merchant_scope"].get("database_target", "runtime"),
        )
    except Exception:  # noqa: BLE001 - a broken scope is the test subject
        return kwargs

    run_id = state.get("run_id")

    with runtime_state.locked_state(session_id) as persisted:
        if persisted.get(HANDOFF_STATE_KEY) is None:
            persisted[HANDOFF_STATE_KEY] = {
                "contract_version": 1,
                "status": "PENDING",
                "owner_session_id": session_id,
                "run_id": run_id,
                "task_id": task_id,
                "teammate_name": TEAMMATE,
                "confirmation_hash": scope["confirmation_hash"],
                "database_target": scope["database_target"],
                "arguments_hash": arguments_hash(tuple(scope["argv"])),
                "completeness": completeness_evidence(
                    scope, run_id=run_id, task_id=task_id
                ),
            }

    with team_lifecycle.locked_team_state(session_id) as team:
        team.setdefault("teammates", {})[TEAMMATE] = {
            "canonical_name": TEAMMATE,
            "status": "RUNNING",
            "current_run_id": run_id,
            "current_task_id": task_id,
            "authorized_operations": ["merchant_execute"],
            "authorized_selected_agents": [TEAMMATE],
            "trusted_pane_session_id": PANE,
            "direct_scope_execution": {
                "version": 1,
                "run_id": run_id,
                "task_id": task_id,
                "command": scope["command"],
                "scope_hash": scope["scope_hash"],
                "confirmation_hash": scope["confirmation_hash"],
                "execution_attempt_id": attempt_id,
                "status": "EXECUTING",
            },
        }

    return kwargs


def record_create_authority(
    session_id: str,
    *,
    run_id: str,
    task_id: str,
    write_id: str,
    teammate_name: str = TEAMMATE,
    database_target: str = "test",
) -> None:
    """Record the spent user authority a reserved Create executor requires."""

    state = runtime_state.load_state(session_id) or {}
    state["run_id"] = run_id
    # Spent authority always comes from the user's scope for this run.
    state.setdefault(
        "merchant_scope",
        {
            "run_id": run_id,
            "command": "merchant create",
            "database_target": database_target,
        },
    )
    state["merchant_runtime_authorization_issued"] = True
    state["merchant_runtime_authorization"] = {
        "run_id": run_id,
        "task_id": task_id,
        "teammate_name": teammate_name,
        "reservation_kind": "create",
        "reservation_id": write_id,
        "database_target": database_target,
    }
    runtime_state.save_state(session_id, state)
