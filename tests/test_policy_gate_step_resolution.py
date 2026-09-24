from __future__ import annotations

from copy import deepcopy

from claude.hooks import policy_gate


MERCHANT_ID = (
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
)

OTHER_MERCHANT_ID = (
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
)

PROJECT_ID = (
    "11111111-1111-4111-8111-111111111111"
)

OTHER_PROJECT_ID = (
    "22222222-2222-4222-8222-222222222222"
)

STEP_ID = (
    "33333333-3333-4333-8333-333333333333"
)

OTHER_STEP_ID = (
    "44444444-4444-4444-8444-444444444444"
)

TEMPLATE_STEP_ID = (
    "55555555-5555-4555-8555-555555555555"
)


def merchant_resolution():
    return {
        "success": True,
        "mode": "RESOLUTION",
        "query": "CGV",
        "status": "RESOLVED",
        "match_kind": "CODE",
        "resolved": True,
        "merchant_id": MERCHANT_ID,
        "code": "CGV",
        "name": "CGV",
        "candidates": [
            {
                "merchant_id": MERCHANT_ID,
                "code": "CGV",
                "name": "CGV",
            }
        ],
    }


def merchant_receipt():
    return {
        "pane_session_id": "pane-1",
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
        "tool_use_id": "merchant-tool",
        "created_at": 1.0,
        "resolution": (
            merchant_resolution()
        ),
    }


def project_candidate():
    return {
        "project_id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "title": "CGV Integration",
        "project_type": "INTEGRATION",
        "workflow_variant": "STANDARD",
        "status": "IN_PROGRESS",
        "version": 1,
    }


def project_resolution():
    return {
        "success": True,
        "mode": "PROJECT_RESOLUTION",
        "query": "CGV Integration",
        "merchant_id": MERCHANT_ID,
        "status": "RESOLVED",
        "match_kind": "TITLE",
        "resolved": True,
        "project_id": PROJECT_ID,
        "title": "CGV Integration",
        "project_type": "INTEGRATION",
        "workflow_variant": "STANDARD",
        "project_status": "IN_PROGRESS",
        "version": 1,
        "candidates": [
            project_candidate()
        ],
    }


def project_receipt():
    return {
        "pane_session_id": "pane-1",
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
        "merchant_id": MERCHANT_ID,
        "tool_use_id": "project-tool",
        "created_at": 1.0,
        "resolution": (
            project_resolution()
        ),
    }


def step_candidate(
    *,
    step_id=STEP_ID,
    project_id=PROJECT_ID,
    step_name="Run UAT test",
):
    return {
        "step_id": step_id,
        "project_id": project_id,
        "template_step_id": (
            TEMPLATE_STEP_ID
        ),
        "branch_key": "uat_branch",
        "step_name": step_name,
        "step_type": "PARALLEL_BRANCH",
        "status": "READY",
        "sequence_number": 20,
        "version": 1,
        "condition_key": None,
        "is_optional": False,
    }


def step_resolution():
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": "Run UAT test",
        "project_id": PROJECT_ID,
        "status": "RESOLVED",
        "match_kind": "STEP_NAME",
        "resolved": True,
        "step_id": STEP_ID,
        "template_step_id": (
            TEMPLATE_STEP_ID
        ),
        "branch_key": "uat_branch",
        "step_name": "Run UAT test",
        "step_type": "PARALLEL_BRANCH",
        "step_status": "READY",
        "sequence_number": 20,
        "version": 1,
        "condition_key": None,
        "is_optional": False,
        "candidates": [
            step_candidate()
        ],
    }


def ambiguous_step_resolution():
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": "Review",
        "project_id": PROJECT_ID,
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
            {
                **step_candidate(
                    step_id=STEP_ID,
                    step_name="Review",
                ),
                "sequence_number": 10,
            },
            {
                **step_candidate(
                    step_id=OTHER_STEP_ID,
                    step_name="Review",
                ),
                "branch_key": "production_branch",
                "sequence_number": 20,
            },
        ],
    }


def not_found_step_resolution():
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": "Unknown Step",
        "project_id": PROJECT_ID,
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


def step_receipt(
    resolution=None,
):
    return {
        "pane_session_id": "pane-1",
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
        "merchant_id": MERCHANT_ID,
        "project_id": PROJECT_ID,
        "tool_use_id": "step-tool",
        "created_at": 1.0,
        "resolution": (
            step_resolution()
            if resolution is None
            else resolution
        ),
    }


def payload(
    command: str,
):
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "pane-1",
        "agent_id": "merchant-agent",
        "agent_type": "merchant-manager",
        "tool_name": "Bash",
        "tool_input": {
            "command": command,
        },
    }


def install_owner(
    monkeypatch,
):
    monkeypatch.setattr(
        policy_gate,
        "find_unique_active_teammate_owner",
        lambda teammate: (
            "lead-1",
            {
                "current_run_id": "run-1",
                "current_task_id": "task-1",
                "authorized_operations": [
                    "merchant_propose",
                ],
                "authorized_selected_agents": [
                    "merchant-manager",
                ],
            },
            "FOUND",
        ),
    )


def install_bindings(
    monkeypatch,
    *,
    merchant_value=None,
    project_value=None,
    step_value=None,
):
    if merchant_value is None:
        merchant_value = (
            merchant_receipt()
        )

    if project_value is None:
        project_value = (
            project_receipt()
        )

    if step_value is None:
        step_value = (
            step_receipt()
        )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: merchant_value,
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        lambda session_id: project_value,
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_step_resolution",
        lambda session_id: step_value,
    )


def deny_reason(
    decision,
):
    return decision[
        "hookSpecificOutput"
    ][
        "permissionDecisionReason"
    ]


def assert_denied(
    decision,
):
    assert decision is not None

    assert (
        decision[
            "hookSpecificOutput"
        ][
            "permissionDecision"
        ]
        == "deny"
    )


def step_update_command(
    step_id=STEP_ID,
):
    return (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        f"step update {step_id} "
        "--status IN_PROGRESS "
        "--expected-version 1 "
        "--propose"
    )


def test_step_resolve_is_exempt():
    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "step resolve "
                f"--project-id {PROJECT_ID} "
                '--query "Run UAT test"'
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_step_update_without_step_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        step_value=False,
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_step_resolution",
        lambda session_id: None,
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "without an exact Step resolver receipt"
        in deny_reason(
            decision
        )
    )


def test_step_update_exact_binding_is_allowed(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command()
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_step_update_wrong_step_id_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command(
                    OTHER_STEP_ID
                )
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "does not match"
        in deny_reason(
            decision
        )
    )


def test_invalid_step_uuid_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command(
                    "not-a-uuid"
                )
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "canonical Step UUID"
        in deny_reason(
            decision
        )
    )


def test_missing_parent_merchant_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: None,
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "parent Merchant"
        in deny_reason(
            decision
        )
    )


def test_missing_parent_project_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    # Install valid Merchant + Project + Step bindings first.
    install_bindings(
        monkeypatch
    )

    # Then remove only the Project parent.
    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        lambda session_id: None,
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "parent Project"
        in deny_reason(
            decision
        )
    )

def test_cross_project_step_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    value = deepcopy(
        step_receipt()
    )

    value[
        "project_id"
    ] = OTHER_PROJECT_ID

    value[
        "resolution"
    ][
        "project_id"
    ] = OTHER_PROJECT_ID

    value[
        "resolution"
    ][
        "candidates"
    ][0][
        "project_id"
    ] = OTHER_PROJECT_ID

    install_bindings(
        monkeypatch,
        step_value=value,
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


def test_cross_merchant_step_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    value = deepcopy(
        step_receipt()
    )

    value[
        "merchant_id"
    ] = OTHER_MERCHANT_ID

    install_bindings(
        monkeypatch,
        step_value=value,
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


def test_ambiguous_step_resolution_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        step_value=(
            step_receipt(
                ambiguous_step_resolution()
            )
        ),
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "Multiple workflow steps match"
        in deny_reason(
            decision
        )
    )


def test_not_found_step_resolution_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        step_value=(
            step_receipt(
                not_found_step_resolution()
            )
        ),
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "No workflow step matched"
        in deny_reason(
            decision
        )
    )


def test_template_step_id_cannot_be_substituted(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                step_update_command(
                    TEMPLATE_STEP_ID
                )
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


def test_non_step_command_needs_no_step_binding(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project show {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_wrapped_step_update_is_blocked():
    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                "python -c "
                "\"print('x')\" | "
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                + (
                    f"step update {STEP_ID} "
                    "--status IN_PROGRESS "
                    "--expected-version 1 "
                    "--propose"
                )
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


def test_step_update_is_registered_step_id_consumer():
    tokens = (
        "python",
        ".claude/agents/tools/merchant/agent_cli.py",
        "step",
        "update",
        STEP_ID,
        "--status",
        "IN_PROGRESS",
        "--expected-version",
        "1",
        "--propose",
    )

    command, step_id = (
        policy_gate
        ._step_id_from_cli_tokens(
            tokens
        )
    )

    assert command == (
        "step update"
    )

    assert step_id == STEP_ID


def test_step_resolve_does_not_consume_step_id():
    tokens = (
        "python",
        ".claude/agents/tools/merchant/agent_cli.py",
        "step",
        "resolve",
        "--project-id",
        PROJECT_ID,
        "--query",
        "Run UAT test",
    )

    command, step_id = (
        policy_gate
        ._step_id_from_cli_tokens(
            tokens
        )
    )

    assert command == (
        "step resolve"
    )

    assert step_id is None


def test_step_update_missing_step_id_fails_closed():
    tokens = (
        "python",
        ".claude/agents/tools/merchant/agent_cli.py",
        "step",
        "update",
    )

    command, step_id = (
        policy_gate
        ._step_id_from_cli_tokens(
            tokens
        )
    )

    assert command == (
        "step update"
    )

    assert step_id == ""


def test_step_update_flag_cannot_replace_positional_step_id(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch
    )

    decision = (
        policy_gate
        .step_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "step update "
                "--status IN_PROGRESS "
                "--expected-version 1 "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )