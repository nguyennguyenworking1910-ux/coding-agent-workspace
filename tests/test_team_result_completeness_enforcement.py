"""Gate 12C.7.3B: machine-enforced Merchant completeness lifecycle."""

from __future__ import annotations
from pathlib import Path
import json
import sys
from io import StringIO
from types import SimpleNamespace

import pytest

from claude.hooks import team_result_hook
from claude.hooks.runtime_state import STATE_DIR_ENV_VAR
from claude.hooks.team_lifecycle import (
    TeammateAllocationDecision,
    TeammateLifecycleStatus,
    allocate_teammate,
    load_team_state,
    mark_teammate_running,
)
from claude.hooks.tmux_merchant_completeness import (
    load_pending_merchant_completeness,
)
from claude.hooks.tmux_merchant_proposal import (
    load_pending_merchant_proposal,
)
from claude.hooks.tmux_result_receipt import (
    load_pending_result,
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"

sys.path.insert(
    0,
    str(HOOKS_DIR),
)

import policy_gate  # noqa: E402


MERCHANT_MANAGER = "merchant-manager"
MERCHANT_PROPOSE = "merchant_propose"


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
        str(tmp_path / "pending_merchant_proposals"),
    )
    monkeypatch.setenv(
        "CLAUDE_RUNTIME_DIR",
        str(tmp_path / "runtime"),
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


def _start_merchant_propose(
    lead_session_id: str,
    *,
    run_id: str,
    task_id: str,
):
    decision, teammate_name = allocate_teammate(
        lead_session_id,
        MERCHANT_MANAGER,
        MERCHANT_MANAGER,
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )
    assert teammate_name == MERCHANT_MANAGER

    assert mark_teammate_running(
        lead_session_id,
        teammate_name,
        run_id,
        task_id,
        operations=[
            MERCHANT_PROPOSE,
        ],
        selected_agents=[
            MERCHANT_MANAGER,
        ],
    )


def _incomplete_completeness_result():
    return {
        "success": True,
        "mode": "COMPLETENESS",
        "command": "document revision-create",
        "complete": False,
        "missing_fields": [
            "project_id",
            "document_type",
            "content_hash",
        ],
        "missing_one_of": [],
        "clarification": {
            "outcome": "REQUIRES_CLARIFICATION",
            "missing_fields": [
                "project_id",
                "document_type",
                "content_hash",
            ],
            "missing_one_of": [],
            "question": (
                "Please provide project_id, "
                "document_type, and content_hash."
            ),
        },
    }


def _complete_completeness_result(
    command: str = "merchant create",
):
    return {
        "success": True,
        "mode": "COMPLETENESS",
        "command": command,
        "complete": True,
        "missing_fields": [],
        "missing_one_of": [],
        "clarification": None,
    }


def _clarification_outcome():
    return {
        "contract_version": 1,
        "outcome": "REQUIRES_CLARIFICATION",
        "operation": MERCHANT_PROPOSE,
        "database_target": "runtime",
        "proposal_emitted": False,
        "missing_fields": [
            "project_id",
            "document_type",
            "content_hash",
        ],
        "missing_one_of": [],
        "question": (
            "Please provide project_id, "
            "document_type, and content_hash."
        ),
    }


def _proposal_ready_outcome():
    return {
        "contract_version": 1,
        "outcome": "PROPOSAL_READY",
        "operation": MERCHANT_PROPOSE,
        "database_target": "runtime",
        "proposal_emitted": True,
    }


def _stage_completeness(
    pane_session_id: str,
    result: dict,
):
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": MERCHANT_MANAGER,
            "tool_name": "Bash",
            "tool_use_id": "completeness-cli",
            "tool_response": {
                "stdout": json.dumps(
                    result
                ),
                "stderr": "",
            },
        }
    ) == 0

    receipt = load_pending_merchant_completeness(
        pane_session_id
    )

    assert receipt is not None
    assert receipt["result"] == result


def _send_team_result(
    pane_session_id: str,
    result: dict,
    *,
    proposal: dict | None = None,
):
    message = (
        "TEAM_RESULT_JSON:\n"
        + json.dumps(
            result
        )
    )

    if proposal is not None:
        message += (
            "\n"
            "MERCHANT_PROPOSAL_RESULT_JSON:\n"
            + json.dumps(
                proposal
            )
        )

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": MERCHANT_MANAGER,
            "tool_name": "SendMessage",
            "tool_use_id": "merchant-send-result",
            "tool_input": {
                "recipient": "team-lead",
                "to": "team-lead",
                "content": "Merchant task result",
                "message": message,
            },
        }
    ) == 0

    assert (
        load_pending_result(
            pane_session_id
        )
        is not None
    )


def _idle(
    pane_session_id: str,
):
    return run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": MERCHANT_MANAGER,
            "teammate_name": MERCHANT_MANAGER,
        }
    )


def _record(
    lead_session_id: str,
):
    state = load_team_state(
        lead_session_id
    )

    assert state is not None

    return state[
        "teammates"
    ][
        MERCHANT_MANAGER
    ]


def _assert_reusable(
    lead_session_id: str,
):
    record = _record(
        lead_session_id
    )

    assert (
        record["status"]
        == TeammateLifecycleStatus.IDLE_REUSABLE.value
    )
    assert record["result_received"] is True
    assert record["current_run_id"] is None
    assert record["current_task_id"] is None


def _assert_not_reusable(
    lead_session_id: str,
):
    record = _record(
        lead_session_id
    )

    assert (
        record["status"]
        != TeammateLifecycleStatus.IDLE_REUSABLE.value
    )


def _install_proposal_capture(
    monkeypatch,
    proposal: dict,
):
    captured = []

    def fake_extract(payload):
        if (
            payload.get("tool_use_id")
            == "proposal-cli"
        ):
            return proposal

        return None

    def fake_capture(
        session_id,
        exact_proposal,
    ):
        captured.append(
            (
                session_id,
                exact_proposal,
            )
        )
        return SimpleNamespace(
            accepted=True,
            reason="",
        )

    monkeypatch.setattr(
        team_result_hook,
        "merchant_proposal_from_tool_response",
        fake_extract,
    )
    monkeypatch.setattr(
        team_result_hook,
        "capture_proposal_receipt",
        fake_capture,
    )

    return captured


def _stage_proposal(
    pane_session_id: str,
    proposal: dict,
):
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": MERCHANT_MANAGER,
            "tool_name": "PowerShell",
            "tool_use_id": "proposal-cli",
            "tool_response": {
                "stdout": json.dumps(
                    proposal
                ),
                "stderr": "",
            },
        }
    ) == 0

    receipt = load_pending_merchant_proposal(
        pane_session_id
    )

    assert receipt is not None
    assert receipt["proposal"] == proposal


def test_requires_clarification_with_exact_incomplete_receipt_releases(
    isolated_runtime,
):
    lead_session_id = "lead-clarification-ok"
    pane_session_id = "pane-clarification-ok"

    _start_merchant_propose(
        lead_session_id,
        run_id="run-clarification-ok",
        task_id="task-clarification-ok",
    )

    _stage_completeness(
        pane_session_id,
        _incomplete_completeness_result(),
    )

    _send_team_result(
        pane_session_id,
        _clarification_outcome(),
    )

    assert _idle(
        pane_session_id
    ) == 0

    _assert_reusable(
        lead_session_id
    )

    assert (
        load_pending_merchant_completeness(
            pane_session_id
        )
        is None
    )
    assert (
        load_pending_result(
            pane_session_id
        )
        is None
    )


def test_requires_clarification_without_receipt_fails_closed(
    isolated_runtime,
):
    lead_session_id = "lead-clarification-missing"
    pane_session_id = "pane-clarification-missing"

    _start_merchant_propose(
        lead_session_id,
        run_id="run-clarification-missing",
        task_id="task-clarification-missing",
    )

    _send_team_result(
        pane_session_id,
        _clarification_outcome(),
    )

    assert _idle(
        pane_session_id
    ) == 2

    _assert_not_reusable(
        lead_session_id
    )


def test_requires_clarification_question_mismatch_fails_closed(
    isolated_runtime,
):
    lead_session_id = "lead-clarification-mismatch"
    pane_session_id = "pane-clarification-mismatch"

    _start_merchant_propose(
        lead_session_id,
        run_id="run-clarification-mismatch",
        task_id="task-clarification-mismatch",
    )

    _stage_completeness(
        pane_session_id,
        _incomplete_completeness_result(),
    )

    outcome = _clarification_outcome()
    outcome[
        "question"
    ] = "Which project should I use?"

    _send_team_result(
        pane_session_id,
        outcome,
    )

    assert _idle(
        pane_session_id
    ) == 2

    _assert_not_reusable(
        lead_session_id
    )

    assert (
        load_pending_merchant_completeness(
            pane_session_id
        )
        is not None
    )


def test_proposal_ready_with_complete_receipt_and_exact_proposal_releases(
    isolated_runtime,
    monkeypatch,
):
    lead_session_id = "lead-proposal-ok"
    pane_session_id = "pane-proposal-ok"

    _start_merchant_propose(
        lead_session_id,
        run_id="run-proposal-ok",
        task_id="task-proposal-ok",
    )

    exact_proposal = {
        "success": True,
        "mode": "PROPOSE",
        "database": "runtime",
        "command": "merchant create",
        "confirmation_token": "exact-cli-token",
    }

    captured = _install_proposal_capture(
        monkeypatch,
        exact_proposal,
    )

    _stage_completeness(
        pane_session_id,
        _complete_completeness_result(
            "merchant create"
        ),
    )

    _stage_proposal(
        pane_session_id,
        exact_proposal,
    )

    _send_team_result(
        pane_session_id,
        _proposal_ready_outcome(),
        proposal=exact_proposal,
    )

    assert _idle(
        pane_session_id
    ) == 0

    _assert_reusable(
        lead_session_id
    )

    assert captured == [
        (
            lead_session_id,
            exact_proposal,
        )
    ]

    assert (
        load_pending_merchant_completeness(
            pane_session_id
        )
        is None
    )
    assert (
        load_pending_merchant_proposal(
            pane_session_id
        )
        is None
    )


def test_proposal_ready_without_completeness_receipt_fails_closed(
    isolated_runtime,
    monkeypatch,
):
    lead_session_id = "lead-proposal-no-completeness"
    pane_session_id = "pane-proposal-no-completeness"

    _start_merchant_propose(
        lead_session_id,
        run_id="run-proposal-no-completeness",
        task_id="task-proposal-no-completeness",
    )

    exact_proposal = {
        "success": True,
        "mode": "PROPOSE",
        "database": "runtime",
        "command": "merchant create",
        "confirmation_token": "exact-cli-token",
    }

    _install_proposal_capture(
        monkeypatch,
        exact_proposal,
    )

    _stage_proposal(
        pane_session_id,
        exact_proposal,
    )

    _send_team_result(
        pane_session_id,
        _proposal_ready_outcome(),
        proposal=exact_proposal,
    )

    assert _idle(
        pane_session_id
    ) == 2

    _assert_not_reusable(
        lead_session_id
    )


def test_proposal_ready_rejects_completeness_command_mismatch(
    isolated_runtime,
    monkeypatch,
):
    lead_session_id = "lead-proposal-command-mismatch"
    pane_session_id = "pane-proposal-command-mismatch"

    _start_merchant_propose(
        lead_session_id,
        run_id="run-proposal-command-mismatch",
        task_id="task-proposal-command-mismatch",
    )

    exact_proposal = {
        "success": True,
        "mode": "PROPOSE",
        "database": "runtime",
        "command": "document revision-create",
        "confirmation_token": "exact-cli-token",
    }

    _install_proposal_capture(
        monkeypatch,
        exact_proposal,
    )

    _stage_completeness(
        pane_session_id,
        _complete_completeness_result(
            "merchant create"
        ),
    )

    _stage_proposal(
        pane_session_id,
        exact_proposal,
    )

    _send_team_result(
        pane_session_id,
        _proposal_ready_outcome(),
        proposal=exact_proposal,
    )

    assert _idle(
        pane_session_id
    ) == 2

    _assert_not_reusable(
        lead_session_id
    )


@pytest.mark.parametrize(
    "outcome_name",
    (
        "BLOCKED",
        "FAILED",
    ),
)
def test_blocked_and_failed_do_not_require_completeness_receipt(
    isolated_runtime,
    outcome_name,
):
    lead_session_id = (
        f"lead-{outcome_name.lower()}"
    )
    pane_session_id = (
        f"pane-{outcome_name.lower()}"
    )

    _start_merchant_propose(
        lead_session_id,
        run_id=f"run-{outcome_name.lower()}",
        task_id=f"task-{outcome_name.lower()}",
    )

    outcome = {
        "contract_version": 1,
        "outcome": outcome_name,
        "operation": MERCHANT_PROPOSE,
        "database_target": "runtime",
        "proposal_emitted": False,
    }

    _send_team_result(
        pane_session_id,
        outcome,
    )

    assert _idle(
        pane_session_id
    ) == 0

    _assert_reusable(
        lead_session_id
    )


def test_action_semantics_clarification_does_not_require_completeness_receipt(
    isolated_runtime,
):
    lead_session_id = "lead-action-semantics"
    pane_session_id = "pane-action-semantics"

    _start_merchant_propose(
        lead_session_id,
        run_id="run-action-semantics",
        task_id="task-action-semantics",
    )

    outcome = {
        "contract_version": 1,
        "outcome": "REQUIRES_CLARIFICATION",
        "operation": MERCHANT_PROPOSE,
        "database_target": "runtime",
        "proposal_emitted": False,
        "missing_fields": [
            "action_semantics"
        ],
        "missing_one_of": [],
        "question": (
            "Which Merchant action should be performed?"
        ),
    }

    _send_team_result(
        pane_session_id,
        outcome,
    )

    assert _idle(
        pane_session_id
    ) == 0

    _assert_reusable(
        lead_session_id
    )

@pytest.mark.parametrize(
    "same_session",
    [False, True],
)
def test_authenticated_merchant_sendmessage_is_deferred_until_idle_validation(
    isolated_runtime,
    same_session,
):
    lead_session_id = "lead-authenticated-deferred"

    pane_session_id = (
        lead_session_id
        if same_session
        else "pane-authenticated-deferred"
    )

    _start_merchant_propose(
        lead_session_id,
        run_id="run-authenticated-deferred",
        task_id="task-authenticated-deferred",
    )

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_id": "merchant-agent-id",
            "agent_type": MERCHANT_MANAGER,
            "tool_name": "SendMessage",
            "tool_use_id": "premature-send",
            "tool_input": {
                "recipient": "team-lead",
                "message": (
                    "I need project_id and document_type."
                ),
            },
        }
    ) == 0

    assert load_pending_result(
        pane_session_id
    ) is not None

    record = _record(
        lead_session_id
    )

    assert (
        record["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )
    assert record["result_received"] is False
    assert record["report_source"] is None

def test_premature_authenticated_merchant_result_does_not_trigger_tool_freeze(
    isolated_runtime,
):
    lead_session_id = "lead-no-premature-freeze"
    pane_session_id = "pane-no-premature-freeze"

    _start_merchant_propose(
        lead_session_id,
        run_id="run-no-premature-freeze",
        task_id="task-no-premature-freeze",
    )

    # Authenticated teammate sends an INVALID/PREMATURE result
    # before deterministic completeness evidence exists.
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_id": "merchant-agent-id",
            "agent_type": MERCHANT_MANAGER,
            "tool_name": "SendMessage",
            "tool_use_id": "premature-send",
            "tool_input": {
                "recipient": "team-lead",
                "message": (
                    "I need project_id and document_type."
                ),
            },
        }
    ) == 0

    # Delivery transport is staged.
    assert (
        load_pending_result(
            pane_session_id
        )
        is not None
    )

    # But lifecycle has NOT accepted the terminal result.
    record = _record(
        lead_session_id
    )

    assert (
        record["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )
    assert record["result_received"] is False
    assert record["report_source"] is None

    # Critical Gate 12C.9A assertion:
    # policy gate must still permit subsequent teammate tools
    # such as the required completeness CLI call.
    freeze_decision = (
        policy_gate.completed_teammate_tool_decision(
            MERCHANT_MANAGER
        )
    )

    assert freeze_decision is None