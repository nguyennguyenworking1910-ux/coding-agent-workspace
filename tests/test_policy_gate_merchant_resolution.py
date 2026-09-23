from __future__ import annotations

from claude.hooks import policy_gate


CGV_ID = (
    "2da7ab08-1eda-5ca2-b28e-f94f3e1be0d0"
)

LOTTE_ID = (
    "9e718abc-47d3-587e-a71e-5967bea119a5"
)


def resolved_receipt():
    return {
        "pane_session_id": "pane-1",
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
        "tool_use_id": "resolve-1",
        "created_at": 1.0,
        "resolution": {
            "success": True,
            "mode": "RESOLUTION",
            "query": "CGV",
            "status": "RESOLVED",
            "match_kind": "CODE",
            "resolved": True,
            "merchant_id": CGV_ID,
            "code": "CGV",
            "name": "CGV",
            "candidates": [
                {
                    "merchant_id": CGV_ID,
                    "code": "CGV",
                    "name": "CGV",
                }
            ],
        },
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


def test_resolver_command_is_allowed_without_prior_receipt(
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

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                'merchant resolve --query "CGV"'
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_list_without_resolution_receipt_is_blocked(
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

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project list "
                f"--merchant-id {CGV_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is not None

    assert (
        decision[
            "hookSpecificOutput"
        ][
            "permissionDecision"
        ]
        == "deny"
    )


def test_project_list_with_exact_binding_is_allowed(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            resolved_receipt()
        ),
    )

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project list "
                f"--merchant-id {CGV_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_mismatched_uuid_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            resolved_receipt()
        ),
    )

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project list "
                f"--merchant-id {LOTTE_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is not None

    reason = (
        decision[
            "hookSpecificOutput"
        ][
            "permissionDecisionReason"
        ]
    )

    assert (
        "does not match"
        in reason
    )


def test_project_create_requires_existing_merchant_binding(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            resolved_receipt()
        ),
    )

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project create "
                f"--merchant-id {CGV_ID} "
                "--type INTEGRATION_NEW_MERCHANT "
                "--variant INTEGRATION_NEW_MERCHANT_STANDARD "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_merchant_create_is_exempt(
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

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "merchant create "
                "--merchant-id "
                "00000000-0000-0000-0000-000000000123 "
                "--code NEW "
                '--name "New Merchant" '
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_wrapped_merchant_cli_is_blocked():
    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python -c "
                "\"print('x')\" | "
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "project list "
                f"--merchant-id {CGV_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is not None


def test_integration_identifier_set_positional_merchant_id_is_allowed(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            resolved_receipt()
        ),
    )

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "integration identifier-set "
                f"{CGV_ID} "
                "--type PARTNER_CODE "
                "--value PCODE_TEST "
                "--scope UAT "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_integration_identifier_set_wrong_positional_merchant_id_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            resolved_receipt()
        ),
    )

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "integration identifier-set "
                f"{LOTTE_ID} "
                "--type PARTNER_CODE "
                "--value PCODE_TEST "
                "--scope UAT "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is not None

    assert (
        decision[
            "hookSpecificOutput"
        ][
            "permissionDecision"
        ]
        == "deny"
    )


def test_integration_identifier_set_without_receipt_is_blocked(
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

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "integration identifier-set "
                f"{CGV_ID} "
                "--type PARTNER_CODE "
                "--value PCODE_TEST "
                "--scope UAT "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is not None


def test_integration_identifier_set_missing_positional_merchant_id_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        lambda session_id: (
            resolved_receipt()
        ),
    )

    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "integration identifier-set "
                "--type PARTNER_CODE "
                "--value PCODE_TEST "
                "--scope UAT "
                "--propose"
            ),
            "pane-1",
        )
    )

    assert decision is not None


def test_piped_resolver_command_is_blocked():
    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "merchant resolve --query CGV "
                "2>&1 | head -40"
            ),
            "pane-1",
        )
    )

    assert decision is not None

    assert (
        decision[
            "hookSpecificOutput"
        ][
            "permissionDecision"
        ]
        == "deny"
    )


def test_chained_resolver_command_is_blocked():
    decision = (
        policy_gate
        .merchant_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                'merchant resolve --query "CGV" '
                "&& echo done"
            ),
            "pane-1",
        )
    )

    assert decision is not None