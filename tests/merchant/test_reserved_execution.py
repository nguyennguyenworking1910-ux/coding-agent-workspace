from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from claude.clients.merchant.atomic_create import _canonical_hash
from claude.hooks import merchant_reserved_execution as module


PAYLOAD = {
    "code": "TEST",
    "name": "Test Merchant",
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


def canonical_hash(payload):
    return _canonical_hash({
        "command": "merchant create",
        "merchant_id": payload.get("merchant_id"),
        "code": payload["code"],
        "name": payload["name"],
        "region_code": payload.get("region_code"),
        "created_by": payload.get("created_by"),
    })


@pytest.fixture
def env(monkeypatch):
    state = {
        "teammates": {
            "merchant-manager": {
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
                        "payload_hash": canonical_hash(PAYLOAD),
                        "operation_key": KEY,
                        "status": "RESERVED",
                    },
                },
            },
        },
    }

    @contextmanager
    def locked(session_id):
        assert session_id == "owner-1"
        yield state

    monkeypatch.setattr(module, "locked_team_state", locked)

    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "mode": "EXECUTE",
            "command": "merchant create",
            "database": "test",
            "result": {
                "success": True,
                "merchant_id": "merchant-1",
            },
            "replayed": False,
        }

    monkeypatch.setattr(
        module, "execute_protected_merchant_create", execute
    )

    repo = SimpleNamespace(
        config=SimpleNamespace(database="coding_agent_merchant_test")
    )

    return state, repo, calls


def run(repo, payload=None, **changes):
    return module.execute_reserved_merchant_create(
        repository=repo,
        payload=PAYLOAD if payload is None else payload,
        **{**CONTEXT, **changes},
    )


def test_valid_reservation_executes_once_per_invocation(env):
    state, repo, calls = env

    result = run(repo)

    assert result["success"] is True
    assert len(calls) == 1
    assert calls[0]["operation_key"] == KEY
    assert calls[0]["database"] == "test"
    assert calls[0]["payload"] == PAYLOAD

    # Execution does not itself mutate reservation state.
    assert state["teammates"]["merchant-manager"][
        "direct_writes"
    ]["write-1"]["status"] == "EXECUTING"


def test_changed_payload_never_executes(env):
    state, repo, calls = env

    with pytest.raises(module.ReservedExecutionError):
        run(repo, {"code": "TEST", "name": "Different"})

    assert calls == []


def test_missing_reservation_never_executes(env):
    state, repo, calls = env

    state["teammates"]["merchant-manager"][
        "direct_writes"
    ].clear()

    with pytest.raises(module.ReservedExecutionError):
        run(repo)

    assert calls == []


def test_reassigned_task_never_executes(env):
    state, repo, calls = env
    state["teammates"]["merchant-manager"][
        "current_task_id"
    ] = "other-task"

    with pytest.raises(module.ReservedExecutionError):
        run(repo)

    assert calls == []


def test_wrong_pane_never_executes(env):
    state, repo, calls = env

    with pytest.raises(module.ReservedExecutionError):
        run(repo, pane_session_id="other-pane")

    assert calls == []


def test_verified_reservation_does_not_execute(env):
    state, repo, calls = env

    state["teammates"]["merchant-manager"][
        "direct_writes"
    ]["write-1"]["status"] = "VERIFIED"

    with pytest.raises(module.ReservedExecutionError):
        run(repo)

    assert calls == []


def test_database_mismatch_never_executes(env):
    state, repo, calls = env

    repo.config.database = "coding_agent_merchant"

    with pytest.raises(module.ReservedExecutionError):
        run(repo)

    assert calls == []


def test_unauthorized_operation_never_executes(env):
    state, repo, calls = env

    state["teammates"]["merchant-manager"][
        "authorized_operations"
    ] = ["merchant_apply"]

    with pytest.raises(module.ReservedExecutionError):
        run(repo)

    assert calls == []


def test_execution_attempt_identity_is_persisted_and_forwarded(env):
    """Trusted reservation and write adapter must share one attempt UUID."""
    import uuid

    state, repo, calls = env

    result = run(repo)

    assert result["success"] is True
    assert len(calls) == 1

    reservation = state["teammates"]["merchant-manager"][
        "direct_writes"
    ]["write-1"]

    assert reservation["status"] == "EXECUTING"

    persisted_attempt = reservation.get("execution_attempt_id")

    assert isinstance(persisted_attempt, str)

    parsed_attempt = uuid.UUID(persisted_attempt)

    assert str(parsed_attempt) == persisted_attempt

    assert calls[0]["execution_attempt_id"] == parsed_attempt