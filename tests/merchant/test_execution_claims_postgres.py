"""PostgreSQL TEST regressions for transaction-scoped claims."""

import os
import uuid
from dataclasses import replace

import psycopg
import pytest

from claude.clients.merchant.execution_claims import (
    ExecutionClaimConflictError,
    acquire_execution_claim,
    complete_execution_claim,
)


HASH = "a" * 64


@pytest.fixture
def connection():
    if (
        os.environ.get("MERCHANT_TEST_DB_NAME")
        != "coding_agent_merchant_test"
        or os.environ.get("MERCHANT_TEST_USER") != "merchant_test"
        or not os.environ.get("MERCHANT_TEST_PASSWORD")
        or os.environ.get("MERCHANT_DB_HOST") != "127.0.0.1"
        or os.environ.get("MERCHANT_DB_PORT") != "5434"
    ):
        pytest.skip("Local Merchant TEST connection not configured")

    conn = psycopg.connect(
        host="127.0.0.1",
        port=5434,
        dbname="coding_agent_merchant_test",
        user="merchant_test",
        password=os.environ["MERCHANT_TEST_PASSWORD"],
        connect_timeout=5,
    )

    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def new_key():
    return f"pytest:claims:{uuid.uuid4()}"


def test_claim_acquisition_returns_exact_identity(connection):
    attempt = uuid.uuid4()
    key = new_key()

    token = acquire_execution_claim(
        connection,
        operation_key=key,
        payload_hash=HASH,
        execution_attempt_id=attempt,
    )

    assert token.operation_key == key
    assert token.payload_hash == HASH
    assert token.execution_attempt_id == attempt
    assert token.claim_generation == 1


def test_same_active_attempt_is_idempotent(connection):
    attempt = uuid.uuid4()
    key = new_key()

    first = acquire_execution_claim(
        connection,
        operation_key=key,
        payload_hash=HASH,
        execution_attempt_id=attempt,
    )

    second = acquire_execution_claim(
        connection,
        operation_key=key,
        payload_hash=HASH,
        execution_attempt_id=attempt,
    )

    assert second == first


def test_different_attempt_and_payload_are_rejected(connection):
    attempt = uuid.uuid4()
    key = new_key()

    acquire_execution_claim(
        connection,
        operation_key=key,
        payload_hash=HASH,
        execution_attempt_id=attempt,
    )

    with pytest.raises(ExecutionClaimConflictError):
        acquire_execution_claim(
            connection,
            operation_key=key,
            payload_hash=HASH,
            execution_attempt_id=uuid.uuid4(),
        )

    with pytest.raises(ExecutionClaimConflictError):
        acquire_execution_claim(
            connection,
            operation_key=key,
            payload_hash="b" * 64,
            execution_attempt_id=attempt,
        )


def test_stale_generation_and_completed_claim_rejected(connection):
    key = new_key()

    token = acquire_execution_claim(
        connection,
        operation_key=key,
        payload_hash=HASH,
        execution_attempt_id=uuid.uuid4(),
    )

    stale = replace(token, claim_generation=token.claim_generation + 1)

    with pytest.raises(ExecutionClaimConflictError):
        complete_execution_claim(connection, token=stale)

    complete_execution_claim(connection, token=token)

    with pytest.raises(ExecutionClaimConflictError):
        complete_execution_claim(connection, token=token)

    with pytest.raises(ExecutionClaimConflictError):
        acquire_execution_claim(
            connection,
            operation_key=key,
            payload_hash=HASH,
            execution_attempt_id=token.execution_attempt_id,
        )


def test_concurrent_claim_cannot_bypass_row_lock(connection):
    key = new_key()

    acquire_execution_claim(
        connection,
        operation_key=key,
        payload_hash=HASH,
        execution_attempt_id=uuid.uuid4(),
    )

    # Connection 1 holds its uncommitted claim and row lock.
    # Connection 2 must not acquire the same operation.
    second = psycopg.connect(
        host="127.0.0.1",
        port=5434,
        dbname="coding_agent_merchant_test",
        user="merchant_test",
        password=os.environ["MERCHANT_TEST_PASSWORD"],
        connect_timeout=5,
        options="-c lock_timeout=300ms",
    )

    try:
        with pytest.raises(psycopg.errors.LockNotAvailable):
            acquire_execution_claim(
                second,
                operation_key=key,
                payload_hash=HASH,
                execution_attempt_id=uuid.uuid4(),
            )
    finally:
        second.rollback()
        second.close()