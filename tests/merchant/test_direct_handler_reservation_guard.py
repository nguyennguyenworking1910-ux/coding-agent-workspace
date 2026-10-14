import pytest

from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)


def test_unreserved_merchant_create_never_calls_handler():
    calls = []

    commands = MerchantWriteCommands({
        "merchant create": lambda payload: calls.append(payload),
    })

    with pytest.raises(
        PermissionError,
        match="durable reservation",
    ):
        commands.execute(
            "merchant create",
            "test",
            {"code": "BLOCK001", "name": "Blocked"},
        )

    assert calls == []
