import json

import pytest

from claude.hooks.merchant_execute_invocation import (
    validated_merchant_execute_invocation,
)
from claude.hooks.merchant_tool_result_contract import (
    merchant_execute_from_tool_response,
)


def make_event(command):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {
            "stdout": json.dumps({
                "success": True,
                "mode": "EXECUTE",
                "command": "merchant create",
                "database": "runtime",
                "result": {"merchant_id": "example"},
            })
        },
    }


def observe(payload):
    result = merchant_execute_from_tool_response(payload)

    if result is None:
        return None

    invocation = validated_merchant_execute_invocation(
        payload, result
    )

    if invocation is None:
        return None

    return result


def test_valid_command_is_structurally_accepted():
    payload = make_event(
        "python .claude/agents/tools/merchant/agent_cli.py "
        "merchant create --code TEST --name Test"
    )

    assert observe(payload) is not None


@pytest.mark.parametrize("command", [
    'echo "{\\"success\\":true}"',
    "python fake/agent_cli.py "
    "merchant create --code TEST --name Test",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant list",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --code TEST --name Test; echo OK",
    "python .claude/agents/tools/merchant/agent_cli.py "
    "merchant create --code TEST --name Test "
    "--database=test",
])
def test_forged_or_invalid_invocation_is_rejected(command):
    assert observe(make_event(command)) is None


def test_stdout_claim_does_not_modify_session():
    state = {
        "current_run_id": "run-1",
        "current_task_id": "task-1",
        "status": "RUNNING",
    }

    original = dict(state)

    observe(
        make_event(
            "python .claude/agents/tools/merchant/agent_cli.py "
            "merchant create --code TEST --name Test"
        )
    )

    assert state == original
    assert state["status"] == "RUNNING"
