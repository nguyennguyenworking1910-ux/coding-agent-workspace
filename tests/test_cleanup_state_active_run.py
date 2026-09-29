from __future__ import annotations

import json
import sys

from io import StringIO

import pytest

from claude.hooks import cleanup_state

from claude.hooks.runtime_state import (
    load_state,
    new_state,
    save_state,
)

from claude.hooks.team_lifecycle import (
    TeammateAllocationDecision,
    allocate_teammate,
    mark_teammate_idle_reusable,
    mark_teammate_running,
)


SESSION_ID = "cleanup-owner-session"
RUN_ID = "cleanup-active-run"
TASK_ID = f"{RUN_ID}:merchant-manager"


@pytest.fixture
def isolated_state(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "CLAUDE_RUNTIME_STATE_DIR",
        str(
            tmp_path
            / "runtime"
        ),
    )

    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(
            tmp_path
            / "team"
        ),
    )

    monkeypatch.setenv(
        "CLAUDE_MERCHANT_PREFERENCES_DIR",
        str(
            tmp_path
            / "preferences"
        ),
    )


def _create_run():
    state = new_state(
        request="Apply exact Merchant project create",
        task_class="small_task",
        risk_level="external_write",
        selected_agents=[
            "merchant-manager",
        ],
        operations=[
            "merchant_apply",
        ],
        limits={
            "max_members": 1,
            "max_tool_rounds": 3,
            "max_total_tool_calls": 12,
            "max_run_budget_usd": 2.0,
        },
        confirmed=True,
        run_id=RUN_ID,
    )

    save_state(
        SESSION_ID,
        state,
    )


def _create_running_teammate():
    decision, name = (
        allocate_teammate(
            SESSION_ID,
            "merchant-manager",
            "merchant-manager",
        )
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert (
        name
        == "merchant-manager"
    )

    assert (
        mark_teammate_running(
            SESSION_ID,
            "merchant-manager",
            RUN_ID,
            TASK_ID,
            operations=[
                "merchant_apply",
            ],
            selected_agents=[
                "merchant-manager",
            ],
        )
        is True
    )


def _run_cleanup(
    monkeypatch,
    event,
):
    monkeypatch.setattr(
        cleanup_state.sys,
        "stdin",
        StringIO(
            json.dumps(
                {
                    "hook_event_name": event,
                    "session_id": SESSION_ID,
                }
            )
        ),
    )

    assert (
        cleanup_state.main()
        == 0
    )


def test_stop_preserves_run_state_while_teammate_active(
    isolated_state,
    monkeypatch,
):
    _create_run()
    _create_running_teammate()

    _run_cleanup(
        monkeypatch,
        "Stop",
    )

    state = load_state(
        SESSION_ID
    )

    assert state is not None

    assert (
        state["run_id"]
        == RUN_ID
    )


def test_stop_clears_run_state_after_teammate_released(
    isolated_state,
    monkeypatch,
):
    _create_run()
    _create_running_teammate()

    assert (
        mark_teammate_idle_reusable(
            SESSION_ID,
            "merchant-manager",
        )
        is True
    )

    _run_cleanup(
        monkeypatch,
        "Stop",
    )

    assert (
        load_state(
            SESSION_ID
        )
        is None
    )


def test_session_end_clears_even_with_active_teammate(
    isolated_state,
    monkeypatch,
):
    _create_run()
    _create_running_teammate()

    _run_cleanup(
        monkeypatch,
        "SessionEnd",
    )

    assert (
        load_state(
            SESSION_ID
        )
        is None
    )