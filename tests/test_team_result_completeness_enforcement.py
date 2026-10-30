"""Gate 12C.7.3B: machine-enforced Merchant completeness lifecycle.

Direct EXECUTE only: completeness evidence supports a no-write terminal
outcome for a merchant_execute task. It never authorizes a write.
"""

from __future__ import annotations
from pathlib import Path
import json
import sys
from io import StringIO

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
from tests.merchant.direct_reservation_support import trust_teammate_pane


@pytest.fixture(autouse=True)
def _trusted_teammate_pane(monkeypatch):
    # Subject here is completion, not pane identity (see test_cp12h5b_*).
    trust_teammate_pane(monkeypatch)



MERCHANT_MANAGER = "merchant-manager"
MERCHANT_EXECUTE = "merchant_execute"


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


def _start_merchant_task(
    lead_session_id: str,
    *,
    run_id: str,
    task_id: str,
    operation: str = MERCHANT_EXECUTE,
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
            operation,
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
        "operation": MERCHANT_EXECUTE,
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


def _completeness_tool_use(
    pane_session_id: str,
    result: dict,
):
    return run_hook(
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
    )


def _stage_completeness(
    pane_session_id: str,
    result: dict,
):
    assert _completeness_tool_use(
        pane_session_id,
        result,
    ) == 0

    receipt = load_pending_merchant_completeness(
        pane_session_id
    )

    assert receipt is not None
    assert receipt["result"] == result


def _send_team_result(
    pane_session_id: str,
    result: dict,
):
    message = (
        "TEAM_RESULT_JSON:\n"
        + json.dumps(
            result
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
    assert "direct_writes" not in record
    assert "direct_no_write_terminal" not in record


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


def test_requires_clarification_with_exact_incomplete_receipt_releases(
    isolated_runtime,
):
    lead_session_id = "lead-clarification-ok"
    pane_session_id = "pane-clarification-ok"

    _start_merchant_task(
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

    _start_merchant_task(
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
    assert "direct_no_write_terminal" not in _record(
        lead_session_id
    )


def test_requires_clarification_question_mismatch_fails_closed(
    isolated_runtime,
):
    lead_session_id = "lead-clarification-mismatch"
    pane_session_id = "pane-clarification-mismatch"

    _start_merchant_task(
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


def test_complete_receipt_cannot_support_clarification(
    isolated_runtime,
):
    """complete=true evidence contradicts a missing-field clarification."""

    lead_session_id = "lead-clarification-complete"
    pane_session_id = "pane-clarification-complete"

    _start_merchant_task(
        lead_session_id,
        run_id="run-clarification-complete",
        task_id="task-clarification-complete",
    )

    _stage_completeness(
        pane_session_id,
        _complete_completeness_result(),
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


def _install_stale_legacy_task(lead_session_id, operation):
    """Simulate a task persisted before the workflow was removed."""
    from claude.hooks.team_lifecycle import locked_team_state

    allocate_teammate(lead_session_id, MERCHANT_MANAGER, MERCHANT_MANAGER)

    with locked_team_state(lead_session_id) as state:
        state["teammates"][MERCHANT_MANAGER].update(
            status="RUNNING",
            current_run_id=f"run-{operation}",
            current_task_id=f"task-{operation}",
            authorized_operations=[operation],
            authorized_selected_agents=[MERCHANT_MANAGER],
            result_received=False,
            report_source=None,
        )


@pytest.mark.parametrize(
    "operation",
    (
        "merchant_propose",
        "merchant_apply",
    ),
)
def test_legacy_owner_cannot_stage_completeness_or_release(
    isolated_runtime,
    operation,
):
    """Removed proposal/apply tasks gain no completeness or release path."""

    lead_session_id = f"lead-legacy-{operation}"
    pane_session_id = f"pane-legacy-{operation}"

    _install_stale_legacy_task(lead_session_id, operation)

    assert _completeness_tool_use(
        pane_session_id,
        _complete_completeness_result(),
    ) == 0

    assert load_pending_merchant_completeness(
        pane_session_id
    ) is None

    _send_team_result(
        pane_session_id,
        {
            "contract_version": 1,
            "outcome": "BLOCKED",
            "operation": operation,
            "database_target": "runtime",
            "proposal_emitted": False,
        },
    )

    # A removed workflow is never released, even with a valid-looking
    # no-write outcome: it terminates once without a write.
    assert _idle(pane_session_id) == 0

    record = _record(lead_session_id)
    assert record["status"] == TeammateLifecycleStatus.FAILED.value
    assert record["failure_reason"] == "LEGACY_MERCHANT_OPERATION_REMOVED"
    assert "direct_no_write_terminal" not in record

    assert _idle(pane_session_id) == 0
    assert _record(lead_session_id)["status"] == (
        TeammateLifecycleStatus.FAILED.value
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

    _start_merchant_task(
        lead_session_id,
        run_id=f"run-{outcome_name.lower()}",
        task_id=f"task-{outcome_name.lower()}",
    )

    outcome = {
        "contract_version": 1,
        "outcome": outcome_name,
        "operation": MERCHANT_EXECUTE,
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

    _start_merchant_task(
        lead_session_id,
        run_id="run-action-semantics",
        task_id="task-action-semantics",
    )

    outcome = {
        "contract_version": 1,
        "outcome": "REQUIRES_CLARIFICATION",
        "operation": MERCHANT_EXECUTE,
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

    _start_merchant_task(
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


def test_authenticated_pane_direct_result_completes_through_idle_gate(
    isolated_runtime,
):
    """An authenticated pane reaches the same trusted no-write gate."""

    lead_session_id = "lead-authenticated-direct"
    pane_session_id = "pane-authenticated-direct"

    _start_merchant_task(
        lead_session_id,
        run_id="run-authenticated-direct",
        task_id="task-authenticated-direct",
    )

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_id": "merchant-agent-id",
            "agent_type": MERCHANT_MANAGER,
            "tool_name": "SendMessage",
            "tool_use_id": "authenticated-blocked",
            "tool_input": {
                "recipient": "team-lead",
                "message": "TEAM_RESULT_JSON:\n" + json.dumps(
                    {
                        "contract_version": 1,
                        "outcome": "BLOCKED",
                        "operation": MERCHANT_EXECUTE,
                        "database_target": "runtime",
                        "proposal_emitted": False,
                    }
                ),
            },
        }
    ) == 0

    assert _record(lead_session_id)["status"] == (
        TeammateLifecycleStatus.RUNNING.value
    )

    assert _idle(pane_session_id) == 0

    _assert_reusable(lead_session_id)


def test_premature_authenticated_merchant_result_does_not_trigger_tool_freeze(
    isolated_runtime,
):
    lead_session_id = "lead-no-premature-freeze"
    pane_session_id = "pane-no-premature-freeze"

    _start_merchant_task(
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
