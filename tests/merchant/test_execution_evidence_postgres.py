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


def test_committed_evidence_requires_matching_claim_attempt(repository):
    """Committed evidence must bind to the exact PostgreSQL claim."""
    entity = MerchantEntityRepository(repository)

    merchant_id = str(uuid.uuid4())
    operation_key = f"pytest:claim-evidence:{uuid.uuid4()}"
    code = f"T{uuid.uuid4().hex[:18].upper()}"
    trusted_attempt = uuid.uuid4()

    payload = {
        "command": "merchant create",
        "merchant_id": merchant_id,
        "code": code,
        "name": "Claim Evidence Merchant",
        "region_code": None,
        "created_by": None,
    }
    expected_hash = atomic_module._canonical_hash(payload)

    try:
        result, replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=operation_key,
            execution_attempt_id=trusted_attempt,
            merchant_id=merchant_id,
            code=code,
            name=payload["name"],
        )

        assert result["success"] is True
        assert replayed is False

        valid = verify_committed_merchant_create(
            repository,
            operation_key=operation_key,
            payload_hash=expected_hash,
            execution_attempt_id=trusted_attempt,
        )

        assert valid is not None
        assert valid["verified"] is True

        invalid = verify_committed_merchant_create(
            repository,
            operation_key=operation_key,
            payload_hash=expected_hash,
            execution_attempt_id=uuid.uuid4(),
        )

        assert invalid is None

    finally:
        with repository.connection() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_claims
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_ledger
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )
                mid = uuid.UUID(merchant_id)
                conn.execute(
                    """
                    DELETE FROM merchant_ops.project_events
                    WHERE merchant_id = %s
                      AND entity_type = 'MERCHANT'
                    """,
                    (mid,),
                )
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchants
                    WHERE id = %s
                    """,
                    (mid,),
                )

@pytest.mark.parametrize(
    "tamper",
    [
        "missing",
        "active",
        "revoked",
        "wrong_hash",
        "wrong_attempt",
    ],
)
def test_claim_integrity_fail_closed(repository, tamper):
    """Invalid claim evidence must never verify committed writes."""
    entity = MerchantEntityRepository(repository)

    merchant_id = str(uuid.uuid4())
    operation_key = f"pytest:claim-integrity:{uuid.uuid4()}"
    attempt_id = uuid.uuid4()
    code = f"T{uuid.uuid4().hex[:18].upper()}"
    name = "Claim Integrity Test Merchant"

    expected_hash = atomic_module._canonical_hash({
        "command": "merchant create",
        "merchant_id": merchant_id,
        "code": code,
        "name": name,
        "region_code": None,
        "created_by": None,
    })

    try:
        result, replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=operation_key,
            execution_attempt_id=attempt_id,
            merchant_id=merchant_id,
            code=code,
            name=name,
        )

        assert result["success"] is True
        assert replayed is False

        baseline = verify_committed_merchant_create(
            repository,
            operation_key=operation_key,
            payload_hash=expected_hash,
            execution_attempt_id=attempt_id,
        )
        assert baseline is not None
        assert baseline["verified"] is True

        with repository.connection() as conn:
            with conn.transaction():
                if tamper == "missing":
                    conn.execute(
                        """
                        DELETE FROM merchant_ops.merchant_execution_claims
                        WHERE operation_key = %s
                        """,
                        (operation_key,),
                    )
                elif tamper in ("active", "revoked"):
                    conn.execute(
                        """
                        UPDATE merchant_ops.merchant_execution_claims
                        SET claim_status = %s
                        WHERE operation_key = %s
                        """,
                        (tamper.upper(), operation_key),
                    )
                elif tamper == "wrong_hash":
                    different_hash = (
                        "b" * 64 if expected_hash != "b" * 64
                        else "a" * 64
                    )
                    conn.execute(
                        """
                        UPDATE merchant_ops.merchant_execution_claims
                        SET payload_hash = %s
                        WHERE operation_key = %s
                        """,
                        (different_hash, operation_key),
                    )
                elif tamper == "wrong_attempt":
                    conn.execute(
                        """
                        UPDATE merchant_ops.merchant_execution_claims
                        SET execution_attempt_id = %s
                        WHERE operation_key = %s
                        """,
                        (uuid.uuid4(), operation_key),
                    )

        evidence = verify_committed_merchant_create(
            repository,
            operation_key=operation_key,
            payload_hash=expected_hash,
            execution_attempt_id=attempt_id,
        )

        assert evidence is None, (
            f"Invalid claim was accepted: {tamper}"
        )

    finally:
        with repository.connection() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_claims
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_ledger
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )
                mid = uuid.UUID(merchant_id)
                conn.execute(
                    """
                    DELETE FROM merchant_ops.project_events
                    WHERE merchant_id = %s
                      AND entity_type = 'MERCHANT'
                    """,
                    (mid,),
                )
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchants
                    WHERE id = %s
                    """,
                    (mid,),
                )


def test_evidence_generation_contract_rejects_mismatch(
    repository, monkeypatch
):
    """Verifier must reject a mismatched expected generation."""
    import inspect

    from claude.hooks.merchant_execution_evidence import (
        verify_committed_merchant_create,
    )

    signature = inspect.signature(
        verify_committed_merchant_create
    )

    assert "claim_generation" in signature.parameters, (
        "Verifier must accept an expected claim_generation"
    )



@pytest.mark.parametrize(
    "expected_generation,accepted",
    [
        (1, True),
        (2, False),
        (0, False),
        (-1, False),
        (True, False),
        ("1", False),
        (1.0, False),
    ],
)
def test_exact_claim_generation_postgres(
    repository, expected_generation, accepted
):
    """Read-only evidence requires the exact expected generation."""
    entity = MerchantEntityRepository(repository)
    merchant_id = str(uuid.uuid4())
    operation_key = f"pytest:claim-generation:{uuid.uuid4()}"
    attempt_id = uuid.uuid4()
    code = f"T{uuid.uuid4().hex[:18].upper()}"
    name = "Generation Evidence Merchant"

    payload_hash = atomic_module._canonical_hash({
        "command": "merchant create",
        "merchant_id": merchant_id,
        "code": code,
        "name": name,
        "region_code": None,
        "created_by": None,
    })

    try:
        result, replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=operation_key,
            execution_attempt_id=attempt_id,
            merchant_id=merchant_id,
            code=code,
            name=name,
        )

        assert result["success"] is True
        assert replayed is False

        evidence = verify_committed_merchant_create(
            repository,
            operation_key=operation_key,
            payload_hash=payload_hash,
            execution_attempt_id=attempt_id,
            claim_generation=expected_generation,
        )

        if accepted:
            assert evidence is not None
            assert evidence["merchant_id"] == merchant_id
        else:
            assert evidence is None

    finally:
        with repository.connection() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_claims
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_ledger
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )

                mid = uuid.UUID(merchant_id)

                conn.execute(
                    """
                    DELETE FROM merchant_ops.project_events
                    WHERE merchant_id = %s
                      AND entity_type = 'MERCHANT'
                    """,
                    (mid,),
                )
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchants
                    WHERE id = %s
                    """,
                    (mid,),
                )



def test_committed_evidence_returns_claim_generation(repository):
    """Exact committed claim evidence exposes its DB generation."""
    entity = MerchantEntityRepository(repository)

    merchant_id = str(uuid.uuid4())
    operation_key = f"pytest:generation-bootstrap:{uuid.uuid4()}"
    attempt_id = uuid.uuid4()
    code = f"T{uuid.uuid4().hex[:18].upper()}"
    name = "Generation Bootstrap Merchant"

    payload_hash = atomic_module._canonical_hash({
        "command": "merchant create",
        "merchant_id": merchant_id,
        "code": code,
        "name": name,
        "region_code": None,
        "created_by": None,
    })

    try:
        result, replayed = atomic_create_merchant(
            repository,
            entity,
            operation_key=operation_key,
            execution_attempt_id=attempt_id,
            merchant_id=merchant_id,
            code=code,
            name=name,
        )

        assert result["success"] is True
        assert replayed is False

        evidence = verify_committed_merchant_create(
            repository,
            operation_key=operation_key,
            payload_hash=payload_hash,
            execution_attempt_id=attempt_id,
            claim_generation=1,
        )

        assert evidence is not None
        assert evidence["verified"] is True
        assert evidence["merchant_id"] == merchant_id
        assert evidence["claim_generation"] == 1

    finally:
        with repository.connection() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_claims
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )

                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchant_execution_ledger
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )

                mid = uuid.UUID(merchant_id)

                conn.execute(
                    """
                    DELETE FROM merchant_ops.project_events
                    WHERE merchant_id = %s
                      AND entity_type = 'MERCHANT'
                    """,
                    (mid,),
                )

                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchants
                    WHERE id = %s
                    """,
                    (mid,),
                )
