"""Direct trusted-scope authorization at the runtime handoff boundary.

The policy-recorded dispatch is modelled directly in trusted session state
here. These tests pin the handoff's own boundary: exact argv, one-use
reservation, scope integrity and run binding. Fake handlers only.
"""

import pytest

from claude.agents.tools.merchant import cli
from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)
from claude.hooks import runtime_state
from claude.system.merchant_runtime_handoff import (
    MerchantRuntimeHandoffError,
    invoke_authorized_scope_apply,
    validate_direct_scope,
)


SESSION_ID = "direct-scope-session"
RUN_ID = "direct-scope-run"
PROJECT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_PROJECT_ID = "00000000-0000-0000-0000-000000000099"
MERCHANT_ID = "00000000-0000-0000-0000-000000000005"

AUTHORIZED_ARGV = [
    "project",
    "update",
    PROJECT_ID,
    "--status",
    "IN_PROGRESS",
    "--expected-version",
    "3",
]


class RecordingHandler:
    def __init__(self):
        self.calls = []

    def __call__(self, payload):
        self.calls.append(payload)
        return {"status": "committed"}


@pytest.fixture(autouse=True)
def isolated_runtime_state(tmp_path, monkeypatch):
    monkeypatch.setenv(runtime_state.STATE_DIR_ENV_VAR, str(tmp_path))


def _trusted_state(argv=AUTHORIZED_ARGV, **changes):
    """Model the state the intent gate and policy gate persist for a scope."""

    scope = validate_direct_scope(argv)
    state = runtime_state.new_state(
        request=f"Update project {PROJECT_ID} to IN_PROGRESS",
        task_class="medium_task",
        risk_level="external_write",
        selected_agents=["merchant-manager"],
        limits={
            "max_members": 1,
            "max_tool_rounds": 1,
            "max_total_tool_calls": 10,
            "max_run_budget_usd": 2.0,
        },
        confirmed=True,
        operations=["merchant_apply"],
        run_id=RUN_ID,
        merchant_scope={
            "argv": list(scope["argv"]),
            "command": scope["command"],
            "database_target": scope["database_target"],
            "scope_hash": scope["scope_hash"],
            "run_id": RUN_ID,
        },
    )
    state["merchant_dispatch_spent"] = True
    state["merchant_dispatch"] = {
        "operation": "merchant_apply",
        "subagent_type": "merchant-manager",
        "teammate_name": "merchant-manager",
        "confirmation_hash": scope["confirmation_hash"],
    }
    state.update(changes)
    return state


def _commands(handler):
    return MerchantWriteCommands({"project update": handler})


def _invoke(argv, handler, capsys=None):
    return invoke_authorized_scope_apply(
        SESSION_ID,
        argv,
        write_command_factory=lambda database: _commands(handler),
    )


def test_exact_authorized_scope_applies_once_without_proposal(capsys):
    handler = RecordingHandler()
    runtime_state.save_state(SESSION_ID, _trusted_state())

    exit_code = _invoke(AUTHORIZED_ARGV, handler)

    assert exit_code == 0
    assert len(handler.calls) == 1
    assert handler.calls[0]["project_id"] == PROJECT_ID
    assert handler.calls[0]["status"] == "IN_PROGRESS"


def test_replay_of_authorized_scope_is_rejected(capsys):
    handler = RecordingHandler()
    runtime_state.save_state(SESSION_ID, _trusted_state())

    _invoke(AUTHORIZED_ARGV, handler)

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(AUTHORIZED_ARGV, handler)

    assert len(handler.calls) == 1


def test_changed_target_is_rejected_before_handler(capsys):
    handler = RecordingHandler()
    runtime_state.save_state(SESSION_ID, _trusted_state())
    other_target = [
        "project",
        "update",
        OTHER_PROJECT_ID,
        "--status",
        "IN_PROGRESS",
        "--expected-version",
        "3",
    ]

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(other_target, handler)

    assert handler.calls == []


def test_changed_payload_is_rejected_before_handler(capsys):
    handler = RecordingHandler()
    runtime_state.save_state(SESSION_ID, _trusted_state())
    changed_payload = [
        "project",
        "update",
        PROJECT_ID,
        "--status",
        "BLOCKED",
        "--expected-version",
        "3",
    ]

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(changed_payload, handler)

    assert handler.calls == []


def test_changed_action_is_rejected_before_handler(capsys):
    handler = RecordingHandler()
    runtime_state.save_state(SESSION_ID, _trusted_state())
    changed_action = [
        "project",
        "create",
        "--merchant-id",
        MERCHANT_ID,
        "--type",
        "OPENING_NEW_CINEMA",
        "--variant",
        "OPENING_NEW_CINEMA_STANDARD",
    ]

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(changed_action, handler)

    assert handler.calls == []


def test_name_only_target_is_rejected_at_scope_validation():
    with pytest.raises(MerchantRuntimeHandoffError, match="exact UUIDs"):
        validate_direct_scope([
            "project",
            "update",
            "CGV Opening Project",
            "--status",
            "IN_PROGRESS",
            "--expected-version",
            "3",
        ])


@pytest.mark.parametrize(
    "argv",
    (
        ["--database", "test", *AUTHORIZED_ARGV],
        [*AUTHORIZED_ARGV, "--apply"],
        [*AUTHORIZED_ARGV, "--propose"],
        [*AUTHORIZED_ARGV, "--proposal-hash", "a" * 64],
    ),
)
def test_scope_cannot_name_database_or_proposal_mode(argv):
    with pytest.raises(MerchantRuntimeHandoffError):
        validate_direct_scope(argv)


def test_forged_scope_argv_is_rejected_by_integrity_check(capsys):
    handler = RecordingHandler()
    state = _trusted_state()
    forged = list(AUTHORIZED_ARGV)
    forged[2] = OTHER_PROJECT_ID
    state["merchant_scope"]["argv"] = forged
    runtime_state.save_state(SESSION_ID, state)

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(forged, handler)

    assert handler.calls == []


def test_wrong_run_scope_is_rejected(capsys):
    handler = RecordingHandler()
    state = _trusted_state(run_id="another-run")
    runtime_state.save_state(SESSION_ID, state)

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(AUTHORIZED_ARGV, handler)

    assert handler.calls == []


def test_dispatch_for_different_scope_is_rejected(capsys):
    handler = RecordingHandler()
    state = _trusted_state()
    state["merchant_dispatch"]["confirmation_hash"] = "b" * 64
    runtime_state.save_state(SESSION_ID, state)

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(AUTHORIZED_ARGV, handler)

    assert handler.calls == []


def test_missing_user_confirmation_is_rejected(capsys):
    handler = RecordingHandler()
    runtime_state.save_state(
        SESSION_ID,
        _trusted_state(confirmed=False),
    )

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(AUTHORIZED_ARGV, handler)

    assert handler.calls == []


def test_missing_scope_is_rejected(capsys):
    handler = RecordingHandler()
    state = _trusted_state()
    del state["merchant_scope"]
    runtime_state.save_state(SESSION_ID, state)

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(AUTHORIZED_ARGV, handler)

    assert handler.calls == []


def test_proposal_confirmation_cannot_mix_with_direct_scope(capsys):
    handler = RecordingHandler()
    state = _trusted_state(merchant_confirmation={"operation": "merchant_apply"})
    runtime_state.save_state(SESSION_ID, state)

    with pytest.raises(MerchantRuntimeHandoffError):
        _invoke(AUTHORIZED_ARGV, handler)

    assert handler.calls == []


def test_ordinary_cli_runtime_write_without_authorization_is_refused(capsys):
    handler = RecordingHandler()

    def factory(database):
        return _commands(handler)

    exit_code = cli.main(
        ["--database", "runtime", *AUTHORIZED_ARGV],
        write_command_factory=factory,
        runtime_authorization=None,
    )

    assert exit_code == 1
    assert handler.calls == []
