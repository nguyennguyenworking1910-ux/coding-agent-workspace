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


def test_proposal_path_is_selected_without_direct_scope(monkeypatch):
    runtime_state.save_state(SESSION, {"merchant_confirmation": {"test": True}})
    calls = []

    def proposal(session_id, arguments, *, write_command_factory=None):
        calls.append(("proposal", session_id, arguments))
        return 9

    def direct(*args, **kwargs):
        raise AssertionError("Direct apply must not run without direct scope")

    monkeypatch.setattr(handoff, "invoke_authorized_scope_apply", direct)
    monkeypatch.setattr(handoff, "invoke_confirmed_merchant_session_apply", proposal)

    assert handoff.invoke_trusted_merchant_session_apply(SESSION, ARGV) == 9
    assert calls == [("proposal", SESSION, ARGV)]


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