import pytest

from claude.hooks.merchant_execute_invocation import (
    validated_merchant_execute_invocation,
)


def result():
    return {
        "success": True,
        "mode": "EXECUTE",
        "command": "merchant create",
        "database": "runtime",
        "result": {"merchant_id": "example"},
    }


def event(command):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def test_valid_direct_invocation():
    arguments = validated_merchant_execute_invocation(
        event(
            "python .claude/agents/tools/merchant/agent_cli.py "
            "merchant create --code TEST --name Test"
        ),
        result(),
    )

    assert arguments is not None
    assert "merchant" in arguments
    assert "create" in arguments


@pytest.mark.parametrize("command", [
    'echo "{\\"success\\":true}"',
    "python other.py merchant create --code TEST --name Test",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant list",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --code TEST --name Test; echo OK",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --code TEST --name Test | cat",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --code TEST --name Test && echo OK",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --database test --code TEST --name Test",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --propose --code TEST --name Test",
])
def test_invalid_invocations_rejected(command):
    assert validated_merchant_execute_invocation(
        event(command),
        result(),
    ) is None


def test_mismatched_result_rejected():
    response = result()
    response["command"] = "project create"

    assert validated_merchant_execute_invocation(
        event(
            "python .claude/agents/tools/merchant/agent_cli.py "
            "merchant create --code TEST --name Test"
        ),
        response,
    ) is None


@pytest.mark.parametrize("command", [
    "python fake/agent_cli.py merchant create --code TEST --name Test",
    "python agent_cli.py merchant create --code TEST --name Test",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --database=runtime --code TEST --name Test",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --database=test --code TEST --name Test",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --proposal-hash=abc --code TEST --name Test",
])
def test_rejects_script_impersonation_and_database_override(command):
    assert validated_merchant_execute_invocation(
        event(command),
        result(),
    ) is None
