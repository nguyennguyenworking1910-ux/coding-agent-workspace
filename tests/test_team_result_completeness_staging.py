from __future__ import annotations

import json

from claude.hooks import (
    team_result_hook,
)

from claude.hooks.team_lifecycle import (
    TeammateAllocationDecision,
    allocate_teammate,
    mark_teammate_running,
)

from claude.hooks.tmux_merchant_completeness import (
    load_pending_merchant_completeness,
)


def completeness_result():
    return {
        "success": True,
        "mode": "COMPLETENESS",
        "command": (
            "document revision-create"
        ),
        "complete": False,
        "missing_fields": [
            "project_id",
            "document_type",
            "content_hash",
        ],
        "missing_one_of": [],
        "clarification": {
            "outcome": (
                "REQUIRES_CLARIFICATION"
            ),
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


def _start_merchant_propose(
    lead_session,
):
    teammate = "merchant-manager"
    run_id = "run-completeness"
    task_id = (
        f"{run_id}:{teammate}"
    )

    decision, name = (
        allocate_teammate(
            lead_session,
            teammate,
            teammate,
        )
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session,
        name,
        run_id,
        task_id,
        operations=[
            "merchant_propose",
        ],
        selected_agents=[
            teammate,
        ],
    )

    return (
        run_id,
        task_id,
    )


def test_post_tool_use_stages_exact_completeness_receipt(
    monkeypatch,
    tmp_path,
):
    lead_session = "lead-completeness"
    pane_session = "pane-completeness"

    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(
            tmp_path
            / "team_state"
        ),
    )

    monkeypatch.setenv(
        "CLAUDE_RUNTIME_DIR",
        str(
            tmp_path
            / "runtime"
        ),
    )

    run_id, task_id = (
        _start_merchant_propose(
            lead_session
        )
    )

    result = completeness_result()

    payload = {
        "hook_event_name": (
            "PostToolUse"
        ),
        "session_id": pane_session,
        "agent_type": (
            "merchant-manager"
        ),
        "tool_name": "Bash",
        "tool_use_id": "tool-1",
        "tool_response": {
            "stdout": json.dumps(
                result
            ),
        },
    }

    team_result_hook.handle_post_tool_use(
        None,
        payload,
        pane_session,
    )

    receipt = (
        load_pending_merchant_completeness(
            pane_session
        )
    )

    assert receipt is not None

    assert (
        receipt["owner_session_id"]
        == lead_session
    )

    assert (
        receipt["teammate_name"]
        == "merchant-manager"
    )

    assert (
        receipt["run_id"]
        == run_id
    )

    assert (
        receipt["task_id"]
        == task_id
    )

    assert (
        receipt["result"]
        == result
    )


def test_non_completeness_stdout_is_not_staged(
    monkeypatch,
    tmp_path,
):
    lead_session = "lead-invalid"
    pane_session = "pane-invalid"

    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(
            tmp_path
            / "team_state"
        ),
    )

    monkeypatch.setenv(
        "CLAUDE_RUNTIME_DIR",
        str(
            tmp_path
            / "runtime"
        ),
    )

    _start_merchant_propose(
        lead_session
    )

    payload = {
        "hook_event_name": (
            "PostToolUse"
        ),
        "session_id": pane_session,
        "agent_type": (
            "merchant-manager"
        ),
        "tool_name": "Bash",
        "tool_response": {
            "stdout": json.dumps(
                {
                    "success": True,
                    "mode": "READ",
                }
            ),
        },
    }

    team_result_hook.handle_post_tool_use(
        None,
        payload,
        pane_session,
    )

    assert (
        load_pending_merchant_completeness(
            pane_session
        )
        is None
    )


def test_non_merchant_role_cannot_stage_completeness(
    monkeypatch,
    tmp_path,
):
    lead_session = "lead-role"
    pane_session = "pane-role"

    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(
            tmp_path
            / "team_state"
        ),
    )

    monkeypatch.setenv(
        "CLAUDE_RUNTIME_DIR",
        str(
            tmp_path
            / "runtime"
        ),
    )

    _start_merchant_propose(
        lead_session
    )

    payload = {
        "hook_event_name": (
            "PostToolUse"
        ),
        "session_id": pane_session,
        "agent_type": "reviewer",
        "tool_name": "Bash",
        "tool_response": {
            "stdout": json.dumps(
                completeness_result()
            ),
        },
    }

    team_result_hook.handle_post_tool_use(
        None,
        payload,
        pane_session,
    )

    assert (
        load_pending_merchant_completeness(
            pane_session
        )
        is None
    )


def test_merchant_read_run_cannot_stage_write_completeness(
    monkeypatch,
    tmp_path,
):
    lead_session = "lead-read"
    pane_session = "pane-read"
    teammate = "merchant-manager"
    run_id = "run-read"
    task_id = (
        f"{run_id}:{teammate}"
    )

    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(
            tmp_path
            / "team_state"
        ),
    )

    monkeypatch.setenv(
        "CLAUDE_RUNTIME_DIR",
        str(
            tmp_path
            / "runtime"
        ),
    )

    decision, name = (
        allocate_teammate(
            lead_session,
            teammate,
            teammate,
        )
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session,
        name,
        run_id,
        task_id,
        operations=[
            "merchant_read",
        ],
        selected_agents=[
            teammate,
        ],
    )

    payload = {
        "hook_event_name": (
            "PostToolUse"
        ),
        "session_id": pane_session,
        "agent_type": teammate,
        "tool_name": "Bash",
        "tool_response": {
            "stdout": json.dumps(
                completeness_result()
            ),
        },
    }

    team_result_hook.handle_post_tool_use(
        None,
        payload,
        pane_session,
    )

    assert (
        load_pending_merchant_completeness(
            pane_session
        )
        is None
    )