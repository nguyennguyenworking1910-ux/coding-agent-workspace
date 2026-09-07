"""Checkpoint 7.5 persisted policy-state to Merchant apply tests."""

import inspect
import json
import threading

import pytest

from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)
from claude.hooks import policy_gate, runtime_state
from claude.system import merchant_runtime_handoff
from claude.system.merchant_runtime_handoff import (
    MerchantRuntimeHandoffError,
    invoke_confirmed_merchant_session_apply,
)


SESSION_ID = "checkpoint-7-gate-5-session"
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
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, payload):
        self.calls.append(payload)

        if self.error is not None:
            raise self.error

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


def _initial_state(proposal, **changes):
    state = runtime_state.new_state(
        request="Apply the exact Merchant project update proposal",
        task_class="medium_task",
        risk_level="external_write",
        selected_agents=["merchant-manager"],
        operations=["merchant_apply"],
        limits={
            "max_members": 1,
            "max_tool_rounds": 1,
            "max_total_tool_calls": 10,
            "max_run_budget_usd": 2.0,
        },
        confirmed=True,
        merchant_confirmation=proposal["confirmation"],
    )
    state.update(changes)
    return state


def _dispatch_prompt(proposal, **changes):
    authorization = {
        **proposal["confirmation"],
        "authorized_mode": policy_gate.MERCHANT_DISPATCH_MODE,
    }
    authorization.update(changes)
    return (
        "Apply only the exact confirmed Merchant proposal.\n\n"
        f"{policy_gate.MERCHANT_DISPATCH_MARKER}\n"
        "```json\n"
        f"{json.dumps(authorization, indent=2, sort_keys=True)}\n"
        "```\n"
    )


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


def _save_and_accept_dispatch(proposal, session_id=SESSION_ID):
    runtime_state.save_state(session_id, _initial_state(proposal))

    with runtime_state.locked_state(session_id) as state:
        decision = policy_gate.apply_call(
            state,
            "Agent",
            {
                "subagent_type": "merchant-manager",
                "name": "merchant-manager",
                "prompt": _dispatch_prompt(proposal),
            },
        )

    assert decision is None


@pytest.fixture(autouse=True)
def isolated_runtime_state(tmp_path, monkeypatch):
    monkeypatch.setenv(
        runtime_state.STATE_DIR_ENV_VAR,
        str(tmp_path),
    )


def test_accepted_policy_session_reaches_repository_once(capsys):
    proposal, commands, handler = _proposal_and_commands()
    _save_and_accept_dispatch(proposal)

    exit_code = invoke_confirmed_merchant_session_apply(
        SESSION_ID,
        _apply_arguments(proposal),
        write_command_factory=lambda database: commands,
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["success"] is True
    assert output["mode"] == "APPLY"
    assert output["database"] == "runtime"
    assert handler.calls == [PAYLOAD]

    stored = runtime_state.load_state(SESSION_ID)
    assert stored["merchant_dispatch_spent"] is True
    assert stored["merchant_runtime_authorization_issued"] is True

    with pytest.raises(MerchantRuntimeHandoffError, match="already issued"):
        invoke_confirmed_merchant_session_apply(
            SESSION_ID,
            _apply_arguments(proposal),
            write_command_factory=lambda database: commands,
        )

    assert len(handler.calls) == 1


def test_payload_mismatch_is_spent_before_repository_handler(capsys):
    proposal, commands, handler = _proposal_and_commands()
    _save_and_accept_dispatch(proposal)

    exit_code = invoke_confirmed_merchant_session_apply(
        SESSION_ID,
        _apply_arguments(proposal, status="BLOCKED"),
        write_command_factory=lambda database: commands,
    )

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 1
    assert error["error"]["type"] == "RuntimeWriteDeniedError"
    assert handler.calls == []
    assert runtime_state.load_state(SESSION_ID)[
        "merchant_runtime_authorization_issued"
    ] is True


def test_handler_failure_remains_non_retryable(capsys):
    handler = RecordingHandler(error=RuntimeError("adapter failed"))
    proposal, commands, _ = _proposal_and_commands(handler)
    _save_and_accept_dispatch(proposal)

    exit_code = invoke_confirmed_merchant_session_apply(
        SESSION_ID,
        _apply_arguments(proposal),
        write_command_factory=lambda database: commands,
    )

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 1
    assert error["error"]["type"] == "MerchantCommandError"
    assert error["error"]["message"] == "Merchant command failed"
    assert len(handler.calls) == 1

    with pytest.raises(MerchantRuntimeHandoffError, match="already issued"):
        invoke_confirmed_merchant_session_apply(
            SESSION_ID,
            _apply_arguments(proposal),
            write_command_factory=lambda database: commands,
        )


@pytest.mark.parametrize(
    "dispatch_change",
    (
        {"command": "step update"},
        {"database_target": "test"},
        {"expected_version": 4},
        {"payload_hash": "0" * 64},
        {"proposal_hash": "0" * 64},
        {"confirmation_hash": "0" * 64},
        {"authorized_mode": "APPLY"},
    ),
)
def test_denied_dispatch_never_creates_runtime_authority(
    dispatch_change,
):
    proposal, commands, handler = _proposal_and_commands()
    runtime_state.save_state(
        SESSION_ID,
        _initial_state(proposal),
    )

    with runtime_state.locked_state(SESSION_ID) as state:
        decision = policy_gate.apply_call(
            state,
            "Agent",
            {
                "subagent_type": "merchant-manager",
                "name": "merchant-manager",
                "prompt": _dispatch_prompt(
                    proposal,
                    **dispatch_change,
                ),
            },
        )

    assert decision["hookSpecificOutput"][
        "permissionDecision"
    ] == "deny"

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke_confirmed_merchant_session_apply(
            SESSION_ID,
            _apply_arguments(proposal),
            write_command_factory=lambda database: commands,
        )

    assert handler.calls == []
    stored = runtime_state.load_state(SESSION_ID)
    assert "merchant_dispatch_spent" not in stored
    assert "merchant_runtime_authorization_issued" not in stored


@pytest.mark.parametrize(
    "state_change",
    (
        {"selected_agents": ["coder"]},
        {"risk_level": "write"},
        {"confirmed": False},
        {"merchant_dispatch_spent": False},
        {"merchant_confirmation": None},
        {"merchant_dispatch": None},
        {"merchant_runtime_authorization_issued": False},
        {"merchant_runtime_authorization_issued": 1},
        {"merchant_runtime_authorization_issued": "yes"},
    ),
)
def test_tampered_persisted_state_stops_before_factory(state_change):
    proposal, commands, handler = _proposal_and_commands()
    _save_and_accept_dispatch(proposal)
    stored = runtime_state.load_state(SESSION_ID)
    stored.update(state_change)
    runtime_state.save_state(SESSION_ID, stored)
    factory_called = False

    def factory(database):
        nonlocal factory_called
        factory_called = True
        return commands

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke_confirmed_merchant_session_apply(
            SESSION_ID,
            _apply_arguments(proposal),
            write_command_factory=factory,
        )

    assert factory_called is False
    assert handler.calls == []


def test_tampered_receipt_spends_persisted_slot_before_issuance():
    proposal, commands, handler = _proposal_and_commands()
    _save_and_accept_dispatch(proposal)
    stored = runtime_state.load_state(SESSION_ID)
    stored["merchant_dispatch"]["confirmation_hash"] = "0" * 64
    runtime_state.save_state(SESSION_ID, stored)

    with pytest.raises(Exception, match="accepted dispatch receipt"):
        invoke_confirmed_merchant_session_apply(
            SESSION_ID,
            _apply_arguments(proposal),
            write_command_factory=lambda database: commands,
        )

    assert handler.calls == []
    assert runtime_state.load_state(SESSION_ID)[
        "merchant_runtime_authorization_issued"
    ] is True


def test_concurrent_session_replay_runs_one_handler(capsys):
    proposal, commands, handler = _proposal_and_commands()
    _save_and_accept_dispatch(proposal)
    outcomes = []

    def attempt():
        try:
            exit_code = invoke_confirmed_merchant_session_apply(
                SESSION_ID,
                _apply_arguments(proposal),
                write_command_factory=lambda database: commands,
            )
            outcomes.append(f"exit:{exit_code}")
        except MerchantRuntimeHandoffError:
            outcomes.append("denied")

    threads = [threading.Thread(target=attempt) for _ in range(2)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    capsys.readouterr()
    assert sorted(outcomes) == ["denied", "exit:0"]
    assert len(handler.calls) == 1


@pytest.mark.parametrize("session_id", (None, "", "   "))
def test_missing_or_invalid_session_never_reaches_factory(session_id):
    proposal, commands, handler = _proposal_and_commands()
    factory_called = False

    def factory(database):
        nonlocal factory_called
        factory_called = True
        return commands

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke_confirmed_merchant_session_apply(
            session_id,
            _apply_arguments(proposal),
            write_command_factory=factory,
        )

    assert factory_called is False
    assert handler.calls == []


def test_unknown_session_never_reaches_factory():
    proposal, commands, handler = _proposal_and_commands()
    factory_called = False

    def factory(database):
        nonlocal factory_called
        factory_called = True
        return commands

    with pytest.raises(
        MerchantRuntimeHandoffError,
        match="No trusted Merchant run state",
    ):
        invoke_confirmed_merchant_session_apply(
            "unknown-session",
            _apply_arguments(proposal),
            write_command_factory=factory,
        )

    assert factory_called is False
    assert handler.calls == []


def test_session_handoff_exposes_no_state_or_authority_override():
    signature = inspect.signature(
        invoke_confirmed_merchant_session_apply
    )
    source = inspect.getsource(merchant_runtime_handoff)

    assert set(signature.parameters) == {
        "session_id",
        "arguments",
        "write_command_factory",
    }
    assert "trusted_state" not in signature.parameters
    assert "runtime_authorization" not in signature.parameters
    assert "confirmation_token" not in signature.parameters
    assert "database" not in signature.parameters
    assert "if __name__" not in source
    assert "os.environ" not in source
    assert "os.getenv" not in source
