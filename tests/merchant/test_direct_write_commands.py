import uuid

import pytest

from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)
from claude.agents.tools.merchant.cli_contract import (
    CommandNotAllowedError,
)


def test_unreserved_create_cannot_call_handler():
    received = []

    commands = MerchantWriteCommands({
        "merchant create": lambda payload: received.append(payload)
    })

    with pytest.raises(PermissionError, match="durable reservation"):
        commands.execute(
            "merchant create",
            "test",
            {"code": "TEST001", "name": "Test Merchant"},
        )

    assert received == []


def test_repeated_unreserved_creates_are_denied():
    received = []

    commands = MerchantWriteCommands({
        "merchant create": lambda payload: received.append(payload)
    })

    payload = {"code": "SAME", "name": "Same Merchant"}

    for _ in range(2):
        with pytest.raises(PermissionError, match="durable reservation"):
            commands.execute("merchant create", "test", payload)

    assert received == []
    assert "merchant_id" not in payload


def test_preflight_runs_before_write():
    events = []

    def preflight(payload):
        events.append("preflight")

    def handler(payload):
        events.append("write")
        return {"updated": True}

    commands = MerchantWriteCommands({
        "merchant activate": handler
    })

    commands.register_preflight_validator(
        "merchant activate",
        preflight,
    )

    result = commands.execute(
        "merchant activate",
        "test",
        {"merchant_id": str(uuid.uuid4())},
    )

    assert events == ["preflight", "write"]
    assert result["success"] is True


def test_preflight_failure_prevents_write():
    calls = []

    def invalid(payload):
        raise ValueError("Business rule violation")

    commands = MerchantWriteCommands({
        "merchant activate": lambda payload: calls.append(payload)
    })

    commands.register_preflight_validator(
        "merchant activate", invalid
    )

    with pytest.raises(ValueError, match="Business rule violation"):
        commands.execute(
            "merchant activate",
            "test",
            {"merchant_id": str(uuid.uuid4())},
        )

    assert calls == []


def test_unregistered_command_rejected():
    commands = MerchantWriteCommands({})

    with pytest.raises(CommandNotAllowedError):
        commands.execute(
            "merchant unknown",
            "test",
            {},
        )


def test_invalid_database_rejected_before_write():
    calls = []

    commands = MerchantWriteCommands({
        "merchant activate": lambda payload: calls.append(payload)
    })

    with pytest.raises(ValueError):
        commands.execute(
            "merchant activate",
            "invalid_database",
            {"merchant_id": str(uuid.uuid4())},
        )

    assert calls == []
