import os
import uuid

import pytest

from claude.agents.tools.merchant.write_adapters import (
    execute_protected_merchant_create,
    WriteAdapterError,
)
from claude.clients.merchant.execution_ledger import (
    ExecutionConflictError,
)
from claude.clients.merchant.repository import MerchantRepository


@pytest.fixture
def test_repository():
    if (
        os.environ.get("MERCHANT_TEST_DB_NAME")
        != "coding_agent_merchant_test"
        or not os.environ.get("MERCHANT_TEST_PASSWORD")
    ):
        pytest.skip("Merchant test database unavailable")

    return MerchantRepository(role="test")


def test_protected_create_replays_generated_id(test_repository):
    key = f"pytest:protected:{uuid.uuid4()}"
    code = f"T{uuid.uuid4().hex[:18].upper()}"
    merchant_id = None

    try:
        payload = {
            "code": code,
            "name": "Protected Test Merchant",
        }

        first = execute_protected_merchant_create(
            database="test",
            operation_key=key,
            payload=payload,
            repository=test_repository,
        )

        merchant_id = first["result"]["merchant_id"]

        second = execute_protected_merchant_create(
            database="test",
            operation_key=key,
            payload=payload,
            repository=test_repository,
        )

        assert first["replayed"] is False
        assert second["replayed"] is True
        assert second["result"] == first["result"]

        with test_repository.connection(read_only=True) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM merchant_ops.merchants
                WHERE id = %s
                """,
                (uuid.UUID(merchant_id),),
            ).fetchone()

        assert row["n"] == 1

        with pytest.raises(ExecutionConflictError):
            execute_protected_merchant_create(
                database="test",
                operation_key=key,
                payload={
                    "code": code,
                    "name": "Different Name",
                },
                repository=test_repository,
            )
    finally:
        with test_repository.connection() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_ledger
                    WHERE operation_key = %s
                    """,
                    (key,),
                )

                if merchant_id is not None:
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


def test_protected_create_rejects_unknown_fields():
    with pytest.raises(WriteAdapterError):
        execute_protected_merchant_create(
            database="test",
            operation_key="test-key",
            payload={
                "code": "TEST",
                "name": "Test",
                "operation_key": "agent-injected",
            },
        )
