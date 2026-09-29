from __future__ import annotations

from claude.hooks import policy_gate
from claude.hooks import team_result_hook


MERCHANT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
REVISION_ID = "41111111-1111-4111-8111-111111111111"


def _tokens(command: str):
    tokens = (
        policy_gate
        ._direct_merchant_agent_cli_tokens(
            command
        )
    )

    assert tokens is not None

    return tokens


def test_release_cleanup_is_child_first(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_document_revision_resolution",
        lambda pane: (
            calls.append(
                (
                    "document_revision",
                    pane,
                )
            )
            or True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_step_resolution",
        lambda pane: (
            calls.append(
                (
                    "step",
                    pane,
                )
            )
            or True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_project_resolution",
        lambda pane: (
            calls.append(
                (
                    "project",
                    pane,
                )
            )
            or True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda pane: (
            calls.append(
                (
                    "merchant",
                    pane,
                )
            )
            or True
        ),
    )

    team_result_hook._clear_merchant_resolution_after_release(
        "pane-1",
        "merchant-manager",
    )

    assert calls == [
        (
            "document_revision",
            "pane-1",
        ),
        (
            "step",
            "pane-1",
        ),
        (
            "project",
            "pane-1",
        ),
        (
            "merchant",
            "pane-1",
        ),
    ]


def test_release_cleanup_ignores_non_merchant_teammate(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_document_revision_resolution",
        lambda pane: (
            calls.append(
                "document_revision"
            )
            or True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_step_resolution",
        lambda pane: (
            calls.append(
                "step"
            )
            or True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_project_resolution",
        lambda pane: (
            calls.append(
                "project"
            )
            or True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda pane: (
            calls.append(
                "merchant"
            )
            or True
        ),
    )

    team_result_hook._clear_merchant_resolution_after_release(
        "pane-1",
        "reviewer",
    )

    assert calls == []


def test_release_cleanup_ignores_empty_pane(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_document_revision_resolution",
        lambda pane: (
            calls.append(
                "document_revision"
            )
            or True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_step_resolution",
        lambda pane: (
            calls.append(
                "step"
            )
            or True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_project_resolution",
        lambda pane: (
            calls.append(
                "project"
            )
            or True
        ),
        raising=False,
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda pane: (
            calls.append(
                "merchant"
            )
            or True
        ),
    )

    team_result_hook._clear_merchant_resolution_after_release(
        "",
        "merchant-manager",
    )

    assert calls == []


def test_document_approve_is_project_scoped_revision_consumer():
    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        f"document approve {REVISION_ID} "
        "--role LEGAL "
        "--status APPROVED "
        "--propose"
    )

    assert (
        policy_gate
        ._document_revision_id_from_cli_tokens(
            _tokens(
                command
            )
        )
        == (
            "document approve",
            REVISION_ID,
            "PROJECT",
        )
    )


def test_project_create_reuse_is_merchant_scoped_revision_consumer():
    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "project create "
        f"--merchant-id {MERCHANT_ID} "
        "--type MEDIA_TOP_UP "
        "--variant MEDIA_TOP_UP_EXISTING_DOCUMENT "
        f"--reused-document-revision-id {REVISION_ID} "
        "--propose"
    )

    assert (
        policy_gate
        ._document_revision_id_from_cli_tokens(
            _tokens(
                command
            )
        )
        == (
            "project create",
            REVISION_ID,
            "MERCHANT",
        )
    )


def test_project_create_reuse_equals_form_has_same_scope():
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

    assert (
        policy_gate
        ._document_revision_id_from_cli_tokens(
            _tokens(
                command
            )
        )
        == (
            "project create",
            REVISION_ID,
            "MERCHANT",
        )
    )


def test_project_create_without_reuse_is_not_revision_consumer():
    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "project create "
        f"--merchant-id {MERCHANT_ID} "
        "--type MEDIA_TOP_UP "
        "--variant STANDARD "
        "--propose"
    )

    assert (
        policy_gate
        ._document_revision_id_from_cli_tokens(
            _tokens(
                command
            )
        )
        == (
            "project create",
            None,
            None,
        )
    )


def test_document_revision_create_is_not_existing_revision_consumer():
    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "document revision-create "
        f"{PROJECT_ID} "
        "--type CONTRACT "
        "--content-hash abc123 "
        "--propose"
    )

    assert (
        policy_gate
        ._document_revision_id_from_cli_tokens(
            _tokens(
                command
            )
        )
        == (
            "document revision-create",
            None,
            None,
        )
    )


def test_document_resolve_establishes_but_does_not_consume_revision_binding():
    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        "document resolve "
        f"--project-id {PROJECT_ID} "
        '--query "CONTRACT#1"'
    )

    assert (
        policy_gate
        ._document_revision_id_from_cli_tokens(
            _tokens(
                command
            )
        )
        == (
            "document resolve",
            None,
            None,
        )
    )


def test_unrelated_project_update_is_not_revision_consumer():
    command = (
        "python "
        ".claude/agents/tools/merchant/agent_cli.py "
        f"project update {PROJECT_ID} "
        "--status IN_PROGRESS "
        "--expected-version 1 "
        "--propose"
    )

    assert (
        policy_gate
        ._document_revision_id_from_cli_tokens(
            _tokens(
                command
            )
        )
        == (
            "project update",
            None,
            None,
        )
    )


def test_revision_consumer_contract_is_exactly_two_command_families():
    commands = {
        "document approve": (
            "python "
            ".claude/agents/tools/merchant/agent_cli.py "
            f"document approve {REVISION_ID} "
            "--role LEGAL "
            "--status APPROVED "
            "--propose"
        ),
        "project create": (
            "python "
            ".claude/agents/tools/merchant/agent_cli.py "
            "project create "
            f"--merchant-id {MERCHANT_ID} "
            "--type MEDIA_TOP_UP "
            "--variant MEDIA_TOP_UP_EXISTING_DOCUMENT "
            f"--reused-document-revision-id {REVISION_ID} "
            "--propose"
        ),
    }

    observed = set()

    for (
        expected_command,
        command,
    ) in commands.items():
        (
            parsed_command,
            revision_id,
            scope,
        ) = (
            policy_gate
            ._document_revision_id_from_cli_tokens(
                _tokens(
                    command
                )
            )
        )

        assert (
            parsed_command
            == expected_command
        )

        assert (
            revision_id
            == REVISION_ID
        )

        assert scope in {
            "PROJECT",
            "MERCHANT",
        }

        observed.add(
            parsed_command
        )

    assert observed == {
        "document approve",
        "project create",
    }
