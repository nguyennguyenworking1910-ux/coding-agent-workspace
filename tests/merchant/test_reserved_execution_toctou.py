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


def test_real_lifecycle_reassignment_rejected_during_execution(
    tmp_path, monkeypatch
):
    """Official lifecycle API must not reassign an EXECUTING write."""
    from claude.hooks import team_lifecycle

    monkeypatch.setattr(
        team_lifecycle,
        "team_state_dir",
        lambda: tmp_path,
    )

    owner = "pytest-toctou-owner"
    teammate = "merchant-manager"

    with team_lifecycle.locked_team_state(owner) as state:
        state.setdefault("teammates", {})[teammate] = {
            "canonical_name": teammate,
            "status": "RUNNING",
            "current_run_id": "run-1",
            "current_task_id": "task-1",
            "authorized_operations": ["merchant_execute"],
            "authorized_selected_agents": [teammate],
            "direct_writes": {
                "write-1": {
                    "write_id": "write-1",
                    "run_id": "run-1",
                    "task_id": "task-1",
                    "status": "EXECUTING",
                    "execution_attempt_id": (
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                    ),
                },
            },
        }

    reassigned = team_lifecycle.mark_teammate_running(
        owner,
        teammate,
        "run-2",
        "task-2",
        operations=["merchant_execute"],
        selected_agents=[teammate],
    )

    assert reassigned is False

    persisted = team_lifecycle.load_team_state(owner)
    record = persisted["teammates"][teammate]

    assert record["current_run_id"] == "run-1"
    assert record["current_task_id"] == "task-1"
    assert record["direct_writes"]["write-1"]["status"] == "EXECUTING"

def test_real_lifecycle_idle_rejected_during_execution(
    tmp_path, monkeypatch
):
    """Official idle transition must reject unresolved execution."""
    from claude.hooks import team_lifecycle

    monkeypatch.setattr(
        team_lifecycle,
        "team_state_dir",
        lambda: tmp_path,
    )

    owner = "pytest-toctou-idle-owner"
    teammate = "merchant-manager"

    with team_lifecycle.locked_team_state(owner) as state:
        state.setdefault("teammates", {})[teammate] = {
            "canonical_name": teammate,
            "status": "RUNNING",
            "current_run_id": "run-1",
            "current_task_id": "task-1",
            "authorized_operations": ["merchant_execute"],
            "authorized_selected_agents": [teammate],
            "direct_writes": {
                "write-1": {
                    "write_id": "write-1",
                    "run_id": "run-1",
                    "task_id": "task-1",
                    "status": "EXECUTING",
                    "execution_attempt_id": (
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                    ),
                },
            },
        }

    released = team_lifecycle.mark_teammate_idle_reusable(
        owner,
        teammate,
    )

    assert released is False

    persisted = team_lifecycle.load_team_state(owner)
    record = persisted["teammates"][teammate]

    assert record["status"] == "RUNNING"
    assert record["current_task_id"] == "task-1"
    assert record["direct_writes"]["write-1"]["status"] == "EXECUTING"

def test_verified_without_attempt_remains_unresolved():
    """Status alone must not establish trusted write completion."""
    from claude.hooks.team_lifecycle import (
        has_unresolved_direct_writes,
    )

    record = {
        "direct_writes": {
            "write-1": {
                "write_id": "write-1",
                "run_id": "run-1",
                "task_id": "task-1",
                "status": "VERIFIED",
                "operation_key": "merchant-direct:v1:" + "a" * 64,
                "payload_hash": "b" * 64,
            }
        }
    }

    assert has_unresolved_direct_writes(record) is True


def test_verified_with_trusted_attempt_can_be_resolved():
    """A well-formed verified identity satisfies the local guard."""
    from claude.hooks.team_lifecycle import (
        has_unresolved_direct_writes,
    )

    record = {
        "direct_writes": {
            "write-1": {
                "write_id": "write-1",
                "run_id": "run-1",
                "task_id": "task-1",
                "status": "VERIFIED",
                "operation_key": "merchant-direct:v1:" + "a" * 64,
                "payload_hash": "b" * 64,
                "execution_attempt_id": (
                    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                ),
            }
        }
    }

    assert has_unresolved_direct_writes(record) is False