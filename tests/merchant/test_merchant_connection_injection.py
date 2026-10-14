from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from claude.clients.merchant import merchant_repository as module


class FakeConnection:
    def __init__(self):
        self.transactions = 0
        self.cursors = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield

    @contextmanager
    def cursor(self, **kwargs):
        self.cursors += 1
        yield object()


def test_external_connection_is_reused(monkeypatch):
    base_repository = Mock()
    base_repository.connection.side_effect = AssertionError(
        "Must not open a second connection"
    )

    repository = module.MerchantEntityRepository(
        base_repository
    )

    plan = SimpleNamespace(
        merchant_id="merchant-1",
        code="TEST",
        name="Test Merchant",
        region_code=None,
        account_status="PLANNED",
        version=1,
        event_type="MERCHANT_CREATED",
    )

    monkeypatch.setattr(
        module,
        "propose_merchant_creation",
        lambda **kwargs: plan,
    )

    inserts = []

    monkeypatch.setattr(
        repository,
        "_insert_merchant",
        lambda cursor, plan: inserts.append("merchant"),
    )

    monkeypatch.setattr(
        repository,
        "_insert_creation_event",
        lambda cursor, plan, event_id: inserts.append("event"),
    )

    connection = FakeConnection()

    result = repository.create_merchant(
        merchant_id="merchant-1",
        code="TEST",
        name="Test Merchant",
        connection=connection,
    )

    assert result.merchant_id == "merchant-1"
    assert connection.transactions == 1
    assert connection.cursors == 1
    assert inserts == ["merchant", "event"]

    base_repository.connection.assert_not_called()


def test_external_connection_failure_propagates(monkeypatch):
    base_repository = Mock()

    repository = module.MerchantEntityRepository(
        base_repository
    )

    plan = SimpleNamespace(
        merchant_id="merchant-1",
        code="TEST",
        name="Test Merchant",
    )

    monkeypatch.setattr(
        module,
        "propose_merchant_creation",
        lambda **kwargs: plan,
    )

    def failing_insert(cursor, plan):
        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        repository,
        "_insert_merchant",
        failing_insert,
    )

    connection = FakeConnection()

    with pytest.raises(
        RuntimeError,
        match="Simulated insert failure",
    ):
        repository.create_merchant(
            merchant_id="merchant-1",
            code="TEST",
            name="Test Merchant",
            connection=connection,
        )

    assert connection.transactions == 1
    base_repository.connection.assert_not_called()
