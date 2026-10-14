from contextlib import contextmanager
from copy import deepcopy

import pytest

from claude.hooks import merchant_direct_write_state as module


CONTEXT = {
    "owner_session_id": "owner-1",
    "teammate_name": "merchant-manager",
    "pane_session_id": "pane-1",
    "run_id": "run-1",
    "task_id": "task-1",
    "write_id": "write-1",
    "database": "test",
    "payload": {
        "code": "TEST",
        "name": "Test Merchant",
    },
}


def active_record():
    return {
        "canonical_name": "merchant-manager",
        "status": "RUNNING",
        "current_run_id": "run-1",
        "current_task_id": "task-1",
        "trusted_pane_session_id": "pane-1",
        "authorized_operations": ["merchant_execute"],
        "authorized_selected_agents": ["merchant-manager"],
    }


@pytest.fixture
def state_env(monkeypatch):
    state = {
        "teammates": {
            "merchant-manager": active_record(),
        }
    }

    @contextmanager
    def locked(session_id):
        assert session_id == "owner-1"
        yield state

    monkeypatch.setattr(
        module, "locked_team_state", locked
    )
    monkeypatch.setattr(
        module,
        "bind_merchant_execute",
        lambda **kwargs: (
            "merchant-direct:v1:test-operation"
        ),
    )

    return state


def test_reservation_is_stable(state_env):
    first = module.reserve_merchant_create(**CONTEXT)
    second = module.reserve_merchant_create(**CONTEXT)

    assert first == second
    assert first["status"] == "RESERVED"
    assert len(
        state_env["teammates"]["merchant-manager"]["direct_writes"]
    ) == 1


def test_reused_write_id_with_new_payload_is_rejected(state_env):
    module.reserve_merchant_create(**CONTEXT)

    changed = deepcopy(CONTEXT)
    changed["payload"]["name"] = "Different Merchant"

    with pytest.raises(module.DirectWriteReservationError):
        module.reserve_merchant_create(**changed)


def test_reassigned_task_is_rejected(state_env):
    record = state_env["teammates"]["merchant-manager"]
    record["current_task_id"] = "other-task"

    with pytest.raises(module.DirectWriteReservationError):
        module.reserve_merchant_create(**CONTEXT)

    assert "direct_writes" not in record


def test_wrong_pane_is_rejected(state_env):
    record = state_env["teammates"]["merchant-manager"]
    record["trusted_pane_session_id"] = "other-pane"

    with pytest.raises(module.DirectWriteReservationError):
        module.reserve_merchant_create(**CONTEXT)


def test_unapproved_operation_is_rejected(state_env):
    record = state_env["teammates"]["merchant-manager"]
    record["authorized_operations"] = ["merchant_apply"]

    with pytest.raises(module.DirectWriteReservationError):
        module.reserve_merchant_create(**CONTEXT)


def test_reserved_write_does_not_mark_report_received(state_env):
    module.reserve_merchant_create(**CONTEXT)

    record = state_env["teammates"]["merchant-manager"]

    assert record["status"] == "RUNNING"
    assert record.get("result_received") is not True
    assert record.get("report_source") is None
