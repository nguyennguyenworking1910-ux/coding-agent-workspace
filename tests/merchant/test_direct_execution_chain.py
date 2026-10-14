import json

import pytest

from claude.agents.tools.merchant.agent_cli import (
    invoke_agent_cli,
)


ARGS = (
    "merchant",
    "create",
    "--code",
    "CHAIN_TEST",
    "--name",
    "Chain Test",
)


class FakeWrites:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def execute(self, command, database, payload):
        self.calls.append((command, database, payload))

        if self.fail:
            raise ValueError("Simulated database failure")

        return {
            "contract_version": 1,
            "success": True,
            "mode": "EXECUTE",
            "command": command,
            "database": database,
            "result": {
                "merchant_id": "test-merchant-id",
            },
        }

    def propose(self, *args, **kwargs):
        raise AssertionError("Legacy propose was called")

    def apply(self, *args, **kwargs):
        raise AssertionError("Legacy apply was called")


def test_full_direct_execution_chain(capsys):
    factory_calls = []

    def forbidden_factory(database):
        factory_calls.append(database)
        raise AssertionError("Write factory must not be called")

    from claude.agents.tools.merchant.agent_cli import (
        invoke_agent_cli,
    )

    code = invoke_agent_cli(
        [
                        "merchant", "create",
            "--code", "SECURITY_TEST",
            "--name", "Unauthorized Merchant",
        ],
        write_command_factory=forbidden_factory,
    )

    captured = capsys.readouterr()

    assert code != 0
    assert factory_calls == []
    assert captured.out.strip() == ""


def test_database_failure_is_not_success(capsys):
    factory_calls = []

    def forbidden_factory(database):
        factory_calls.append(database)
        raise AssertionError("Write factory must not be called")

    from claude.agents.tools.merchant.agent_cli import (
        invoke_agent_cli,
    )

    code = invoke_agent_cli(
        [
                        "merchant", "create",
            "--code", "SECURITY_TEST",
            "--name", "Unauthorized Merchant",
        ],
        write_command_factory=forbidden_factory,
    )

    captured = capsys.readouterr()

    assert code != 0
    assert factory_calls == []
    assert captured.out.strip() == ""


def test_no_legacy_mode_called(capsys):
    factory_calls = []

    def forbidden_factory(database):
        factory_calls.append(database)
        raise AssertionError("Write factory must not be called")

    from claude.agents.tools.merchant.agent_cli import (
        invoke_agent_cli,
    )

    code = invoke_agent_cli(
        [
                        "merchant", "create",
            "--code", "SECURITY_TEST",
            "--name", "Unauthorized Merchant",
        ],
        write_command_factory=forbidden_factory,
    )

    captured = capsys.readouterr()

    assert code != 0
    assert factory_calls == []
    assert captured.out.strip() == ""
