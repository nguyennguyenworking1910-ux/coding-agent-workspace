from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from claude.clients.merchant import atomic_create as module


class FakeConnection:
    def __init__(self, events):
        self.events = events

    @contextmanager
    def transaction(self):
        self.events.append("begin")
        try:
            yield self
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")


class FakeRepository:
    def __init__(self):
        self.events = []
        self._connection = FakeConnection(self.events)

    @contextmanager
    def connection(self):
        yield self._connection


class FakeEntity:
    def __init__(self, events):
        self.events = events

    def create_merchant(self, **kwargs):
        self.events.append("create")
        return SimpleNamespace(
            to_dict=lambda: {
                "merchant_id": kwargs["merchant_id"]
            }
        )


def test_create_and_ledger_share_connection(monkeypatch):
    repository = FakeRepository()
    entity = FakeEntity(repository.events)

    def fake_execute_once(
        connection, *, operation_key, payload_hash, execute
    ):
        assert connection is repository._connection
        assert operation_key == "run-1:task-1:write-1"
        assert len(payload_hash) == 64
        repository.events.append("ledger_claim")
        result = execute()
        repository.events.append("ledger_result")
        return result, False

    monkeypatch.setattr(
        module, "execute_once", fake_execute_once
    )

    result, replayed = module.atomic_create_merchant(
        repository,
        entity,
        operation_key="run-1:task-1:write-1",
        merchant_id="merchant-1",
        code="TEST",
        name="Test Merchant",
    )

    assert result == {"merchant_id": "merchant-1", "success": True}
    assert replayed is False

    assert repository.events == [
        "begin",
        "ledger_claim",
        "create",
        "ledger_result",
        "commit",
    ]


def test_ledger_failure_rolls_back(monkeypatch):
    repository = FakeRepository()
    entity = FakeEntity(repository.events)

    def fail(*args, **kwargs):
        raise RuntimeError("Ledger failure")

    monkeypatch.setattr(
        module, "execute_once", fail
    )

    with pytest.raises(RuntimeError):
        module.atomic_create_merchant(
            repository,
            entity,
            operation_key="run-1:task-1:write-1",
            merchant_id="merchant-1",
            code="TEST",
            name="Test Merchant",
        )

    assert repository.events == ["begin", "rollback"]


def test_generated_merchant_id_is_created_inside_execute(
    monkeypatch,
):
    repository = FakeRepository()
    entity = FakeEntity(repository.events)

    generated_ids = []

    def fake_uuid4():
        value = f"generated-{len(generated_ids) + 1}"
        generated_ids.append(value)
        return value

    monkeypatch.setattr(
        module.uuid,
        "uuid4",
        fake_uuid4,
    )

    def fake_execute_once(
        connection, *, operation_key, payload_hash, execute
    ):
        assert generated_ids == []
        result = execute()
        return result, False

    monkeypatch.setattr(
        module,
        "execute_once",
        fake_execute_once,
    )

    result, replayed = module.atomic_create_merchant(
        repository,
        entity,
        operation_key="run-1:task-1:write-2",
        code="TEST_AUTO",
        name="Auto ID Merchant",
    )

    assert replayed is False
    assert result["merchant_id"] == "generated-1"
    assert generated_ids == ["generated-1"]
