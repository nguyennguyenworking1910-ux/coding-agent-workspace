import os
import uuid

import pytest

from claude.clients.merchant import atomic_create as atomic_module
from claude.clients.merchant.atomic_create import atomic_create_merchant
from claude.clients.merchant.merchant_repository import (
    MerchantEntityRepository,
)
from claude.clients.merchant.repository import MerchantRepository
from claude.hooks.merchant_execution_evidence import (
    verify_committed_merchant_create,
)


@pytest.fixture
def repository():
    if (
        os.environ.get("MERCHANT_TEST_DB_NAME")
        != "coding_agent_merchant_test"
        or not os.environ.get("MERCHANT_TEST_PASSWORD")
    ):
        pytest.skip("Merchant test database not configured")

    return MerchantRepository(role="test")


def test_verified_committed_create_and_rejected_evidence(
    repository, monkeypatch
):
    entity = MerchantEntityRepository(repository)

    merchant_id = str(uuid.uuid4())
    operation_key = f"pytest:evidence:{uuid.uuid4()}"
    code = f"T{uuid.uuid4().hex[:18].upper()}"

    captured = {}
    original_execute_once = atomic_module.execute_once

    def capture_hash(
        connection, *, operation_key, payload_hash, execute
    ):
        captured["payload_hash"] = payload_hash
        return original_execute_once(
            connection,
            operation_key=operation_key,
            payload_hash=payload_hash,
            execute=execute,
        )

    monkeypatch.setattr(
        atomic_module,
        "execute_once",
        capture_hash,
    )

    try:
        result, replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=operation_key,
            merchant_id=merchant_id,
            code=code,
            name="Evidence Integration Merchant",
        )

        assert replayed is False
        assert result["merchant_id"] == merchant_id

        expected_hash = captured["payload_hash"]

        evidence = verify_committed_merchant_create(
            repository,
            operation_key=operation_key,
            payload_hash=expected_hash,
        )


        assert evidence is not None
        assert evidence["verified"] is True
        assert evidence["merchant_id"] == merchant_id
        assert evidence["payload_hash"] == expected_hash
        assert evidence["source"] == "postgresql"

        assert verify_committed_merchant_create(
            repository,
            operation_key=operation_key,
            payload_hash="b" * 64
            if expected_hash != "b" * 64
            else "a" * 64,
        ) is None

        assert verify_committed_merchant_create(
            repository,
            operation_key=operation_key + ":missing",
            payload_hash=expected_hash,
        ) is None

        second, second_replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=operation_key,
            merchant_id=merchant_id,
            code=code,
            name="Evidence Integration Merchant",
        )

        assert second_replayed is True
        assert second == result

    finally:
        with repository.connection() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    DELETE FROM
                        merchant_ops.merchant_execution_ledger
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )

                merchant_uuid = uuid.UUID(merchant_id)

                conn.execute(
                    """
                    DELETE FROM merchant_ops.project_events
                    WHERE merchant_id = %s
                      AND entity_type = 'MERCHANT'
                    """,
                    (merchant_uuid,),
                )

                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchants
                    WHERE id = %s
                    """,
                    (merchant_uuid,),
                )
