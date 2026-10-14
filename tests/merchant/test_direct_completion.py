from copy import deepcopy

import pytest

from claude.hooks import merchant_direct_completion as module


def make_state(status="EXECUTING"):
    return {
        "teammates": {
            "merchant-manager": {
                "canonical_name": "merchant-manager",
                "status": "RUNNING",
                "current_run_id": "run-1",
                "current_task_id": "task-1",
                "authorized_operations": ["merchant_execute"],
                "authorized_selected_agents": ["merchant-manager"],
                "direct_writes": {
                    "write-1": {
                        "write_id": "write-1",
                        "run_id": "run-1",
                        "task_id": "task-1",
                        "command": "merchant create",
                        "database": "test",
                        "operation_key": "merchant-direct:v1:example",
                        "payload_hash": "a" * 64,
                        "status": status,
                    }
                },
            }
        }
    }


CONTEXT = {
    "owner_session_id": "owner-1",
    "teammate_name": "merchant-manager",
    "run_id": "run-1",
    "task_id": "task-1",
}


@pytest.fixture
def env(monkeypatch):
    state = make_state()
    calls = []

    monkeypatch.setattr(
        module,
        "load_team_state",
        lambda owner: state,
    )

    def verify(repository, **kwargs):
        calls.append(kwargs)
        write = state["teammates"]["merchant-manager"][
            "direct_writes"
        ][kwargs["write_id"]]
        write["status"] = "VERIFIED"
        return dict(write)

    monkeypatch.setattr(
        module,
        "reconcile_committed_merchant_create",
        verify,
    )

    return state, calls


def run():
    return module.reconcile_all_direct_writes(
        **CONTEXT,
        repository_factory=lambda database: object(),
    )


def test_one_committed_write(env):
    state, calls = env
    assert run() is True
    assert len(calls) == 1
    assert calls[0]["write_id"] == "write-1"


def test_missing_write_denied(env):
    state, calls = env
    state["teammates"]["merchant-manager"][
        "direct_writes"
    ] = {}

    assert run() is False
    assert calls == []


def test_wrong_task_denied(env):
    state, calls = env
    state["teammates"]["merchant-manager"][
        "current_task_id"
    ] = "other-task"

    assert run() is False
    assert calls == []


def test_malformed_write_denied(env):
    state, calls = env
    state["teammates"]["merchant-manager"][
        "direct_writes"
    ]["invalid"] = None

    assert run() is False
    assert calls == []


def test_all_writes_required(env):
    state, calls = env
    writes = state["teammates"]["merchant-manager"][
        "direct_writes"
    ]

    second = deepcopy(writes["write-1"])
    second["write_id"] = "write-2"
    second["operation_key"] = "merchant-direct:v1:other"
    writes["write-2"] = second

    assert run() is True
    assert len(calls) == 2
    assert all(
        w["status"] == "VERIFIED"
        for w in writes.values()
    )


def test_missing_evidence_denied(env, monkeypatch):
    state, calls = env

    monkeypatch.setattr(
        module,
        "reconcile_committed_merchant_create",
        lambda *args, **kwargs: None,
    )

    assert run() is False
    assert state["teammates"]["merchant-manager"][
        "direct_writes"
    ]["write-1"]["status"] == "EXECUTING"


def test_reassignment_during_verification_denied(
    env, monkeypatch
):
    state, calls = env

    def verify(*args, **kwargs):
        record = state["teammates"]["merchant-manager"]
        record["current_task_id"] = "replacement"
        return {"status": "VERIFIED"}

    monkeypatch.setattr(
        module,
        "reconcile_committed_merchant_create",
        verify,
    )

    assert run() is False
