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
import policy_gate

from runtime_state import (  # noqa: E402
    STATE_DIR_ENV_VAR,
    clear_state,
    load_state,
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
from tmux_merchant_proposal import (  # noqa: E402
    load_pending_merchant_proposal,
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
    monkeypatch.setenv(
        "CLAUDE_PENDING_MERCHANT_PROPOSAL_DIR",
        str(
            tmp_path
            / "pending_merchant_proposals"
        ),
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
    lead_session_id = (
        "lead-merchant-session"
    )

    pane_session_id = (
        "merchant-pane-session"
    )

    save_state(
        lead_session_id,
        new_state(
            request=(
                "prepare merchant proposal"
            ),
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
        "run-merchant-1",
        "task-merchant-1",
        operations=[
            "merchant_propose",
        ],
        selected_agents=[
            "merchant-manager",
        ],
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

    exact_proposal = {
        "success": True,
        "mode": "PROPOSE",
        "database": "runtime",
        "confirmation_token": (
            "exact-cli-token"
        ),
        "command": "project update",
    }

    # We test orchestration here.
    # validate_proposal_result itself already has
    # its own dedicated tests.
    monkeypatch.setattr(
        team_result_hook,
        "merchant_proposal_from_tool_response",
        lambda payload: (
            exact_proposal
            if payload.get(
                "tool_name"
            )
            == "PowerShell"
            else None
        ),
    )

    # -------------------------------------------------
    # 1. Merchant CLI produces the exact proposal.
    # -------------------------------------------------

    assert run_hook(
        {
            "hook_event_name": (
                "PostToolUse"
            ),
            "session_id": (
                pane_session_id
            ),
            "agent_type": (
                "merchant-manager"
            ),
            "tool_name": (
                "PowerShell"
            ),
            "tool_use_id": (
                "merchant-cli-propose"
            ),
            "tool_response": {
                "stdout": json.dumps(
                    exact_proposal
                ),
                "stderr": "",
            },
        }
    ) == 0

    pending_proposal = (
        load_pending_merchant_proposal(
            pane_session_id
        )
    )

    assert (
        pending_proposal
        is not None
    )

    assert (
        pending_proposal[
            "proposal"
        ]
        == exact_proposal
    )

    # Still only staged.
    assert captured == []

    # -------------------------------------------------
    # 2. Model sends a MUTATED token in SendMessage.
    #
    # This must be delivery proof only.
    # -------------------------------------------------

    mutated_proposal = dict(
        exact_proposal
    )

    mutated_proposal[
        "confirmation_token"
    ] = "model-mutated-token"

    assert run_hook(
        {
            "hook_event_name": (
                "PostToolUse"
            ),
            "session_id": (
                pane_session_id
            ),
            "agent_type": (
                "merchant-manager"
            ),
            "tool_name": (
                "SendMessage"
            ),
            "tool_use_id": (
                "merchant-send-1"
            ),
            "tool_input": {
                "recipient": (
                    "team-lead"
                ),
                "to": (
                    "team-lead"
                ),
                "content": (
                    "Proposal delivered"
                ),
                "message": (
                    "Merchant proposal complete\n"
                    "MERCHANT_PROPOSAL_RESULT_JSON:\n"
                    + json.dumps(
                        mutated_proposal
                    )
                ),
            },
        }
    ) == 0

    # SendMessage must NOT capture proposal authority.
    assert captured == []

    # -------------------------------------------------
    # 3. Trusted TeammateIdle consumes exact CLI copy.
    # -------------------------------------------------

    assert run_hook(
        {
            "hook_event_name": (
                "TeammateIdle"
            ),
            "session_id": (
                pane_session_id
            ),
            "agent_type": (
                "merchant-manager"
            ),
            "teammate_name": (
                "merchant-manager"
            ),
        }
    ) == 0

    assert (
        len(captured)
        == 1
    )

    (
        captured_session_id,
        captured_proposal,
    ) = captured[0]

    assert (
        captured_session_id
        == lead_session_id
    )

    # Critical Gate 11I assertion:
    assert (
        captured_proposal
        == exact_proposal
    )

    assert (
        captured_proposal[
            "confirmation_token"
        ]
        == "exact-cli-token"
    )

    assert (
        captured_proposal[
            "confirmation_token"
        ]
        != mutated_proposal[
            "confirmation_token"
        ]
    )

    # Raw transient token must be cleaned.
    assert (
        load_pending_merchant_proposal(
            pane_session_id
        )
        is None
    )

    state = load_team_state(
        lead_session_id
    )

    record = state[
        "teammates"
    ][
        "merchant-manager"
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus
        .IDLE_REUSABLE
        .value
    )

    assert (
        record["result_received"]
        is True
    )

def test_tmux_merchant_proposal_survives_stop_before_idle(
    isolated_runtime,
    monkeypatch,
):
    lead_session_id = (
        "lead-stop-session"
    )

    pane_session_id = (
        "merchant-stop-pane"
    )

    save_state(
        lead_session_id,
        new_state(
            request=(
                "prepare merchant proposal"
            ),
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
        "run-stop-1",
        "task-stop-1",
        operations=[
            "merchant_propose",
        ],
        selected_agents=[
            "merchant-manager",
        ],
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

    exact_proposal = {
        "success": True,
        "mode": "PROPOSE",
        "database": "runtime",
        "confirmation_token": (
            "exact-stop-token"
        ),
        "command": "project update",
    }

    monkeypatch.setattr(
        team_result_hook,
        "merchant_proposal_from_tool_response",
        lambda payload: (
            exact_proposal
            if payload.get(
                "tool_name"
            )
            == "PowerShell"
            else None
        ),
    )

    # -------------------------------------------------
    # Exact CLI proposal happens BEFORE Stop.
    # -------------------------------------------------

    assert run_hook(
        {
            "hook_event_name": (
                "PostToolUse"
            ),
            "session_id": (
                pane_session_id
            ),
            "agent_type": (
                "merchant-manager"
            ),
            "tool_name": (
                "PowerShell"
            ),
            "tool_use_id": (
                "merchant-stop-cli"
            ),
            "tool_response": {
                "stdout": json.dumps(
                    exact_proposal
                ),
                "stderr": "",
            },
        }
    ) == 0

    pending_proposal = (
        load_pending_merchant_proposal(
            pane_session_id
        )
    )

    assert (
        pending_proposal
        is not None
    )

    assert (
        pending_proposal[
            "proposal"
        ]
        == exact_proposal
    )

    # -------------------------------------------------
    # SendMessage report.
    # -------------------------------------------------

    mutated_proposal = dict(
        exact_proposal
    )

    mutated_proposal[
        "confirmation_token"
    ] = "mutated-stop-token"

    assert run_hook(
        {
            "hook_event_name": (
                "PostToolUse"
            ),
            "session_id": (
                pane_session_id
            ),
            "agent_type": (
                "merchant-manager"
            ),
            "tool_name": (
                "SendMessage"
            ),
            "tool_use_id": (
                "merchant-stop-send"
            ),
            "tool_input": {
                "recipient": (
                    "team-lead"
                ),
                "to": (
                    "team-lead"
                ),
                "content": (
                    "Proposal delivered"
                ),
                "message": (
                    "Merchant proposal complete\n"
                    "MERCHANT_PROPOSAL_RESULT_JSON:\n"
                    + json.dumps(
                        mutated_proposal
                    )
                ),
            },
        }
    ) == 0

    assert captured == []

    # -------------------------------------------------
    # Real ordering:
    # Stop removes run state before TeammateIdle.
    # -------------------------------------------------

    assert clear_state(
        lead_session_id
    )

    # Exact proposal must still exist because its owner/run/task
    # binding was captured before Stop.
    assert (
        load_pending_merchant_proposal(
            pane_session_id
        )
        is not None
    )

    # -------------------------------------------------
    # Trusted TeammateIdle.
    # -------------------------------------------------

    assert run_hook(
        {
            "hook_event_name": (
                "TeammateIdle"
            ),
            "session_id": (
                pane_session_id
            ),
            "agent_type": (
                "merchant-manager"
            ),
            "teammate_name": (
                "merchant-manager"
            ),
        }
    ) == 0

    assert (
        len(captured)
        == 1
    )

    (
        captured_session_id,
        captured_proposal,
    ) = captured[0]

    assert (
        captured_session_id
        == lead_session_id
    )

    assert (
        captured_proposal
        == exact_proposal
    )

    assert (
        captured_proposal[
            "confirmation_token"
        ]
        == "exact-stop-token"
    )

    assert (
        load_pending_merchant_proposal(
            pane_session_id
        )
        is None
    )

    state = load_team_state(
        lead_session_id
    )

    record = state[
        "teammates"
    ][
        "merchant-manager"
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus
        .IDLE_REUSABLE
        .value
    )

    assert (
        record[
            "last_completed_task_id"
        ]
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

def test_tmux_merchant_proposal_stages_when_agent_id_is_present(
    isolated_runtime,
    monkeypatch,
):
    lead_session_id = "lead-agent-id-session"
    pane_session_id = "merchant-agent-id-pane"

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
            run_id="run-agent-id-1",
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
        "run-agent-id-1",
        "task-agent-id-1",
        operations=[
            "merchant_propose",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    exact_proposal = {
        "success": True,
        "mode": "PROPOSE",
        "database": "runtime",
        "confirmation_token": "exact-agent-id-token",
        "command": "project update",
    }

    monkeypatch.setattr(
        team_result_hook,
        "merchant_proposal_from_tool_response",
        lambda payload: (
            exact_proposal
            if payload.get("tool_name") == "Bash"
            else None
        ),
    )

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_id": "merchant-agent-id",
            "agent_type": "merchant-manager",
            "tool_name": "Bash",
            "tool_use_id": "merchant-agent-id-cli",
            "tool_response": {
                "stdout": json.dumps(
                    exact_proposal
                ),
                "stderr": "",
            },
        }
    ) == 0

    pending = load_pending_merchant_proposal(
        pane_session_id
    )

    assert pending is not None

    assert (
        pending["owner_session_id"]
        == lead_session_id
    )

    assert (
        pending["teammate_name"]
        == "merchant-manager"
    )

    assert (
        pending["run_id"]
        == "run-agent-id-1"
    )

    assert (
        pending["task_id"]
        == "task-agent-id-1"
    )

    assert (
        pending["proposal"]
        == exact_proposal
    )

def test_tmux_merchant_proposal_missing_exact_cli_blocks_idle(
    isolated_runtime,
):
    lead_session_id = "lead-missing-proposal"
    pane_session_id = "pane-missing-proposal"

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
            run_id="run-missing-proposal",
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
        "run-missing-proposal",
        "task-missing-proposal",
        operations=[
            "merchant_propose",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    # SendMessage exists, but NO exact CLI proposal was staged.
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "SendMessage",
            "tool_use_id": "missing-proposal-send",
            "tool_input": {
                "recipient": "team-lead",
                "content": "Proposal delivered",
                "message": (
                    "Merchant proposal complete"
                ),
            },
        }
    ) == 0

    result = run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
        }
    )

    # TeammateIdle must be rejected.
    assert result == 2

    state = load_team_state(
        lead_session_id
    )

    record = state[
        "teammates"
    ][
        "merchant-manager"
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus
        .REPORT_RECEIVED
        .value
    )

    assert (
        record["current_run_id"]
        == "run-missing-proposal"
    )

    assert (
        record["current_task_id"]
        == "task-missing-proposal"
    )

    # SendMessage evidence must remain.
    assert (
        load_pending_result(
            pane_session_id
        )
        is not None
    )

    # No exact CLI proposal exists.
    assert (
        load_pending_merchant_proposal(
            pane_session_id
        )
        is None
    )


def test_tmux_merchant_proposal_capture_failure_blocks_idle_and_preserves_evidence(
    isolated_runtime,
    monkeypatch,
):
    lead_session_id = "lead-capture-failure"
    pane_session_id = "pane-capture-failure"

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
            run_id="run-capture-failure",
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
        "run-capture-failure",
        "task-capture-failure",
        operations=[
            "merchant_propose",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    exact_proposal = {
        "success": True,
        "mode": "PROPOSE",
        "database": "runtime",
        "confirmation_token": (
            "exact-capture-failure-token"
        ),
        "command": "project update",
    }

    monkeypatch.setattr(
        team_result_hook,
        "merchant_proposal_from_tool_response",
        lambda payload: (
            exact_proposal
            if payload.get("tool_name") == "Bash"
            else None
        ),
    )

    # Stage exact CLI proposal.
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_id": "merchant-agent-id",
            "agent_type": "merchant-manager",
            "tool_name": "Bash",
            "tool_use_id": "capture-failure-cli",
            "tool_response": {
                "stdout": json.dumps(
                    exact_proposal
                ),
                "stderr": "",
            },
        }
    ) == 0

    assert (
        load_pending_merchant_proposal(
            pane_session_id
        )
        is not None
    )

    # Delivery proof.
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "SendMessage",
            "tool_use_id": "capture-failure-send",
            "tool_input": {
                "recipient": "team-lead",
                "content": "Proposal delivered",
                "message": (
                    "Merchant proposal complete"
                ),
            },
        }
    ) == 0

    # Force long-lived receipt capture to fail.
    monkeypatch.setattr(
        team_result_hook,
        "capture_proposal_receipt",
        lambda session_id, proposal: (
            SimpleNamespace(
                accepted=False,
                reason="forced failure",
            )
        ),
    )

    result = run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
        }
    )

    assert result == 2

    state = load_team_state(
        lead_session_id
    )

    record = state[
        "teammates"
    ][
        "merchant-manager"
    ]

    # Must NOT become reusable.
    assert (
        record["status"]
        == TeammateLifecycleStatus
        .REPORT_RECEIVED
        .value
    )

    assert (
        record["current_run_id"]
        == "run-capture-failure"
    )

    assert (
        record["current_task_id"]
        == "task-capture-failure"
    )

    # Both pieces of evidence must survive for diagnosis/retry.
    assert (
        load_pending_result(
            pane_session_id
        )
        is not None
    )

    assert (
        load_pending_merchant_proposal(
            pane_session_id
        )
        is not None
    )

def test_tmux_merchant_proposal_stages_after_lead_run_state_is_cleared(
    isolated_runtime,
    monkeypatch,
):
    lead_session_id = "lead-stop-before-cli"
    pane_session_id = "pane-stop-before-cli"

    run_state = new_state(
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
        run_id="run-stop-before-cli",
    )

    save_state(
        lead_session_id,
        run_state,
    )

    # Use the real policy gate so authorization is snapshotted
    # exactly where production dispatch does it.
    assert policy_gate.apply_call(
        run_state,
        "Agent",
        {
            "subagent_type": "merchant-manager",
            "name": "merchant-manager",
        },
        lead_session_id,
    ) is None

    team_state = load_team_state(
        lead_session_id
    )

    record = team_state[
        "teammates"
    ][
        "merchant-manager"
    ]

    assert (
        record[
            "authorized_operations"
        ]
        == [
            "merchant_propose"
        ]
    )

    assert (
        record[
            "authorized_selected_agents"
        ]
        == [
            "merchant-manager"
        ]
    )

    # Critical production ordering:
    # runtime state disappears BEFORE Merchant CLI PostToolUse.
    assert clear_state(
        lead_session_id
    )

    assert (
        load_state(
            lead_session_id
        )
        is None
    )

    exact_proposal = {
        "success": True,
        "mode": "PROPOSE",
        "database": "runtime",
        "confirmation_token": (
            "exact-stop-before-cli-token"
        ),
        "command": "project create",
    }

    monkeypatch.setattr(
        team_result_hook,
        "merchant_proposal_from_tool_response",
        lambda payload: (
            exact_proposal
            if payload.get(
                "tool_name"
            )
            == "Bash"
            else None
        ),
    )

    # Must stage successfully even though runtime_state is gone.
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_id": "merchant-agent",
            "agent_type": "merchant-manager",
            "tool_name": "Bash",
            "tool_use_id": "stop-before-cli-tool",
            "tool_response": {
                "stdout": json.dumps(
                    exact_proposal
                ),
                "stderr": "",
            },
        }
    ) == 0

    pending = (
        load_pending_merchant_proposal(
            pane_session_id
        )
    )

    assert pending is not None

    assert (
        pending[
            "owner_session_id"
        ]
        == lead_session_id
    )

    assert (
        pending[
            "run_id"
        ]
        == "run-stop-before-cli"
    )

    assert (
        pending[
            "proposal"
        ]
        == exact_proposal
    )