from contextlib import contextmanager

import pytest

from claude.system import merchant_runtime_handoff as handoff


@contextmanager
def owner_state(state):
    yield state


def test_missing_direct_scope_rejects_legacy_fallback(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Legacy apply must never be invoked")

    monkeypatch.setattr(
        handoff,
        "locked_state",
        lambda session_id: owner_state({}),
    )
    monkeypatch.setattr(
        handoff,
        "invoke_confirmed_merchant_session_apply",
        forbidden,
    )

    with pytest.raises(
        handoff.MerchantRuntimeHandoffStageError,
        match="SELECT_AUTHORIZATION",
    ):
        handoff.invoke_trusted_merchant_session_apply(
            "owner-session",
            ("merchant", "create"),
        )


def test_direct_scope_still_routes_to_authorized_handler(
    monkeypatch,
):
    expected = ("merchant", "create")
    calls = []

    def direct_handler(session_id, arguments, **kwargs):
        calls.append((session_id, tuple(arguments)))
        return 0

    def forbidden(*args, **kwargs):
        pytest.fail("Legacy apply must never be invoked")

    monkeypatch.setattr(
        handoff,
        "locked_state",
        lambda session_id: owner_state(
            {"merchant_scope": {"trusted": True}}
        ),
    )
    monkeypatch.setattr(
        handoff,
        "invoke_authorized_scope_apply",
        direct_handler,
    )
    monkeypatch.setattr(
        handoff,
        "invoke_confirmed_merchant_session_apply",
        forbidden,
    )

    result = handoff.invoke_trusted_merchant_session_apply(
        "owner-session",
        expected,
    )

    assert result == 0
    assert calls == [("owner-session", expected)]
