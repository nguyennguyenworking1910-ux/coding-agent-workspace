"""Team reporting and fail-closed authority tests for Merchant Manager."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from claude.agents.tools.merchant import agent_cli
from claude.agents.tools.merchant.agent_cli import (
    MerchantAgentCliError,
    invoke_agent_cli,
    main,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_PATH = (
    PROJECT_ROOT
    / ".claude"
    / "agents"
    / "merchant-manager.md"
)
REGISTRY_PATH = PROJECT_ROOT / ".claude" / "agents.json"
SOLVE_PATH = (
    PROJECT_ROOT
    / ".claude"
    / "commands"
    / "solve.md"
)


def _agent_content() -> str:
    return AGENT_PATH.read_text(encoding="utf-8")


def _solve_content() -> str:
    return SOLVE_PATH.read_text(encoding="utf-8")


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _frontmatter() -> dict[str, str]:
    fields = {}

    for line in _agent_content().splitlines()[1:]:
        if line == "---":
            break

        key, separator, value = line.partition(":")

        if separator:
            fields[key.strip()] = value.strip()

    return fields


def _valid_apply_arguments(*extra: str) -> list[str]:
    return [
        "merchant",
        "create",
        "--apply",
        "--proposal-hash",
        "a" * 64,
        "--code",
        "SAFE",
        "--name",
        "Fictitious Merchant",
        *extra,
    ]


def test_agent_frontmatter_exposes_only_supported_team_tools():
    assert _frontmatter()["tools"] == (
        "Read, Bash, SendMessage, TaskUpdate"
    )


def test_registry_team_tools_match_agent_frontmatter():
    entry = next(
        agent
        for agent in _registry()["agents"]
        if agent["id"] == "merchant-manager"
    )

    assert entry["tools"] == [
        "Read",
        "Bash",
        "SendMessage",
        "TaskUpdate",
    ]


def test_solve_requires_complete_merchant_assignment_fields():
    content = _solve_content()

    assert "Every Merchant assignment must explicitly declare" in content
    assert "`database_target: runtime`" in content
    assert "`authorized_mode: READ`" in content
    assert "`authorized_mode: PROPOSE`" in content
    assert "database and credential arguments are forbidden" in content
    assert "runtime `--apply` is outside Checkpoint 6 authority" in (
        content
    )


def test_incomplete_merchant_assignment_stops_dispatch():
    content = _solve_content()

    assert "If any required field is missing" in content
    assert "do not improvise it" in content
    assert "Stop the\nMerchant dispatch" in content


def test_missing_selected_agent_authority_has_no_lead_fallback():
    content = _solve_content()

    assert "`merchant-manager` is absent from" in content
    assert "report the authorization mismatch and stop" in content
    assert "The lead must never run the Merchant CLI" in content
    assert "move an unauthorized\n  Merchant operation" in content


def test_other_roles_cannot_execute_operational_merchant_cli():
    content = _solve_content()

    assert "Do not route Merchant operations to `coder`" in content
    assert "`bug-fixer`" in content
    assert "`diagnostician`" in content
    assert "may not execute operational Merchant CLI commands" in content


def test_write_assignment_is_proposal_only():
    content = _solve_content()

    assert "A Merchant write-intent proposal may be assigned only" in (
        content
    )
    assert "redacted `--propose` result" in content
    assert "no change may be applied" in content


def test_runtime_apply_waits_for_checkpoint_7_handoff():
    agent = _agent_content()
    solve = _solve_content()

    assert "do not execute any runtime command in `--apply` mode" in agent
    assert "Runtime `--apply` remains unavailable in Checkpoint 6" in (
        solve
    )
    assert "Checkpoint 7 intent/policy authorization handoff" in solve


def test_task_update_occurs_before_final_send_message():
    content = _agent_content()
    reporting = content[content.index("## Delivering your result to the lead") :]

    task_update = reporting.index("mark it completed with `TaskUpdate`")
    send_message = reporting.index("final action")

    assert task_update < send_message


def test_final_action_delivers_complete_report_with_send_message():
    content = _agent_content()

    assert "ordinary final text in your pane is not delivered" in content
    assert "As your **final action**" in content
    assert "send the complete report to `team-lead`" in content
    assert "with `SendMessage`" in content


def test_merchant_report_contains_every_required_field():
    content = _agent_content()

    assert "operation, database, mode" in content
    assert "redacted CLI result" in content
    assert "exit outcome" in content
    assert "confirmation state" in content
    assert "failures, and unresolved work" in content


def test_delivery_retry_does_not_repeat_merchant_command():
    content = _agent_content()

    assert "retry it once" in content
    assert "Never repeat a Merchant command" in content
    assert "message-delivery\nfailure" in content


def test_solve_ledger_accepts_only_complete_send_message():
    content = _solve_content()

    assert "For the Merchant report ledger" in content
    assert "accept delivery only when `SendMessage`" in content
    assert "`TaskUpdate`, pane\ntext, and idle notifications" in content
    assert "do not establish Merchant result delivery" in content


def test_environment_variables_cannot_unlock_apply(monkeypatch):
    monkeypatch.setenv("MERCHANT_RUNTIME_AUTHORIZED", "true")
    monkeypatch.setenv("MERCHANT_CONFIRMED", "true")
    factory_called = False

    def factory(database):
        nonlocal factory_called
        factory_called = True
        raise AssertionError("Apply must be denied before dispatch")

    with pytest.raises(MerchantAgentCliError, match="may not apply"):
        invoke_agent_cli(
            _valid_apply_arguments(),
            write_command_factory=factory,
        )

    assert factory_called is False


@pytest.mark.parametrize(
    "flag",
    (
        "--confirmed",
        "--confirmation",
        "--runtime-authorized",
    ),
)
def test_confirmation_like_flags_cannot_unlock_apply(flag):
    factory_called = False

    def factory(database):
        nonlocal factory_called
        factory_called = True
        raise AssertionError("Apply must be denied before dispatch")

    with pytest.raises(MerchantAgentCliError):
        invoke_agent_cli(
            _valid_apply_arguments(flag),
            write_command_factory=factory,
        )

    assert factory_called is False


def test_apply_denial_is_safe_json_and_does_not_echo_payload(capsys):
    exit_code = main(_valid_apply_arguments())

    captured = capsys.readouterr()
    result = json.loads(captured.err)
    assert exit_code == 2
    assert captured.out == ""
    assert result["success"] is False
    assert result["error"]["type"] == "MerchantAgentCliError"
    assert "Fictitious Merchant" not in captured.err
    assert "a" * 64 not in captured.err


def test_agent_interface_exposes_no_runtime_authority_parameter():
    signature = inspect.signature(invoke_agent_cli)

    assert "runtime_authorized" not in signature.parameters
    assert "confirmed" not in signature.parameters


def test_agent_interface_does_not_read_authority_from_environment():
    source = inspect.getsource(agent_cli)

    assert "os.environ" not in source
    assert "os.getenv" not in source
    assert "getenv(" not in source


def test_proposal_hash_is_binding_not_authority_everywhere():
    agent = _agent_content()
    solve = _solve_content()

    assert "proposal hash is payload binding, not permission" in agent
    assert "It is not permission, a\n  credential" in solve
