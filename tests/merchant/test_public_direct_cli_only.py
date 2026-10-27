import pytest

from claude.agents.tools.merchant import cli


@pytest.mark.parametrize("database", ["test", "runtime"])
@pytest.mark.parametrize("mode", ["--propose", "--apply"])
def test_public_cli_rejects_legacy_write_before_factory(
    database, mode, capsys
):
    calls = []

    def forbidden_factory(target):
        calls.append(target)
        pytest.fail("Legacy write reached command factory")

    exit_code = cli.main(
        [
            "--database", database,
            "project", "update",
            "00000000-0000-0000-0000-000000000001",
            "--status", "PLANNED",
            "--expected-version", "1",
            mode,
        ],
        write_command_factory=forbidden_factory,
    )

    assert exit_code == 1
    assert calls == []
    assert "MerchantCommandError" in capsys.readouterr().err
