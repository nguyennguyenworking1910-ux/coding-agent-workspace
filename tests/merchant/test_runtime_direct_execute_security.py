"""Security contract for future runtime Direct Execute migration."""

import pytest

from claude.agents.tools.merchant.cli import main
from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)


ARGV = [
    "project",
    "update",
    "00000000-0000-0000-0000-000000000001",
    "--status",
    "IN_PROGRESS",
    "--expected-version",
    "3",
    "--execute",
]


@pytest.mark.parametrize(
    "authorization",
    [None, object(), {"authorized": True}],
)
def test_runtime_execute_rejects_untrusted_authorization(
    authorization, capsys
):
    calls = []

    def factory(database):
        calls.append(database)
        return MerchantWriteCommands({
            "project update": lambda payload: {
                "updated": True
            }
        })

    code = main(
        ARGV,
        write_command_factory=factory,
        runtime_authorization=authorization,
    )

    assert code != 0
    assert calls == []

    output = capsys.readouterr()
    assert output.err
