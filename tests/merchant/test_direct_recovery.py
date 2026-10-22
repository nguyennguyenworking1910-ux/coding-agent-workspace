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


def test_reserved_write_cannot_verify_unbound_evidence(
    env, monkeypatch
):
    state, repo = env

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda *args, **kwargs: pytest.fail(
            "RESERVED write must not query evidence"
        ),
    )

    result = module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    )

    assert result is None
    assert reservation(state)["status"] == "RESERVED"
    assert "merchant_id" not in reservation(state)

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
    reservation(state)["status"] = "EXECUTING"
    reservation(state)["execution_attempt_id"] = (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )

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

    assert reservation(state)["status"] == "EXECUTING"


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
            "verified": True,
            "merchant_id": "merchant-123",
            "claim_generation": 1,
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
            "claim_generation": 1,
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

def test_unbound_reserved_write_cannot_be_verified(env, monkeypatch):
    """A reservation without an attempt is not committed-write proof."""
    state, repo = env
    current = reservation(state)

    assert current["status"] == "RESERVED"
    assert "execution_attempt_id" not in current

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda *args, **kwargs: pytest.fail(
            "Unbound RESERVED must not query committed evidence"
        ),
    )

    result = module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    )

    assert result is None
    assert current["status"] == "RESERVED"
    assert "merchant_id" not in current

def test_verified_without_attempt_cannot_reverify(env, monkeypatch):
    """Legacy VERIFIED without trusted attempt must fail closed."""
    state, repo = env
    current = reservation(state)
    current["status"] = "VERIFIED"
    current["merchant_id"] = "merchant-legacy"
    current.pop("execution_attempt_id", None)

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda *args, **kwargs: pytest.fail(
            "Unbound VERIFIED must not query evidence"
        ),
    )

    with pytest.raises(module.DirectRecoveryError):
        module.reconcile_committed_merchant_create(
            repo, **CONTEXT
        )

    assert current["status"] == "VERIFIED"
    assert current["merchant_id"] == "merchant-legacy"




def test_missing_generation_without_committed_evidence(
    env, monkeypatch
):
    """Unknown commit must remain EXECUTING without retry."""
    state, repo = env
    current = reservation(state)

    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = (
        "00000000-0000-4000-8000-000000000001"
    )
    current.pop("claim_generation", None)

    calls = []

    def verify(_repo, **kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(
        module, "verify_committed_merchant_create", verify
    )

    result = module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    )

    assert result is None
    assert len(calls) == 1
    assert current["status"] == "EXECUTING"
    assert "claim_generation" not in current
    assert "merchant_id" not in current


def test_committed_evidence_bootstraps_exact_generation(
    env, monkeypatch
):
    """Crash recovery can bind the generation of its own claim."""
    import uuid

    state, repo = env
    current = reservation(state)

    attempt = uuid.uuid4()
    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = str(attempt)
    current.pop("claim_generation", None)

    def verify(
        _repo,
        *,
        operation_key,
        payload_hash,
        execution_attempt_id,
        **kwargs,
    ):
        assert operation_key == KEY
        assert payload_hash == HASH
        assert execution_attempt_id == attempt

        return {
            "verified": True,
            "merchant_id": "merchant-123",
            "claim_generation": 1,
        }

    monkeypatch.setattr(
        module, "verify_committed_merchant_create", verify
    )

    result = module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    )

    assert result is not None
    assert result["status"] == "VERIFIED"
    assert result["claim_generation"] == 1
    assert current["claim_generation"] == 1
    assert current["merchant_id"] == "merchant-123"


def test_generation_change_during_verification_is_rejected(
    env, monkeypatch
):
    """Evidence cannot overwrite an intervening generation change."""
    import uuid

    state, repo = env
    current = reservation(state)

    attempt = uuid.uuid4()
    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = str(attempt)
    current["claim_generation"] = 1

    def verify(_repo, **kwargs):
        assert kwargs.get("claim_generation") == 1

        # Simulate an unauthorized concurrent state mutation.
        current["claim_generation"] = 2

        return {
            "verified": True,
            "merchant_id": "merchant-123",
            "claim_generation": 1,
        }

    monkeypatch.setattr(
        module, "verify_committed_merchant_create", verify
    )

    with pytest.raises(module.DirectRecoveryError):
        module.reconcile_committed_merchant_create(
            repo, **CONTEXT
        )

    assert current["status"] == "EXECUTING"
    assert current["claim_generation"] == 2
    assert "merchant_id" not in current
