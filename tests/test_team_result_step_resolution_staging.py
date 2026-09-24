from __future__ import annotations

import json

import pytest

from claude.hooks import (
    team_result_hook,
)


MERCHANT_A = (
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
)

MERCHANT_B = (
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
)

PROJECT_A = (
    "11111111-1111-4111-8111-111111111111"
)

PROJECT_B = (
    "22222222-2222-4222-8222-222222222222"
)

STEP_A = (
    "33333333-3333-4333-8333-333333333333"
)

STEP_B = (
    "44444444-4444-4444-8444-444444444444"
)

TEMPLATE_A = (
    "55555555-5555-4555-8555-555555555555"
)

TEMPLATE_B = (
    "66666666-6666-4666-8666-666666666666"
)

PANE = "pane-step-resolution"
OWNER = "lead-step-resolution"
TEAMMATE = "merchant-manager"
RUN_ID = "run-step-resolution"
TASK_ID = "task-step-resolution"


def _candidate(
    step_id: str = STEP_A,
    *,
    project_id: str = PROJECT_A,
    template_step_id: str = TEMPLATE_A,
    step_name: str = "Run UAT test",
    branch_key: str | None = "uat_branch",
    sequence_number: int = 20,
):
    return {
        "step_id": step_id,
        "project_id": project_id,
        "template_step_id": (
            template_step_id
        ),
        "branch_key": branch_key,
        "step_name": step_name,
        "step_type": "PARALLEL_BRANCH",
        "status": "READY",
        "sequence_number": (
            sequence_number
        ),
        "version": 1,
        "condition_key": None,
        "is_optional": False,
    }


def _resolved_step(
    *,
    query: str = "Run UAT test",
    project_id: str = PROJECT_A,
):
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": query,
        "project_id": project_id,
        "status": "RESOLVED",
        "match_kind": "STEP_NAME",
        "resolved": True,
        "step_id": STEP_A,
        "template_step_id": TEMPLATE_A,
        "branch_key": "uat_branch",
        "step_name": "Run UAT test",
        "step_type": "PARALLEL_BRANCH",
        "step_status": "READY",
        "sequence_number": 20,
        "version": 1,
        "condition_key": None,
        "is_optional": False,
        "candidates": [
            _candidate(
                project_id=project_id
            ),
        ],
    }


def _ambiguous_step():
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": "Review",
        "project_id": PROJECT_A,
        "status": "AMBIGUOUS",
        "match_kind": "STEP_NAME",
        "resolved": False,
        "step_id": None,
        "template_step_id": None,
        "branch_key": None,
        "step_name": None,
        "step_type": None,
        "step_status": None,
        "sequence_number": None,
        "version": None,
        "condition_key": None,
        "is_optional": None,
        "candidates": [
            _candidate(
                STEP_A,
                step_name="Review",
                sequence_number=10,
            ),
            _candidate(
                STEP_B,
                template_step_id=TEMPLATE_B,
                step_name="Review",
                branch_key="production_branch",
                sequence_number=20,
            ),
        ],
    }


def _not_found_step():
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": "Unknown Step",
        "project_id": PROJECT_A,
        "status": "NOT_FOUND",
        "match_kind": "NONE",
        "resolved": False,
        "step_id": None,
        "template_step_id": None,
        "branch_key": None,
        "step_name": None,
        "step_type": None,
        "step_status": None,
        "sequence_number": None,
        "version": None,
        "condition_key": None,
        "is_optional": None,
        "candidates": [],
    }


def _merchant_receipt(
    *,
    merchant_id: str = MERCHANT_A,
    status: str = "RESOLVED",
):
    return {
        "resolution": {
            "status": status,
            "resolved": (
                status
                == "RESOLVED"
            ),
            "merchant_id": (
                merchant_id
                if status
                == "RESOLVED"
                else None
            ),
        },
    }


def _project_receipt(
    *,
    project_id: str = PROJECT_A,
    merchant_id: str = MERCHANT_A,
    status: str = "RESOLVED",
):
    return {
        "merchant_id": merchant_id,
        "resolution": {
            "status": status,
            "resolved": (
                status
                == "RESOLVED"
            ),
            "merchant_id": merchant_id,
            "project_id": (
                project_id
                if status
                == "RESOLVED"
                else None
            ),
        },
    }


def _command(
    *,
    project_id: str = PROJECT_A,
    query: str = "Run UAT test",
):
    return (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "step resolve "
        f'--project-id "{project_id}" '
        f'--query "{query}"'
    )


def _payload(
    *,
    command: str | None = None,
    result: dict | None = None,
    stdout: str | None = None,
    tool_use_id: str = "tool-step-resolve",
):
    if command is None:
        command = _command()

    if stdout is None:
        stdout = json.dumps(
            _resolved_step()
            if result is None
            else result
        )

    return {
        "hook_event_name": "PostToolUse",
        "session_id": PANE,
        "agent_type": TEAMMATE,
        "tool_name": "Bash",
        "tool_use_id": tool_use_id,
        "tool_input": {
            "command": command,
        },
        "tool_response": {
            "stdout": stdout,
        },
    }


def _install_parents(
    monkeypatch,
    *,
    merchant_receipt=None,
    project_receipt=None,
    merchant_matches=True,
    project_matches=True,
):
    if merchant_receipt is None:
        merchant_receipt = (
            _merchant_receipt()
        )

    if project_receipt is None:
        project_receipt = (
            _project_receipt()
        )

    monkeypatch.setattr(
        team_result_hook,
        "load_pending_merchant_resolution",
        lambda pane: (
            merchant_receipt
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "pending_merchant_resolution_matches",
        lambda *args, **kwargs: (
            merchant_matches
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "load_pending_project_resolution",
        lambda pane: (
            project_receipt
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "pending_project_resolution_matches",
        lambda *args, **kwargs: (
            project_matches
        ),
    )


def _capture_stage(
    monkeypatch,
):
    captured = {}

    def fake_stage(
        **kwargs,
    ):
        captured.update(
            kwargs
        )
        return True

    monkeypatch.setattr(
        team_result_hook,
        "stage_pending_step_resolution",
        fake_stage,
    )

    return captured


def _stage(
    payload,
    *,
    operations=("merchant_read",),
    teammate_name=TEAMMATE,
):
    return (
        team_result_hook
        ._stage_exact_tmux_step_resolution(
            payload=payload,
            pane_session_id=PANE,
            owner_session_id=OWNER,
            teammate_name=(
                teammate_name
            ),
            run_id=RUN_ID,
            task_id=TASK_ID,
            authorized_operations=list(
                operations
            ),
        )
    )


def test_exact_step_resolution_stages(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload()
        )
        is True
    )

    assert (
        captured[
            "merchant_id"
        ]
        == MERCHANT_A
    )

    assert (
        captured[
            "project_id"
        ]
        == PROJECT_A
    )

    assert (
        captured[
            "resolution"
        ][
            "step_id"
        ]
        == STEP_A
    )

    assert (
        captured[
            "tool_use_id"
        ]
        == "tool-step-resolve"
    )


@pytest.mark.parametrize(
    "operation",
    [
        "merchant_read",
        "merchant_propose",
        "merchant_apply",
    ],
)
def test_all_merchant_operations_stage(
    monkeypatch,
    operation,
):
    _install_parents(
        monkeypatch
    )

    _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(),
            operations=(
                operation,
            ),
        )
        is True
    )


def test_missing_merchant_receipt_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    monkeypatch.setattr(
        team_result_hook,
        "load_pending_merchant_resolution",
        lambda pane: None,
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload()
        )
        is False
    )

    assert captured == {}


def test_merchant_binding_mismatch_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch,
        merchant_matches=False,
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload()
        )
        is False
    )

    assert captured == {}


def test_unresolved_merchant_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch,
        merchant_receipt=(
            _merchant_receipt(
                status="NOT_FOUND"
            )
        ),
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload()
        )
        is False
    )

    assert captured == {}


def test_missing_project_receipt_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    monkeypatch.setattr(
        team_result_hook,
        "load_pending_project_resolution",
        lambda pane: None,
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload()
        )
        is False
    )

    assert captured == {}


def test_project_binding_mismatch_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch,
        project_matches=False,
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload()
        )
        is False
    )

    assert captured == {}


@pytest.mark.parametrize(
    "status",
    [
        "AMBIGUOUS",
        "NOT_FOUND",
    ],
)
def test_project_parent_must_be_resolved(
    monkeypatch,
    status,
):
    _install_parents(
        monkeypatch,
        project_receipt=(
            _project_receipt(
                status=status
            )
        ),
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload()
        )
        is False
    )

    assert captured == {}


def test_command_project_must_match_parent(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    payload = _payload(
        command=_command(
            project_id=PROJECT_B
        ),
        result=_resolved_step(
            project_id=PROJECT_B
        ),
    )

    assert (
        _stage(
            payload
        )
        is False
    )

    assert captured == {}


def test_output_project_must_match_parent(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(
                result=(
                    _resolved_step(
                        project_id=PROJECT_B
                    )
                )
            )
        )
        is False
    )

    assert captured == {}


def test_output_query_must_match_command(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(
                result=(
                    _resolved_step(
                        query="Different Step"
                    )
                )
            )
        )
        is False
    )

    assert captured == {}


def test_wrong_teammate_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(),
            teammate_name="reviewer",
        )
        is False
    )

    assert captured == {}


def test_wrong_operation_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(),
            operations=(
                "github_read",
            ),
        )
        is False
    )

    assert captured == {}


def test_mixed_operations_block(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(),
            operations=(
                "merchant_read",
                "merchant_propose",
            ),
        )
        is False
    )

    assert captured == {}


@pytest.mark.parametrize(
    "suffix",
    [
        " | head -10",
        " && echo done",
        " ; echo done",
        " > output.json",
    ],
)
def test_wrapped_step_resolver_blocks(
    monkeypatch,
    suffix,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(
                command=(
                    _command()
                    + suffix
                )
            )
        )
        is False
    )

    assert captured == {}


def test_extra_argument_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(
                command=(
                    _command()
                    + " --status READY"
                )
            )
        )
        is False
    )

    assert captured == {}


def test_malformed_json_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(
                stdout="{not-json"
            )
        )
        is False
    )

    assert captured == {}


def test_stdout_must_be_exact_json(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    stdout = (
        json.dumps(
            _resolved_step()
        )
        + "\nextra"
    )

    assert (
        _stage(
            _payload(
                stdout=stdout
            )
        )
        is False
    )

    assert captured == {}


def test_missing_tool_use_id_blocks(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(
                tool_use_id=""
            )
        )
        is False
    )

    assert captured == {}


def test_ambiguous_step_result_stages(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(
                command=_command(
                    query="Review"
                ),
                result=(
                    _ambiguous_step()
                ),
            )
        )
        is True
    )

    assert (
        captured[
            "resolution"
        ][
            "status"
        ]
        == "AMBIGUOUS"
    )


def test_not_found_step_result_stages(
    monkeypatch,
):
    _install_parents(
        monkeypatch
    )

    captured = _capture_stage(
        monkeypatch
    )

    assert (
        _stage(
            _payload(
                command=_command(
                    query="Unknown Step"
                ),
                result=(
                    _not_found_step()
                ),
            )
        )
        is True
    )

    assert (
        captured[
            "resolution"
        ][
            "status"
        ]
        == "NOT_FOUND"
    )


def test_handle_post_tool_use_wires_step_staging(
    monkeypatch,
):
    staged = {
        "project": 0,
        "step": 0,
    }

    monkeypatch.setattr(
        team_result_hook,
        "merchant_completeness_from_tool_response",
        lambda payload: None,
    )

    monkeypatch.setattr(
        team_result_hook,
        "merchant_resolution_from_tool_response",
        lambda payload: None,
    )

    monkeypatch.setattr(
        team_result_hook,
        "merchant_proposal_from_tool_response",
        lambda payload: None,
    )

    monkeypatch.setattr(
        team_result_hook,
        "_trusted_tmux_merchant_stage_context",
        lambda **kwargs: (
            PANE,
            OWNER,
            TEAMMATE,
            RUN_ID,
            TASK_ID,
            ["merchant_read"],
        ),
    )

    def fake_project_stage(
        **kwargs,
    ):
        staged[
            "project"
        ] += 1
        return False

    def fake_step_stage(
        **kwargs,
    ):
        staged[
            "step"
        ] += 1
        return True

    monkeypatch.setattr(
        team_result_hook,
        "_stage_exact_tmux_project_resolution",
        fake_project_stage,
    )

    monkeypatch.setattr(
        team_result_hook,
        "_stage_exact_tmux_step_resolution",
        fake_step_stage,
    )

    team_result_hook.handle_post_tool_use(
        None,
        _payload(),
        PANE,
    )

    assert staged == {
        "project": 1,
        "step": 1,
    }


def test_handle_post_tool_use_does_not_wire_entity_staging_for_non_bash(
    monkeypatch,
):
    called = {
        "context": 0,
    }

    monkeypatch.setattr(
        team_result_hook,
        "merchant_completeness_from_tool_response",
        lambda payload: None,
    )

    monkeypatch.setattr(
        team_result_hook,
        "merchant_resolution_from_tool_response",
        lambda payload: None,
    )

    monkeypatch.setattr(
        team_result_hook,
        "merchant_proposal_from_tool_response",
        lambda payload: None,
    )

    def fake_context(
        **kwargs,
    ):
        called[
            "context"
        ] += 1
        return None

    monkeypatch.setattr(
        team_result_hook,
        "_trusted_tmux_merchant_stage_context",
        fake_context,
    )

    payload = _payload()
    payload[
        "tool_name"
    ] = "Read"

    team_result_hook.handle_post_tool_use(
        None,
        payload,
        PANE,
    )

    assert called[
        "context"
    ] == 0