import pytest

from claude.agents.tools.merchant import agent_cli


def test_direct_write_dispatches_once(monkeypatch):
    calls = []

    def fake_cli(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        return 0

    monkeypatch.setattr(
        agent_cli,
        "merchant_cli_main",
        fake_cli,
    )

    code = agent_cli.invoke_agent_cli((
        "merchant",
        "create",
        "--code",
        "TEST",
        "--name",
        "Test",
    ))

    assert code == 0
    assert len(calls) == 1

    argv, kwargs = calls[0]

    assert argv[:2] == (
        "--database",
        "runtime",
    )

    assert kwargs["runtime_authorization"] is None

    parser = agent_cli.build_argument_parser()
    args = parser.parse_args(argv)

    assert args.mode == "EXECUTE"
    assert args.resource == "merchant"
    assert args.action == "create"


@pytest.mark.parametrize("arguments", [
    (
        "merchant", "create", "--apply",
        "--code", "TEST", "--name", "Test",
    ),
    (
        "merchant", "create", "--propose",
        "--code", "TEST", "--name", "Test",
    ),
    (
        "merchant", "create",
        "--database=test",
        "--code", "TEST", "--name", "Test",
    ),
])
def test_legacy_or_target_override_never_dispatches(
    monkeypatch, arguments
):
    calls = []

    def fake_cli(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(
        agent_cli,
        "merchant_cli_main",
        fake_cli,
    )

    with pytest.raises(
        agent_cli.MerchantAgentCliError
    ):
        agent_cli.invoke_agent_cli(arguments)

    assert calls == []
