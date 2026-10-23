"""CP6.5B: trusted selection uses persisted owner state only.

These tests use isolated runtime state and fake handlers. No database writes.
"""

import pytest

from claude.hooks import runtime_state
from claude.system import merchant_runtime_handoff as handoff


SESSION = "cp6-trusted-selection"
ARGV = ("example", "non-executed")


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv(runtime_state.STATE_DIR_ENV_VAR, str(tmp_path))


def test_direct_path_is_selected_from_persisted_scope(monkeypatch):
    runtime_state.save_state(SESSION, {"merchant_scope": {"argv": ["one"]}})
    calls = []

    def direct(session_id, arguments, *, write_command_factory=None):
        calls.append(("direct", session_id, arguments))
        return 7

    def legacy(*args, **kwargs):
        raise AssertionError("Legacy apply must not run for direct scope")

    monkeypatch.setattr(handoff, "invoke_authorized_scope_apply", direct)
    monkeypatch.setattr(handoff, "invoke_confirmed_merchant_session_apply", legacy)

    assert handoff.invoke_trusted_merchant_session_apply(SESSION, ARGV) == 7
    assert calls == [("direct", SESSION, ARGV)]


def test_missing_direct_scope_rejects_legacy_proposal(monkeypatch):
    import pytest

    runtime_state.save_state(
        SESSION, {"merchant_confirmation": {"test": True}}
    )

    def forbidden(*args, **kwargs):
        pytest.fail("No execution path is allowed without direct scope")

    monkeypatch.setattr(
        handoff, "invoke_authorized_scope_apply", forbidden
    )
    monkeypatch.setattr(
        handoff, "invoke_confirmed_merchant_session_apply", forbidden
    )

    with pytest.raises(
        handoff.MerchantRuntimeHandoffStageError,
        match="SELECT_AUTHORIZATION",
    ):
        handoff.invoke_trusted_merchant_session_apply(SESSION, ARGV)


def test_missing_owner_state_fails_closed(monkeypatch):
    monkeypatch.setattr(
        handoff,
        "invoke_authorized_scope_apply",
        lambda *args, **kwargs: pytest.fail("unexpected direct execution"),
    )
    monkeypatch.setattr(
        handoff,
        "invoke_confirmed_merchant_session_apply",
        lambda *args, **kwargs: pytest.fail("unexpected legacy execution"),
    )
    with pytest.raises(handoff.MerchantRuntimeHandoffStageError):
        handoff.invoke_trusted_merchant_session_apply(SESSION, ARGV)


def test_invalid_session_fails_closed():
    with pytest.raises(handoff.MerchantRuntimeHandoffStageError):
        handoff.invoke_trusted_merchant_session_apply("", ARGV)