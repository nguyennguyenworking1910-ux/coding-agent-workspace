"""Direct dispatcher must reject legacy Merchant write modes."""

from unittest.mock import Mock

import pytest

from claude.agents.tools.merchant.cli import (
    build_argument_parser,
    dispatch_write_command,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize("database", ["test", "runtime"])
@pytest.mark.parametrize("mode", ["PROPOSE", "APPLY"])
def test_direct_dispatch_rejects_legacy_before_handler(
    database, mode
):
    arguments = [
        "project",
        "update",
        PROJECT_ID,
        "--status",
        "PLANNED",
        "--expected-version",
        "1",
    ]

    if mode == "PROPOSE":
        arguments.append("--propose")
    else:
        arguments.extend([
            "--apply",
            "--proposal-hash",
            "a" * 64,
        ])

    args = build_argument_parser().parse_args(arguments)
    commands = Mock()

    with pytest.raises(
        PermissionError,
        match="EXECUTE",
    ):
        dispatch_write_command(
            args,
            commands,
            database=database,
        )

    commands.execute.assert_not_called()
    commands.propose.assert_not_called()
    commands.apply.assert_not_called()
