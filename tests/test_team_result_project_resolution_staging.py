from __future__ import annotations

import json

import pytest

from claude.hooks import team_result_hook


MERCHANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MERCHANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"

PANE = "pane-project-resolution"
OWNER = "lead-project-resolution"
TEAMMATE = "merchant-manager"
RUN_ID = "run-project-resolution"
TASK_ID = "task-project-resolution"


def _resolved_project(
    *,
    query: str = "CGV Media Top Up 2026",
    merchant_id: str = MERCHANT_A,
) -> dict:
    return {
        "success": True,
        "mode": "PROJECT_RESOLUTION",
        "query": query,
        "merchant_id": merchant_id,
        "status": "RESOLVED",
        "match_kind": "TITLE",
        "resolved": True,
        "project_id": PROJECT_A,
        "title": "CGV Media Top Up 2026",
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "project_status": "PLANNED",
        "version": 1,
        "candidates": [
            {
                "project_id": PROJECT_A,
                "merchant_id": merchant_id,
                "title": "CGV Media Top Up 2026",
                "project_type": "MEDIA_TOP_UP",
                "workflow_variant": "STANDARD",
                "status": "PLANNED",
                "version": 1,
            }
        ],
    }


def _ambiguous_project() -> dict:
    return {
        "success": True,
        "mode": "PROJECT_RESOLUTION",
        "query": "Media Top Up",
        "merchant_id": MERCHANT_A,
        "status": "AMBIGUOUS",
        "match_kind": "CANDIDATE",
        "resolved": False,
        "project_id": None,
        "title": None,
        "project_type": None,
        "workflow_variant": None,
        "project_status": None,
        "version": None,
        "candidates": [
            {
                "project_id": PROJECT_A,
                "merchant_id": MERCHANT_A,
                "title": "CGV Media Top Up 2026",
                "project_type": "MEDIA_TOP_UP",
                "workflow_variant": "STANDARD",
                "status": "PLANNED",
                "version": 1,
            },
            {
                "project_id": PROJECT_B,
                "merchant_id": MERCHANT_A,
                "title": "CGV Media Top Up 2027",
                "project_type": "MEDIA_TOP_UP",
                "workflow_variant": "STANDARD",
                "status": "PLANNED",
                "version": 1,
            },
        ],
    }


def _not_found_project() -> dict:
    return {
        "success": True,
        "mode": "PROJECT_RESOLUTION",
        "query": "Unknown Project",
        "merchant_id": MERCHANT_A,
        "status": "NOT_FOUND",
        "match_kind": "NONE",
        "resolved": False,
        "project_id": None,
        "title": None,
        "project_type": None,
        "workflow_variant": None,
        "project_status": None,
        "version": None,
        "candidates": [],
    }


def _parent_receipt(
    *,
    merchant_id: str = MERCHANT_A,
    status: str = "RESOLVED",
) -> dict:
    if status == "RESOLVED":
        resolution = {
            "status": "RESOLVED",
            "resolved": True,
            "merchant_id": merchant_id,
        }
    elif status == "AMBIGUOUS":
        resolution = {
            "status": "AMBIGUOUS",
            "resolved": False,
            "merchant_id": None,
        }
    else:
        resolution = {
            "status": "NOT_FOUND",
            "resolved": False,
            "merchant_id": None,
        }

    return {
        "pane_session_id": PANE,
        "owner_session_id": OWNER,
        "teammate_name": TEAMMATE,
        "run_id": RUN_ID,
        "task_id": TASK_ID,
        "resolution": resolution,
    }


def _command(
    *,
    merchant_id: str = MERCHANT_A,
    query: str = "CGV Media Top Up 2026",
) -> str:
    return (
        "python .claude/agents/tools/merchant/agent_cli.py "
        "project resolve "
        f'--merchant-id "{merchant_id}" '
        f'--query "{query}"'
    )


def _payload(
    *,
    command: str | None = None,
    result: dict | None = None,
    stdout: str | None = None,
    tool_use_id: str = "tool-project-resolve",
) -> dict:
    if command is None:
        command = _command()

    if stdout is None:
        stdout = json.dumps(
            _resolved_project()
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


def _install_parent(
    monkeypatch,
    *,
    receipt: dict | None = None,
    matches: bool = True,
) -> None:
    if receipt is None:
        receipt = _parent_receipt()

    monkeypatch.setattr(
        team_result_hook,
        "load_pending_merchant_resolution",
        lambda pane_session_id: receipt,
    )

    monkeypatch.setattr(
        team_result_hook,
        "pending_merchant_resolution_matches",
        lambda *args, **kwargs: matches,
    )


def _capture_stage(monkeypatch) -> dict:
    captured: dict = {}

    def fake_stage(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        team_result_hook,
        "stage_pending_project_resolution",
        fake_stage,
    )

    return captured


def _stage(
    payload: dict,
    *,
    operations=("merchant_read",),
    teammate_name: str = TEAMMATE,
) -> bool:
    return team_result_hook._stage_exact_tmux_project_resolution(
        payload=payload,
        pane_session_id=PANE,
        owner_session_id=OWNER,
        teammate_name=teammate_name,
        run_id=RUN_ID,
        task_id=TASK_ID,
        authorized_operations=list(operations),
    )

def test_exact_project_resolution_stages(monkeypatch):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    assert _stage(_payload()) is True

    assert captured["pane_session_id"] == PANE
    assert captured["owner_session_id"] == OWNER
    assert captured["teammate_name"] == TEAMMATE
    assert captured["run_id"] == RUN_ID
    assert captured["task_id"] == TASK_ID
    assert captured["merchant_id"] == MERCHANT_A
    assert captured["tool_use_id"] == "tool-project-resolve"
    assert captured["resolution"]["project_id"] == PROJECT_A


@pytest.mark.parametrize(
    "operation",
    [
        "merchant_read",
        "merchant_propose",
        "merchant_apply",
    ],
)
def test_all_merchant_operation_scopes_can_stage(
    monkeypatch,
    operation,
):
    _install_parent(monkeypatch)
    _capture_stage(monkeypatch)

    assert _stage(
        _payload(),
        operations=(operation,),
    ) is True


def test_missing_parent_merchant_receipt_does_not_stage(
    monkeypatch,
):
    monkeypatch.setattr(
        team_result_hook,
        "load_pending_merchant_resolution",
        lambda pane_session_id: None,
    )

    captured = _capture_stage(monkeypatch)

    assert _stage(_payload()) is False
    assert captured == {}


def test_parent_binding_mismatch_does_not_stage(
    monkeypatch,
):
    _install_parent(
        monkeypatch,
        matches=False,
    )
    captured = _capture_stage(monkeypatch)

    assert _stage(_payload()) is False
    assert captured == {}


@pytest.mark.parametrize(
    "status",
    [
        "AMBIGUOUS",
        "NOT_FOUND",
    ],
)
def test_parent_merchant_must_be_resolved(
    monkeypatch,
    status,
):
    _install_parent(
        monkeypatch,
        receipt=_parent_receipt(
            status=status,
        ),
    )
    captured = _capture_stage(monkeypatch)

    assert _stage(_payload()) is False
    assert captured == {}


def test_command_merchant_id_must_match_parent_receipt(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    payload = _payload(
        command=_command(
            merchant_id=MERCHANT_B,
        ),
        result=_resolved_project(
            merchant_id=MERCHANT_B,
        ),
    )

    assert _stage(payload) is False
    assert captured == {}


def test_output_merchant_id_must_match_command(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    payload = _payload(
        result=_resolved_project(
            merchant_id=MERCHANT_B,
        )
    )

    assert _stage(payload) is False
    assert captured == {}


def test_output_query_must_match_command(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    payload = _payload(
        result=_resolved_project(
            query="Different Project",
        )
    )

    assert _stage(payload) is False
    assert captured == {}


def test_wrong_teammate_does_not_stage(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    assert _stage(
        _payload(),
        teammate_name="reviewer",
    ) is False

    assert captured == {}


def test_unauthorized_operation_does_not_stage(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    assert _stage(
        _payload(),
        operations=("github_read",),
    ) is False

    assert captured == {}


def test_mixed_operations_do_not_stage(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    assert _stage(
        _payload(),
        operations=(
            "merchant_read",
            "merchant_propose",
        ),
    ) is False

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
def test_wrapped_project_resolver_does_not_stage(
    monkeypatch,
    suffix,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    payload = _payload(
        command=_command() + suffix,
    )

    assert _stage(payload) is False
    assert captured == {}


def test_extra_cli_argument_does_not_stage(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    payload = _payload(
        command=_command() + " --status PLANNED",
    )

    assert _stage(payload) is False
    assert captured == {}


def test_missing_query_does_not_stage(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    command = (
        "python .claude/agents/tools/merchant/agent_cli.py "
        "project resolve "
        f'--merchant-id "{MERCHANT_A}"'
    )

    assert _stage(
        _payload(command=command)
    ) is False

    assert captured == {}


def test_missing_merchant_id_does_not_stage(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    command = (
        "python .claude/agents/tools/merchant/agent_cli.py "
        "project resolve "
        '--query "CGV Media Top Up 2026"'
    )

    assert _stage(
        _payload(command=command)
    ) is False

    assert captured == {}


def test_malformed_json_stdout_does_not_stage(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    assert _stage(
        _payload(stdout="{not-json")
    ) is False

    assert captured == {}


def test_stdout_must_be_exact_json_only(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    stdout = (
        json.dumps(_resolved_project())
        + "\nextra output"
    )

    assert _stage(
        _payload(stdout=stdout)
    ) is False

    assert captured == {}


def test_missing_tool_use_id_does_not_stage(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    assert _stage(
        _payload(tool_use_id="")
    ) is False

    assert captured == {}


def test_ambiguous_project_result_is_authoritative_and_stages(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    result = _ambiguous_project()

    payload = _payload(
        command=_command(
            query="Media Top Up",
        ),
        result=result,
    )

    assert _stage(payload) is True
    assert captured["resolution"]["status"] == "AMBIGUOUS"


def test_not_found_project_result_is_authoritative_and_stages(
    monkeypatch,
):
    _install_parent(monkeypatch)
    captured = _capture_stage(monkeypatch)

    result = _not_found_project()

    payload = _payload(
        command=_command(
            query="Unknown Project",
        ),
        result=result,
    )

    assert _stage(payload) is True
    assert captured["resolution"]["status"] == "NOT_FOUND"