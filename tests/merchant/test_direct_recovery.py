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



def test_repeat_recovery_preserves_verified_identity(
    env, monkeypatch
):
    """A second reconciliation must not mutate verified identity."""
    import copy

    state, repo = env
    current = reservation(state)

    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = (
        "00000000-0000-4000-8000-000000000001"
    )
    current["claim_generation"] = 1

    calls = []

    def verify(_repo, **kwargs):
        calls.append(dict(kwargs))
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

    first = module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    )

    assert first is not None
    assert first["status"] == "VERIFIED"

    verified_snapshot = copy.deepcopy(current)

    try:
        second = module.reconcile_committed_merchant_create(
            repo, **CONTEXT
        )
    except module.DirectRecoveryError:
        second = None

    assert current == verified_snapshot
    assert current["status"] == "VERIFIED"
    assert current["claim_generation"] == 1
    assert current["execution_attempt_id"] == (
        "00000000-0000-4000-8000-000000000001"
    )
    assert current["merchant_id"] == "merchant-123"

    # A rejected duplicate is acceptable. An accepted duplicate
    # must still refer to exactly the original verified identity.
    if second is not None:
        assert second["status"] == "VERIFIED"
        assert second["execution_attempt_id"] == (
            current["execution_attempt_id"]
        )
        assert second["claim_generation"] == 1
        assert second["merchant_id"] == "merchant-123"

    # This mock represents evidence reads, not business writes.
    assert len(calls) >= 1



def test_persistence_failure_retries_original_committed_attempt(
    env, monkeypatch
):
    """A failed state save must not create a new execution identity."""
    import copy
    import uuid
    from contextlib import contextmanager

    initial_state, repo = env

    current = reservation(initial_state)
    attempt = "00000000-0000-4000-8000-000000000001"
    merchant_id = "11111111-1111-4111-8111-111111111111"

    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = attempt
    current["claim_generation"] = 1

    # Model the durable JSON document separately from in-memory state.
    durable = copy.deepcopy(initial_state)
    lock_entries = []
    evidence_reads = []

    @contextmanager
    def simulated_locked_state(_session_id):
        local = copy.deepcopy(durable)
        lock_entries.append(len(lock_entries) + 1)
        entry_number = len(lock_entries)

        yield local

        # Fail on the second lock's persistence boundary,
        # after the recovery code has mutated its local state.
        if entry_number == 2:
            raise OSError("SIMULATED_STATE_PERSISTENCE_FAILURE")

        # A successful save atomically replaces the durable snapshot.
        durable.clear()
        durable.update(copy.deepcopy(local))

    def verify(_repo, **kwargs):
        evidence_reads.append(dict(kwargs))

        assert kwargs["execution_attempt_id"] == uuid.UUID(attempt)
        assert kwargs["claim_generation"] == 1

        return {
            "verified": True,
            "merchant_id": merchant_id,
            "claim_generation": 1,
        }

    monkeypatch.setattr(
        module,
        "locked_team_state",
        simulated_locked_state,
    )
    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        verify,
    )

    # Recovery verified PostgreSQL evidence, but saving VERIFIED fails.
    with pytest.raises(
        OSError,
        match="SIMULATED_STATE_PERSISTENCE_FAILURE",
    ):
        module.reconcile_committed_merchant_create(
            repo, **CONTEXT
        )

    after_failure = reservation(durable)

    assert after_failure["status"] == "EXECUTING"
    assert after_failure["execution_attempt_id"] == attempt
    assert after_failure["claim_generation"] == 1
    assert "merchant_id" not in after_failure

    # Retrying recovery reads the SAME committed evidence.
    recovered = module.reconcile_committed_merchant_create(
        repo, **CONTEXT
    )

    assert recovered is not None
    assert recovered["status"] == "VERIFIED"
    assert recovered["execution_attempt_id"] == attempt
    assert recovered["claim_generation"] == 1
    assert recovered["merchant_id"] == merchant_id

    persisted = reservation(durable)

    assert persisted["status"] == "VERIFIED"
    assert persisted["execution_attempt_id"] == attempt
    assert persisted["claim_generation"] == 1
    assert persisted["merchant_id"] == merchant_id

    assert len(evidence_reads) == 2
    assert len(lock_entries) == 4



def test_team_state_failed_atomic_replace_preserves_durable_state(
    tmp_path, monkeypatch
):
    """Failed replacement must preserve the last durable state."""
    import json
    from pathlib import Path

    from claude.hooks import team_lifecycle

    target = tmp_path / "session.json"

    monkeypatch.setattr(
        team_lifecycle,
        "team_state_path",
        lambda _session: target,
    )

    original = {
        "session_id": "owner-1",
        "teammates": {
            "merchant-manager": {
                "status": "RUNNING",
                "direct_writes": {
                    "write-1": {
                        "status": "EXECUTING",
                        "execution_attempt_id": (
                            "00000000-0000-4000-8000-000000000001"
                        ),
                        "claim_generation": 1,
                    }
                },
            }
        },
    }

    team_lifecycle.save_team_state("owner-1", original)

    original_bytes = target.read_bytes()
    assert json.loads(original_bytes) == original

    verified = json.loads(original_bytes)
    write = verified["teammates"]["merchant-manager"][
        "direct_writes"
    ]["write-1"]

    write["status"] = "VERIFIED"
    write["merchant_id"] = (
        "11111111-1111-4111-8111-111111111111"
    )

    actual_replace = team_lifecycle.replace_with_retry
    attempts = []

    def fail_replace(source, destination):
        attempts.append((source, destination))
        assert Path(source).exists()
        assert Path(destination) == target
        raise OSError("SIMULATED_ATOMIC_REPLACE_FAILURE")

    monkeypatch.setattr(
        team_lifecycle,
        "replace_with_retry",
        fail_replace,
    )

    with pytest.raises(
        OSError,
        match="SIMULATED_ATOMIC_REPLACE_FAILURE",
    ):
        team_lifecycle.save_team_state("owner-1", verified)

    assert len(attempts) == 1

    # Previous committed filesystem snapshot must survive.
    assert target.read_bytes() == original_bytes

    # No stale scratch files should remain after a failed replace.
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "session.json"
    ]

    monkeypatch.setattr(
        team_lifecycle,
        "replace_with_retry",
        actual_replace,
    )

    team_lifecycle.save_team_state("owner-1", verified)

    assert json.loads(target.read_text(encoding="utf-8")) == verified

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "session.json"
    ]



def test_real_locked_recovery_survives_failed_verified_persistence(
    tmp_path, monkeypatch
):
    """Retry through real locks and JSON persistence preserves identity."""
    import json
    import uuid

    from claude.hooks import team_lifecycle

    target = tmp_path / "owner-1.json"
    lock_path = tmp_path / "owner-1.lock"

    monkeypatch.setattr(
        team_lifecycle, "team_state_dir", lambda: tmp_path
    )
    monkeypatch.setattr(
        team_lifecycle,
        "team_state_path",
        lambda _session: target,
    )
    monkeypatch.setattr(
        team_lifecycle,
        "team_lock_path",
        lambda _session: lock_path,
    )

    state = state_fixture()
    current = reservation(state)
    attempt = "00000000-0000-4000-8000-000000000001"
    merchant_id = "11111111-1111-4111-8111-111111111111"

    current["status"] = "EXECUTING"
    current["execution_attempt_id"] = attempt
    current["claim_generation"] = 1

    team_lifecycle.save_team_state("owner-1", state)

    repo = SimpleNamespace(
        config=SimpleNamespace(
            database="coding_agent_merchant_test"
        )
    )

    # Use real lifecycle lock, not the existing in-memory fixture.
    monkeypatch.setattr(
        module,
        "locked_team_state",
        team_lifecycle.locked_team_state,
    )

    evidence_reads = []
    diagnostic_events = []

    def collect_diagnostic(encoded):
        import json
        diagnostic_events.append(json.loads(encoded))

    def verify(_repo, **kwargs):
        evidence_reads.append(dict(kwargs))

        assert kwargs["execution_attempt_id"] == uuid.UUID(attempt)
        assert kwargs["claim_generation"] == 1

        return {
            "verified": True,
            "merchant_id": merchant_id,
            "claim_generation": 1,
        }

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        verify,
    )

    original_replace = team_lifecycle.replace_with_retry
    failures = []

    def fail_verified_replace(source, destination):
        pending = json.loads(
            Path(source).read_text(encoding="utf-8")
        )

        pending_write = reservation(pending)

        if (
            pending_write["status"] == "VERIFIED"
            and not failures
        ):
            failures.append("verified-save")
            raise OSError("INJECTED_VERIFIED_SAVE_FAILURE")

        return original_replace(source, destination)

    from pathlib import Path

    monkeypatch.setattr(
        team_lifecycle,
        "replace_with_retry",
        fail_verified_replace,
    )

    with pytest.raises(
        OSError,
        match="INJECTED_VERIFIED_SAVE_FAILURE",
    ):
        module.reconcile_committed_merchant_create(
            repo,
            **CONTEXT,
            diagnostic_sink=collect_diagnostic,
        )

    assert diagnostic_events == []

    persisted_after_failure = json.loads(
        target.read_text(encoding="utf-8")
    )
    failed_write = reservation(persisted_after_failure)

    assert failed_write["status"] == "EXECUTING"
    assert failed_write["execution_attempt_id"] == attempt
    assert failed_write["claim_generation"] == 1
    assert "merchant_id" not in failed_write

    recovered = module.reconcile_committed_merchant_create(
        repo,
        **CONTEXT,
        diagnostic_sink=collect_diagnostic,
    )

    assert len(diagnostic_events) == 1
    assert diagnostic_events[0]["event_type"] == "merchant.recovery"
    assert diagnostic_events[0]["outcome"] == "verified"
    assert diagnostic_events[0]["claim_generation"] == 1

    assert recovered is not None
    assert recovered["status"] == "VERIFIED"

    persisted_after_retry = json.loads(
        target.read_text(encoding="utf-8")
    )
    final_write = reservation(persisted_after_retry)

    assert final_write["status"] == "VERIFIED"
    assert final_write["execution_attempt_id"] == attempt
    assert final_write["claim_generation"] == 1
    assert final_write["merchant_id"] == merchant_id

    assert len(evidence_reads) == 2
    assert failures == ["verified-save"]

    assert not list(tmp_path.glob("*.tmp"))



def test_verified_diagnostic_emitted_only_after_persistence(
    env, monkeypatch
):
    """Emit only after the trusted state context has exited."""
    import json
    from contextlib import contextmanager

    state, repo = env
    write = reservation(state)
    write["status"] = "EXECUTING"
    write["execution_attempt_id"] = (
        "00000000-0000-4000-8000-000000000001"
    )
    write["claim_generation"] = 1

    events = []
    inside_lock = [False]

    @contextmanager
    def locked(_owner):
        inside_lock[0] = True
        try:
            yield state
        finally:
            inside_lock[0] = False

    monkeypatch.setattr(module, "locked_team_state", locked)

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda _repo, **kwargs: {
            "verified": True,
            "merchant_id": "merchant-123",
            "claim_generation": 1,
        },
    )

    def sink(encoded):
        assert inside_lock[0] is False
        events.append(json.loads(encoded))

    result = module.reconcile_committed_merchant_create(
        repo,
        **CONTEXT,
        diagnostic_sink=sink,
    )

    assert result["status"] == "VERIFIED"
    assert len(events) == 1
    assert events[0]["event_type"] == "merchant.recovery"
    assert events[0]["outcome"] == "verified"
    assert events[0]["claim_generation"] == 1


def test_diagnostic_sink_failure_cannot_fail_verified_recovery(
    env, monkeypatch
):
    """A broken diagnostic sink cannot change a verified result."""
    state, repo = env
    write = reservation(state)
    write["status"] = "EXECUTING"
    write["execution_attempt_id"] = (
        "00000000-0000-4000-8000-000000000001"
    )
    write["claim_generation"] = 1

    monkeypatch.setattr(
        module,
        "verify_committed_merchant_create",
        lambda _repo, **kwargs: {
            "verified": True,
            "merchant_id": "merchant-123",
            "claim_generation": 1,
        },
    )

    def broken_sink(_encoded):
        raise OSError("PRIVATE_DIAGNOSTIC_SINK_FAILURE")

    result = module.reconcile_committed_merchant_create(
        repo,
        **CONTEXT,
        diagnostic_sink=broken_sink,
    )

    assert result["status"] == "VERIFIED"
    assert reservation(state)["status"] == "VERIFIED"
