"""Gate 11: multi-role tmux lifecycle safety."""

from __future__ import annotations

import json
import os
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"

sys.path.insert(0, str(HOOKS_DIR))

import team_result_hook  # noqa: E402

from runtime_state import (  # noqa: E402
    STATE_DIR_ENV_VAR,
    clear_state,
    new_state,
    save_state,
)
from team_lifecycle import (  # noqa: E402
    TeammateAllocationDecision,
    TeammateLifecycleStatus,
    allocate_teammate,
    load_team_state,
    mark_teammate_idle_reusable,
    mark_teammate_running,
)
from tmux_result_receipt import (  # noqa: E402
    load_pending_result,
)


@pytest.fixture
def isolated_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv(
        STATE_DIR_ENV_VAR,
        str(tmp_path / "run_state"),
    )
    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(tmp_path / "team_state"),
    )
    monkeypatch.setenv(
        "CLAUDE_PENDING_TEAM_RESULT_DIR",
        str(tmp_path / "pending_results"),
    )


def run_hook(payload):
    original_stdin = sys.stdin

    try:
        sys.stdin = StringIO(
            json.dumps(payload)
        )
        return team_result_hook.main()
    finally:
        sys.stdin = original_stdin


def test_tmux_merchant_manager_reconciles_to_idle(
    isolated_runtime,
):
    lead_session_id = "lead-merchant-session"
    pane_session_id = "merchant-pane-session"

    decision, teammate_name = allocate_teammate(
        lead_session_id,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )
    assert teammate_name == "merchant-manager"

    assert mark_teammate_running(
        lead_session_id,
        "merchant-manager",
        "run-merchant-1",
        "task-merchant-1",
    )

    send_result = {
        "hook_event_name": "PostToolUse",
        "session_id": pane_session_id,

        # Model current tmux behavior:
        # agent_type exists, agent_id does not.
        "agent_type": "merchant-manager",

        "tool_name": "SendMessage",
        "tool_use_id": "merchant-send-1",
        "tool_input": {
            "recipient": "team-lead",
            "content": "Merchant task complete",
        },
    }

    assert run_hook(send_result) == 0

    # SendMessage is staged, but owner remains RUNNING
    # until the authenticated TeammateIdle event arrives.
    state = load_team_state(
        lead_session_id
    )

    record = state["teammates"][
        "merchant-manager"
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )

    assert (
        load_pending_result(
            pane_session_id
        )
        is not None
    )

    idle_result = {
        "hook_event_name": "TeammateIdle",
        "session_id": pane_session_id,
        "agent_type": "merchant-manager",
        "teammate_name": "merchant-manager",
        "team_name": "session-lead-merchant",
    }

    assert run_hook(idle_result) == 0

    state = load_team_state(
        lead_session_id
    )

    record = state["teammates"][
        "merchant-manager"
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus.IDLE_REUSABLE.value
    )
    assert record["result_received"] is True
    assert record["report_source"] == "sendmessage"
    assert record["current_run_id"] is None
    assert record["current_task_id"] is None
    assert (
        record["last_completed_task_id"]
        == "task-merchant-1"
    )

    # Receipt must be consumed.
    assert (
        load_pending_result(
            pane_session_id
        )
        is None
    )

    # Pane must not create its own empty team-state.
    assert (
        load_team_state(
            pane_session_id
        )
        is None
    )


def test_tmux_ambiguous_owner_fails_closed(
    isolated_runtime,
):
    pane_session_id = "merchant-pane-session"

    for lead_session_id in (
        "lead-session-a",
        "lead-session-b",
    ):
        decision, teammate_name = (
            allocate_teammate(
                lead_session_id,
                "merchant-manager",
                "merchant-manager",
            )
        )

        assert (
            decision
            == TeammateAllocationDecision.CREATE
        )

        assert mark_teammate_running(
            lead_session_id,
            teammate_name,
            f"run-{lead_session_id}",
            f"task-{lead_session_id}",
        )

    exit_code = run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
        }
    )

    assert exit_code == 2

    for lead_session_id in (
        "lead-session-a",
        "lead-session-b",
    ):
        state = load_team_state(
            lead_session_id
        )

        record = state["teammates"][
            "merchant-manager"
        ]

        assert (
            record["status"]
            == TeammateLifecycleStatus.RUNNING.value
        )
        assert record["result_received"] is False

    assert (
        load_team_state(
            pane_session_id
        )
        is None
    )


def test_stale_tmux_receipt_cannot_complete_new_run(
    isolated_runtime,
):
    lead_session_id = "lead-session"
    pane_session_id = "merchant-pane-session"

    decision, teammate_name = allocate_teammate(
        lead_session_id,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session_id,
        teammate_name,
        "run-old",
        "task-old",
    )

    # A report is sent for the OLD run but TeammateIdle
    # has not consumed it yet.
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "SendMessage",
            "tool_use_id": "old-send",
            "tool_input": {
                "recipient": "team-lead",
                "content": "Old run report",
            },
        }
    ) == 0

    assert (
        load_pending_result(
            pane_session_id
        )
        is not None
    )

    # Simulate a stale receipt surviving across a lifecycle
    # boundary so we can prove it cannot authorize run-new.
    assert mark_teammate_idle_reusable(
        lead_session_id,
        teammate_name,
    )

    decision, reused_name = allocate_teammate(
        lead_session_id,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision
        == TeammateAllocationDecision.REUSE
    )
    assert reused_name == teammate_name

    assert mark_teammate_running(
        lead_session_id,
        teammate_name,
        "run-new",
        "task-new",
    )

    # The OLD receipt must NOT satisfy the NEW run.
    exit_code = run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
        }
    )

    assert exit_code == 2

    state = load_team_state(
        lead_session_id
    )

    record = state["teammates"][
        "merchant-manager"
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )
    assert record["current_run_id"] == "run-new"
    assert record["current_task_id"] == "task-new"
    assert record["result_received"] is False
    assert record["report_source"] is None

def test_tmux_sendmessage_without_role_hint_is_not_staged(
    isolated_runtime,
):
    lead_session_id = "lead-session"
    pane_session_id = "pane-session"

    decision, teammate_name = allocate_teammate(
        lead_session_id,
        "reviewer",
        "reviewer",
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session_id,
        teammate_name,
        "run-1",
        "task-1",
    )

    # No agent_id and no agent_type:
    # there is not enough harness context to bind safely.
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "tool_name": "SendMessage",
            "tool_use_id": "send-1",
            "tool_input": {
                "recipient": "team-lead",
                "content": "Unbound report",
            },
        }
    ) == 0

    assert (
        load_pending_result(
            pane_session_id
        )
        is None
    )

    exit_code = run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "teammate_name": "reviewer",
        }
    )

    assert exit_code == 2

    state = load_team_state(
        lead_session_id
    )

    record = state["teammates"][
        "reviewer"
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )
    assert record["result_received"] is False

def test_tmux_merchant_proposal_is_captured_for_lead_session(
    isolated_runtime,
    monkeypatch,
):
    lead_session_id = "lead-merchant-session"
    pane_session_id = "merchant-pane-session"

    save_state(
        lead_session_id,
        new_state(
            request="prepare merchant proposal",
            task_class="small_task",
            risk_level="read_only",
            selected_agents=[
                "merchant-manager",
            ],
            operations=[
                "merchant_propose",
            ],
            limits={
                "max_members": 1,
                "max_total_tool_calls": 10,
            },
            confirmed=False,
            run_id="run-merchant-1",
        ),
    )

    decision, teammate_name = allocate_teammate(
        lead_session_id,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session_id,
        teammate_name,
        "run-merchant-1",
        "task-merchant-1",
    )

    captured = []

    def fake_capture(
        session_id,
        proposal,
    ):
        captured.append(
            (
                session_id,
                proposal,
            )
        )

        return SimpleNamespace(
            accepted=True,
            reason="",
        )

    monkeypatch.setattr(
        team_result_hook,
        "capture_proposal_receipt",
        fake_capture,
    )

    proposal = {
        "success": True,
        "confirmation_token": "test-token",
        "command": "project update",
        "database_target": "runtime",
    }

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,

            # tmux shape:
            # no agent_id, role hint only.
            "agent_type": "merchant-manager",

            "tool_name": "SendMessage",
            "tool_use_id": "merchant-send-1",
            "tool_input": {
                "recipient": "team-lead",
                "content": (
                    "Merchant proposal complete\n"
                    "MERCHANT_PROPOSAL_RESULT_JSON:\n"
                    + json.dumps(proposal)
                ),
            },
        }
    ) == 0

    # PostToolUse alone must not trust the pane identity.
    assert captured == []

    assert run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
        }
    ) == 0

    # Trusted TeammateIdle + exact run/task receipt binding
    # now authorizes proposal capture under the LEAD session.
    assert len(captured) == 1

    captured_session_id, captured_proposal = (
        captured[0]
    )

    assert (
        captured_session_id
        == lead_session_id
    )

    assert (
        captured_proposal
        == proposal
    )

def test_tmux_merchant_proposal_survives_stop_before_idle(
    isolated_runtime,
    monkeypatch,
):
    lead_session_id = "lead-stop-session"
    pane_session_id = "merchant-stop-pane"

    save_state(
        lead_session_id,
        new_state(
            request="prepare merchant proposal",
            task_class="small_task",
            risk_level="read_only",
            selected_agents=[
                "merchant-manager",
            ],
            operations=[
                "merchant_propose",
            ],
            limits={
                "max_members": 1,
                "max_total_tool_calls": 10,
            },
            confirmed=False,
            run_id="run-stop-1",
        ),
    )

    decision, teammate_name = allocate_teammate(
        lead_session_id,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session_id,
        teammate_name,
        "run-stop-1",
        "task-stop-1",
    )

    captured = []

    def fake_capture(
        session_id,
        proposal,
    ):
        captured.append(
            (
                session_id,
                proposal,
            )
        )

        return SimpleNamespace(
            accepted=True,
            reason="",
        )

    monkeypatch.setattr(
        team_result_hook,
        "capture_proposal_receipt",
        fake_capture,
    )

    proposal = {
        "success": True,
        "confirmation_token": "test-token",
        "command": "project update",
        "database_target": "runtime",
    }

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "SendMessage",
            "tool_use_id": "merchant-stop-send",
            "tool_input": {
                "recipient": "team-lead",
                "content": (
                    "Merchant proposal complete\n"
                    "MERCHANT_PROPOSAL_RESULT_JSON:\n"
                    + json.dumps(proposal)
                ),
            },
        }
    ) == 0

    # tmux PostToolUse alone must not capture the proposal.
    assert captured == []

    # Model real Claude hook ordering:
    # Stop clears the lead run-state before TeammateIdle.
    assert clear_state(
        lead_session_id
    )

    assert run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
        }
    ) == 0

    # Exact-bound pending receipt must contain enough trusted
    # lead-run context for Merchant proposal capture even though
    # Stop removed runtime_state.
    assert len(captured) == 1

    captured_session_id, captured_proposal = (
        captured[0]
    )

    assert (
        captured_session_id
        == lead_session_id
    )

    assert (
        captured_proposal
        == proposal
    )

    state = load_team_state(
        lead_session_id
    )

    record = state["teammates"][
        "merchant-manager"
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus.IDLE_REUSABLE.value
    )

    assert (
        record["last_completed_task_id"]
        == "task-stop-1"
    )

def test_tmux_merchant_proposal_prose_only_does_not_capture(
    isolated_runtime,
    monkeypatch,
):
    captured = []

    def fake_capture(
        session_id,
        proposal,
    ):
        captured.append(
            (
                session_id,
                proposal,
            )
        )

        return SimpleNamespace(
            accepted=True,
            reason="",
        )

    monkeypatch.setattr(
        team_result_hook,
        "capture_proposal_receipt",
        fake_capture,
    )

    message = (
        "Proposal Status: SUCCESS\n"
        "- Code: GATE11_TMUX\n"
        "- Database Target: runtime\n"
        "- Confirmation token: ready"
    )

    result = (
        team_result_hook
        .merchant_proposal_candidate_from_message(
            message
        )
    )

    assert result is None
    assert captured == []

def test_tmux_merchant_proposal_marker_requires_exact_json():
    message = (
        "MERCHANT_PROPOSAL_RESULT_JSON:\n"
        '{"success": true, '
        '"confirmation_token": "token"}\n'
        "extra prose"
    )

    assert (
        team_result_hook
        .merchant_proposal_candidate_from_message(
            message
        )
        is None
    )