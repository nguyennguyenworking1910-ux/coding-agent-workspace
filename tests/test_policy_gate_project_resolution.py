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
        "tool_use_id": "merchant-resolve-1",
        "created_at": 1.0,
        "resolution": merchant_resolution(),
    }


def project_candidate(
    *,
    project_id=PROJECT_ID,
    merchant_id=MERCHANT_ID,
    title="CGV Media Top Up 2026",
):
    return {
        "project_id": project_id,
        "merchant_id": merchant_id,
        "title": title,
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "status": "PLANNED",
        "version": 1,
    }


def project_resolution():
    return {
        "success": True,
        "mode": "PROJECT_RESOLUTION",
        "query": "CGV Media Top Up 2026",
        "merchant_id": MERCHANT_ID,
        "status": "RESOLVED",
        "match_kind": "TITLE",
        "resolved": True,
        "project_id": PROJECT_ID,
        "title": "CGV Media Top Up 2026",
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "project_status": "PLANNED",
        "version": 1,
        "candidates": [
            project_candidate()
        ],
    }


def ambiguous_project_resolution():
    return {
        "success": True,
        "mode": "PROJECT_RESOLUTION",
        "query": "Media Top Up",
        "merchant_id": MERCHANT_ID,
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
            project_candidate(),
            project_candidate(
                project_id=OTHER_PROJECT_ID,
                title="CGV Media Top Up 2027",
            ),
        ],
    }


def project_receipt(
    resolution=None,
):
    return {
        "pane_session_id": "pane-1",
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
        "merchant_id": MERCHANT_ID,
        "tool_use_id": "project-resolve-1",
        "created_at": 1.0,
        "resolution": (
            project_resolution()
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
                    "merchant_read",
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
):
    if merchant_value is None:
        merchant_value = (
            merchant_receipt()
        )

    if project_value is None:
        project_value = (
            project_receipt()
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


def test_project_resolve_is_exempt(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        project_value=None,
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project resolve "
                f"--merchant-id {MERCHANT_ID} "
                '--query "CGV Media Top Up 2026"'
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_show_without_project_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            merchant_receipt()
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        lambda session_id: None,
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project show {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "without an exact Project resolver receipt"
        in deny_reason(
            decision
        )
    )


def test_project_show_with_exact_binding_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project show {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_show_wrong_project_id_is_blocked(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project show {OTHER_PROJECT_ID}"
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


def test_invalid_project_uuid_is_blocked(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project show not-a-uuid"
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "canonical Project UUID"
        in deny_reason(
            decision
        )
    )


def test_project_history_exact_binding_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project history {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_blockers_exact_binding_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project blockers {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_update_exact_binding_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project update {PROJECT_ID} "
                "--status IN_PROGRESS "
                "--expected-version 1 "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_document_revision_create_exact_binding_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "document revision-create "
                f"{PROJECT_ID} "
                "--type APPENDIX "
                "--content-hash abc123 "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_procurement_update_exact_binding_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "procurement update "
                f"{PROJECT_ID} "
                "--type PURCHASE_ORDER "
                "--status OPEN "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_missing_parent_merchant_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: None,
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        lambda session_id: (
            project_receipt()
        ),
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project show {PROJECT_ID}"
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


def test_cross_merchant_project_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    merchant_value = (
        merchant_receipt()
    )

    resolution = (
        project_resolution()
    )

    resolution[
        "merchant_id"
    ] = OTHER_MERCHANT_ID

    resolution[
        "candidates"
    ][0][
        "merchant_id"
    ] = OTHER_MERCHANT_ID

    project_value = (
        project_receipt(
            resolution
        )
    )

    project_value[
        "merchant_id"
    ] = OTHER_MERCHANT_ID

    install_bindings(
        monkeypatch,
        merchant_value=(
            merchant_value
        ),
        project_value=(
            project_value
        ),
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project show {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


def test_ambiguous_project_resolution_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        project_value=(
            project_receipt(
                ambiguous_project_resolution()
            )
        ),
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project show {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "Multiple projects match"
        in deny_reason(
            decision
        )
    )


def test_project_list_does_not_require_project_binding(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        project_value=None,
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project list "
                f"--merchant-id {MERCHANT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_wrapped_project_command_is_blocked():
    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python -c "
                "\"print('x')\" | "
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project show {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


def test_project_alerts_positional_project_id_exact_binding_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project alerts {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_alerts_project_id_flag_exact_binding_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project alerts "
                f"--project-id {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_alerts_project_id_equals_form_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project alerts "
                f"--project-id={PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_alerts_same_positional_and_flag_project_id_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project alerts "
                f"{PROJECT_ID} "
                f"--project-id {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_alerts_conflicting_positional_and_flag_is_blocked(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project alerts "
                f"{PROJECT_ID} "
                f"--project-id {OTHER_PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


def test_project_alerts_wrong_bound_project_is_blocked(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project alerts "
                f"--project-id {OTHER_PROJECT_ID}"
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


def test_project_alerts_without_project_filter_needs_no_project_binding(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            merchant_receipt()
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        lambda session_id: None,
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project alerts "
                f"--merchant-id {MERCHANT_ID} "
                "--alert-type OVERDUE"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_alerts_project_filter_without_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            merchant_receipt()
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        lambda session_id: None,
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project alerts "
                f"--project-id {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "without an exact Project resolver receipt"
        in deny_reason(
            decision
        )
    )


def test_identifier_set_without_project_id_needs_no_project_binding(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            merchant_receipt()
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        lambda session_id: None,
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "integration identifier-set "
                f"{MERCHANT_ID} "
                "--type PARTNER_CODE "
                "--value PCODE_TEST "
                "--scope UAT "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_identifier_set_with_project_id_exact_binding_is_allowed(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "integration identifier-set "
                f"{MERCHANT_ID} "
                f"{PROJECT_ID} "
                "--type PARTNER_CODE "
                "--value PCODE_TEST "
                "--scope UAT "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_identifier_set_with_wrong_project_id_is_blocked(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "integration identifier-set "
                f"{MERCHANT_ID} "
                f"{OTHER_PROJECT_ID} "
                "--type PARTNER_CODE "
                "--value PCODE_TEST "
                "--scope UAT "
                "--propose"
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


def test_identifier_set_project_scope_without_project_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            merchant_receipt()
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        lambda session_id: None,
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "integration identifier-set "
                f"{MERCHANT_ID} "
                f"{PROJECT_ID} "
                "--type PARTNER_CODE "
                "--value PCODE_TEST "
                "--scope UAT "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


def test_step_resolve_without_project_receipt_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            merchant_receipt()
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        lambda session_id: None,
    )

    decision = (
        policy_gate
        .project_resolution_use_decision(
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

    assert_denied(
        decision
    )


def test_step_resolve_with_exact_project_binding_is_allowed(
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
        .project_resolution_use_decision(
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


def test_step_resolve_wrong_project_id_is_blocked(
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
        .project_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "step resolve "
                f"--project-id {OTHER_PROJECT_ID} "
                '--query "Run UAT test"'
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