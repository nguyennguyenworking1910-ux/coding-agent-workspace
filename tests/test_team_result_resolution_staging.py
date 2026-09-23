"""PostToolUse staging tests for exact Merchant resolver evidence."""

from __future__ import annotations

import json

import pytest

from claude.hooks import team_result_hook
from claude.hooks.tmux_merchant_resolution import (
    PENDING_MERCHANT_RESOLUTION_DIR_ENV_VAR,
    load_pending_merchant_resolution,
)


CGV_ID = (
    "2da7ab08-1eda-5ca2-b28e-f94f3e1be0d0"
)


@pytest.fixture(
    autouse=True
)
def isolated_resolution_store(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        PENDING_MERCHANT_RESOLUTION_DIR_ENV_VAR,
        str(
            tmp_path
            / "resolution"
        ),
    )


def resolved_cgv():
    return {
        "candidates": [
            {
                "code": "CGV",
                "merchant_id": CGV_ID,
                "name": "CGV",
            }
        ],
        "code": "CGV",
        "match_kind": "CODE",
        "merchant_id": CGV_ID,
        "mode": "RESOLUTION",
        "name": "CGV",
        "query": "CGV",
        "resolved": True,
        "status": "RESOLVED",
        "success": True,
    }


def payload(
    *,
    command=(
        "python "
        ".claude/agents/tools/merchant/"
        "agent_cli.py "
        "merchant resolve "
        '--query "CGV"'
    ),
    result=None,
    session_agent=True,
):
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_use_id": "resolve-tool-1",
        "agent_type": "merchant-manager",
        **(
            {
                "agent_id": "merchant-agent-id",
            }
            if session_agent
            else {}
        ),
        "tool_input": {
            "command": command,
        },
        "tool_response": {
            "stdout": json.dumps(
                (
                    resolved_cgv()
                    if result is None
                    else result
                ),
                ensure_ascii=False,
            ),
        },
    }


def owner_record():
    return {
        "current_run_id": "run-1",
        "current_task_id": "task-1",
        "authorized_operations": [
            "merchant_propose",
        ],
        "authorized_selected_agents": [
            "merchant-manager",
        ],
    }


def test_exact_resolution_stdout_is_parsed():
    result = (
        team_result_hook
        .merchant_resolution_from_tool_response(
            payload()
        )
    )

    assert result == resolved_cgv()


def test_prose_wrapped_json_is_rejected():
    candidate = payload()

    candidate[
        "tool_response"
    ][
        "stdout"
    ] = (
        "Resolution result:\n"
        + json.dumps(
            resolved_cgv()
        )
    )

    assert (
        team_result_hook
        .merchant_resolution_from_tool_response(
            candidate
        )
        is None
    )


def test_fake_echo_command_cannot_stage_resolution():
    candidate = payload(
        command=(
            "echo "
            + json.dumps(
                resolved_cgv()
            )
        )
    )

    assert (
        team_result_hook
        .merchant_resolution_from_tool_response(
            candidate
        )
        is None
    )


def test_query_mismatch_is_rejected():
    candidate = payload(
        command=(
            "python "
            ".claude/agents/tools/merchant/"
            "agent_cli.py "
            "merchant resolve "
            '--query "LOTTE"'
        )
    )

    assert (
        team_result_hook
        .merchant_resolution_from_tool_response(
            candidate
        )
        is None
    )


@pytest.mark.parametrize(
    "pane_session_id",
    (
        "pane-1",
        "lead-1",
    ),
)
def test_exact_resolution_is_staged_for_different_or_same_session(
    monkeypatch,
    pane_session_id,
):
    monkeypatch.setattr(
        team_result_hook,
        "find_unique_active_teammate_owner",
        lambda teammate_name: (
            "lead-1",
            owner_record(),
            "FOUND",
        ),
    )

    candidate = payload()

    resolution = (
        team_result_hook
        .merchant_resolution_from_tool_response(
            candidate
        )
    )

    assert resolution is not None

    assert (
        team_result_hook
        ._stage_exact_tmux_merchant_resolution(
            candidate,
            pane_session_id,
            resolution,
        )
    )

    receipt = (
        load_pending_merchant_resolution(
            pane_session_id
        )
    )

    assert receipt is not None

    assert (
        receipt[
            "owner_session_id"
        ]
        == "lead-1"
    )

    assert (
        receipt[
            "run_id"
        ]
        == "run-1"
    )

    assert (
        receipt[
            "task_id"
        ]
        == "task-1"
    )

    assert (
        receipt[
            "resolution"
        ]
        == resolved_cgv()
    )


def test_wrong_teammate_role_cannot_stage(
    monkeypatch,
):
    monkeypatch.setattr(
        team_result_hook,
        "find_unique_active_teammate_owner",
        lambda teammate_name: (
            "lead-1",
            owner_record(),
            "FOUND",
        ),
    )

    candidate = payload()

    candidate[
        "agent_type"
    ] = "reviewer"

    resolution = resolved_cgv()

    assert not (
        team_result_hook
        ._stage_exact_tmux_merchant_resolution(
            candidate,
            "pane-1",
            resolution,
        )
    )


def test_wrong_authorized_operation_cannot_stage(
    monkeypatch,
):
    record = owner_record()

    record[
        "authorized_operations"
    ] = [
        "github_read",
    ]

    monkeypatch.setattr(
        team_result_hook,
        "find_unique_active_teammate_owner",
        lambda teammate_name: (
            "lead-1",
            record,
            "FOUND",
        ),
    )

    candidate = payload()

    assert not (
        team_result_hook
        ._stage_exact_tmux_merchant_resolution(
            candidate,
            "pane-1",
            resolved_cgv(),
        )
    )


def test_handle_post_tool_use_stages_resolution(
    monkeypatch,
):
    monkeypatch.setattr(
        team_result_hook,
        "find_unique_active_teammate_owner",
        lambda teammate_name: (
            "lead-1",
            owner_record(),
            "FOUND",
        ),
    )

    team_result_hook.handle_post_tool_use(
        None,
        payload(),
        "pane-integrated",
    )

    receipt = (
        load_pending_merchant_resolution(
            "pane-integrated"
        )
    )

    assert receipt is not None

    assert (
        receipt[
            "resolution"
        ][
            "merchant_id"
        ]
        == CGV_ID
    )


@pytest.mark.parametrize(
    "operation",
    (
        "merchant_read",
        "merchant_propose",
        "merchant_apply",
    ),
)
def test_resolution_staging_accepts_each_merchant_operation(
    monkeypatch,
    operation,
):
    record = owner_record()

    record[
        "authorized_operations"
    ] = [
        operation,
    ]

    monkeypatch.setattr(
        team_result_hook,
        "find_unique_active_teammate_owner",
        lambda teammate_name: (
            "lead-operation",
            record,
            "FOUND",
        ),
    )

    candidate = payload()

    resolution = (
        team_result_hook
        .merchant_resolution_from_tool_response(
            candidate
        )
    )

    assert resolution is not None

    assert (
        team_result_hook
        ._stage_exact_tmux_merchant_resolution(
            candidate,
            "pane-operation",
            resolution,
        )
    )

    receipt = (
        load_pending_merchant_resolution(
            "pane-operation"
        )
    )

    assert receipt is not None

    assert (
        receipt[
            "resolution"
        ][
            "merchant_id"
        ]
        == CGV_ID
    )


def test_resolution_staging_rejects_mixed_operations(
    monkeypatch,
):
    record = owner_record()

    record[
        "authorized_operations"
    ] = [
        "merchant_read",
        "merchant_propose",
    ]

    monkeypatch.setattr(
        team_result_hook,
        "find_unique_active_teammate_owner",
        lambda teammate_name: (
            "lead-mixed",
            record,
            "FOUND",
        ),
    )

    candidate = payload()

    assert not (
        team_result_hook
        ._stage_exact_tmux_merchant_resolution(
            candidate,
            "pane-mixed",
            resolved_cgv(),
        )
    )