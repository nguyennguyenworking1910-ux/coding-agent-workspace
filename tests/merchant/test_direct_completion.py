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
                        "execution_attempt_id": (
                            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                        ),
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

    # The trusted completion persistence boundary uses the same
    # in-memory state as the mocked read path.
    from contextlib import contextmanager

    @contextmanager
    def locked(_owner):
        yield state

    monkeypatch.setattr(
        module,
        "locked_team_state",
        locked,
    )

    def verify(repository, **kwargs):
        calls.append(kwargs)
        write = state["teammates"]["merchant-manager"][
            "direct_writes"
        ][kwargs["write_id"]]
        write["claim_generation"] = 1
        write["merchant_id"] = (
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        )
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


def test_attempt_identity_change_during_completion_is_rejected(
    env, monkeypatch
):
    """Completion must reject a changed trusted execution identity."""
    import uuid

    state, calls = env
    write = state["teammates"]["merchant-manager"][
        "direct_writes"
    ]["write-1"]

    original_attempt = str(uuid.uuid4())
    replacement_attempt = str(uuid.uuid4())

    write["execution_attempt_id"] = original_attempt

    def verify(repository, **kwargs):
        calls.append(kwargs)

        # Simulate trusted state changing during reconciliation.
        write["execution_attempt_id"] = replacement_attempt
        write["status"] = "VERIFIED"

        return dict(write)

    monkeypatch.setattr(
        module,
        "reconcile_committed_merchant_create",
        verify,
    )

    assert run() is False
    assert len(calls) == 1
    assert write["execution_attempt_id"] == replacement_attempt

def test_mutated_second_write_cannot_change_reconciliation_target(
    env, monkeypatch
):
    """Later reconciliation targets must use the original snapshot."""
    state, calls = env
    writes = state["teammates"]["merchant-manager"]["direct_writes"]

    second = deepcopy(writes["write-1"])
    second["write_id"] = "write-2"
    second["operation_key"] = "merchant-direct:v1:other"
    second["execution_attempt_id"] = (
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    )
    writes["write-2"] = second

    databases = []

    def repository_factory(database):
        databases.append(database)
        return object()

    def verify(repository, **kwargs):
        calls.append(kwargs)
        if kwargs["write_id"] == "write-1":
            writes["write-2"]["database"] = "runtime"

        writes[kwargs["write_id"]]["status"] = "VERIFIED"
        return dict(writes[kwargs["write_id"]])

    monkeypatch.setattr(
        module, "reconcile_committed_merchant_create", verify
    )

    result = module.reconcile_all_direct_writes(
        **CONTEXT,
        repository_factory=repository_factory,
    )

    assert result is False
    assert "runtime" not in databases


def test_bound_generation_mutation_blocks_completion(
    env, monkeypatch
):
    """A changed generation must block final report completion."""
    state, calls = env
    write = state["teammates"]["merchant-manager"][
        "direct_writes"
    ]["write-1"]

    write["claim_generation"] = 1

    def verify(repository, **kwargs):
        calls.append(kwargs)
        write["claim_generation"] = 2
        write["status"] = "VERIFIED"
        return dict(write)

    monkeypatch.setattr(
        module,
        "reconcile_committed_merchant_create",
        verify,
    )

    assert run() is False
    assert write["claim_generation"] == 2


def test_verified_write_requires_valid_generation(
    env, monkeypatch
):
    """A VERIFIED write without a valid generation is incomplete."""
    state, calls = env
    write = state["teammates"]["merchant-manager"][
        "direct_writes"
    ]["write-1"]

    def verify(repository, **kwargs):
        calls.append(kwargs)
        write["status"] = "VERIFIED"
        return dict(write)

    monkeypatch.setattr(
        module,
        "reconcile_committed_merchant_create",
        verify,
    )

    assert run() is False



def test_completion_persists_exact_receipt(env, monkeypatch):
    """Trusted completion persists a receipt for verified writes."""
    from contextlib import contextmanager

    from claude.hooks.merchant_completion_receipt import (
        receipt_matches_state,
    )

    state, calls = env

    @contextmanager
    def locked(_owner):
        yield state

    monkeypatch.setattr(
        module, "locked_team_state", locked, raising=False
    )

    assert run() is True

    record = state["teammates"]["merchant-manager"]
    receipt = record.get("direct_completion_receipt")

    assert receipt is not None
    assert receipt_matches_state(record, receipt)


def test_completion_rejects_mutation_before_receipt_persist(
    env, monkeypatch
):
    """Mutation at final lock boundary must prevent receipt creation."""
    from contextlib import contextmanager

    state, calls = env
    record = state["teammates"]["merchant-manager"]

    @contextmanager
    def locked(_owner):
        record["direct_writes"]["write-1"][
            "claim_generation"
        ] = 2
        yield state

    monkeypatch.setattr(
        module, "locked_team_state", locked, raising=False
    )

    assert run() is False
    assert "direct_completion_receipt" not in record
