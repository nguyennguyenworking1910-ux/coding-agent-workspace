"""CP12H.5C: atomic attempt evidence, replay, crash and fence on the test DB."""

import dataclasses
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

from claude.clients.merchant.attempt_evidence import (
    COMMITTED,
    NOT_COMMITTED,
    UNCERTAIN,
    AttemptIdentity,
    EvidenceBindingError,
    evidence_bound_repository,
    resolve_attempt,
)
from claude.clients.merchant.merchant_repository import MerchantEntityRepository
from claude.clients.merchant.repository import MerchantRepository


pytestmark = pytest.mark.skipif(
    os.environ.get("MERCHANT_TEST_DB_NAME")
    != "coding_agent_merchant_test"
    or not os.environ.get("MERCHANT_TEST_PASSWORD"),
    reason="Merchant test database is not configured",
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def case():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    identity = AttemptIdentity(
        operation_key=f"pytest:attempt:{uuid.uuid4()}",
        payload_hash=uuid.uuid4().hex * 2,
        execution_attempt_id=uuid.uuid4(),
        command="merchant create",
    )
    merchant_id = str(uuid.uuid4())
    code = f"T{uuid.uuid4().hex[:18].upper()}"

    yield repository, identity, merchant_id, code

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                for table in (
                    "merchant_execution_claims",
                    "merchant_execution_ledger",
                ):
                    cursor.execute(
                        f"DELETE FROM merchant_ops.{table} "
                        "WHERE operation_key = %s",
                        (identity.operation_key,),
                    )
                cursor.execute(
                    "DELETE FROM merchant_ops.project_events "
                    "WHERE merchant_id = %s",
                    (uuid.UUID(merchant_id),),
                )
                cursor.execute(
                    "DELETE FROM merchant_ops.merchants WHERE id = %s",
                    (uuid.UUID(merchant_id),),
                )


def snapshot(repository, identity, merchant_id):
    with repository.connection(read_only=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT claim_status, execution_attempt_id "
                "FROM merchant_ops.merchant_execution_claims "
                "WHERE operation_key = %s",
                (identity.operation_key,),
            )
            claim = cursor.fetchone()
            cursor.execute(
                "SELECT result FROM merchant_ops.merchant_execution_ledger "
                "WHERE operation_key = %s",
                (identity.operation_key,),
            )
            ledger = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(*) AS n FROM merchant_ops.merchants "
                "WHERE id = %s",
                (uuid.UUID(merchant_id),),
            )
            merchants = cursor.fetchone()["n"]

    return claim, ledger, merchants


def create(repository, merchant_id, code):
    return MerchantEntityRepository(repository).create_merchant(
        merchant_id=merchant_id,
        code=code,
        name="CP12H5C attempt evidence",
    )


def test_mutation_and_evidence_commit_together(case):
    repository, identity, merchant_id, code = case

    create(evidence_bound_repository(repository, identity), merchant_id, code)

    claim, ledger, merchants = snapshot(repository, identity, merchant_id)
    assert merchants == 1
    assert claim["claim_status"] == "COMPLETED"
    assert str(claim["execution_attempt_id"]) == str(
        identity.execution_attempt_id
    )
    assert ledger["result"]["execution_attempt_id"] == str(
        identity.execution_attempt_id
    )
    assert resolve_attempt(repository, identity, fence=False) == COMMITTED
    # A fence never overrides committed evidence.
    assert resolve_attempt(repository, identity, fence=True) == COMMITTED


def test_failed_mutation_rolls_back_evidence_then_fence_settles(case):
    repository, identity, merchant_id, code = case

    with pytest.raises(Exception):
        create(
            evidence_bound_repository(repository, identity),
            merchant_id,
            "",  # rejected inside the transaction
        )

    assert snapshot(repository, identity, merchant_id) == (None, None, 0)
    assert resolve_attempt(repository, identity, fence=False) == UNCERTAIN
    assert resolve_attempt(repository, identity, fence=True) == NOT_COMMITTED

    claim, _, _ = snapshot(repository, identity, merchant_id)
    assert claim["claim_status"] == "REVOKED"

    # The fenced attempt can never commit afterwards.
    with pytest.raises(Exception):
        create(
            evidence_bound_repository(repository, identity),
            merchant_id,
            code,
        )

    assert snapshot(repository, identity, merchant_id)[2] == 0


def test_replay_of_the_same_operation_never_writes_twice(case):
    repository, identity, merchant_id, code = case

    create(evidence_bound_repository(repository, identity), merchant_id, code)

    replay = dataclasses.replace(identity, execution_attempt_id=uuid.uuid4())

    with pytest.raises(Exception):
        create(
            evidence_bound_repository(repository, replay),
            str(uuid.uuid4()),
            f"R{code[1:]}",
        )

    assert snapshot(repository, identity, merchant_id)[2] == 1
    assert resolve_attempt(repository, replay, fence=True) == UNCERTAIN
    assert resolve_attempt(repository, identity, fence=False) == COMMITTED


def test_second_write_transaction_is_refused(case):
    repository, identity, merchant_id, code = case
    bound = evidence_bound_repository(repository, identity)

    create(bound, merchant_id, code)

    with pytest.raises(EvidenceBindingError):
        with bound.connection() as connection:
            with connection.transaction():
                pass


CHILD = r"""
import os, sys, uuid
sys.path.insert(0, sys.argv[1])
from claude.clients.merchant.attempt_evidence import (
    AttemptIdentity, evidence_bound_repository,
)
from claude.clients.merchant import merchant_repository
from claude.clients.merchant.repository import MerchantRepository

key, payload_hash, attempt, merchant_id, code, mode = sys.argv[2:8]
identity = AttemptIdentity(key, payload_hash, uuid.UUID(attempt), "merchant create")
bound = evidence_bound_repository(MerchantRepository(role="test"), identity)

if mode == "crash-before-commit":
    original = merchant_repository.MerchantEntityRepository._insert_creation_event

    def crash(*args, **kwargs):
        original(*args, **kwargs)  # merchant row and event written, uncommitted
        os._exit(17)

    merchant_repository.MerchantEntityRepository._insert_creation_event = (
        staticmethod(crash)
    )

merchant_repository.MerchantEntityRepository(bound).create_merchant(
    merchant_id=merchant_id, code=code, name="CP12H5C crash",
)
os._exit(18)  # committed, but the caller never learns the outcome
"""


def run_child(identity, merchant_id, code, mode):
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD,
            str(ROOT),
            identity.operation_key,
            identity.payload_hash,
            str(identity.execution_attempt_id),
            merchant_id,
            code,
            mode,
        ],
        env=os.environ.copy(),
        capture_output=True,
        timeout=120,
    )
    return completed.returncode


def test_process_crash_before_commit_is_fenced_not_committed(case):
    repository, identity, merchant_id, code = case

    assert run_child(identity, merchant_id, code, "crash-before-commit") == 17

    assert snapshot(repository, identity, merchant_id) == (None, None, 0)
    assert resolve_attempt(repository, identity, fence=True) == NOT_COMMITTED


def test_process_crash_after_commit_is_recovered_as_committed(case):
    repository, identity, merchant_id, code = case

    assert run_child(identity, merchant_id, code, "crash-after-commit") == 18

    assert resolve_attempt(repository, identity, fence=True) == COMMITTED
    assert snapshot(repository, identity, merchant_id)[2] == 1


def test_fence_never_settles_an_in_flight_attempt(case):
    repository, identity, merchant_id, code = case
    holding = threading.Event()
    release = threading.Event()
    errors = []

    def in_flight():
        try:
            bound = evidence_bound_repository(repository, identity)
            with bound.connection() as connection:
                with connection.transaction():
                    holding.set()
                    release.wait(30)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
            holding.set()

    worker = threading.Thread(target=in_flight)
    worker.start()
    assert holding.wait(30)

    impatient = MerchantRepository(
        dataclasses.replace(repository.config, lock_timeout_ms=300)
    )

    try:
        assert resolve_attempt(impatient, identity, fence=True) == UNCERTAIN
    finally:
        release.set()
        worker.join(30)

    assert not errors
    assert resolve_attempt(repository, identity, fence=True) == COMMITTED


def test_handoff_scope_writes_commit_with_their_evidence(case):
    """The real handoff factory: handler mutation and evidence are atomic."""

    from claude.hooks import merchant_direct_handoff

    repository, identity, merchant_id, code = case
    payload = {"merchant_id": merchant_id, "code": code, "name": "CP12H5C"}

    commands = merchant_direct_handoff._scope_write_commands(
        "test", repository, identity
    )
    commands.execute("merchant create", "test", payload)

    assert snapshot(repository, identity, merchant_id)[2] == 1
    assert resolve_attempt(repository, identity, fence=False) == COMMITTED

    # A replay through a fresh factory for the same operation never writes.
    replay = dataclasses.replace(identity, execution_attempt_id=uuid.uuid4())
    other_id = str(uuid.uuid4())

    with pytest.raises(Exception):
        merchant_direct_handoff._scope_write_commands(
            "test", repository, replay
        ).execute(
            "merchant create",
            "test",
            {"merchant_id": other_id, "code": f"R{code[1:]}", "name": "R"},
        )

    assert snapshot(repository, identity, other_id)[2] == 0


def test_retention_sweeps_only_aged_test_claims():
    """Ancient rows make the sweep touch only what this test inserted."""

    from claude.clients.merchant.claim_retention import sweep_test_claims

    repository = MerchantRepository(role="test")
    test_key = f"pytest:retention:{uuid.uuid4()}"
    operational_key = "merchant-direct:v1:" + uuid.uuid4().hex * 2

    with repository.connection() as connection:
        with connection.transaction():
            for key, status in (
                (test_key, "COMPLETED"),
                (operational_key, "REVOKED"),
            ):
                connection.execute(
                    "INSERT INTO merchant_ops.merchant_execution_claims ("
                    "operation_key, payload_hash, execution_attempt_id, "
                    "claim_status, claimed_at, updated_at) VALUES "
                    "(%s, %s, %s, %s, NOW() - interval '3650 days', "
                    "NOW() - interval '3650 days')",
                    (key, "c" * 64, uuid.uuid4(), status),
                )

    try:
        planned = sweep_test_claims(
            repository, older_than_days=3000, apply=False
        )
        assert [row["operation_key"] for row in planned] == [test_key]

        swept = sweep_test_claims(
            repository, older_than_days=3000, apply=True
        )
        assert [row["operation_key"] for row in swept] == [test_key]

        with repository.connection(read_only=True) as connection:
            remaining = connection.execute(
                "SELECT operation_key FROM merchant_ops.merchant_execution_claims "
                "WHERE operation_key = ANY(%s)",
                ([test_key, operational_key],),
            ).fetchall()

        # Operational evidence (here a fence) is never swept.
        assert [row["operation_key"] for row in remaining] == [operational_key]
    finally:
        with repository.connection() as connection:
            with connection.transaction():
                connection.execute(
                    "DELETE FROM merchant_ops.merchant_execution_claims "
                    "WHERE operation_key = ANY(%s)",
                    ([test_key, operational_key],),
                )


def test_retention_refuses_any_database_but_test():
    from contextlib import contextmanager

    from claude.clients.merchant.claim_retention import sweep_test_claims

    class Runtime:
        @contextmanager
        def connection(self, read_only=False):
            class Cursor:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def execute(self, *args):
                    pass

                def fetchone(self):
                    return {"db": "coding_agent_merchant", "u": "merchant_app"}

            class Connection:
                @contextmanager
                def transaction(self):
                    yield

                def cursor(self):
                    return Cursor()

            yield Connection()

    with pytest.raises(PermissionError):
        sweep_test_claims(Runtime(), older_than_days=1, apply=True)
