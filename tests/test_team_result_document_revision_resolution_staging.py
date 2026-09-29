

import json

import pytest

from claude.hooks import team_result_hook as hook


MERCHANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MERCHANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"

REVISION_A = "41111111-1111-4111-8111-111111111111"
REVISION_B = "42222222-2222-4222-8222-222222222222"


def _merchant_receipt(
    *,
    merchant_id: str = MERCHANT_A,
    status: str = "RESOLVED",
    resolved: bool = True,
):
    return {
        "resolution": {
            "status": status,
            "resolved": resolved,
            "merchant_id": merchant_id,
        }
    }


def _project_receipt(
    *,
    project_id: str = PROJECT_A,
    status: str = "RESOLVED",
    resolved: bool = True,
):
    return {
        "resolution": {
            "status": status,
            "resolved": resolved,
            "project_id": project_id,
        }
    }


def _candidate(
    *,
    revision_id: str = REVISION_A,
    project_id: str = PROJECT_A,
    merchant_id: str = MERCHANT_A,
    document_type: str = "CONTRACT",
    revision_number: int = 1,
    signed: bool = True,
):
    return {
        "revision_id": revision_id,
        "project_id": project_id,
        "merchant_id": merchant_id,
        "document_type": document_type,
        "revision_number": revision_number,
        "signed": signed,
        "superseded_by": None,
    }


def _merchant_resolution(
    *,
    query: str = "MEDIA_APPENDIX#1",
    merchant_id: str = MERCHANT_A,
):
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": query,
        "scope": "MERCHANT",
        "merchant_id": merchant_id,
        "project_id": None,
        "status": "RESOLVED",
        "match_kind": "REVISION_KEY",
        "resolved": True,
        "revision_id": REVISION_B,
        "source_project_id": PROJECT_B,
        "document_type": "MEDIA_APPENDIX",
        "revision_number": 1,
        "signed": False,
        "superseded_by": None,
        "candidates": [
            _candidate(
                revision_id=REVISION_B,
                project_id=PROJECT_B,
                merchant_id=merchant_id,
                document_type="MEDIA_APPENDIX",
                revision_number=1,
                signed=False,
            )
        ],
    }


def _project_resolution(
    *,
    query: str = "CONTRACT#1",
    merchant_id: str = MERCHANT_A,
    project_id: str = PROJECT_A,
):
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": query,
        "scope": "PROJECT",
        "merchant_id": merchant_id,
        "project_id": project_id,
        "status": "RESOLVED",
        "match_kind": "REVISION_KEY",
        "resolved": True,
        "revision_id": REVISION_A,
        "source_project_id": project_id,
        "document_type": "CONTRACT",
        "revision_number": 1,
        "signed": True,
        "superseded_by": None,
        "candidates": [
            _candidate(
                revision_id=REVISION_A,
                project_id=project_id,
                merchant_id=merchant_id,
            )
        ],
    }


def _payload(
    command: str,
    resolution: dict,
    *,
    tool_name: str = "Bash",
    tool_use_id: str = "tool-1",
):
    return {
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "tool_input": {
            "command": command,
        },
        "tool_response": {
            "stdout": json.dumps(
                resolution
            ),
        },
    }


def _merchant_command(
    *,
    merchant_id: str = MERCHANT_A,
    query: str = "MEDIA_APPENDIX#1",
):
    return (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "document resolve "
        f'--merchant-id "{merchant_id}" '
        f'--query "{query}"'
    )


def _project_command(
    *,
    project_id: str = PROJECT_A,
    query: str = "CONTRACT#1",
):
    return (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "document resolve "
        f'--project-id "{project_id}" '
        f'--query "{query}"'
    )


@pytest.fixture
def trusted_environment(
    monkeypatch,
):
    staged = []

    monkeypatch.setattr(
        hook,
        "load_pending_merchant_resolution",
        lambda pane_id: _merchant_receipt(),
    )

    monkeypatch.setattr(
        hook,
        "pending_merchant_resolution_matches",
        lambda *args, **kwargs: True,
    )

    monkeypatch.setattr(
        hook,
        "load_pending_project_resolution",
        lambda pane_id: _project_receipt(),
        raising=False,
    )

    monkeypatch.setattr(
        hook,
        "project_resolution_receipt_matches",
        lambda *args, **kwargs: True,
        raising=False,
    )

    def fake_stage(**kwargs):
        staged.append(
            kwargs
        )
        return True

    monkeypatch.setattr(
        hook,
        "stage_pending_document_revision_resolution",
        fake_stage,
        raising=False,
    )

    return staged


def _call(
    payload,
    *,
    operations=("merchant_read",),
    pane_session_id="pane-1",
    owner_session_id="lead-1",
    teammate_name="merchant-manager",
    run_id="run-1",
    task_id="task-1",
):
    return hook._stage_exact_tmux_document_revision_resolution(
        payload=payload,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        authorized_operations=list(
            operations
        ),
    )


# ---------------------------------------------------------------------
# MERCHANT scope
# ---------------------------------------------------------------------


def test_merchant_scope_direct_exact_command_stages(
    trusted_environment,
):
    resolution = _merchant_resolution()

    result = _call(
        _payload(
            _merchant_command(),
            resolution,
        )
    )

    assert result is True
    assert len(
        trusted_environment
    ) == 1

    staged = trusted_environment[0]

    assert staged["scope"] == "MERCHANT"
    assert staged["merchant_id"] == MERCHANT_A
    assert staged["project_id"] is None
    assert staged["resolution"] == resolution
    assert staged["tool_use_id"] == "tool-1"


def test_merchant_scope_does_not_require_project_receipt(
    trusted_environment,
    monkeypatch,
):
    monkeypatch.setattr(
        hook,
        "load_pending_project_resolution",
        lambda pane_id: None,
        raising=False,
    )

    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
        )
    ) is True


def test_merchant_scope_requires_merchant_receipt(
    trusted_environment,
    monkeypatch,
):
    monkeypatch.setattr(
        hook,
        "load_pending_merchant_resolution",
        lambda pane_id: None,
    )

    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
        )
    ) is False


def test_merchant_scope_requires_resolved_merchant(
    trusted_environment,
    monkeypatch,
):
    monkeypatch.setattr(
        hook,
        "load_pending_merchant_resolution",
        lambda pane_id: _merchant_receipt(
            status="NOT_FOUND",
            resolved=False,
        ),
    )

    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
        )
    ) is False


def test_merchant_scope_requires_command_merchant_match(
    trusted_environment,
):
    assert _call(
        _payload(
            _merchant_command(
                merchant_id=MERCHANT_B
            ),
            _merchant_resolution(),
        )
    ) is False


def test_merchant_scope_allows_source_revision_from_sibling_project(
    trusted_environment,
):
    resolution = _merchant_resolution()

    assert (
        resolution[
            "source_project_id"
        ]
        == PROJECT_B
    )

    assert _call(
        _payload(
            _merchant_command(),
            resolution,
        )
    ) is True


# ---------------------------------------------------------------------
# PROJECT scope
# ---------------------------------------------------------------------


def test_project_scope_direct_exact_command_stages(
    trusted_environment,
):
    resolution = _project_resolution()

    result = _call(
        _payload(
            _project_command(),
            resolution,
        )
    )

    assert result is True
    assert len(
        trusted_environment
    ) == 1

    staged = trusted_environment[0]

    assert staged["scope"] == "PROJECT"
    assert staged["merchant_id"] == MERCHANT_A
    assert staged["project_id"] == PROJECT_A
    assert staged["resolution"] == resolution


def test_project_scope_requires_project_receipt(
    trusted_environment,
    monkeypatch,
):
    monkeypatch.setattr(
        hook,
        "load_pending_project_resolution",
        lambda pane_id: None,
        raising=False,
    )

    assert _call(
        _payload(
            _project_command(),
            _project_resolution(),
        )
    ) is False


def test_project_scope_requires_resolved_project(
    trusted_environment,
    monkeypatch,
):
    monkeypatch.setattr(
        hook,
        "load_pending_project_resolution",
        lambda pane_id: _project_receipt(
            status="NOT_FOUND",
            resolved=False,
        ),
        raising=False,
    )

    assert _call(
        _payload(
            _project_command(),
            _project_resolution(),
        )
    ) is False


def test_project_scope_requires_project_receipt_binding(
    trusted_environment,
    monkeypatch,
):
    monkeypatch.setattr(
        hook,
        "project_resolution_receipt_matches",
        lambda *args, **kwargs: False,
        raising=False,
    )

    assert _call(
        _payload(
            _project_command(),
            _project_resolution(),
        )
    ) is False


def test_project_scope_requires_command_project_match(
    trusted_environment,
):
    assert _call(
        _payload(
            _project_command(
                project_id=PROJECT_B
            ),
            _project_resolution(),
        )
    ) is False


# ---------------------------------------------------------------------
# Exact command surface
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    (
        (
            "python "
            ".claude/agents/tools/merchant/agent_cli.py "
            "document resolve "
            f'--merchant-id "{MERCHANT_A}" '
            '--query "MEDIA_APPENDIX#1" '
            "&& echo done"
        ),
        (
            "python "
            ".claude/agents/tools/merchant/agent_cli.py "
            "document resolve "
            f'--merchant-id "{MERCHANT_A}" '
            '--query "MEDIA_APPENDIX#1" '
            "| cat"
        ),
        (
            "python "
            ".claude/agents/tools/merchant/agent_cli.py "
            "document resolve "
            f'--merchant-id "{MERCHANT_A}" '
            '--query "MEDIA_APPENDIX#1" '
            "> out.json"
        ),
    ),
)
def test_shell_composition_is_rejected(
    trusted_environment,
    command,
):
    assert _call(
        _payload(
            command,
            _merchant_resolution(),
        )
    ) is False


def test_non_bash_is_rejected(
    trusted_environment,
):
    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
            tool_name="PowerShell",
        )
    ) is False


def test_wrong_executable_is_rejected(
    trusted_environment,
):
    command = (
        "node "
        ".claude/agents/tools/merchant/agent_cli.py "
        "document resolve "
        f'--merchant-id "{MERCHANT_A}" '
        '--query "MEDIA_APPENDIX#1"'
    )

    assert _call(
        _payload(
            command,
            _merchant_resolution(),
        )
    ) is False


def test_wrong_cli_path_is_rejected(
    trusted_environment,
):
    command = (
        "python other/agent_cli.py "
        "document resolve "
        f'--merchant-id "{MERCHANT_A}" '
        '--query "MEDIA_APPENDIX#1"'
    )

    assert _call(
        _payload(
            command,
            _merchant_resolution(),
        )
    ) is False


def test_unknown_extra_flag_is_rejected(
    trusted_environment,
):
    command = (
        _merchant_command()
        + " --extra nope"
    )

    assert _call(
        _payload(
            command,
            _merchant_resolution(),
        )
    ) is False


def test_duplicate_query_is_rejected(
    trusted_environment,
):
    command = (
        _merchant_command()
        + ' --query "again"'
    )

    assert _call(
        _payload(
            command,
            _merchant_resolution(),
        )
    ) is False


def test_duplicate_merchant_id_is_rejected(
    trusted_environment,
):
    command = (
        _merchant_command()
        + f' --merchant-id "{MERCHANT_A}"'
    )

    assert _call(
        _payload(
            command,
            _merchant_resolution(),
        )
    ) is False


def test_duplicate_project_id_is_rejected(
    trusted_environment,
):
    command = (
        _project_command()
        + f' --project-id "{PROJECT_A}"'
    )

    assert _call(
        _payload(
            command,
            _project_resolution(),
        )
    ) is False


def test_both_parent_flags_are_rejected(
    trusted_environment,
):
    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "document resolve "
        f'--merchant-id "{MERCHANT_A}" '
        f'--project-id "{PROJECT_A}" '
        '--query "CONTRACT#1"'
    )

    assert _call(
        _payload(
            command,
            _project_resolution(),
        )
    ) is False


def test_neither_parent_flag_is_rejected(
    trusted_environment,
):
    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "document resolve "
        '--query "CONTRACT#1"'
    )

    assert _call(
        _payload(
            command,
            _project_resolution(),
        )
    ) is False


# ---------------------------------------------------------------------
# Output binding
# ---------------------------------------------------------------------


def test_non_json_stdout_is_rejected(
    trusted_environment,
):
    payload = _payload(
        _merchant_command(),
        _merchant_resolution(),
    )

    payload["tool_response"][
        "stdout"
    ] = "not-json"

    assert _call(
        payload
    ) is False


def test_prose_around_json_is_rejected(
    trusted_environment,
):
    payload = _payload(
        _merchant_command(),
        _merchant_resolution(),
    )

    payload["tool_response"][
        "stdout"
    ] = (
        "result: "
        + json.dumps(
            _merchant_resolution()
        )
    )

    assert _call(
        payload
    ) is False


def test_output_query_mismatch_is_rejected(
    trusted_environment,
):
    resolution = _merchant_resolution(
        query="OTHER"
    )

    assert _call(
        _payload(
            _merchant_command(),
            resolution,
        )
    ) is False


def test_output_scope_mismatch_is_rejected(
    trusted_environment,
):
    resolution = _merchant_resolution()
    resolution["scope"] = "PROJECT"

    assert _call(
        _payload(
            _merchant_command(),
            resolution,
        )
    ) is False


def test_output_merchant_mismatch_is_rejected(
    trusted_environment,
):
    resolution = _merchant_resolution(
        merchant_id=MERCHANT_B
    )

    assert _call(
        _payload(
            _merchant_command(),
            resolution,
        )
    ) is False


def test_project_output_project_mismatch_is_rejected(
    trusted_environment,
):
    resolution = _project_resolution(
        project_id=PROJECT_B
    )

    assert _call(
        _payload(
            _project_command(),
            resolution,
        )
    ) is False


def test_missing_tool_use_id_is_rejected(
    trusted_environment,
):
    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
            tool_use_id="",
        )
    ) is False


# ---------------------------------------------------------------------
# Authorization / lifecycle identity
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "operation",
    (
        "merchant_read",
        "merchant_propose",
        "merchant_apply",
    ),
)
def test_authorized_merchant_operations_are_accepted(
    trusted_environment,
    operation,
):
    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
        ),
        operations=(
            operation,
        ),
    ) is True


def test_unrelated_operation_is_rejected(
    trusted_environment,
):
    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
        ),
        operations=(
            "review",
        ),
    ) is False


def test_multiple_operations_are_rejected(
    trusted_environment,
):
    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
        ),
        operations=(
            "merchant_read",
            "merchant_propose",
        ),
    ) is False


def test_wrong_teammate_is_rejected(
    trusted_environment,
):
    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
        ),
        teammate_name="reviewer",
    ) is False


@pytest.mark.parametrize(
    (
        "field",
        "value",
    ),
    (
        ("pane_session_id", ""),
        ("owner_session_id", ""),
        ("run_id", ""),
        ("task_id", ""),
    ),
)
def test_missing_lifecycle_binding_is_rejected(
    trusted_environment,
    field,
    value,
):
    kwargs = {
        "pane_session_id": "pane-1",
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
    }

    kwargs[field] = value

    assert _call(
        _payload(
            _merchant_command(),
            _merchant_resolution(),
        ),
        **kwargs,
    ) is False
