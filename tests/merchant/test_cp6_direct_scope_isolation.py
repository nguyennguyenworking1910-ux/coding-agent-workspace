"""CP6 regression: Direct Scope stays isolated and fail-closed.

No live database access: runtime state is temporary and handlers are fake.
"""

import pytest

from claude.hooks import runtime_state
from claude.system.merchant_runtime_handoff import (
    MerchantRuntimeHandoffError,
    invoke_authorized_scope_apply,
    validate_direct_scope,
)
from claude.agents.tools.merchant.write_commands import MerchantWriteCommands

SESSION = "cp6-direct-boundary"
PROJECT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_PROJECT_ID = "00000000-0000-0000-0000-000000000099"
ARGV = ["project", "update", PROJECT_ID, "--status", "IN_PROGRESS", "--expected-version", "3"]


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv(runtime_state.STATE_DIR_ENV_VAR, str(tmp_path))


def authorized_state():
    scope = validate_direct_scope(ARGV)
    run_id = "cp6-direct-run"
    state = runtime_state.new_state(
        request=f"Update project {PROJECT_ID} to IN_PROGRESS",
        task_class="medium_task",
        risk_level="external_write",
        selected_agents=["merchant-manager"],
        limits={"max_members": 1, "max_tool_rounds": 1, "max_total_tool_calls": 10, "max_run_budget_usd": 1.0},
        confirmed=True,
        operations=["merchant_apply"],
        run_id=run_id,
        merchant_scope={
            "argv": list(scope["argv"]),
            "command": scope["command"],
            "database_target": scope["database_target"],
            "scope_hash": scope["scope_hash"],
            "run_id": run_id,
        },
    )
    state["merchant_dispatch_spent"] = True
    state["merchant_dispatch"] = {
        "operation": "merchant_apply",
        "subagent_type": "merchant-manager",
        "teammate_name": "merchant-manager",
        "confirmation_hash": scope["confirmation_hash"],
    }
    return state


def invoke(argv, calls):
    commands = MerchantWriteCommands({
        "project update": lambda payload: (calls.append(payload) or {"status": "committed"})
    })
    return invoke_authorized_scope_apply(
        SESSION,
        argv,
        write_command_factory=lambda database: commands,
    )


@pytest.mark.parametrize("mutation", [
    lambda state: state.update(operations=["merchant_propose"]),
    lambda state: state.update(selected_agents=["reviewer"]),
    lambda state: state.update(risk_level="read_only"),
    lambda state: state.update(merchant_dispatch_spent=False),
    lambda state: state["merchant_dispatch"].update(confirmation_hash="0" * 64),
    lambda state: state.update(merchant_confirmation={"operation": "merchant_apply"}),
], ids=["wrong-operation", "wrong-agent", "read-only-risk", "unaccepted-dispatch", "wrong-dispatch-hash", "proposal-confirmation-mixing"])
def test_direct_scope_rejects_non_direct_authority(mutation):
    state = authorized_state()
    mutation(state)
    runtime_state.save_state(SESSION, state)
    calls = []
    with pytest.raises(MerchantRuntimeHandoffError):
        invoke(ARGV, calls)
    assert calls == []


def test_changed_arguments_burn_direct_authorization():
    runtime_state.save_state(SESSION, authorized_state())
    calls = []
    altered = list(ARGV)
    altered[2] = OTHER_PROJECT_ID
    with pytest.raises(MerchantRuntimeHandoffError):
        invoke(altered, calls)
    with pytest.raises(MerchantRuntimeHandoffError):
        invoke(ARGV, calls)
    assert calls == []


def test_direct_success_remains_single_use():
    runtime_state.save_state(SESSION, authorized_state())
    calls = []
    assert invoke(ARGV, calls) == 0
    with pytest.raises(MerchantRuntimeHandoffError):
        invoke(ARGV, calls)
    assert len(calls) == 1


def test_authorization_issuance_failure_burns_reservation(monkeypatch):
    from claude.system import merchant_runtime_handoff as handoff

    runtime_state.save_state(SESSION, authorized_state())
    calls = []

    def fail_issue(*args, **kwargs):
        raise RuntimeError("synthetic authorization issuance failure")

    original = handoff.issue_runtime_apply_authorization

    monkeypatch.setattr(
        handoff,
        "issue_runtime_apply_authorization",
        fail_issue,
    )

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke(ARGV, calls)

    monkeypatch.setattr(
        handoff,
        "issue_runtime_apply_authorization",
        original,
    )

    with pytest.raises(MerchantRuntimeHandoffError):
        invoke(ARGV, calls)

    assert calls == []
