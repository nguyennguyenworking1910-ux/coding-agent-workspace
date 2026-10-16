"""Direct Merchant scope: user prompt through trusted runtime handoff."""

import json

import pytest

from claude.hooks import intent_gate, policy_gate, runtime_state
from claude.hooks import intent_envelope_bridge
from claude.agents.tools.merchant.write_commands import MerchantWriteCommands
from claude.system.merchant_runtime_handoff import (
    MerchantRuntimeHandoffError,
    invoke_authorized_scope_apply,
)

SESSION_ID = "checkpoint-3d-direct-e2e"
PROJECT_ID = "00000000-0000-0000-0000-000000000001"

ARGV = [
    "project", "update", PROJECT_ID,
    "--status", "IN_PROGRESS",
    "--expected-version", "3",
]

REQUEST = f"Update project {PROJECT_ID} to IN_PROGRESS"


class FakeParser:
    def __init__(self):
        self.requests = []

    def parse(self, request):
        self.requests.append(request)
        return {
            "request_id": "checkpoint-3d-request",
            "raw_request": request,
            "task_class": "small_task",
            "risk_level": "external_write",
            "confidence": 0.99,
            "complexity_score": 1,
            "domains": ["merchant"],
            "operations": ["merchant_apply"],
            "selected_agents": ["merchant-manager"],
            "limits": {
                "max_members": 1,
                "max_tool_rounds": 1,
                "max_total_tool_calls": 10,
                "max_run_budget_usd": 1.0,
            },
            "reasons": ["Explicit project update"],
            "requires_clarification": False,
            "requires_confirmation": True,
        }


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv(
        runtime_state.STATE_DIR_ENV_VAR,
        str(tmp_path / "runtime"),
    )
    monkeypatch.setenv(
        intent_envelope_bridge.ENVELOPE_DIR_ENV_VAR,
        str(tmp_path / "envelopes"),
    )


def submit(*, confirmed=True):
    parser = FakeParser()
    prefix = "/solve --confirm" if confirmed else "/solve"
    prompt = (
        f"{prefix} --merchant-scope "
        f"{json.dumps(ARGV)} {REQUEST}"
    )

    result = intent_gate.run(
        {
            "hook_event_name": "UserPromptExpansion",
            "session_id": SESSION_ID,
            "prompt": prompt,
        },
        parser_factory=lambda: parser,
        env={},
    )
    return result, parser


def dispatch():
    with runtime_state.locked_state(SESSION_ID) as state:
        assert state is not None
        return policy_gate.apply_call(
            state,
            "Agent",
            {
                "subagent_type": "merchant-manager",
                "name": "merchant-manager",
                "prompt": "Apply the user-authorized scope.",
            },
        )


def test_user_confirmed_scope_reaches_handler_once(capsys):
    result, parser = submit()

    assert "hookSpecificOutput" in result
    assert parser.requests == [REQUEST]

    state = runtime_state.load_state(SESSION_ID)
    assert state["confirmed"] is True
    assert state["merchant_scope"]["argv"] == ARGV
    assert state["merchant_scope"]["run_id"] == state["run_id"]
    assert "merchant_confirmation" not in state

    decision = dispatch()
    assert decision is None

    calls = []

    def handler(payload):
        calls.append(payload)
        return {"status": "committed"}

    commands = MerchantWriteCommands({"project update": handler})

    exit_code = invoke_authorized_scope_apply(
        SESSION_ID,
        ARGV,
        write_command_factory=lambda database: commands,
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["database"] == "runtime"
    assert len(calls) == 1
    assert calls[0]["project_id"] == PROJECT_ID

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke_authorized_scope_apply(
            SESSION_ID,
            ARGV,
            write_command_factory=lambda database: commands,
        )

    assert len(calls) == 1


def test_direct_scope_executes_without_legacy_confirmation(
    monkeypatch, capsys
):
    def forbidden_legacy(*args, **kwargs):
        raise AssertionError(
            "Direct Scope must not use legacy confirmation"
        )

    monkeypatch.setattr(
        intent_gate,
        "authorize_local_auto_apply",
        forbidden_legacy,
    )
    monkeypatch.setattr(
        intent_gate,
        "load_merchant_confirmation",
        forbidden_legacy,
    )

    result, _ = submit()
    assert "hookSpecificOutput" in result
    assert dispatch() is None

    calls = []
    commands = MerchantWriteCommands({
        "project update": lambda payload: (
            calls.append(payload) or {"status": "committed"}
        )
    })

    exit_code = invoke_authorized_scope_apply(
        SESSION_ID,
        ARGV,
        write_command_factory=lambda database: commands,
    )

    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["mode"] == "EXECUTE"
    assert output["database"] == "runtime"
    assert len(calls) == 1


def test_unconfirmed_scope_does_not_create_write_session():
    result, parser = submit(confirmed=False)

    assert "hookSpecificOutput" not in result
    assert parser.requests == []
    assert runtime_state.load_state(SESSION_ID) is None


def test_changed_target_never_reaches_handler():
    result, _ = submit()
    assert "hookSpecificOutput" in result
    assert dispatch() is None

    calls = []
    commands = MerchantWriteCommands(
        {"project update": lambda payload: calls.append(payload)}
    )
    changed = list(ARGV)
    changed[2] = "00000000-0000-0000-0000-000000000099"

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke_authorized_scope_apply(
            SESSION_ID,
            changed,
            write_command_factory=lambda database: commands,
        )

    assert calls == []


def test_direct_scope_expansion_submit_preserves_authorization():
    parser = FakeParser()
    prompt = (
        "/solve --confirm --merchant-scope "
        f"{json.dumps(ARGV)} {REQUEST}"
    )

    expansion = intent_gate.run(
        {
            "hook_event_name": "UserPromptExpansion",
            "session_id": SESSION_ID,
            "prompt": prompt,
        },
        parser_factory=lambda: parser,
        env={},
    )

    assert "hookSpecificOutput" in expansion

    first = runtime_state.load_state(SESSION_ID)
    first_run = first["run_id"]
    first_scope = dict(first["merchant_scope"])

    submit_output = intent_gate.run(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": SESSION_ID,
            "prompt": prompt,
        },
        parser_factory=lambda: parser,
        env={},
    )

    second = runtime_state.load_state(SESSION_ID)

    assert submit_output == {}
    assert parser.requests == [REQUEST]
    assert second["run_id"] == first_run
    assert second["merchant_scope"] == first_scope


# Checkpoint 3D-D.2: trusted Direct Scope handoff staging.
from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_STATE_KEY,
    HANDOFF_PENDING,
    stage_runtime_handoff_attempt,
)
from claude.system.merchant_runtime_handoff import validate_direct_scope


def _direct_staging_candidate(arguments=None):
    validated = validate_direct_scope(ARGV)

    return {
        "contract_version": 1,
        "operation": "merchant_apply",
        "database_target": "runtime",
        "confirmation_hash": validated["confirmation_hash"],
        "arguments": tuple(ARGV if arguments is None else arguments),
    }


def _stage_direct_candidate(state, candidate):
    return stage_runtime_handoff_attempt(
        state,
        owner_session_id=SESSION_ID,
        teammate_name="merchant-manager",
        run_id=state["run_id"],
        task_id="checkpoint-3d-direct-task",
        candidate=candidate,
    )


def test_direct_scope_staging_accepts_exact_authorized_arguments():
    submit()
    dispatch()

    with runtime_state.locked_state(SESSION_ID) as state:
        assert state is not None
        candidate = _direct_staging_candidate()

        attempt, reason = _stage_direct_candidate(
            state, candidate
        )

        assert reason == ""
        assert attempt is not None
        assert attempt.arguments == tuple(ARGV)
        assert attempt.confirmation_hash == candidate["confirmation_hash"]
        assert state[HANDOFF_STATE_KEY]["status"] == HANDOFF_PENDING


def test_direct_scope_staging_rejects_changed_arguments():
    submit()
    dispatch()

    changed = list(ARGV)
    changed[2] = "00000000-0000-0000-0000-000000000099"

    with runtime_state.locked_state(SESSION_ID) as state:
        assert state is not None

        attempt, reason = _stage_direct_candidate(
            state,
            _direct_staging_candidate(changed),
        )

        assert attempt is None
        assert reason
        assert HANDOFF_STATE_KEY not in state


def test_direct_scope_staging_rejects_replay():
    submit()
    dispatch()

    with runtime_state.locked_state(SESSION_ID) as state:
        assert state is not None
        candidate = _direct_staging_candidate()

        first, first_reason = _stage_direct_candidate(
            state, candidate
        )
        second, second_reason = _stage_direct_candidate(
            state, candidate
        )

        assert first is not None
        assert first_reason == ""
        assert second is None
        assert second_reason
        assert state[HANDOFF_STATE_KEY]["status"] == HANDOFF_PENDING


@pytest.mark.parametrize(
    "change",
    ["different_scope", "missing_confirmation"],
)
def test_direct_scope_submit_rejects_changed_authorization(change):
    # Establish the original authorization through the real Intent Gate.
    result, _ = submit()
    assert "hookSpecificOutput" in result

    original = runtime_state.load_state(SESSION_ID)
    assert original is not None

    original_scope = dict(original["merchant_scope"])
    original_run = original["run_id"]

    if change == "different_scope":
        changed_argv = list(ARGV)
        changed_argv[2] = (
            "00000000-0000-0000-0000-000000000099"
        )
        followup = (
            "/solve --confirm --merchant-scope "
            f"{json.dumps(changed_argv)} {REQUEST}"
        )
    else:
        followup = (
            "/solve --merchant-scope "
            f"{json.dumps(ARGV)} {REQUEST}"
        )

    parser = FakeParser()

    outcome = intent_gate.run(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": SESSION_ID,
            "prompt": followup,
        },
        parser_factory=lambda: parser,
        env={},
    )

    current = runtime_state.load_state(SESSION_ID)

    assert current is not None
    assert current["run_id"] == original_run
    assert current["merchant_scope"] == original_scope

    # A changed authorization must not be silently accepted as the
    # already-validated Expansion event.
    assert outcome != {}, (
        "Changed Submit authorization was silently accepted"
    )


def test_direct_scope_runtime_rejects_unconfirmed_state():
    submit()
    dispatch()

    with runtime_state.locked_state(SESSION_ID) as state:
        assert state is not None
        assert state["merchant_scope"]
        state["confirmed"] = False

    called = []

    def fake_factory(database):
        called.append(database)
        raise AssertionError("Unconfirmed state reached runtime factory")

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke_authorized_scope_apply(
            SESSION_ID,
            ARGV,
            write_command_factory=fake_factory,
        )

    assert called == []
