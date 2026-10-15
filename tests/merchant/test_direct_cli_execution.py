import json

import pytest

from claude.agents.tools.merchant.cli import (
    build_argument_parser,
    main,
)
from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)


class RecordingCreate:
    def __init__(self):
        self.calls = []

    def execute(self, command, database, payload):
        self.calls.append((command, database, payload))
        return {"success": True, "database": database}


def test_cli_main_allows_direct_create_on_test_target(capsys):
    writes = RecordingCreate()
    factory_calls = []

    def factory(database):
        factory_calls.append(database)
        return writes

    exit_code = main(
        [
            "--database", "test",
            "merchant", "create",
            "--code", "CP3C001",
            "--name", "Checkpoint 3C",
        ],
        write_command_factory=factory,
    )

    assert exit_code == 0
    assert factory_calls == ["test"]
    assert [call[:2] for call in writes.calls] == [
        ("merchant create", "test"),
    ]


def test_cli_main_rejects_explicit_runtime_create(capsys):
    factory_calls = []

    def factory(database):
        factory_calls.append(database)
        raise AssertionError("Factory must not be called")

    exit_code = main(
        [
            "--database", "runtime",
            "merchant", "create",
            "--execute",
            "--code", "CP3C002",
            "--name", "Explicit Execute",
        ],
        write_command_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert factory_calls == []
    assert json.loads(captured.err)["success"] is False


def test_invalid_payload_does_not_bypass_reservation_gate(capsys):
    writes = []

    commands = MerchantWriteCommands({
        "merchant create": lambda payload: writes.append(payload),
    })

    def reject(payload):
        raise ValueError("Domain validation rejected request")

    commands.register_preflight_validator(
        "merchant create", reject
    )

    exit_code = main(
        [
            "--database", "test",
            "merchant", "create",
            "--code", "CP3C003",
            "--name", "Rejected",
        ],
        write_command_factory=lambda database: commands,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert writes == []
    assert json.loads(captured.err)["success"] is False


def test_old_modes_still_parse_during_migration():
    parser = build_argument_parser()

    for mode, expected in (
        ("--propose", "PROPOSE"),
        ("--apply", "APPLY"),
    ):
        args = parser.parse_args([
            "--database", "test",
            "merchant", "create",
            mode,
            "--code", "CP3C004",
            "--name", "Compatibility",
        ])

        assert args.mode == expected


def test_default_execution_is_not_proposal():
    parser = build_argument_parser()

    args = parser.parse_args([
        "--database", "test",
        "merchant", "create",
        "--code", "CP3C005",
        "--name", "Default Mode",
    ])

    assert args.mode == "EXECUTE"
    assert args.proposal_hash is None


def test_conflicting_execution_modes_rejected():
    parser = build_argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([
            "--database", "test",
            "merchant", "create",
            "--execute",
            "--propose",
            "--code", "CP3C006",
            "--name", "Invalid Modes",
        ])
