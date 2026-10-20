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
    reservation(state)["execution_attempt_id"] = (
        "00000000-0000-4000-8000-000000000001"
    )

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
    reservation(state)["execution_attempt_id"] = (
        "00000000-0000-4000-8000-000000000001"
    )

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


def test_attempt_changed_during_verification_is_rejected(
    env, monkeypatch
):
    """Stale evidence must not verify a different execution attempt."""
    import uuid

    state, repo = env
    current = reservation(state)

    original_attempt = str(uuid.uuid4())
    replacement_attempt = str(uuid.uuid4())

    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = original_attempt

    def verify(
        _repo,
        *,
        operation_key,
        payload_hash,
        execution_attempt_id,
    ):
        assert operation_key == KEY
        assert payload_hash == HASH
        assert execution_attempt_id == uuid.UUID(original_attempt)

        # Simulate state mutation while PostgreSQL evidence is read.
        current["execution_attempt_id"] = replacement_attempt

        return {
            "verified": True,
            "merchant_id": "merchant-123",
        }

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        verify,
    )

    with pytest.raises(module.DirectRecoveryError):
        module.reconcile_committed_merchant_create(
            repo, **CONTEXT
        )

    assert current["status"] == "EXECUTING"
    assert current["execution_attempt_id"] == replacement_attempt
    assert "merchant_id" not in current

def test_executing_recovery_requires_bound_claim_attempt(
    env, monkeypatch
):
    """Recovery must pass persisted attempt ID to DB evidence verifier."""
    import uuid

    state, repo = env
    current = reservation(state)

    attempt_id = uuid.uuid4()

    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = str(attempt_id)

    def verify(
        _repo,
        *,
        operation_key,
        payload_hash,
        execution_attempt_id,
    ):
        assert operation_key == KEY
        assert payload_hash == HASH
        assert execution_attempt_id == attempt_id

        return {
            "verified": True,
            "merchant_id": "merchant-123",
        }

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        verify,
    )

    result = module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    )

    assert result is not None
    assert result["status"] == "VERIFIED"
    assert current["execution_attempt_id"] == str(attempt_id)


def test_executing_recovery_rejects_missing_attempt(
    env, monkeypatch
):
    """Missing trusted attempt must not reach PostgreSQL verification."""
    state, repo = env
    current = reservation(state)

    current["status"] = "EXECUTING"
    current.pop("execution_attempt_id", None)

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

    assert current["status"] == "EXECUTING"
    assert "merchant_id" not in current

@pytest.mark.parametrize(
    "bad_attempt",
    [
        "",
        "not-a-uuid",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa".upper(),
        123,
    ],
)
def test_executing_recovery_rejects_malformed_attempt(
    env, monkeypatch, bad_attempt
):
    """Invalid attempt IDs must fail before evidence verification."""
    state, repo = env
    current = reservation(state)
    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = bad_attempt

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda *args, **kwargs: pytest.fail(
            "Invalid attempt must not reach verifier"
        ),
    )

    with pytest.raises(module.DirectRecoveryError):
        module.reconcile_committed_merchant_create(
            repo, **CONTEXT
        )

    assert current["status"] == "EXECUTING"
    assert "merchant_id" not in current


def test_unknown_commit_preserves_trusted_attempt(
    env, monkeypatch
):
    """Missing committed evidence never authorizes a new attempt."""
    import uuid

    state, repo = env
    current = reservation(state)
    attempt = uuid.uuid4()

    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = str(attempt)

    calls = []

    def verify(
        _repo,
        *,
        operation_key,
        payload_hash,
        execution_attempt_id,
    ):
        calls.append(execution_attempt_id)
        assert operation_key == KEY
        assert payload_hash == HASH
        return None

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        verify,
    )

    result = module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    )

    assert result is None
    assert calls == [attempt]
    assert current["status"] == "EXECUTING"
    assert current["execution_attempt_id"] == str(attempt)
    assert "merchant_id" not in current