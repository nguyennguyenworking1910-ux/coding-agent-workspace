import os
import uuid

import pytest

from claude.clients.merchant.atomic_create import atomic_create_merchant
from claude.clients.merchant.execution_ledger import ExecutionConflictError
from claude.clients.merchant.merchant_repository import MerchantEntityRepository
from claude.clients.merchant.repository import MerchantRepository


pytestmark = pytest.mark.skipif(
    os.environ.get("MERCHANT_TEST_DB_NAME")
    != "coding_agent_merchant_test"
    or not os.environ.get("MERCHANT_TEST_PASSWORD"),
    reason="Merchant test database is not configured",
)


def setup():
    repository = MerchantRepository(role="test")
    entity = MerchantEntityRepository(repository)
    merchant_id = str(uuid.uuid4())
    key = f"pytest:atomic:{uuid.uuid4()}"
    code = f"T{uuid.uuid4().hex[:18].upper()}"
    return repository, entity, merchant_id, key, code


def counts(repository, merchant_id, key):
    with repository.connection(read_only=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM merchant_ops.merchants
                WHERE id = %s
                """,
                (uuid.UUID(merchant_id),),
            )
            merchants = cur.fetchone()["n"]

            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM merchant_ops.project_events
                WHERE merchant_id = %s
                  AND entity_type = 'MERCHANT'
                """,
                (uuid.UUID(merchant_id),),
            )
            events = cur.fetchone()["n"]

            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM merchant_ops.merchant_execution_ledger
                WHERE operation_key = %s
                """,
                (key,),
            )
            ledger = cur.fetchone()["n"]

    return merchants, events, ledger


def claim_snapshot(repository, key):
    with repository.connection(read_only=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT claim_status, claim_generation,
                       execution_attempt_id
                FROM merchant_ops.merchant_execution_claims
                WHERE operation_key = %s
                """,
                (key,),
            )
            return cur.fetchone()


def cleanup(repository, merchant_id, key):
    with repository.connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_claims
                    WHERE operation_key = %s
                    """,
                    (key,),
                )
                cur.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_ledger
                    WHERE operation_key = %s
                    """,
                    (key,),
                )
                cur.execute(
                    """
                    DELETE FROM merchant_ops.project_events
                    WHERE merchant_id = %s
                      AND entity_type = 'MERCHANT'
                    """,
                    (uuid.UUID(merchant_id),),
                )
                cur.execute(
                    """
                    DELETE FROM merchant_ops.merchants
                    WHERE id = %s
                    """,
                    (uuid.UUID(merchant_id),),
                )


def test_atomic_create_commit_and_replay():
    repository, entity, merchant_id, key, code = setup()

    try:
        first, replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=key,
            merchant_id=merchant_id,
            code=code,
            name="Atomic Test Merchant",
        )

        assert replayed is False
        assert first["merchant_id"] == merchant_id
        assert counts(repository, merchant_id, key) == (1, 1, 1)

        second, replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=key,
            merchant_id=merchant_id,
            code=code,
            name="Atomic Test Merchant",
        )

        assert replayed is True
        assert second == first
        assert counts(repository, merchant_id, key) == (1, 1, 1)

        with pytest.raises(ExecutionConflictError):
            atomic_create_merchant(
                repository,
                entity,
                operation_key=key,
                merchant_id=merchant_id,
                code=code,
                name="Different Merchant Name",
            )

        assert counts(repository, merchant_id, key) == (1, 1, 1)

    finally:
        cleanup(repository, merchant_id, key)


def test_atomic_create_rollback_after_domain_write(monkeypatch):
    from claude.clients.merchant import atomic_create as module

    repository, entity, merchant_id, key, code = setup()
    original_execute_once = module.execute_once

    def inject_failure(connection, *, operation_key, payload_hash, execute):
        def wrapped_execute():
            execute()
            raise RuntimeError("Injected post-write failure")

        return original_execute_once(
            connection,
            operation_key=operation_key,
            payload_hash=payload_hash,
            execute=wrapped_execute,
        )

    monkeypatch.setattr(
        module,
        "execute_once",
        inject_failure,
    )

    try:
        with pytest.raises(
            RuntimeError,
            match="Injected post-write failure",
        ):
            atomic_create_merchant(
                repository,
                entity,
                operation_key=key,
                merchant_id=merchant_id,
                code=code,
                name="Rollback Test Merchant",
            )

        assert counts(repository, merchant_id, key) == (0, 0, 0)
        assert claim_snapshot(repository, key) is None
    finally:
        cleanup(repository, merchant_id, key)


def test_atomic_create_persists_completed_execution_claim():
    repository, entity, merchant_id, key, code = setup()

    try:
        result, replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=key,
            merchant_id=merchant_id,
            code=code,
            name="Claim Integration Test Merchant",
        )

        assert replayed is False
        assert result["merchant_id"] == merchant_id

        with repository.connection(read_only=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT claim_status, claim_generation,
                           execution_attempt_id
                    FROM merchant_ops.merchant_execution_claims
                    WHERE operation_key = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()

        assert row is not None
        assert row["claim_status"] == "COMPLETED"
        assert row["claim_generation"] == 1
        assert row["execution_attempt_id"] is not None

        original_claim = claim_snapshot(repository, key)

        replay_result, replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=key,
            merchant_id=merchant_id,
            code=code,
            name="Claim Integration Test Merchant",
        )

        assert replayed is True
        assert replay_result == result
        assert claim_snapshot(repository, key) == original_claim
        assert counts(repository, merchant_id, key) == (1, 1, 1)

    finally:
        with repository.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM merchant_ops.merchant_execution_claims
                        WHERE operation_key = %s
                        """,
                        (key,),
                    )

        cleanup(repository, merchant_id, key)