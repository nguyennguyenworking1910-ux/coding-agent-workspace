import json

import pytest

from claude.agents.tools.merchant.agent_cli import (
    MerchantAgentCliError,
    prepare_agent_cli_argv,
    invoke_agent_cli,
)
from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)


def test_agent_cli_rejects_direct_write_without_mode():
    with pytest.raises(MerchantAgentCliError):
        prepare_agent_cli_argv([
            "merchant", "create",
            "--code", "CP3D_TEST",
            "--name", "Direct Merchant",
        ])


def test_agent_cli_rejects_direct_write_before_handler(capsys):
    factory_calls = []

    def forbidden_factory(database):
        factory_calls.append(database)
        raise AssertionError("Write factory must not be called")

    with pytest.raises(MerchantAgentCliError):
        invoke_agent_cli(
            [
                "merchant", "create",
                "--code", "SECURITY_TEST",
                "--name", "Unauthorized Merchant",
            ],
            write_command_factory=forbidden_factory,
        )

    captured = capsys.readouterr()

    assert factory_calls == []
    assert captured.out.strip() == ""


@pytest.mark.parametrize(
    "legacy_mode",
    ["--propose", "--apply"],
)
def test_agent_cli_rejects_legacy_modes(legacy_mode):
    with pytest.raises(MerchantAgentCliError):
        prepare_agent_cli_argv([
            "merchant", "create",
            legacy_mode,
            "--code", "CP3D_TEST",
            "--name", "Direct Merchant",
        ])


def test_agent_cli_rejects_database_override():
    with pytest.raises(MerchantAgentCliError):
        prepare_agent_cli_argv([
            "--database", "test",
            "merchant", "create",
            "--code", "CP3D_TEST",
            "--name", "Direct Merchant",
        ])
