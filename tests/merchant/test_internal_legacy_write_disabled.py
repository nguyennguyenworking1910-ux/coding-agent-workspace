"""Legacy Merchant write APIs must fail closed."""

import pytest

from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"

PAYLOAD = {
    "project_id": PROJECT_ID,
    "status": "BLOCKED",
    "expected_version": 2,
}


@pytest.mark.parametrize("database", ["test", "runtime"])
def test_internal_propose_is_disabled_before_preflight(database):
    handler_calls = []
    preflight_calls = []

    commands = MerchantWriteCommands({
        "project update": lambda payload: handler_calls.append(payload)
    })
    commands.register_preflight_validator(
        "project update",
        lambda payload: preflight_calls.append(payload),
    )

    with pytest.raises(PermissionError, match="EXECUTE"):
        commands.propose(
            "project update",
            database,
            PAYLOAD,
        )

    assert handler_calls == []
    assert preflight_calls == []


def test_internal_apply_is_disabled_before_preflight():
    handler_calls = []
    preflight_calls = []

    commands = MerchantWriteCommands({
        "project update": lambda payload: handler_calls.append(payload)
    })
    commands.register_preflight_validator(
        "project update",
        lambda payload: preflight_calls.append(payload),
    )

    with pytest.raises(PermissionError, match="EXECUTE"):
        commands.apply(
            "project update",
            "test",
            PAYLOAD,
            proposal_hash="a" * 64,
        )

    assert handler_calls == []
    assert preflight_calls == []
