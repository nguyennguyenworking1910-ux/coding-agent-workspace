import pytest

from claude.agents.tools.merchant import agent_cli
from claude.agents.tools.merchant import cli


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"

WRITE_ARGUMENTS = (
    ("merchant", "create", "--code", "TEST", "--name", "Test"),
    ("merchant", "create", "--execute", "--code", "TEST", "--name", "Test"),
    (
        "merchant", "activate",
        "--merchant-id", MERCHANT_ID,
        "--expected-version", "1",
        "--reason", "test",
        "--triggered-by", PROJECT_ID,
    ),
    (
        "project", "create",
        "--merchant-id", MERCHANT_ID,
        "--type", "OPENING_NEW_CINEMA",
        "--variant", "OPENING_NEW_CINEMA_STANDARD",
    ),
    (
        "project", "update", PROJECT_ID,
        "--status", "PLANNED",
        "--expected-version", "1",
    ),
)


@pytest.mark.parametrize("arguments", WRITE_ARGUMENTS)
def test_ordinary_adapter_rejects_every_write_without_dispatch(
    monkeypatch, arguments
):
    calls = []

    monkeypatch.setattr(
        agent_cli,
        "merchant_cli_main",
        lambda *args, **kwargs: calls.append((args, kwargs)) or 0,
    )

    with pytest.raises(agent_cli.MerchantAgentCliError):
        agent_cli.invoke_agent_cli(arguments)

    assert calls == []


def test_ordinary_adapter_still_dispatches_reads(monkeypatch):
    calls = []

    monkeypatch.setattr(
        agent_cli,
        "merchant_cli_main",
        lambda argv, **kwargs: calls.append((tuple(argv), kwargs)) or 0,
    )

    code = agent_cli.invoke_agent_cli(("merchant", "list"))

    assert code == 0
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:2] == ("--database", "runtime")
    assert kwargs["runtime_authorization"] is None


@pytest.mark.parametrize("arguments", WRITE_ARGUMENTS)
def test_cli_main_refuses_unauthorized_runtime_write(arguments):
    factory_calls = []

    def factory(database):
        factory_calls.append(database)
        raise AssertionError("write handlers must not be built")

    code = cli.main(
        ("--database", "runtime", *arguments),
        write_command_factory=factory,
        runtime_authorization=None,
    )

    assert code == 1
    assert factory_calls == []


def test_cli_main_runtime_proposal_is_not_blocked_by_write_guard():
    factory_calls = []

    def factory(database):
        factory_calls.append(database)
        raise RuntimeError("stop after guard")

    cli.main(
        (
            "--database",
            "runtime",
            "project",
            "update",
            PROJECT_ID,
            "--status",
            "PLANNED",
            "--expected-version",
            "1",
            "--propose",
        ),
        write_command_factory=factory,
        runtime_authorization=None,
    )

    assert factory_calls == ["runtime"]
