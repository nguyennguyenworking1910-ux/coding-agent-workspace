"""Gate 11: multi-role tmux lifecycle safety."""

from __future__ import annotations

import json
import os
import sys
import time
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
    find_unique_active_teammate_owner,
    init_teammate_record,
    load_team_state,
    mark_teammate_idle_reusable,
    mark_teammate_running,
    new_team_state,
    save_team_state,
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
    monkeypatch.setenv(
        "CLAUDE_PENDING_MERCHANT_PROPOSAL_DIR",
        str(
            tmp_path
            / "pending_merchant_proposals"
        ),
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


def stage_incomplete_merchant_completeness(
    pane_session_id: str,
    *,
    command: str,
    missing_fields: list[str],
    question: str,
    missing_one_of: list[list[str]] | None = None,
):
    if missing_one_of is None:
        missing_one_of = []

    result = {
        "success": True,
        "mode": "COMPLETENESS",
        "command": command,
        "complete": False,
        "missing_fields": missing_fields,
        "missing_one_of": missing_one_of,
        "clarification": {
            "outcome": "REQUIRES_CLARIFICATION",
            "missing_fields": missing_fields,
            "missing_one_of": missing_one_of,
            "question": question,
        },
    }

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "Bash",
            "tool_use_id": "merchant-completeness-check",
            "tool_response": {
                "stdout": json.dumps(
                    result
                ),
                "stderr": "",
            },
        }
    ) == 0

    return result


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
    """Corrupted duplicate active ownership must still fail closed.

    Normal allocation can no longer create this state. Construct it
    directly to simulate stale state, legacy state, or disk corruption.
    """

    pane_session_id = "merchant-pane-session"

    for lead_session_id in (
        "lead-session-a",
        "lead-session-b",
    ):
        state = new_team_state()

        state[
            "session_id"
        ] = lead_session_id

        record = init_teammate_record(
            "merchant-manager",
            "merchant-manager",
        )

        record["status"] = (
            TeammateLifecycleStatus.RUNNING.value
        )

        record["current_run_id"] = (
            f"run-{lead_session_id}"
        )

        record["current_task_id"] = (
            f"task-{lead_session_id}"
        )

        record[
            "authorized_operations"
        ] = [
            "merchant_read",
        ]

        record[
            "authorized_selected_agents"
        ] = [
            "merchant-manager",
        ]

        state["teammates"][
            "merchant-manager"
        ] = record

        save_team_state(
            lead_session_id,
            state,
        )

    (
        owner_session_id,
        owner_record,
        resolution,
    ) = find_unique_active_teammate_owner(
        "merchant-manager"
    )

    assert owner_session_id is None
    assert owner_record is None
    assert resolution == "AMBIGUOUS"

    exit_code = run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
        }
    )

    assert exit_code == 2

    # Fail closed: neither conflicting owner is mutated/released.
    for lead_session_id in (
        "lead-session-a",
        "lead-session-b",
    ):
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
            == TeammateLifecycleStatus.RUNNING.value
        )

        assert (
            record["result_received"]
            is False
        )

    # Pane must not manufacture its own owner state.
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

    # Simulate a completed old lifecycle using isolated test state.
    # Do not bypass production release validation.
    from team_lifecycle import locked_team_state

    with locked_team_state(lead_session_id) as state:
        assert state is not None
        record = state["teammates"][teammate_name]
        assert record["current_run_id"] == "run-old"
        assert record["current_task_id"] == "task-old"

        record["status"] = TeammateLifecycleStatus.IDLE_REUSABLE.value
        record["last_completed_task_id"] = "task-old"
        record["current_task_id"] = None
        record["current_run_id"] = None
        record["authorized_operations"] = []
        record["authorized_selected_agents"] = []

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


def test_tmux_merchant_clarification_is_terminal_without_write(
    isolated_runtime,
):
    """A clarification result is terminal even when merchant_execute was authorized.

    Authorization permits the teammate to attempt a write. It does not mean
    that every task outcome must contain a write.

    REQUIRES_CLARIFICATION for a task with no write footprint must:
    - accept the already-delivered SendMessage;
    - match exact CLI completeness evidence;
    - record a run/task-bound no-write terminal marker;
    - release the teammate to IDLE_REUSABLE;
    - consume the pending SendMessage receipt.
    """

    lead_session_id = "lead-merchant-clarification"
    pane_session_id = "merchant-pane-clarification"
    run_id = "run-merchant-clarification"
    task_id = "task-merchant-clarification"

    save_state(
        lead_session_id,
        new_state(
            request=(
                "add project appendix 16 to merchant CGV"
            ),
            task_class="small_task",
            risk_level="read_only",
            selected_agents=[
                "merchant-manager",
            ],
            operations=[
                "merchant_execute",
            ],
            limits={
                "max_members": 1,
                "max_total_tool_calls": 10,
            },
            confirmed=False,
            run_id=run_id,
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

    assert teammate_name == "merchant-manager"

    assert mark_teammate_running(
        lead_session_id,
        teammate_name,
        run_id,
        task_id,
        operations=[
            "merchant_execute",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    clarification_result = {
        "contract_version": 1,
        "outcome": "REQUIRES_CLARIFICATION",
        "operation": "merchant_execute",
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

    # -------------------------------------------------
    # Gate 12C:
    # deterministic completeness evidence must exist
    # BEFORE the teammate sends TEAM_RESULT_JSON.
    # -------------------------------------------------

    stage_incomplete_merchant_completeness(
        pane_session_id,
        command="document revision-create",
        missing_fields=[
            "project_id",
            "document_type",
            "content_hash",
        ],
        question=(
            "Please provide project_id, "
            "document_type, and content_hash."
        ),
    )

    # -------------------------------------------------
    # 1. Teammate successfully delivers clarification.
    # -------------------------------------------------

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "SendMessage",
            "tool_use_id": "merchant-clarification-send-1",
            "tool_input": {
                "recipient": "team-lead",
                "message": (
                    "Merchant task requires clarification.\n"
                    "TEAM_RESULT_JSON:\n"
                    + json.dumps(
                        clarification_result
                    )
                ),
            },
        }
    ) == 0

    pending_result = load_pending_result(
        pane_session_id
    )

    assert pending_result is not None

    # SendMessage alone does not complete a Direct EXECUTE task.
    assert (
        load_team_state(lead_session_id)["teammates"][
            "merchant-manager"
        ]["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )

    # -------------------------------------------------
    # 2. Authenticated TeammateIdle must accept it.
    # -------------------------------------------------

    assert run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
        }
    ) == 0

    # -------------------------------------------------
    # 3. Clarification is terminal for this task.
    # -------------------------------------------------

    team_state = load_team_state(
        lead_session_id
    )

    record = team_state[
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

    assert record["result_received"] is True
    assert record["report_source"] == "sendmessage"

    assert record["current_run_id"] is None
    assert record["current_task_id"] is None

    assert (
        record["last_completed_task_id"]
        == task_id
    )

    # Delivery evidence was consumed exactly once.
    assert (
        load_pending_result(
            pane_session_id
        )
        is None
    )

    # No write was invented, and the task-bound marker is spent.
    assert "direct_writes" not in record
    assert "direct_completion_receipt" not in record
    assert "direct_no_write_terminal" not in record


def test_tmux_malformed_merchant_result_blocks_only_once_then_fails_terminally(
    isolated_runtime,
):
    """Repeated idle after the same invalid Merchant result must not loop.

    One bounded recovery request is allowed. If the same task still reaches
    TeammateIdle without a valid structured outcome, orchestration must stop
    feeding the teammate another LLM turn.

    The teammate is marked FAILED rather than being released as successfully
    reusable, because no trustworthy terminal task outcome was established.
    """

    lead_session_id = "lead-bounded-recovery"
    pane_session_id = "pane-bounded-recovery"
    run_id = "run-bounded-recovery"
    task_id = "task-bounded-recovery"

    save_state(
        lead_session_id,
        new_state(
            request=(
                "add Appendix 16 to merchant CGV"
            ),
            task_class="small_task",
            risk_level="read_only",
            selected_agents=[
                "merchant-manager",
            ],
            operations=[
                "merchant_execute",
            ],
            limits={
                "max_members": 1,
                "max_tool_rounds": 1,
                "max_total_tool_calls": 10,
                "max_run_budget_usd": 1.0,
            },
            confirmed=False,
            run_id=run_id,
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
        run_id,
        task_id,
        operations=[
            "merchant_execute",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    # -------------------------------------------------
    # Transport succeeds, but the model violates the
    # structured Gate 12A result contract.
    #
    # This mirrors the live failure class:
    # clarification prose arrives, but no trustworthy
    # TEAM_RESULT_JSON outcome is available.
    # -------------------------------------------------

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "SendMessage",
            "tool_use_id": "malformed-clarification-send",
            "tool_input": {
                "recipient": "team-lead",
                "message": (
                    "Merchant CGV resolved successfully, "
                    "but no project was found. "
                    "Which project should receive Appendix 16?"
                ),
            },
        }
    ) == 0

    assert (
        load_pending_result(
            pane_session_id
        )
        is not None
    )

    idle_event = {
        "hook_event_name": "TeammateIdle",
        "session_id": pane_session_id,
        "agent_type": "merchant-manager",
        "teammate_name": "merchant-manager",
    }

    # -------------------------------------------------
    # First invalid completion:
    # one bounded recovery opportunity is allowed.
    # -------------------------------------------------

    assert run_hook(
        idle_event
    ) == 2

    state = load_team_state(
        lead_session_id
    )

    record = state[
        "teammates"
    ][
        "merchant-manager"
    ]

    # A malformed Direct EXECUTE result is never recorded as a
    # trusted report; the correction turn stays bound to the task.
    assert (
        record["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )
    assert record["result_received"] is False
    assert record["terminal_recovery_sent"] is True

    # -------------------------------------------------
    # Second identical idle attempt:
    #
    # MUST NOT create another teammate turn.
    # This is the exact infinite-loop breaker.
    # -------------------------------------------------

    assert run_hook(
        idle_event
    ) == 0

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
        == TeammateLifecycleStatus.FAILED.value
    )

    assert record["current_run_id"] is None
    assert record["current_task_id"] is None

    # Nothing may invent write or no-write terminal evidence.
    assert "direct_writes" not in record
    assert "direct_no_write_terminal" not in record
    assert load_pending_result(pane_session_id) is None


def test_tmux_invalid_merchant_result_can_recover_with_valid_clarification(
    isolated_runtime,
):
    """One terminal-contract repair may recover to IDLE_REUSABLE."""

    lead_session_id = "lead-terminal-recovery-success"
    pane_session_id = "pane-terminal-recovery-success"
    run_id = "run-terminal-recovery-success"
    task_id = "task-terminal-recovery-success"

    save_state(
        lead_session_id,
        new_state(
            request=(
                "add Appendix 16 to merchant CGV"
            ),
            task_class="small_task",
            risk_level="read_only",
            selected_agents=[
                "merchant-manager",
            ],
            operations=[
                "merchant_execute",
            ],
            limits={
                "max_members": 1,
                "max_tool_rounds": 1,
                "max_total_tool_calls": 10,
                "max_run_budget_usd": 1.0,
            },
            confirmed=False,
            run_id=run_id,
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
        run_id,
        task_id,
        operations=[
            "merchant_execute",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    # -------------------------------------------------
    # First delivery reaches the lead, but violates the
    # structured terminal-result contract.
    # -------------------------------------------------

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "SendMessage",
            "tool_use_id": "invalid-terminal-send",
            "tool_input": {
                "recipient": "team-lead",
                "message": (
                    "Merchant CGV resolved, but no project "
                    "was found. Which project should receive "
                    "Appendix 16?"
                ),
            },
        }
    ) == 0

    idle_event = {
        "hook_event_name": "TeammateIdle",
        "session_id": pane_session_id,
        "agent_type": "merchant-manager",
        "teammate_name": "merchant-manager",
    }

    # Exactly one repair turn is granted.
    assert run_hook(
        idle_event
    ) == 2

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
        == TeammateLifecycleStatus.RUNNING.value
    )

    assert (
        record["terminal_recovery_sent"]
        is True
    )

    # -------------------------------------------------
    # Same task now sends the corrected structured
    # outcome. No work is repeated and no write is
    # invented.
    # -------------------------------------------------

    corrected_result = {
        "contract_version": 1,
        "outcome": "REQUIRES_CLARIFICATION",
        "operation": "merchant_execute",
        "database_target": "runtime",
        "proposal_emitted": False,
        "missing_fields": [
            "project_id",
        ],
        "missing_one_of": [],
        "question": (
            "Please provide project_id."
        ),
    }

    stage_incomplete_merchant_completeness(
        pane_session_id,
        command="document revision-create",
        missing_fields=[
            "project_id",
        ],
        question=(
            "Please provide project_id."
        ),
    )

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "SendMessage",
            "tool_use_id": "corrected-terminal-send",
            "tool_input": {
                "recipient": "team-lead",
                "message": (
                    "Merchant clarification result.\n"
                    "TEAM_RESULT_JSON:\n"
                    + json.dumps(
                        corrected_result
                    )
                ),
            },
        }
    ) == 0

    # Corrected terminal result now reconciles normally.
    assert run_hook(
        idle_event
    ) == 0

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
        == TeammateLifecycleStatus.IDLE_REUSABLE.value
    )

    assert record["result_received"] is True
    assert record["report_source"] == "sendmessage"

    assert record["current_run_id"] is None
    assert record["current_task_id"] is None

    assert (
        record["last_completed_task_id"]
        == task_id
    )

    assert (
        load_pending_result(
            pane_session_id
        )
        is None
    )

    assert "direct_writes" not in record
    assert "direct_no_write_terminal" not in record


def test_tmux_repeated_idle_after_valid_clarification_is_idempotent(
    isolated_runtime,
):
    """Repeated TeammateIdle after successful reconciliation is a no-op."""

    lead_session_id = "lead-repeated-idle"
    pane_session_id = "pane-repeated-idle"
    run_id = "run-repeated-idle"
    task_id = "task-repeated-idle"

    save_state(
        lead_session_id,
        new_state(
            request=(
                "add Appendix 16 to merchant CGV"
            ),
            task_class="small_task",
            risk_level="read_only",
            selected_agents=[
                "merchant-manager",
            ],
            operations=[
                "merchant_execute",
            ],
            limits={
                "max_members": 1,
                "max_tool_rounds": 1,
                "max_total_tool_calls": 10,
                "max_run_budget_usd": 1.0,
            },
            confirmed=False,
            run_id=run_id,
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
        run_id,
        task_id,
        operations=[
            "merchant_execute",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    clarification_result = {
        "contract_version": 1,
        "outcome": "REQUIRES_CLARIFICATION",
        "operation": "merchant_execute",
        "database_target": "runtime",
        "proposal_emitted": False,
        "missing_fields": [
            "project_id",
        ],
        "missing_one_of": [],
        "question": (
            "Please provide project_id."
        ),
    }

    stage_incomplete_merchant_completeness(
        pane_session_id,
        command="document revision-create",
        missing_fields=[
            "project_id",
        ],
        question=(
            "Please provide project_id."
        ),
    )

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane_session_id,
            "agent_type": "merchant-manager",
            "tool_name": "SendMessage",
            "tool_use_id": "valid-clarification-send",
            "tool_input": {
                "recipient": "team-lead",
                "message": (
                    "Merchant clarification result.\n"
                    "TEAM_RESULT_JSON:\n"
                    + json.dumps(
                        clarification_result
                    )
                ),
            },
        }
    ) == 0

    idle_event = {
        "hook_event_name": "TeammateIdle",
        "session_id": pane_session_id,
        "agent_type": "merchant-manager",
        "teammate_name": "merchant-manager",
    }

    # First idle performs the actual reconciliation.
    assert run_hook(
        idle_event
    ) == 0

    state = load_team_state(
        lead_session_id
    )

    first_record = dict(
        state[
            "teammates"
        ][
            "merchant-manager"
        ]
    )

    assert (
        first_record["status"]
        == TeammateLifecycleStatus.IDLE_REUSABLE.value
    )

    assert first_record["result_received"] is True
    assert first_record["report_source"] == "sendmessage"

    assert first_record["current_run_id"] is None
    assert first_record["current_task_id"] is None

    assert (
        first_record["last_completed_task_id"]
        == task_id
    )

    assert (
        load_pending_result(
            pane_session_id
        )
        is None
    )

    # -------------------------------------------------
    # Harness may emit duplicate/repeated idle events.
    # They must never create another model turn or
    # mutate the completed lifecycle.
    # -------------------------------------------------

    assert run_hook(
        idle_event
    ) == 0

    assert run_hook(
        idle_event
    ) == 0

    state = load_team_state(
        lead_session_id
    )

    final_record = state[
        "teammates"
    ][
        "merchant-manager"
    ]

    assert (
        final_record["status"]
        == TeammateLifecycleStatus.IDLE_REUSABLE.value
    )

    assert (
        final_record["last_completed_task_id"]
        == task_id
    )

    assert final_record["current_run_id"] is None
    assert final_record["current_task_id"] is None

    assert final_record["result_received"] is True
    assert final_record["report_source"] == "sendmessage"

    assert (
        load_pending_result(
            pane_session_id
        )
        is None
    )

    # Repeated idle never re-establishes no-write evidence.
    assert "direct_no_write_terminal" not in final_record


def test_second_lead_cannot_allocate_same_active_teammate(
    isolated_runtime,
):
    """One canonical teammate may have only one active lead owner."""

    lead_a = "lead-global-owner-a"
    lead_b = "lead-global-owner-b"

    run_a = "run-global-owner-a"
    task_a = "task-global-owner-a"

    # Lead A acquires merchant-manager.
    decision_a, teammate_a = allocate_teammate(
        lead_a,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision_a
        == TeammateAllocationDecision.CREATE
    )

    assert teammate_a == "merchant-manager"

    assert mark_teammate_running(
        lead_a,
        teammate_a,
        run_a,
        task_a,
        operations=[
            "merchant_read",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    state_a = load_team_state(
        lead_a
    )

    assert (
        state_a["teammates"]
        ["merchant-manager"]
        ["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )

    # -------------------------------------------------
    # A second lead session attempts to allocate the
    # same canonical teammate while lead A still owns it.
    #
    # It MUST NOT create another active owner.
    # -------------------------------------------------

    decision_b, teammate_b = allocate_teammate(
        lead_b,
        "merchant-manager",
        "merchant-manager",
    )

    assert teammate_b == "merchant-manager"

    assert (
        decision_b
        == TeammateAllocationDecision.BUSY
    )

    # Lead B must not acquire an active teammate record.
    state_b = load_team_state(
        lead_b
    )

    if state_b is not None:
        record_b = (
            state_b.get(
                "teammates",
                {},
            ).get(
                "merchant-manager"
            )
        )

        assert record_b is None


def test_tmux_second_active_owner_is_blocked_before_ambiguity(
    isolated_runtime,
):
    lead_a = "lead-owner-a"
    lead_b = "lead-owner-b"

    decision_a, teammate_a = allocate_teammate(
        lead_a,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision_a
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_a,
        teammate_a,
        "run-owner-a",
        "task-owner-a",
        operations=[
            "merchant_read",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    decision_b, teammate_b = allocate_teammate(
        lead_b,
        "merchant-manager",
        "merchant-manager",
    )

    assert teammate_b == "merchant-manager"

    assert (
        decision_b
        == TeammateAllocationDecision.BUSY
    )

    (
        owner_session_id,
        owner_record,
        resolution,
    ) = find_unique_active_teammate_owner(
        "merchant-manager"
    )

    assert resolution == "FOUND"
    assert owner_session_id == lead_a

    assert (
        owner_record["current_run_id"]
        == "run-owner-a"
    )

    assert (
        owner_record["current_task_id"]
        == "task-owner-a"
    )


def test_stale_global_owner_is_failed_and_new_session_can_allocate(
    isolated_runtime,
):
    """An abandoned old owner must not block the canonical teammate forever."""

    stale_lead = "lead-stale-owner"
    new_lead = "lead-new-owner"

    # Simulate legacy/crashed team state directly.
    stale_state = new_team_state()

    stale_state[
        "session_id"
    ] = stale_lead

    stale_record = init_teammate_record(
        "merchant-manager",
        "merchant-manager",
    )

    stale_record["status"] = (
        TeammateLifecycleStatus.RUNNING.value
    )

    stale_record[
        "current_run_id"
    ] = "run-stale"

    stale_record[
        "current_task_id"
    ] = "task-stale"

    stale_record[
        "authorized_operations"
    ] = [
        "merchant_read",
    ]

    stale_record[
        "authorized_selected_agents"
    ] = [
        "merchant-manager",
    ]

    # Older than the intended one-hour stale-owner lease.
    stale_record[
        "last_transition_at"
    ] = (
        time.time()
        - 7200
    )

    stale_state[
        "teammates"
    ][
        "merchant-manager"
    ] = stale_record

    save_team_state(
        stale_lead,
        stale_state,
    )

    # Deliberately DO NOT create run state for stale_lead.
    # This models a crashed/abandoned session whose run document
    # is no longer available.

    decision, teammate_name = allocate_teammate(
        new_lead,
        "merchant-manager",
        "merchant-manager",
    )

    assert teammate_name == "merchant-manager"

    # Desired Gate 12B.5 behavior:
    # stale ownership is reconciled before new allocation.
    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    old_state = load_team_state(
        stale_lead
    )

    old_record = old_state[
        "teammates"
    ][
        "merchant-manager"
    ]

    assert (
        old_record["status"]
        == TeammateLifecycleStatus.FAILED.value
    )

    assert (
        old_record["failure_reason"]
        == "STALE_GLOBAL_OWNER"
    )

    assert old_record["current_run_id"] is None
    assert old_record["current_task_id"] is None

    (
        owner_session_id,
        owner_record,
        resolution,
    ) = find_unique_active_teammate_owner(
        "merchant-manager"
    )

    # CREATE is a global ownership reservation, so the
    # newly-created teammate is now the unique owner.
    assert resolution == "FOUND"
    assert owner_session_id == new_lead

    assert (
        owner_record["status"]
        == TeammateLifecycleStatus.CREATED.value
    )


def test_old_owner_with_live_run_state_remains_busy(
    isolated_runtime,
):
    owner = "lead-live-old"
    challenger = "lead-challenger"

    save_state(
        owner,
        new_state(
            request="merchant proposal",
            task_class="small_task",
            risk_level="read_only",
            selected_agents=[
                "merchant-manager",
            ],
            operations=[
                "merchant_read",
            ],
            limits={
                "max_members": 1,
                "max_tool_rounds": 1,
                "max_total_tool_calls": 10,
                "max_run_budget_usd": 1.0,
            },
            confirmed=False,
            run_id="run-live-old",
        ),
    )

    decision, teammate = allocate_teammate(
        owner,
        "merchant-manager",
        "merchant-manager",
    )

    assert decision == TeammateAllocationDecision.CREATE

    assert mark_teammate_running(
        owner,
        teammate,
        "run-live-old",
        "task-live-old",
        operations=[
            "merchant_read",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    # Artificially age only the team lifecycle record.
    state = load_team_state(
        owner
    )

    state["teammates"][
        "merchant-manager"
    ][
        "last_transition_at"
    ] = (
        time.time()
        - 7200
    )

    save_team_state(
        owner,
        state,
    )

    decision, _ = allocate_teammate(
        challenger,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision
        == TeammateAllocationDecision.BUSY
    )

    state = load_team_state(
        owner
    )

    assert (
        state["teammates"]
        ["merchant-manager"]
        ["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )


def test_recent_owner_without_run_state_is_not_reclaimed(
    isolated_runtime,
):
    owner = "lead-recent-owner"
    challenger = "lead-recent-challenger"

    state = new_team_state()
    state["session_id"] = owner

    record = init_teammate_record(
        "merchant-manager",
        "merchant-manager",
    )

    record["status"] = (
        TeammateLifecycleStatus.RUNNING.value
    )

    record["current_run_id"] = "run-recent"
    record["current_task_id"] = "task-recent"

    record[
        "authorized_operations"
    ] = [
        "merchant_read",
    ]

    record[
        "authorized_selected_agents"
    ] = [
        "merchant-manager",
    ]

    # Fresh lifecycle evidence.
    record[
        "last_transition_at"
    ] = time.time()

    state["teammates"][
        "merchant-manager"
    ] = record

    save_team_state(
        owner,
        state,
    )

    # No run state, but owner is too recent to reclaim.
    decision, _ = allocate_teammate(
        challenger,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision
        == TeammateAllocationDecision.BUSY
    )


def test_stale_owner_with_different_current_run_is_reclaimed(
    isolated_runtime,
):
    """An expired teammate bound to an older run must not block a newer run."""

    old_owner = "lead-run-mismatch"
    challenger = "lead-after-run-mismatch"

    old_run_id = "run-old"
    current_run_id = "run-current"

    # -------------------------------------------------
    # Old abandoned team ownership.
    # -------------------------------------------------

    team_state = new_team_state()
    team_state["session_id"] = old_owner

    record = init_teammate_record(
        "merchant-manager",
        "merchant-manager",
    )

    record["status"] = (
        TeammateLifecycleStatus.RUNNING.value
    )

    record["current_run_id"] = old_run_id
    record["current_task_id"] = "task-old"

    record[
        "authorized_operations"
    ] = [
        "merchant_read",
    ]

    record[
        "authorized_selected_agents"
    ] = [
        "merchant-manager",
    ]

    record[
        "last_transition_at"
    ] = (
        time.time()
        - 7200
    )

    team_state[
        "teammates"
    ][
        "merchant-manager"
    ] = record

    save_team_state(
        old_owner,
        team_state,
    )

    # -------------------------------------------------
    # The same lead session now has a DIFFERENT current
    # run. Therefore the old teammate record cannot be
    # proof of ownership for this current run.
    # -------------------------------------------------

    save_state(
        old_owner,
        new_state(
            request="new unrelated run",
            task_class="small_task",
            risk_level="read_only",
            selected_agents=[
                "reviewer",
            ],
            operations=[
                "review",
            ],
            limits={
                "max_members": 1,
                "max_tool_rounds": 1,
                "max_total_tool_calls": 10,
                "max_run_budget_usd": 1.0,
            },
            confirmed=False,
            run_id=current_run_id,
        ),
    )

    decision, teammate_name = allocate_teammate(
        challenger,
        "merchant-manager",
        "merchant-manager",
    )

    assert teammate_name == "merchant-manager"

    # Desired behavior:
    # current run-state does not validate old_run_id ownership.
    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    stale_state = load_team_state(
        old_owner
    )

    stale_record = stale_state[
        "teammates"
    ][
        "merchant-manager"
    ]

    assert (
        stale_record["status"]
        == TeammateLifecycleStatus.FAILED.value
    )

    assert (
        stale_record["failure_reason"]
        == "STALE_GLOBAL_OWNER"
    )

    assert stale_record["current_run_id"] is None
    assert stale_record["current_task_id"] is None


def test_stale_owner_with_malformed_run_state_remains_busy(
    isolated_runtime,
):
    owner = "lead-malformed-run"
    challenger = "lead-malformed-challenger"

    team_state = new_team_state()
    team_state["session_id"] = owner

    record = init_teammate_record(
        "merchant-manager",
        "merchant-manager",
    )

    record["status"] = (
        TeammateLifecycleStatus.RUNNING.value
    )

    record["current_run_id"] = "run-old"
    record["current_task_id"] = "task-old"

    record[
        "last_transition_at"
    ] = (
        time.time()
        - 7200
    )

    record[
        "authorized_operations"
    ] = [
        "merchant_read",
    ]

    record[
        "authorized_selected_agents"
    ] = [
        "merchant-manager",
    ]

    team_state[
        "teammates"
    ][
        "merchant-manager"
    ] = record

    save_team_state(
        owner,
        team_state,
    )

    # Existing but malformed run-state:
    # no trustworthy run_id.
    save_state(
        owner,
        {
            "request": "malformed",
            "selected_agents": [],
            "operations": [],
            "limits": {},
        },
    )

    decision, _ = allocate_teammate(
        challenger,
        "merchant-manager",
        "merchant-manager",
    )

    assert (
        decision
        == TeammateAllocationDecision.BUSY
    )

    state = load_team_state(
        owner
    )

    assert (
        state["teammates"]
        ["merchant-manager"]
        ["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )


def test_lifecycle_transitions_refresh_last_transition_at(
    isolated_runtime,
    monkeypatch,
):
    """Lifecycle transitions must refresh the owner lease timestamp."""

    import team_lifecycle

    session_id = "lead-transition-timestamps"
    teammate_name = "merchant-manager"
    run_id = "run-transition-timestamps"
    task_id = "task-transition-timestamps"

    clock = iter(
        [
            1000.0,  # init teammate
            1100.0,  # mark running
            1200.0,  # report received
            1300.0,  # release idle
        ]
    )

    monkeypatch.setattr(
        team_lifecycle.time,
        "time",
        lambda: next(clock),
    )

    decision, teammate = allocate_teammate(
        session_id,
        "merchant-manager",
        teammate_name,
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    state = load_team_state(
        session_id
    )

    created_at = state[
        "teammates"
    ][
        teammate_name
    ][
        "last_transition_at"
    ]

    assert created_at == 1000.0

    assert mark_teammate_running(
        session_id,
        teammate,
        run_id,
        task_id,
        operations=[
            "merchant_read",
        ],
        selected_agents=[
            "merchant-manager",
        ],
    )

    state = load_team_state(
        session_id
    )

    running_at = state[
        "teammates"
    ][
        teammate_name
    ][
        "last_transition_at"
    ]

    assert running_at == 1100.0
    assert running_at > created_at

    assert team_lifecycle.mark_bound_report_received(
        session_id,
        teammate_name,
        run_id,
        task_id,
        "sendmessage",
    )

    state = load_team_state(
        session_id
    )

    reported_at = state[
        "teammates"
    ][
        teammate_name
    ][
        "last_transition_at"
    ]

    assert reported_at == 1200.0
    assert reported_at > running_at

    released, prior_status = (
        team_lifecycle.release_reported_teammate_to_idle(
            session_id,
            teammate_name,
        )
    )

    assert released is True

    assert (
        prior_status
        == TeammateLifecycleStatus.REPORT_RECEIVED.value
    )

    state = load_team_state(
        session_id
    )

    record = state[
        "teammates"
    ][
        teammate_name
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus.IDLE_REUSABLE.value
    )

    assert (
        record["last_transition_at"]
        == 1300.0
    )


# E2E-03: Isolated Merchant Manager terminal lifecycle regressions.

def _e2e03_setup_merchant_run(operation, suffix):
    owner = f"e2e03-owner-{suffix}"
    pane = f"e2e03-pane-{suffix}"
    run_id = f"e2e03-run-{suffix}"
    task_id = f"e2e03-task-{suffix}"

    save_state(
        owner,
        new_state(
            request="GALAXY merchant lifecycle validation",
            task_class="small_task",
            risk_level="read_only",
            selected_agents=["merchant-manager"],
            operations=[operation],
            limits={
                "max_members": 1,
                "max_tool_rounds": 3,
                "max_total_tool_calls": 24,
                "max_run_budget_usd": 4.0,
            },
            confirmed=False,
            run_id=run_id,
        ),
    )

    decision, name = allocate_teammate(
        owner, "merchant-manager", "merchant-manager"
    )
    assert decision == TeammateAllocationDecision.CREATE
    assert name == "merchant-manager"

    assert mark_teammate_running(
        owner,
        name,
        run_id,
        task_id,
        operations=[operation],
        selected_agents=["merchant-manager"],
    )

    return owner, pane, task_id


def _e2e03_send(pane, message):
    return run_hook({
        "hook_event_name": "PostToolUse",
        "session_id": pane,
        "agent_type": "merchant-manager",
        "tool_name": "SendMessage",
        "tool_use_id": "e2e03-terminal-message",
        "tool_input": {
            "recipient": "team-lead",
            "message": message,
        },
    })


def _e2e03_idle(pane):
    return run_hook({
        "hook_event_name": "TeammateIdle",
        "session_id": pane,
        "agent_type": "merchant-manager",
        "teammate_name": "merchant-manager",
    })


def test_e2e03_galaxy_read_only_report_releases(isolated_runtime):
    owner, pane, task_id = _e2e03_setup_merchant_run(
        "merchant_read", "galaxy-read"
    )

    assert _e2e03_send(
        pane,
        "GALAXY integration readiness: NOT_VERIFIABLE. "
        "No merchant changes were performed.",
    ) == 0

    assert _e2e03_idle(pane) == 0

    record = load_team_state(owner)["teammates"]["merchant-manager"]
    assert record["status"] == "IDLE_REUSABLE"
    assert record["result_received"] is True
    assert record["report_source"] == "sendmessage"
    assert record["last_completed_task_id"] == task_id
    assert record["current_run_id"] is None
    assert record["current_task_id"] is None
    assert load_pending_result(pane) is None
