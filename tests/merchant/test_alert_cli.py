"""Checkpoint 8.4 global Merchant alert CLI contract tests."""

from __future__ import annotations

import json
from datetime import date

import pytest

from claude.agents.tools.merchant.agent_cli import (
    invoke_agent_cli,
    prepare_agent_cli_argv,
)
from claude.agents.tools.merchant.cli import (
    build_argument_parser,
    dispatch_read_command,
    main,
)


PROJECT_ID = "00000000-0000-0000-0000-00000000000a"
MERCHANT_ID = "00000000-0000-0000-0000-00000000000b"
SECOND_PROJECT_ID = "00000000-0000-0000-0000-00000000000c"


class RecordingAlertCommands:
    def __init__(self):
        self.calls = []

    def project_alerts(
        self,
        project_id=None,
        *,
        merchant_id=None,
        alert_type=None,
        due_date_before=None,
    ):
        self.calls.append(
            (
                project_id,
                merchant_id,
                alert_type,
                due_date_before,
            )
        )
        return [
            {
                "project_id": project_id or PROJECT_ID,
                "alert_type": alert_type or "DUE_SOON",
                "business_due_date": date(2026, 9, 10),
            }
        ]


def _dispatch(arguments):
    parser = build_argument_parser()
    args = parser.parse_args(arguments)
    commands = RecordingAlertCommands()
    result = dispatch_read_command(args, commands)
    return result, commands


def test_global_alert_command_accepts_no_filters():
    result, commands = _dispatch(["project", "alerts"])

    assert commands.calls == [(None, None, None, None)]
    assert result[0]["alert_type"] == "DUE_SOON"


def test_global_alert_command_dispatches_all_documented_filters():
    result, commands = _dispatch(
        [
            "project",
            "alerts",
            "--merchant-id",
            MERCHANT_ID,
            "--project-id",
            PROJECT_ID,
            "--alert-type",
            "overdue",
            "--due-date-before",
            "2026-09-10",
        ]
    )

    assert commands.calls == [
        (
            PROJECT_ID,
            MERCHANT_ID,
            "OVERDUE",
            date(2026, 9, 10),
        )
    ]
    assert result[0]["alert_type"] == "OVERDUE"


def test_legacy_positional_project_id_remains_compatible():
    _, commands = _dispatch(
        ["project", "alerts", PROJECT_ID]
    )

    assert commands.calls == [(PROJECT_ID, None, None, None)]


def test_equivalent_positional_and_flagged_project_ids_are_allowed():
    _, commands = _dispatch(
        [
            "project",
            "alerts",
            PROJECT_ID.upper(),
            "--project-id",
            PROJECT_ID,
        ]
    )

    assert commands.calls == [(PROJECT_ID, None, None, None)]


def test_conflicting_project_ids_fail_before_command_dispatch():
    parser = build_argument_parser()
    args = parser.parse_args(
        [
            "project",
            "alerts",
            PROJECT_ID,
            "--project-id",
            SECOND_PROJECT_ID,
        ]
    )
    commands = RecordingAlertCommands()

    with pytest.raises(ValueError, match="must match"):
        dispatch_read_command(args, commands)

    assert commands.calls == []


@pytest.mark.parametrize(
    "arguments",
    (
        ["project", "alerts", "--alert-type", "UNKNOWN"],
        ["project", "alerts", "--due-date-before", "20260910"],
        ["project", "alerts", "--due-date-before", "2026-02-30"],
        ["project", "alerts", "--merchant-id", "not-a-uuid"],
        ["project", "alerts", "--project-id", "not-a-uuid"],
        ["project", "alerts", "not-a-uuid"],
        ["project", "alerts", "--project-limit", "500"],
    ),
)
def test_invalid_or_undocumented_filters_fail_closed(arguments):
    with pytest.raises(SystemExit) as error:
        build_argument_parser().parse_args(arguments)

    assert error.value.code == 2


def test_main_returns_deterministic_json_for_global_alerts(capsys):
    commands = RecordingAlertCommands()
    selected_databases = []

    def factory(database):
        selected_databases.append(database)
        return commands

    exit_code = main(
        [
            "project",
            "alerts",
            "--merchant-id",
            MERCHANT_ID,
            "--alert-type",
            "due_soon",
        ],
        command_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert selected_databases == ["runtime"]
    assert captured.err == ""
    assert json.loads(captured.out) == [
        {
            "alert_type": "DUE_SOON",
            "business_due_date": "2026-09-10",
            "project_id": PROJECT_ID,
        }
    ]


def test_agent_interface_forwards_global_alert_filters_to_runtime(
    capsys,
):
    commands = RecordingAlertCommands()
    selected_databases = []
    arguments = [
        "project",
        "alerts",
        "--merchant-id",
        MERCHANT_ID,
        "--due-date-before",
        "2026-09-10",
    ]

    prepared = prepare_agent_cli_argv(arguments)
    assert prepared[:2] == ("--database", "runtime")

    exit_code = invoke_agent_cli(
        arguments,
        command_factory=lambda database: (
            selected_databases.append(database) or commands
        ),
    )

    assert exit_code == 0
    assert selected_databases == ["runtime"]
    assert commands.calls == [
        (None, MERCHANT_ID, None, date(2026, 9, 10))
    ]
    assert json.loads(capsys.readouterr().out)[0][
        "alert_type"
    ] == "DUE_SOON"
