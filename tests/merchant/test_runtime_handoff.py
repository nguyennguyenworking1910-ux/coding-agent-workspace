"""Checkpoint 7.4 trusted in-process Merchant runtime handoff tests."""

import inspect
import json

import pytest

from claude.agents.tools.merchant.agent_cli import (
    MerchantAgentCliError,
    invoke_agent_cli,
)
from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)
from claude.system import merchant_runtime_handoff
from claude.system.merchant_runtime_handoff import (
    invoke_trusted_merchant_session_apply,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
PAYLOAD = {
    "project_id": PROJECT_ID,
    "status": "IN_PROGRESS",
    "expected_version": 3,
    "occurred_at": None,
    "triggered_by": None,
    "allow_reopen": False,
}


class RecordingHandler:
    def __init__(self):
        self.calls = []

    def __call__(self, payload):
        self.calls.append(payload)
        return {"status": "committed"}


def _proposal_and_commands(handler=None):
    selected_handler = handler or RecordingHandler()
    commands = MerchantWriteCommands(
        {"project update": selected_handler}
    )
    proposal = commands.propose(
        "project update",
        "runtime",
        PAYLOAD,
    )
    return proposal, commands, selected_handler


def _apply_arguments(proposal, *, status="IN_PROGRESS"):
    return [
        "project",
        "update",
        PROJECT_ID,
        "--apply",
        "--proposal-hash",
        proposal["proposal_hash"],
        "--status",
        status,
        "--expected-version",
        "3",
    ]


def test_ordinary_agent_cli_still_rejects_apply_before_factory():
    proposal, _commands, _handler = _proposal_and_commands()
    factory_called = False

    def factory(database):
        nonlocal factory_called
        factory_called = True
        raise AssertionError("Ordinary agent CLI must not dispatch apply")

    with pytest.raises(MerchantAgentCliError, match="may not apply"):
        invoke_agent_cli(
            _apply_arguments(proposal),
            write_command_factory=factory,
        )

    assert factory_called is False


def test_handoff_has_no_cli_main_environment_or_boolean_authority():
    source = inspect.getsource(merchant_runtime_handoff)
    signature = inspect.signature(invoke_trusted_merchant_session_apply)

    assert "if __name__" not in source
    assert "os.environ" not in source
    assert "os.getenv" not in source
    assert "runtime_authorized" not in source
    assert "runtime_authorized" not in signature.parameters
    assert "confirmation_token" not in signature.parameters
    assert "database" not in signature.parameters
    assert "clock" not in signature.parameters
    assert "ttl_seconds" not in signature.parameters
