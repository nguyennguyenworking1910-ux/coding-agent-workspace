import pytest

from claude.hooks import merchant_direct_coordinator as module
from claude.hooks.merchant_direct_binding import (
    DirectExecutionBindingError,
)


CONTEXT = {
    "owner_session_id": "owner-1",
    "teammate_name": "merchant-manager",
    "pane_session_id": "pane-1",
    "run_id": "run-1",
    "task_id": "task-1",
    "write_id": "write-1",
    "payload": {
        "code": "TEST",
        "name": "Test Merchant",
    },
    "database": "test",
}


def test_authorization_precedes_database_write(monkeypatch):
    events = []

    def bind(**kwargs):
        events.append("authorize")
        assert kwargs["database"] == CONTEXT["database"]
        assert kwargs["payload"] == CONTEXT["payload"]
        return "trusted-operation-key"

    def execute(**kwargs):
        events.append("execute")
        assert kwargs["database"] == CONTEXT["database"]
        assert kwargs["payload"] == CONTEXT["payload"]
        assert kwargs["repository"] is not None
        return {
            "success": True,
            "mode": "EXECUTE",
            "command": "merchant create",
            "database": "test",
            "result": {"merchant_id": "merchant-1"},
            "replayed": False,
        }

    monkeypatch.setattr(
        module, "reserve_merchant_create", bind
    )
    monkeypatch.setattr(
        module, "execute_reserved_merchant_create", execute
    )

    result = module.execute_bound_merchant_create(**CONTEXT, repository=object())

    assert events == ["authorize", "execute"]
    assert result["success"] is True


def test_denied_authority_never_executes(monkeypatch):
    calls = []

    def deny(**kwargs):
        raise DirectExecutionBindingError("NOT_RUNNING")

    monkeypatch.setattr(
        module, "reserve_merchant_create", deny
    )
    monkeypatch.setattr(
        module,
        "execute_reserved_merchant_create",
        lambda **kwargs: calls.append(kwargs),
    )

    with pytest.raises(DirectExecutionBindingError):
        module.execute_bound_merchant_create(**CONTEXT, repository=object())

    assert calls == []


@pytest.mark.parametrize("database", [
    "unknown",
    "coding_agent_rag",
    "",
])
def test_invalid_target_never_executes(monkeypatch, database):
    calls = []

    monkeypatch.setattr(
        module,
        "reserve_merchant_create",
        lambda **kwargs: calls.append("bind"),
    )

    monkeypatch.setattr(
        module,
        "execute_reserved_merchant_create",
        lambda **kwargs: calls.append("execute"),
    )

    with pytest.raises(module.DirectCoordinatorError):
        module.execute_bound_merchant_create(
            **{**CONTEXT, "database": database}
        )

    assert calls == []


def test_injected_payload_field_rejected(monkeypatch):
    calls = []

    monkeypatch.setattr(
        module,
        "execute_reserved_merchant_create",
        lambda **kwargs: calls.append(kwargs),
    )

    with pytest.raises(module.DirectCoordinatorError):
        module.execute_bound_merchant_create(
            **{
                **CONTEXT,
                "payload": {
                    "code": "TEST",
                    "name": "Test",
                    "operation_key": "forged-key",
                },
            }
        )

    assert calls == []


def test_invalid_execution_response_rejected(monkeypatch):
    monkeypatch.setattr(
        module,
        "reserve_merchant_create",
        lambda **kwargs: "trusted-key",
    )
    monkeypatch.setattr(
        module,
        "execute_reserved_merchant_create",
        lambda **kwargs: {
            "success": True,
            "mode": "APPLY",
            "command": "merchant create",
            "database": "test",
        },
    )

    with pytest.raises(module.DirectCoordinatorError):
        module.execute_bound_merchant_create(**CONTEXT)
