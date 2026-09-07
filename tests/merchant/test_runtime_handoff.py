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
    MerchantRuntimeHandoffError,
    invoke_confirmed_merchant_apply,
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


def _trusted_state(proposal, **changes):
    confirmation = proposal["confirmation"]
    state = {
        "request": "Apply the exact Merchant project update proposal",
        "operations": ["merchant_apply"],
        "selected_agents": ["merchant-manager"],
        "risk_level": "external_write",
        "confirmed": True,
        "merchant_dispatch_spent": True,
        "merchant_confirmation": confirmation,
        "merchant_dispatch": {
            "operation": "merchant_apply",
            "subagent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
            "confirmation_hash": confirmation[
                "confirmation_hash"
            ],
        },
    }
    state.update(changes)
    return state


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


def test_trusted_handoff_applies_exact_proposal_once(capsys):
    proposal, commands, handler = _proposal_and_commands()
    state = _trusted_state(proposal)

    exit_code = invoke_confirmed_merchant_apply(
        _apply_arguments(proposal),
        trusted_state=state,
        write_command_factory=lambda database: commands,
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["success"] is True
    assert output["mode"] == "APPLY"
    assert output["database"] == "runtime"
    assert handler.calls == [PAYLOAD]
    assert state["merchant_runtime_authorization_issued"] is True

    with pytest.raises(
        MerchantRuntimeHandoffError,
        match="already issued",
    ):
        invoke_confirmed_merchant_apply(
            _apply_arguments(proposal),
            trusted_state=state,
            write_command_factory=lambda database: commands,
        )

    assert len(handler.calls) == 1


def test_mismatched_apply_is_safe_failed_and_cannot_retry(capsys):
    proposal, commands, handler = _proposal_and_commands()
    state = _trusted_state(proposal)

    exit_code = invoke_confirmed_merchant_apply(
        _apply_arguments(proposal, status="BLOCKED"),
        trusted_state=state,
        write_command_factory=lambda database: commands,
    )

    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert exit_code == 1
    assert captured.out == ""
    assert error["error"]["type"] == "RuntimeWriteDeniedError"
    assert "does not match the confirmed proposal" in (
        error["error"]["message"]
    )
    assert handler.calls == []
    assert state["merchant_runtime_authorization_issued"] is True

    with pytest.raises(MerchantRuntimeHandoffError, match="already issued"):
        invoke_confirmed_merchant_apply(
            _apply_arguments(proposal),
            trusted_state=state,
            write_command_factory=lambda database: commands,
        )


@pytest.mark.parametrize(
    "change",
    (
        {"operations": ["merchant_propose"]},
        {"operations": ["merchant_apply", "schedule"]},
        {"selected_agents": ["coder"]},
        {"selected_agents": ["merchant-manager", "coder"]},
        {"risk_level": "write"},
        {"confirmed": False},
        {"merchant_dispatch_spent": False},
        {"merchant_confirmation": None},
        {"merchant_dispatch": None},
        {"confirmation_token": "must-not-be-accepted"},
    ),
)
def test_untrusted_state_stops_before_cli_factory(change):
    proposal, _commands, _handler = _proposal_and_commands()
    state = _trusted_state(proposal, **change)
    factory_called = False

    def factory(database):
        nonlocal factory_called
        factory_called = True
        raise AssertionError("Untrusted state must stop first")

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke_confirmed_merchant_apply(
            _apply_arguments(proposal),
            trusted_state=state,
            write_command_factory=factory,
        )

    assert factory_called is False
    assert "merchant_runtime_authorization_issued" not in state


@pytest.mark.parametrize(
    "arguments",
    (
        ["--database", "test", "merchant", "list"],
        ["--database=runtime", "merchant", "list"],
        ["--password", "private", "merchant", "list"],
        ["merchant", "list"],
        [
            "project",
            "update",
            PROJECT_ID,
            "--propose",
            "--status",
            "IN_PROGRESS",
            "--expected-version",
            "3",
        ],
    ),
)
def test_handoff_rejects_target_credentials_read_or_propose(arguments):
    proposal, commands, _handler = _proposal_and_commands()
    state = _trusted_state(proposal)

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke_confirmed_merchant_apply(
            arguments,
            trusted_state=state,
            write_command_factory=lambda database: commands,
        )


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
    signature = inspect.signature(invoke_confirmed_merchant_apply)

    assert "if __name__" not in source
    assert "os.environ" not in source
    assert "os.getenv" not in source
    assert "runtime_authorized" not in source
    assert "runtime_authorized" not in signature.parameters
    assert "confirmation_token" not in signature.parameters
    assert "database" not in signature.parameters
    assert "clock" not in signature.parameters
    assert "ttl_seconds" not in signature.parameters
