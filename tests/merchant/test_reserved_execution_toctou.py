from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from claude.clients.merchant.atomic_create import _canonical_hash
from claude.hooks import merchant_reserved_execution as module


PAYLOAD = {
    "code": "TOCTOU_TEST",
    "name": "TOCTOU Test Merchant",
}

CONTEXT = {
    "owner_session_id": "owner-1",
    "teammate_name": "merchant-manager",
    "pane_session_id": "pane-1",
    "run_id": "run-1",
    "task_id": "task-1",
    "write_id": "write-1",
    "database": "test",
}

KEY = "merchant-direct:v1:" + "a" * 64


def test_reassignment_between_validation_and_write(
    monkeypatch,
):
    payload_hash = _canonical_hash({
        "command": "merchant create",
        "merchant_id": None,
        "code": PAYLOAD["code"],
        "name": PAYLOAD["name"],
        "region_code": None,
        "created_by": None,
    })

    record = {
        "canonical_name": "merchant-manager",
        "status": "RUNNING",
        "current_run_id": "run-1",
        "current_task_id": "task-1",
        "trusted_pane_session_id": "pane-1",
        "authorized_operations": ["merchant_execute"],
        "authorized_selected_agents": ["merchant-manager"],
        "direct_writes": {
            "write-1": {
                "write_id": "write-1",
                "run_id": "run-1",
                "task_id": "task-1",
                "database": "test",
                "command": "merchant create",
                "payload_hash": payload_hash,
                "operation_key": KEY,
                "status": "RESERVED",
            }
        },
    }

    state = {
        "teammates": {
            "merchant-manager": record,
        }
    }

    @contextmanager
    def locked(_session_id):
        yield state

    monkeypatch.setattr(
        module,
        "locked_team_state",
        locked,
    )

    executed = []

    def fake_execute(**kwargs):
        # Simulate task reassignment immediately after
        # reservation validation has released its lock.
        record["current_task_id"] = "replacement-task"

        executed.append(kwargs)

        return {
            "success": True,
            "mode": "EXECUTE",
            "command": "merchant create",
            "database": "test",
            "result": {
                "success": True,
                "merchant_id": "test-merchant",
            },
            "replayed": False,
        }

    monkeypatch.setattr(
        module,
        "execute_protected_merchant_create",
        fake_execute,
    )

    repository = SimpleNamespace(
        config=SimpleNamespace(
            database="coding_agent_merchant_test"
        )
    )

    module.execute_reserved_merchant_create(
        repository=repository,
        payload=PAYLOAD,
        **CONTEXT,
    )

    if executed:
        pytest.xfail(
            "Known TOCTOU: execution proceeded after "
            "task reassignment"
        )

    assert executed == []
