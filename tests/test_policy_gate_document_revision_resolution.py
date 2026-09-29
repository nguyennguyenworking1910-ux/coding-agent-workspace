from __future__ import annotations

from types import SimpleNamespace

import pytest

from claude.hooks import policy_gate


MERCHANT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
REVISION_ID = "41111111-1111-4111-8111-111111111111"
OTHER_REVISION_ID = "42222222-2222-4222-8222-222222222222"


def payload(command: str):
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


def install_owner(monkeypatch):
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
    merchant_receipt=True,
    project_receipt=True,
    revision_receipt=True,
    revision_scope="PROJECT",
    revision_id=REVISION_ID,
    revision_outcome="BOUND",
    revision_question=None,
):
    monkeypatch.setattr(
        policy_gate,
        "load_pending_merchant_resolution",
        (
            (lambda session_id: {
                "resolution": {
                    "query": "CGV",
                }
            })
            if merchant_receipt
            else (lambda session_id: None)
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "bind_merchant_resolution_receipt",
        lambda *args, **kwargs: SimpleNamespace(
            accepted=True,
            outcome="BOUND",
            merchant_id=MERCHANT_ID,
            question=None,
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_project_resolution",
        (
            (lambda session_id: {
                "resolution": {
                    "query": "CGV Project",
                }
            })
            if project_receipt
            else (lambda session_id: None)
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "bind_project_resolution_receipt",
        lambda *args, **kwargs: SimpleNamespace(
            accepted=True,
            outcome="BOUND",
            project_id=PROJECT_ID,
            merchant_id=MERCHANT_ID,
            question=None,
        ),
    )

    monkeypatch.setattr(
        policy_gate,
        "load_pending_document_revision_resolution",
        (
            (lambda session_id: {
                "resolution": {
                    "query": "CONTRACT#1",
                    "scope": revision_scope,
                }
            })
            if revision_receipt
            else (lambda session_id: None)
        ),
        raising=False,
    )

    def bind_revision(*args, **kwargs):
        return SimpleNamespace(
            accepted=(
                revision_outcome
                == "BOUND"
            ),
            outcome=revision_outcome,
            revision_id=revision_id,
            merchant_id=MERCHANT_ID,
            project_id=(
                PROJECT_ID
                if kwargs.get(
                    "expected_scope"
                )
                == "PROJECT"
                else None
            ),
            scope=kwargs.get(
                "expected_scope"
            ),
            question=revision_question,
        )

    monkeypatch.setattr(
        policy_gate,
        "bind_document_revision_resolution_receipt",
        bind_revision,
        raising=False,
    )


def deny_reason(decision):
    return decision[
        "hookSpecificOutput"
    ][
        "permissionDecisionReason"
    ]


def assert_denied(decision):
    assert decision is not None
    assert (
        decision[
            "hookSpecificOutput"
        ][
            "permissionDecision"
        ]
        == "deny"
    )


def document_approve(
    revision_id=REVISION_ID,
):
    return (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        f"document approve {revision_id} "
        "--role LEGAL "
        "--status APPROVED "
        "--propose"
    )


def project_create_with_reuse(
    revision_id=REVISION_ID,
):
    return (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "project create "
        f"--merchant-id {MERCHANT_ID} "
        "--type MEDIA_TOP_UP "
        "--variant MEDIA_TOP_UP_EXISTING_DOCUMENT "
        f"--reused-document-revision-id {revision_id} "
        "--propose"
    )


def test_document_resolve_is_exempt(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                "document resolve "
                f"--project-id {PROJECT_ID} "
                '--query "CONTRACT#1"'
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_document_approve_exact_project_binding_is_allowed(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        revision_scope="PROJECT",
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                document_approve()
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_document_approve_requires_parent_merchant_receipt(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        merchant_receipt=False,
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                document_approve()
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


def test_document_approve_requires_parent_project_receipt(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        project_receipt=False,
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                document_approve()
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


def test_document_approve_requires_revision_receipt(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        revision_receipt=False,
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                document_approve()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "Document Revision resolver receipt"
        in deny_reason(
            decision
        )
    )


def test_document_approve_wrong_revision_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        revision_id=REVISION_ID,
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                document_approve(
                    OTHER_REVISION_ID
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


def test_document_approve_non_uuid_is_blocked(
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
        .document_revision_resolution_use_decision(
            payload(
                document_approve(
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
        "canonical Document Revision UUID"
        in deny_reason(
            decision
        )
    )


def test_document_approve_ambiguous_resolution_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        revision_outcome=(
            "REQUIRES_CLARIFICATION"
        ),
        revision_question=(
            "Multiple document revisions match."
        ),
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                document_approve()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "Multiple document revisions match."
        in deny_reason(
            decision
        )
    )


def test_project_create_reused_revision_uses_merchant_scope(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    captured = {}

    install_bindings(
        monkeypatch,
        project_receipt=False,
        revision_scope="MERCHANT",
    )

    original = (
        policy_gate
        .bind_document_revision_resolution_receipt
    )

    def capture(*args, **kwargs):
        captured.update(
            kwargs
        )
        return original(
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        policy_gate,
        "bind_document_revision_resolution_receipt",
        capture,
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                project_create_with_reuse()
            ),
            "pane-1",
        )
    )

    assert decision is None
    assert (
        captured[
            "expected_scope"
        ]
        == "MERCHANT"
    )
    assert (
        captured[
            "trusted_project_id"
        ]
        is None
    )


def test_project_create_reuse_does_not_require_project_receipt(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        project_receipt=False,
        revision_scope="MERCHANT",
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                project_create_with_reuse()
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_create_without_reuse_needs_no_revision_binding(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "project create "
        f"--merchant-id {MERCHANT_ID} "
        "--type MEDIA_TOP_UP "
        "--variant STANDARD "
        "--propose"
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                command
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_project_create_reused_revision_wrong_id_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        project_receipt=False,
        revision_scope="MERCHANT",
        revision_id=REVISION_ID,
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                project_create_with_reuse(
                    OTHER_REVISION_ID
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


def test_project_create_reuse_requires_revision_receipt(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        project_receipt=False,
        revision_receipt=False,
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                project_create_with_reuse()
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


def test_project_create_reuse_equals_form_is_supported(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        project_receipt=False,
        revision_scope="MERCHANT",
    )

    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "project create "
        f"--merchant-id {MERCHANT_ID} "
        "--type MEDIA_TOP_UP "
        "--variant MEDIA_TOP_UP_EXISTING_DOCUMENT "
        f"--reused-document-revision-id={REVISION_ID} "
        "--propose"
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                command
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_duplicate_reuse_flag_is_blocked(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    install_bindings(
        monkeypatch,
        project_receipt=False,
        revision_scope="MERCHANT",
    )

    command = (
        project_create_with_reuse()
        + (
            " "
            f"--reused-document-revision-id "
            f"{REVISION_ID}"
        )
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                command
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )


@pytest.mark.parametrize(
    "command",
    (
        (
            "python "
            ".claude/agents/tools/merchant/agent_cli.py "
            f"document approve {REVISION_ID} "
            "--role LEGAL "
            "--status APPROVED "
            "--propose "
            "&& echo done"
        ),
        (
            "python "
            ".claude/agents/tools/merchant/agent_cli.py "
            f"document approve {REVISION_ID} "
            "--role LEGAL "
            "--status APPROVED "
            "--propose | cat"
        ),
    ),
)
def test_wrapped_revision_consumer_is_blocked(
    command,
):
    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                command
            ),
            "pane-1",
        )
    )

    assert_denied(
        decision
    )

    assert (
        "invoked directly"
        in deny_reason(
            decision
        )
    )


def test_unrelated_command_needs_no_revision_binding(
    monkeypatch,
):
    install_owner(
        monkeypatch
    )

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            payload(
                "python "
                ".claude/agents/tools/merchant/agent_cli.py "
                f"project show {PROJECT_ID}"
            ),
            "pane-1",
        )
    )

    assert decision is None


def test_wrong_agent_type_is_ignored():
    value = payload(
        document_approve()
    )

    value[
        "agent_type"
    ] = "reviewer"

    decision = (
        policy_gate
        .document_revision_resolution_use_decision(
            value,
            "pane-1",
        )
    )

    assert decision is None
