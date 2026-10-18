"""Regression tests for shared Merchant resolution CLI preflight."""

import pytest

from claude.hooks import policy_gate


@pytest.mark.parametrize(
    "agent_type,tool_name,tool_input",
    [
        ("reviewer", "Bash", {"command": "test"}),
        ("merchant-manager", "Read", {"command": "test"}),
        ("merchant-manager", "Bash", "not-a-dict"),
        ("merchant-manager", "PowerShell", None),
    ],
)
def test_preflight_ignores_out_of_scope_payload(
    monkeypatch,
    agent_type,
    tool_name,
    tool_input,
):
    def unexpected_parser(_):
        raise AssertionError("Parser must not run")

    monkeypatch.setattr(
        policy_gate,
        "_direct_merchant_agent_cli_tokens",
        unexpected_parser,
    )

    result = policy_gate._resolution_cli_preflight({
        "agent_type": agent_type,
        "tool_name": tool_name,
        "tool_input": tool_input,
    })

    assert result is None


@pytest.mark.parametrize("tool_name", ["Bash", "PowerShell"])
def test_preflight_passes_exact_command_to_parser(
    monkeypatch,
    tool_name,
):
    observed = []

    def parser(command):
        observed.append(command)
        return ("merchant", "list")

    monkeypatch.setattr(
        policy_gate,
        "_direct_merchant_agent_cli_tokens",
        parser,
    )

    command = "example-command"

    result = policy_gate._resolution_cli_preflight({
        "agent_type": policy_gate.MERCHANT_MANAGER_AGENT,
        "tool_name": tool_name,
        "tool_input": {"command": command},
    })

    assert observed == [command]
    assert result == (("merchant", "list"), command)


def test_preflight_preserves_none_parser_result(
    monkeypatch,
):
    monkeypatch.setattr(
        policy_gate,
        "_direct_merchant_agent_cli_tokens",
        lambda command: None,
    )

    command = "python .claude/agents/tools/merchant/agent_cli.py"

    result = policy_gate._resolution_cli_preflight({
        "agent_type": policy_gate.MERCHANT_MANAGER_AGENT,
        "tool_name": "Bash",
        "tool_input": {"command": command},
    })

    assert result == (None, command)
