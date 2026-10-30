"""CP12H.3: the only runtime write entry is the user-scoped Direct EXECUTE.

Isolated runtime state and fake handlers only. No database writes.
"""

import pytest

from claude.hooks import runtime_state
from claude.system import merchant_runtime_handoff as handoff
from tests.merchant.direct_reservation_support import (
    isolate_team_state,
    reserve_scoped_write,
)


SESSION = "cp12h3-entrypoint"
ARGV = ("project", "update", "00000000-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv(runtime_state.STATE_DIR_ENV_VAR, str(tmp_path))
    isolate_team_state(monkeypatch, tmp_path)


RESERVATION = {
    "teammate_name": "merchant-manager",
    "task_id": "task-1",
    "execution_attempt_id": "00000000-0000-4000-8000-000000000001",
}


@pytest.mark.parametrize(
    "name",
    [
        "invoke_confirmed_merchant_session_apply",
        "invoke_trusted_merchant_session_apply",
        "MERCHANT_APPLY_OPERATION",
    ],
)
def test_legacy_runtime_entrypoints_are_removed(name):
    assert not hasattr(handoff, name)


@pytest.mark.parametrize(
    "state",
    [
        {"merchant_confirmation": {"legacy": True}},
        {"operations": ["merchant_apply"], "merchant_scope": {"argv": []}},
        {"operations": ["merchant_propose"]},
        {},
    ],
)
def test_runtime_write_without_trusted_scope_fails_closed(
    monkeypatch, state
):
    runtime_state.save_state(SESSION, state)

    monkeypatch.setattr(
        handoff,
        "_invoke_authorized_apply",
        lambda *args, **kwargs: pytest.fail("unexpected runtime write"),
    )

    with pytest.raises(
        handoff.MerchantRuntimeHandoffStageError,
        match="RESERVE_AUTHORIZATION",
    ):
        handoff.invoke_authorized_scope_apply(SESSION, ARGV, **RESERVATION)


def test_missing_owner_state_fails_closed(monkeypatch):
    monkeypatch.setattr(
        handoff,
        "_invoke_authorized_apply",
        lambda *args, **kwargs: pytest.fail("unexpected runtime write"),
    )

    with pytest.raises(handoff.MerchantRuntimeHandoffStageError):
        handoff.invoke_authorized_scope_apply(SESSION, ARGV, **RESERVATION)


def _dispatch_state(**overrides):
    state = {
        "operations": ["merchant_execute"],
        "selected_agents": ["merchant-manager"],
        "risk_level": "external_write",
        "confirmed": True,
    }
    state.update(overrides)
    return state


def _check(state, prompt="Create merchant CGV."):
    from claude.hooks import policy_gate

    return policy_gate._check_merchant_dispatch(
        state,
        "merchant-manager",
        "merchant-manager",
        {"prompt": prompt},
    )


def test_unscoped_execute_dispatch_is_allowed():
    assert _check(_dispatch_state()) is None


@pytest.mark.parametrize(
    "state, prompt",
    [
        # Removed workflows.
        (_dispatch_state(operations=["merchant_propose"]), "x"),
        (_dispatch_state(operations=["merchant_apply"]), "x"),
        # Agent-authored legacy authority never counts.
        (_dispatch_state(), "MERCHANT_DISPATCH_AUTHORIZATION_JSON\n{}"),
        (_dispatch_state(merchant_confirmation={"legacy": True}), "x"),
        # Execute needs a mutating, confirmed, unspent envelope.
        (_dispatch_state(risk_level="read_only"), "x"),
        (_dispatch_state(confirmed=False), "x"),
        (_dispatch_state(merchant_dispatch_spent=True), "x"),
        # A read can never carry a write scope.
        (
            _dispatch_state(
                operations=["merchant_read"],
                merchant_scope={"argv": ["merchant", "list"]},
            ),
            "x",
        ),
        # Exclusive merchant-manager authority.
        (_dispatch_state(selected_agents=["coder"]), "x"),
    ],
)
def test_policy_rejects_non_direct_dispatch(state, prompt):
    assert _check(state, prompt) is not None


@pytest.mark.parametrize("session_id", ["", "   ", None])
def test_invalid_session_fails_closed(session_id):
    with pytest.raises(handoff.MerchantRuntimeHandoffStageError):
        handoff.reserve_direct_scope_authorization(
            session_id,
            ARGV,
            teammate_name="merchant-manager",
            task_id="task-1",
            reservation={"kind": "scope", "execution_attempt_id": "x"},
        )
