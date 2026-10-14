from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from claude.hooks import merchant_direct_recovery as module


KEY = "merchant-direct:v1:example"
HASH = "a" * 64

CONTEXT = {
    "owner_session_id": "owner-1",
    "teammate_name": "merchant-manager",
    "run_id": "run-1",
    "task_id": "task-1",
    "write_id": "write-1",
    "database": "test",
}


def state_fixture():
    return {
        "teammates": {
            "merchant-manager": {
                "canonical_name": "merchant-manager",
                "status": "RUNNING",
                "current_run_id": "run-1",
                "current_task_id": "task-1",
                "authorized_operations": ["merchant_execute"],
                "authorized_selected_agents": ["merchant-manager"],
                "result_received": False,
                "report_source": None,
                "direct_writes": {
                    "write-1": {
                        "write_id": "write-1",
                        "run_id": "run-1",
                        "task_id": "task-1",
                        "database": "test",
                        "command": "merchant create",
                        "operation_key": KEY,
                        "payload_hash": HASH,
                        "status": "RESERVED",
                    }
                },
            }
        }
    }


@pytest.fixture
def env(monkeypatch):
    state = state_fixture()

    @contextmanager
    def locked(_session_id):
        yield state

    monkeypatch.setattr(module, "locked_team_state", locked)

    repo = SimpleNamespace(
        config=SimpleNamespace(
            database="coding_agent_merchant_test"
        )
    )

    return state, repo


def reservation(state):
    return state["teammates"]["merchant-manager"][
        "direct_writes"
    ]["write-1"]


def test_committed_write_becomes_verified(env, monkeypatch):
    state, repo = env

    def verify(_repo, *, operation_key, payload_hash):
        assert operation_key == KEY
        assert payload_hash == HASH
        return {
            "verified": True,
            "merchant_id": "merchant-123",
        }

    monkeypatch.setattr(
        module, "verify_committed_merchant_create", verify
    )

    result = module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    )

    assert result["status"] == "VERIFIED"
    assert result["merchant_id"] == "merchant-123"
    assert reservation(state)["status"] == "VERIFIED"
    assert state["teammates"]["merchant-manager"]["status"] == "RUNNING"
    assert state["teammates"]["merchant-manager"]["result_received"] is False


def test_missing_evidence_keeps_reserved(env, monkeypatch):
    state, repo = env

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda *args, **kwargs: None,
    )

    assert module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    ) is None

    assert reservation(state)["status"] == "RESERVED"


def test_reassigned_task_is_rejected(env, monkeypatch):
    state, repo = env
    state["teammates"]["merchant-manager"][
        "current_task_id"
    ] = "new-task"

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda *args, **kwargs: pytest.fail(
            "Verifier must not be called"
        ),
    )

    with pytest.raises(module.DirectRecoveryError):
        module.reconcile_committed_merchant_create(
            repo, **CONTEXT
        )


def test_reassignment_during_db_read_is_rejected(
    env, monkeypatch
):
    state, repo = env

    def verify(*args, **kwargs):
        state["teammates"]["merchant-manager"][
            "current_task_id"
        ] = "new-task"
        return {
            "verified": True,
            "merchant_id": "merchant-123",
        }

    monkeypatch.setattr(
        module, "verify_committed_merchant_create", verify
    )

    with pytest.raises(module.DirectRecoveryError):
        module.reconcile_committed_merchant_create(
            repo, **CONTEXT
        )

    assert reservation(state)["status"] == "RESERVED"


def test_database_mismatch_is_rejected(env, monkeypatch):
    state, repo = env

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda *args, **kwargs: pytest.fail(
            "Verifier must not be called"
        ),
    )

    with pytest.raises(module.DirectRecoveryError):
        module.reconcile_committed_merchant_create(
            repo,
            **{**CONTEXT, "database": "runtime"},
        )


def test_executing_committed_write_becomes_verified(
    env, monkeypatch
):
    state, repo = env
    reservation(state)["status"] = "EXECUTING"

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda *args, **kwargs: {
            "merchant_id": "merchant-123",
        },
    )

    result = module.reconcile_committed_merchant_create(
        repository=repo,
        owner_session_id="owner-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        write_id="write-1",
        database="test",
    )

    assert result is not None
    assert result["status"] == "VERIFIED"
    assert reservation(state)["status"] == "VERIFIED"


def test_executing_without_evidence_stays_executing(
    env, monkeypatch
):
    state, repo = env
    reservation(state)["status"] = "EXECUTING"

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda *args, **kwargs: None,
    )

    result = module.reconcile_committed_merchant_create(
        repository=repo,
        owner_session_id="owner-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        write_id="write-1",
        database="test",
    )

    assert result is None
    assert reservation(state)["status"] == "EXECUTING"
