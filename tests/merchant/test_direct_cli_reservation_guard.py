from argparse import Namespace
from unittest.mock import Mock

import pytest

from claude.agents.tools.merchant.cli import dispatch_write_command


def test_generic_cli_cannot_execute_merchant_create():
    args = Namespace(
        resource="merchant",
        action="create",
        mode="EXECUTE",
        proposal_hash=None,
    )

    commands = Mock()

    with pytest.raises(
        PermissionError,
        match="durable reservation",
    ):
        dispatch_write_command(
            args,
            commands,
            database="runtime",
        )

    commands.execute.assert_not_called()
