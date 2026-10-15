import pytest

from claude.agents.tools.merchant.agent_cli import (
    MerchantAgentCliError,
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


def _assert_ordinary_write_refused(capsys, arguments):
    factory_calls = []

    def forbidden_factory(database):
        factory_calls.append(database)
        raise AssertionError("Write factory must not be called")

    with pytest.raises(MerchantAgentCliError):
        invoke_agent_cli(
            arguments,
            write_command_factory=forbidden_factory,
        )

    captured = capsys.readouterr()

    assert factory_calls == []
    assert captured.out.strip() == ""


def test_full_direct_execution_chain(capsys):
    _assert_ordinary_write_refused(capsys, ARGS)


def test_database_failure_is_not_success(capsys):
    _assert_ordinary_write_refused(capsys, ARGS)


def test_no_legacy_mode_called(capsys):
    _assert_ordinary_write_refused(
        capsys,
        (*ARGS, "--propose"),
    )
