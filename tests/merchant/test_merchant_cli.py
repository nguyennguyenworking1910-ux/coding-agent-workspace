"""Tests for the non-interactive Merchant JSON CLI."""

from __future__ import annotations

import argparse
import json

import pytest

from claude.agents.tools.merchant.cli import (
    build_argument_parser,
    dispatch_read_command,
    dispatch_write_command,
    main,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
MERCHANT_ID = "00000000-0000-0000-0000-000000000002"


class RecordingCommands:
    def __init__(self):
        self.calls = []

    def merchant_list(self, *, status=None):
        self.calls.append(("merchant_list", status))
        return [{"code": "BETA", "name": "Beta Media"}]

    def project_list(self, *, merchant_id=None, status=None):
        self.calls.append(
            ("project_list", merchant_id, status)
        )
        return [{"id": PROJECT_ID, "status": "IN_PROGRESS"}]

    def project_show(self, project_id):
        self.calls.append(("project_show", project_id))
        return {"project": {"id": project_id}}

    def project_history(self, project_id, *, limit):
        self.calls.append(("project_history", project_id, limit))
        return [{"event_type": "PROJECT_CREATED"}]

    def project_blockers(self, project_id):
        self.calls.append(("project_blockers", project_id))
        return [{"alert_type": "BLOCKED"}]

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
                "project_alerts",
                project_id,
                merchant_id,
                alert_type,
                due_date_before,
            )
        )
        return [{"alert_type": "DUE_SOON"}]


class RecordingWriteCommands:
    def __init__(self):
        self.calls = []

    def propose(self, command, database, payload):
        self.calls.append(
            ("propose", command, database, payload)
        )
        return {
            "success": True,
            "mode": "PROPOSE",
            "command": command,
        }

    def apply(
        self,
        command,
        database,
        payload,
        *,
        proposal_hash,
        runtime_authorization,
    ):
        self.calls.append(
            (
                "apply",
                command,
                database,
                payload,
                proposal_hash,
                runtime_authorization,
            )
        )
        return {
            "success": True,
            "mode": "APPLY",
            "command": command,
        }


@pytest.mark.parametrize(
    ("argv", "expected"),
    (
        (
            ["merchant", "list", "--status", "active"],
            ("merchant_list", "ACTIVE"),
        ),
        (
            [
                "project",
                "list",
                "--merchant-id",
                MERCHANT_ID,
                "--status",
                "in_progress",
            ],
            (
                "project_list",
                MERCHANT_ID,
                "IN_PROGRESS",
            ),
        ),
        (
            ["project", "show", PROJECT_ID],
            ("project_show", PROJECT_ID),
        ),
        (
            ["project", "history", PROJECT_ID, "--limit", "25"],
            ("project_history", PROJECT_ID, 25),
        ),
        (
            ["project", "blockers", PROJECT_ID],
            ("project_blockers", PROJECT_ID),
        ),
        (
            ["project", "alerts", PROJECT_ID],
            (
                "project_alerts",
                PROJECT_ID,
                None,
                None,
                None,
            ),
        ),
    ),
)
def test_all_read_commands_dispatch(argv, expected):
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    commands = RecordingCommands()

    dispatch_read_command(args, commands)

    assert commands.calls == [expected]


def test_database_defaults_to_runtime():
    args = build_argument_parser().parse_args(
        ["merchant", "list"]
    )

    assert args.database == "runtime"


def test_test_database_can_be_selected_explicitly():
    args = build_argument_parser().parse_args(
        ["--database", "test", "project", "show", PROJECT_ID]
    )

    assert args.database == "test"


@pytest.mark.parametrize(
    "argv",
    (
        [],
        ["merchant"],
        ["project"],
        ["project", "delete", PROJECT_ID],
        ["merchant", "list", "--status", "DELETED"],
        ["project", "history", PROJECT_ID, "--limit", "0"],
        ["project", "history", PROJECT_ID, "--limit", "501"],
    ),
)
def test_invalid_or_incomplete_command_fails_without_dispatch(argv):
    parser = build_argument_parser()

    with pytest.raises(SystemExit) as error:
        parser.parse_args(argv)

    assert error.value.code == 2


def test_main_prints_deterministic_json_and_returns_zero(capsys):
    commands = RecordingCommands()
    selected_databases = []

    def factory(database):
        selected_databases.append(database)
        return commands

    exit_code = main(
        ["--database", "test", "merchant", "list"],
        command_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert selected_databases == ["test"]
    assert captured.err == ""
    assert json.loads(captured.out) == [
        {"code": "BETA", "name": "Beta Media"}
    ]
    assert captured.out.index('"code"') < captured.out.index('"name"')


def test_main_returns_safe_json_for_expected_error(capsys):
    class FailingCommands(RecordingCommands):
        def project_show(self, project_id):
            raise ValueError(f"Invalid project: {project_id}")

    exit_code = main(
        ["project", "show", PROJECT_ID],
        command_factory=lambda database: FailingCommands(),
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert exit_code == 1
    assert captured.out == ""
    assert payload == {
        "success": False,
        "error": {
            "type": "ValueError",
            "message": f"Invalid project: {PROJECT_ID}",
        },
    }


def test_main_hides_unexpected_error_details(capsys):
    private_value = "private-database-diagnostic"

    def failing_factory(database):
        raise RuntimeError(private_value)

    exit_code = main(
        ["merchant", "list"],
        command_factory=failing_factory,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert exit_code == 1
    assert private_value not in captured.err
    assert payload["error"] == {
        "type": "MerchantCommandError",
        "message": "Merchant command failed",
    }


def test_dispatch_rejects_non_allowlisted_namespace():
    commands = RecordingCommands()
    args = argparse.Namespace(
        resource="merchant",
        action="delete",
    )

    with pytest.raises(ValueError, match="not allowlisted"):
        dispatch_read_command(args, commands)

    assert commands.calls == []


@pytest.mark.parametrize(
    ("argv", "command", "expected_payload"),
    (
        (
            [
                "merchant",
                "create",
                "--propose",
                "--code",
                "BETA",
                "--name",
                "Beta Media",
                "--region",
                "VN",
            ],
            "merchant create",
            {
                "code": "BETA",
                "name": "Beta Media",
                "region_code": "VN",
            },
        ),
        (
            [
                "project",
                "create",
                "--propose",
                "--merchant-id",
                MERCHANT_ID,
                "--type",
                "MEDIA_TOP_UP",
                "--variant",
                "MEDIA_TOP_UP_NEW_DOCUMENT",
                "--requires-procurement",
            ],
            "project create",
            {
                "merchant_id": MERCHANT_ID,
                "project_type": "MEDIA_TOP_UP",
                "workflow_variant": (
                    "MEDIA_TOP_UP_NEW_DOCUMENT"
                ),
                "requires_procurement": True,
            },
        ),
        (
            [
                "project",
                "update",
                PROJECT_ID,
                "--propose",
                "--status",
                "in_progress",
                "--expected-version",
                "2",
            ],
            "project update",
            {
                "project_id": PROJECT_ID,
                "status": "IN_PROGRESS",
                "expected_version": 2,
            },
        ),
        (
            [
                "step",
                "update",
                PROJECT_ID,
                "--propose",
                "--status",
                "in_progress",
                "--assigned-to",
                MERCHANT_ID,
                "--expected-version",
                "3",
            ],
            "step update",
            {
                "step_id": PROJECT_ID,
                "status": "IN_PROGRESS",
                "assigned_to": MERCHANT_ID,
                "expected_version": 3,
            },
        ),
        (
            [
                "document",
                "revision-create",
                PROJECT_ID,
                "--propose",
                "--type",
                "merchant_agreement",
                "--content-hash",
                "private-hash",
                "--effective-date",
                "2026-09-05",
            ],
            "document revision-create",
            {
                "project_id": PROJECT_ID,
                "document_type": "MERCHANT_AGREEMENT",
                "content_hash": "private-hash",
                "effective_date": "2026-09-05",
            },
        ),
        (
            [
                "document",
                "approve",
                PROJECT_ID,
                "--propose",
                "--role",
                "legal",
                "--status",
                "approved",
            ],
            "document approve",
            {
                "document_revision_id": PROJECT_ID,
                "approver_role": "LEGAL",
                "approval_status": "APPROVED",
            },
        ),
        (
            [
                "procurement",
                "update",
                PROJECT_ID,
                "--propose",
                "--type",
                "purchase_request",
                "--external-id",
                "PR-TEST-001",
            ],
            "procurement update",
            {
                "project_id": PROJECT_ID,
                "procurement_type": "PURCHASE_REQUEST",
                "external_id": "PR-TEST-001",
            },
        ),
        (
            [
                "integration",
                "identifier-set",
                MERCHANT_ID,
                PROJECT_ID,
                "--propose",
                "--type",
                "product_id",
                "--value",
                "private-id",
                "--scope",
                "uat",
            ],
            "integration identifier-set",
            {
                "merchant_id": MERCHANT_ID,
                "project_id": PROJECT_ID,
                "identifier_type": "PRODUCT_ID",
                "value": "private-id",
                "scope": "UAT",
                "is_active": True,
            },
        ),
    ),
)
def test_write_proposals_parse_and_dispatch(
    argv,
    command,
    expected_payload,
):
    args = build_argument_parser().parse_args(argv)
    commands = RecordingWriteCommands()

    result = dispatch_write_command(
        args,
        commands,
        database="test",
    )

    assert result["mode"] == "PROPOSE"
    assert len(commands.calls) == 1
    mode, actual_command, database, payload = commands.calls[0]
    assert mode == "propose"
    assert actual_command == command
    assert database == "test"

    for field, value in expected_payload.items():
        assert payload[field] == value


def test_contact_import_reads_utf8_csv(tmp_path):
    contact_file = tmp_path / "contacts.csv"
    contact_file.write_text(
        "name,email,phone,is_primary\n"
        "Nguyễn Văn A,private@example.com,0900000000,true\n",
        encoding="utf-8",
    )
    args = build_argument_parser().parse_args(
        [
            "contact",
            "import",
            "--propose",
            "--merchant-id",
            MERCHANT_ID,
            "--file",
            str(contact_file),
            "--expected-version",
            "4",
        ]
    )
    commands = RecordingWriteCommands()
    dispatch_write_command(
        args,
        commands,
        database="test",
    )
    payload = commands.calls[0][3]

    assert payload["merchant_id"] == MERCHANT_ID
    assert payload["expected_version"] == 4
    assert payload["contacts"] == [
        {
            "name": "Nguyễn Văn A",
            "email": "private@example.com",
            "phone": "0900000000",
            "is_primary": True,
        }
    ]


def test_write_apply_dispatches_hash_and_in_process_authority():
    proposal = "a" * 64
    args = build_argument_parser().parse_args(
        [
            "project",
            "update",
            PROJECT_ID,
            "--apply",
            "--proposal-hash",
            proposal,
            "--status",
            "BLOCKED",
            "--expected-version",
            "2",
        ]
    )
    commands = RecordingWriteCommands()
    authorization = object()

    result = dispatch_write_command(
        args,
        commands,
        database="runtime",
        runtime_authorization=authorization,
    )

    assert result["mode"] == "APPLY"
    call = commands.calls[0]
    assert call[0] == "apply"
    assert call[1] == "project update"
    assert call[2] == "runtime"
    assert call[4] == proposal
    assert call[5] is authorization


def test_propose_rejects_proposal_hash():
    args = build_argument_parser().parse_args(
        [
            "merchant",
            "create",
            "--propose",
            "--proposal-hash",
            "a" * 64,
            "--code",
            "BETA",
            "--name",
            "Beta Media",
        ]
    )
    commands = RecordingWriteCommands()

    with pytest.raises(ValueError, match="only valid"):
        dispatch_write_command(
            args,
            commands,
            database="test",
        )

    assert commands.calls == []


def test_apply_requires_proposal_hash():
    args = build_argument_parser().parse_args(
        [
            "merchant",
            "create",
            "--apply",
            "--code",
            "BETA",
            "--name",
            "Beta Media",
        ]
    )
    commands = RecordingWriteCommands()

    with pytest.raises(ValueError, match="requires"):
        dispatch_write_command(
            args,
            commands,
            database="test",
        )

    assert commands.calls == []


def test_main_routes_write_without_building_read_commands(capsys):
    writes = RecordingWriteCommands()
    read_calls = []

    exit_code = main(
        [
            "--database",
            "test",
            "merchant",
            "create",
            "--propose",
            "--code",
            "BETA",
            "--name",
            "Beta Media",
        ],
        command_factory=lambda database: read_calls.append(database),
        write_command_factory=lambda database: writes,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert json.loads(captured.out)["mode"] == "PROPOSE"
    assert read_calls == []
    assert writes.calls[0][0] == "propose"


@pytest.mark.parametrize(
    "argv",
    (
        [
            "merchant",
            "create",
            "--code",
            "BETA",
            "--name",
            "Beta Media",
        ],
        [
            "merchant",
            "create",
            "--propose",
            "--apply",
            "--code",
            "BETA",
            "--name",
            "Beta Media",
        ],
        [
            "step",
            "update",
            PROJECT_ID,
            "--propose",
            "--status",
            "NOT_A_STATUS",
            "--expected-version",
            "1",
        ],
    ),
)
def test_invalid_write_shapes_fail_during_parse(argv):
    with pytest.raises(SystemExit) as error:
        build_argument_parser().parse_args(argv)

    assert error.value.code == 2
