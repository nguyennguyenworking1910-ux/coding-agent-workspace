import pytest

from claude.hooks import merchant_direct_binding as module


CONTEXT = {
    "owner_session_id": "owner-1",
    "teammate_name": "merchant-manager",
    "pane_session_id": "pane-1",
    "run_id": "run-1",
    "task_id": "task-1",
    "write_id": "write-1",
    "command": "merchant create",
}


def test_authorized_binding_is_stable(monkeypatch):
    calls = []

    def allow(*args, **kwargs):
        calls.append((args, kwargs))
        return True, "MATCHED"

    monkeypatch.setattr(
        module,
        "trusted_teammate_pane_session_matches",
        allow,
    )

    first = module.bind_merchant_execute(**CONTEXT)
    second = module.bind_merchant_execute(**CONTEXT)

    assert first == second
    assert first.startswith("merchant-direct:v1:")
    assert len(calls) == 2

    assert calls[0][1]["required_operation"] == (
        "merchant_execute"
    )


@pytest.mark.parametrize("reason", [
    "NOT_RUNNING",
    "BINDING_MISMATCH",
    "STATE_UNAVAILABLE",
    "UNAUTHORIZED_OPERATION",
])
def test_denied_lifecycle_never_produces_key(
    monkeypatch, reason
):
    monkeypatch.setattr(
        module,
        "trusted_teammate_pane_session_matches",
        lambda *args, **kwargs: (False, reason),
    )

    with pytest.raises(
        module.DirectExecutionBindingError
    ):
        module.bind_merchant_execute(**CONTEXT)


def test_new_write_id_produces_new_key(monkeypatch):
    monkeypatch.setattr(
        module,
        "trusted_teammate_pane_session_matches",
        lambda *args, **kwargs: (True, "MATCHED"),
    )

    first = module.bind_merchant_execute(**CONTEXT)

    changed = {
        **CONTEXT,
        "write_id": "write-2",
    }

    second = module.bind_merchant_execute(**changed)

    assert first != second


def test_wrong_command_rejected(monkeypatch):
    monkeypatch.setattr(
        module,
        "trusted_teammate_pane_session_matches",
        lambda *args, **kwargs: (True, "MATCHED"),
    )

    with pytest.raises(
        module.DirectExecutionBindingError
    ):
        module.bind_merchant_execute(
            **{**CONTEXT, "command": "project create"}
        )
