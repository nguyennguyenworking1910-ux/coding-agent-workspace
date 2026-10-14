from contextlib import contextmanager

import pytest

from claude.clients.merchant.execution_ledger import (
    ExecutionConflictError,
    execute_once,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


class FakeConnection:
    def __init__(self):
        self.records = {}
        self.pending = {}
        self.executions = 0

    @contextmanager
    def cursor(self):
        yield FakeCursor(self)

    def commit(self):
        self.records.update(self.pending)
        self.pending.clear()

    def rollback(self):
        self.pending.clear()


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def execute(self, sql, params):
        statement = " ".join(sql.upper().split()).replace("MERCHANT_OPS.MERCHANT_EXECUTION_LEDGER", "MERCHANT_EXECUTION_LEDGER")

        if statement.startswith("INSERT INTO MERCHANT_EXECUTION_LEDGER"):
            key, payload_hash = params

            if (
                key in self.connection.records
                or key in self.connection.pending
            ):
                self.rows = [None]
            else:
                self.connection.pending[key] = {
                    "hash": payload_hash,
                    "result": None,
                }
                self.rows = [(key,)]

        elif statement.startswith("SELECT PAYLOAD_HASH"):
            key = params[0]

            record = (
                self.connection.pending.get(key)
                or self.connection.records.get(key)
            )

            self.rows = [
                (
                    record["hash"],
                    record["result"],
                )
            ] if record else [None]

        elif statement.startswith("UPDATE MERCHANT_EXECUTION_LEDGER"):
            import json

            result_json, key = params

            record = (
                self.connection.pending.get(key)
                or self.connection.records.get(key)
            )

            record["result"] = json.loads(result_json)

            self.rows = []

        else:
            raise AssertionError(
                f"Unexpected SQL: {statement}"
            )

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


def test_first_execution_and_replay():
    connection = FakeConnection()
    calls = []

    def execute():
        calls.append("executed")
        return {"success": True, "merchant_id": "m1"}

    first, replayed = execute_once(
        connection,
        operation_key="task-1:operation-1",
        payload_hash=HASH_A,
        execute=execute,
    )

    assert replayed is False
    assert first["merchant_id"] == "m1"

    connection.commit()

    second, replayed = execute_once(
        connection,
        operation_key="task-1:operation-1",
        payload_hash=HASH_A,
        execute=execute,
    )

    assert replayed is True
    assert second == first
    assert calls == ["executed"]


def test_different_payload_rejected():
    connection = FakeConnection()

    execute_once(
        connection,
        operation_key="operation-1",
        payload_hash=HASH_A,
        execute=lambda: {"success": True},
    )
    connection.commit()

    with pytest.raises(ExecutionConflictError):
        execute_once(
            connection,
            operation_key="operation-1",
            payload_hash=HASH_B,
            execute=lambda: {"success": True},
        )


def test_callback_failure_does_not_store_success():
    connection = FakeConnection()

    def failing_execute():
        raise RuntimeError("Database write failed")

    with pytest.raises(
        RuntimeError, match="Database write failed"
    ):
        execute_once(
            connection,
            operation_key="operation-failed",
            payload_hash=HASH_A,
            execute=failing_execute,
        )

    connection.rollback()

    assert "operation-failed" not in connection.records
    assert "operation-failed" not in connection.pending


def test_rollback_allows_fresh_execution():
    connection = FakeConnection()
    calls = []

    def execute():
        calls.append("executed")
        return {"success": True}

    execute_once(
        connection,
        operation_key="operation-rollback",
        payload_hash=HASH_A,
        execute=execute,
    )

    connection.rollback()

    _, replayed = execute_once(
        connection,
        operation_key="operation-rollback",
        payload_hash=HASH_A,
        execute=execute,
    )

    assert replayed is False
    assert len(calls) == 2


@pytest.mark.parametrize("operation_key,payload_hash", [
    ("", HASH_A),
    ("test", "invalid"),
    ("test", "z" * 64),
])
def test_invalid_identity_rejected(operation_key, payload_hash):
    with pytest.raises(ValueError):
        execute_once(
            FakeConnection(),
            operation_key=operation_key,
            payload_hash=payload_hash,
            execute=lambda: {},
        )
