#!/usr/bin/env python3
"""Non-interactive JSON CLI for Merchant project management."""

from __future__ import annotations

import argparse
import csv
import sys
import uuid
from collections.abc import Callable, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


try:
    from claude.agents.tools.merchant.checker import (
        ALERT_TYPES,
        MerchantProjectChecker,
    )
    from claude.agents.tools.merchant.cli_contract import (
        READ_COMMANDS,
        WRITE_COMMANDS,
        normalize_command,
        normalize_database_target,
        render_json,
        repository_role_for_target,
    )
    from claude.agents.tools.merchant.gates import (
        APPROVAL_STATUSES,
        APPROVER_ROLES,
    )
    from claude.agents.tools.merchant.identifier_engine import (
        IDENTIFIER_SCOPES,
        IDENTIFIER_TYPES,
    )
    from claude.agents.tools.merchant.procurement_engine import (
        PROCUREMENT_TYPES,
    )
    from claude.agents.tools.merchant.read_commands import (
        MerchantReadCommands,
    )
    from claude.agents.tools.merchant.write_commands import (
        MerchantWriteCommands,
    )
    from claude.agents.tools.merchant.state_machine import (
        STEP_STATUSES,
    )
    from claude.agents.tools.merchant.workflow import (
        PROJECT_TYPES,
    )
    from claude.agents.tools.merchant.workflow_templates import (
        STANDARD_WORKFLOW_TEMPLATES,
    )
    from claude.clients.merchant.read_repository import (
        DEFAULT_HISTORY_LIMIT,
        MAX_HISTORY_LIMIT,
        MERCHANT_ACCOUNT_STATUSES,
        PROJECT_STATUSES,
        MerchantReadRepository,
    )
    from claude.clients.merchant.repository import (
        MerchantRepository,
        MerchantRepositoryError,
    )
except ModuleNotFoundError:
    CLAUDE_ROOT = Path(__file__).resolve().parents[3]

    if str(CLAUDE_ROOT) not in sys.path:
        sys.path.insert(0, str(CLAUDE_ROOT))

    from agents.tools.merchant.checker import (  # type: ignore
        ALERT_TYPES,
        MerchantProjectChecker,
    )
    from agents.tools.merchant.cli_contract import (  # type: ignore
        READ_COMMANDS,
        WRITE_COMMANDS,
        normalize_command,
        normalize_database_target,
        render_json,
        repository_role_for_target,
    )
    from agents.tools.merchant.gates import (  # type: ignore
        APPROVAL_STATUSES,
        APPROVER_ROLES,
    )
    from agents.tools.merchant.identifier_engine import (  # type: ignore
        IDENTIFIER_SCOPES,
        IDENTIFIER_TYPES,
    )
    from agents.tools.merchant.procurement_engine import (  # type: ignore
        PROCUREMENT_TYPES,
    )
    from agents.tools.merchant.read_commands import (  # type: ignore
        MerchantReadCommands,
    )
    from agents.tools.merchant.write_commands import (  # type: ignore
        MerchantWriteCommands,
    )
    from agents.tools.merchant.state_machine import (  # type: ignore
        STEP_STATUSES,
    )
    from agents.tools.merchant.workflow import (  # type: ignore
        PROJECT_TYPES,
    )
    from agents.tools.merchant.workflow_templates import (  # type: ignore
        STANDARD_WORKFLOW_TEMPLATES,
    )
    from clients.merchant.read_repository import (  # type: ignore
        DEFAULT_HISTORY_LIMIT,
        MAX_HISTORY_LIMIT,
        MERCHANT_ACCOUNT_STATUSES,
        PROJECT_STATUSES,
        MerchantReadRepository,
    )
    from clients.merchant.repository import (  # type: ignore
        MerchantRepository,
        MerchantRepositoryError,
    )


CommandFactory = Callable[[str], MerchantReadCommands]
WriteCommandFactory = Callable[[str], MerchantWriteCommands]

MAX_CONTACT_FILE_BYTES = 1_048_576
MAX_CONTACT_ROWS = 1_000
CONTACT_FILE_FIELDS = frozenset(
    {
        "contact_id",
        "contact_type",
        "email",
        "is_primary",
        "name",
        "phone",
        "privacy_classification",
    }
)
WORKFLOW_VARIANTS = frozenset(
    template.variant
    for template in STANDARD_WORKFLOW_TEMPLATES
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merchant",
        description=(
            "Read and propose Merchant project operations as JSON"
        ),
    )
    parser.add_argument(
        "--database",
        choices=("runtime", "test"),
        default="runtime",
        help="Merchant database target (default: runtime)",
    )

    resources = parser.add_subparsers(
        dest="resource",
        required=True,
    )
    merchant_parser = resources.add_parser("merchant")
    merchant_actions = merchant_parser.add_subparsers(
        dest="action",
        required=True,
    )
    merchant_list = merchant_actions.add_parser("list")
    merchant_list.add_argument(
        "--status",
        type=_upper,
        choices=tuple(sorted(MERCHANT_ACCOUNT_STATUSES)),
    )
    merchant_create = merchant_actions.add_parser("create")
    _add_write_mode(merchant_create)
    merchant_create.add_argument("--code", required=True)
    merchant_create.add_argument("--name", required=True)
    merchant_create.add_argument("--region", dest="region_code")
    merchant_create.add_argument("--created-by")
    merchant_create.add_argument("--merchant-id")

    contact_parser = resources.add_parser("contact")
    contact_actions = contact_parser.add_subparsers(
        dest="action",
        required=True,
    )
    contact_import = contact_actions.add_parser("import")
    _add_write_mode(contact_import)
    contact_import.add_argument("--merchant-id", required=True)
    contact_import.add_argument("--file", required=True)
    contact_import.add_argument(
        "--expected-version",
        type=_positive_integer,
        required=True,
    )
    contact_import.add_argument("--triggered-by")

    project_parser = resources.add_parser("project")
    project_actions = project_parser.add_subparsers(
        dest="action",
        required=True,
    )
    project_list = project_actions.add_parser("list")
    project_list.add_argument("--merchant-id")
    project_list.add_argument(
        "--status",
        type=_upper,
        choices=tuple(sorted(PROJECT_STATUSES)),
    )

    project_show = project_actions.add_parser("show")
    project_show.add_argument("project_id")

    project_history = project_actions.add_parser("history")
    project_history.add_argument("project_id")
    project_history.add_argument(
        "--limit",
        type=_history_limit,
        default=DEFAULT_HISTORY_LIMIT,
    )

    project_blockers = project_actions.add_parser("blockers")
    project_blockers.add_argument("project_id")

    project_alerts = project_actions.add_parser("alerts")
    project_alerts.add_argument(
        "legacy_project_id",
        nargs="?",
        type=_uuid_filter,
        help=(
            "Optional project id retained for compatibility; prefer "
            "--project-id for filtered global reads"
        ),
    )
    project_alerts.add_argument(
        "--merchant-id",
        type=_uuid_filter,
    )
    project_alerts.add_argument(
        "--project-id",
        type=_uuid_filter,
    )
    project_alerts.add_argument(
        "--alert-type",
        type=_upper,
        choices=tuple(sorted(ALERT_TYPES)),
    )
    project_alerts.add_argument(
        "--due-date-before",
        type=_alert_due_date,
    )

    project_create = project_actions.add_parser("create")
    _add_write_mode(project_create)
    project_create.add_argument("--merchant-id", required=True)
    project_create.add_argument(
        "--type",
        dest="project_type",
        type=_upper,
        choices=tuple(sorted(PROJECT_TYPES)),
        required=True,
    )
    project_create.add_argument(
        "--variant",
        dest="workflow_variant",
        type=_upper,
        choices=tuple(sorted(WORKFLOW_VARIANTS)),
        required=True,
    )
    project_create.add_argument(
        "--requires-procurement",
        action="store_true",
    )
    project_create.add_argument(
        "--payment-period-number",
        type=_positive_integer,
    )
    project_create.add_argument(
        "--reused-document-revision-id"
    )
    project_create.add_argument("--title")
    project_create.add_argument("--created-by")
    project_create.add_argument("--project-id")

    project_update = project_actions.add_parser("update")
    _add_write_mode(project_update)
    project_update.add_argument("project_id")
    project_update.add_argument(
        "--status",
        type=_upper,
        choices=tuple(sorted(PROJECT_STATUSES)),
        required=True,
    )
    project_update.add_argument(
        "--expected-version",
        type=_positive_integer,
        required=True,
    )
    project_update.add_argument("--occurred-at", type=_iso_datetime)
    project_update.add_argument("--triggered-by")
    project_update.add_argument(
        "--allow-reopen",
        action="store_true",
    )

    step_parser = resources.add_parser("step")
    step_actions = step_parser.add_subparsers(
        dest="action",
        required=True,
    )
    step_update = step_actions.add_parser("update")
    _add_write_mode(step_update)
    step_update.add_argument("step_id")
    step_update.add_argument(
        "--status",
        type=_upper,
        choices=tuple(sorted(STEP_STATUSES)),
        required=True,
    )
    step_update.add_argument("--assigned-to")
    step_update.add_argument(
        "--expected-version",
        type=_positive_integer,
        required=True,
    )
    step_update.add_argument("--occurred-at", type=_iso_datetime)
    step_update.add_argument("--triggered-by")
    step_update.add_argument(
        "--allow-reopen",
        action="store_true",
    )

    document_parser = resources.add_parser("document")
    document_actions = document_parser.add_subparsers(
        dest="action",
        required=True,
    )
    revision_create = document_actions.add_parser(
        "revision-create"
    )
    _add_write_mode(revision_create)
    revision_create.add_argument("project_id")
    revision_create.add_argument(
        "--type",
        dest="document_type",
        type=_upper,
        required=True,
    )
    revision_create.add_argument("--content-hash", required=True)
    revision_create.add_argument("--effective-date", type=_iso_date)
    revision_create.add_argument("--expiry-date", type=_iso_date)
    revision_create.add_argument("--created-by")
    revision_create.add_argument("--revision-id")

    document_approve = document_actions.add_parser("approve")
    _add_write_mode(document_approve)
    document_approve.add_argument("revision_id")
    document_approve.add_argument(
        "--role",
        dest="approver_role",
        type=_upper,
        choices=tuple(sorted(APPROVER_ROLES)),
        required=True,
    )
    document_approve.add_argument(
        "--status",
        dest="approval_status",
        type=_upper,
        choices=tuple(sorted(APPROVAL_STATUSES)),
        required=True,
    )
    document_approve.add_argument(
        "--expected-status",
        type=_upper,
        choices=tuple(sorted(APPROVAL_STATUSES)),
    )
    document_approve.add_argument("--occurred-at", type=_iso_datetime)
    document_approve.add_argument("--acted-by")
    document_approve.add_argument("--notes")
    document_approve.add_argument("--approval-id")

    procurement_parser = resources.add_parser("procurement")
    procurement_actions = procurement_parser.add_subparsers(
        dest="action",
        required=True,
    )
    procurement_update = procurement_actions.add_parser("update")
    _add_write_mode(procurement_update)
    procurement_update.add_argument("project_id")
    procurement_update.add_argument(
        "--type",
        dest="procurement_type",
        type=_upper,
        choices=tuple(sorted(PROCUREMENT_TYPES)),
        required=True,
    )
    procurement_update.add_argument("--external-id")
    procurement_update.add_argument("--status", type=_upper)
    procurement_update.add_argument(
        "--expected-version",
        type=_positive_integer,
    )
    procurement_update.add_argument("--document-type", type=_upper)
    procurement_update.add_argument("--triggered-by")
    procurement_update.add_argument("--procurement-id")

    integration_parser = resources.add_parser("integration")
    integration_actions = integration_parser.add_subparsers(
        dest="action",
        required=True,
    )
    identifier_set = integration_actions.add_parser(
        "identifier-set"
    )
    _add_write_mode(identifier_set)
    identifier_set.add_argument("merchant_id")
    identifier_set.add_argument("project_id", nargs="?")
    identifier_set.add_argument(
        "--type",
        dest="identifier_type",
        type=_upper,
        choices=tuple(sorted(IDENTIFIER_TYPES)),
        required=True,
    )
    identifier_set.add_argument("--value", required=True)
    identifier_set.add_argument(
        "--scope",
        type=_upper,
        choices=tuple(sorted(IDENTIFIER_SCOPES)),
        required=True,
    )
    identifier_set.add_argument(
        "--inactive",
        dest="is_active",
        action="store_false",
        default=True,
    )
    identifier_set.add_argument(
        "--expected-version",
        type=_positive_integer,
    )
    identifier_set.add_argument("--triggered-by")
    identifier_set.add_argument("--identifier-id")

    return parser


def dispatch_read_command(
    args: argparse.Namespace,
    commands: MerchantReadCommands,
) -> Any:
    command = f"{args.resource} {args.action}"

    if command == "merchant list":
        return commands.merchant_list(status=args.status)

    if command == "project list":
        return commands.project_list(
            merchant_id=args.merchant_id,
            status=args.status,
        )

    if command == "project show":
        return commands.project_show(args.project_id)

    if command == "project history":
        return commands.project_history(
            args.project_id,
            limit=args.limit,
        )

    if command == "project blockers":
        return commands.project_blockers(args.project_id)

    if command == "project alerts":
        project_id = _selected_alert_project_id(args)
        return commands.project_alerts(
            project_id,
            merchant_id=args.merchant_id,
            alert_type=args.alert_type,
            due_date_before=args.due_date_before,
        )

    raise ValueError(
        f"Merchant read command is not allowlisted: {command!r}"
    )


def dispatch_write_command(
    args: argparse.Namespace,
    commands: MerchantWriteCommands,
    *,
    database: str,
    runtime_authorization: Any = None,
) -> Any:
    """Build an exact payload and select propose or apply."""

    command = normalize_command(
        f"{args.resource} {args.action}"
    )

    if command not in WRITE_COMMANDS:
        raise ValueError(
            f"Merchant write command is not allowlisted: {command!r}"
        )

    payload = build_write_payload(args, command)

    if args.mode == "PROPOSE":
        if args.proposal_hash is not None:
            raise ValueError(
                "--proposal-hash is only valid with --apply"
            )

        return commands.propose(
            command,
            database,
            payload,
        )

    if args.mode == "APPLY":
        if args.proposal_hash is None:
            raise ValueError(
                "--apply requires --proposal-hash"
            )

        return commands.apply(
            command,
            database,
            payload,
            proposal_hash=args.proposal_hash,
            runtime_authorization=runtime_authorization,
        )

    raise ValueError("Write mode must be PROPOSE or APPLY")


def build_write_payload(
    args: argparse.Namespace,
    command: str,
) -> dict[str, Any]:
    """Translate parsed CLI fields to repository-neutral payloads."""

    if command == "merchant create":
        return _selected_fields(
            args,
            (
                "merchant_id",
                "code",
                "name",
                "region_code",
                "created_by",
            ),
        )

    if command == "contact import":
        return {
            "merchant_id": args.merchant_id,
            "contacts": _load_contact_file(args.file),
            "expected_version": args.expected_version,
            "triggered_by": args.triggered_by,
        }

    if command == "project create":
        return _selected_fields(
            args,
            (
                "project_id",
                "merchant_id",
                "project_type",
                "workflow_variant",
                "requires_procurement",
                "payment_period_number",
                "reused_document_revision_id",
                "title",
                "created_by",
            ),
        )

    if command == "project update":
        return _selected_fields(
            args,
            (
                "project_id",
                "status",
                "expected_version",
                "occurred_at",
                "triggered_by",
                "allow_reopen",
            ),
        )

    if command == "step update":
        return _selected_fields(
            args,
            (
                "step_id",
                "status",
                "assigned_to",
                "expected_version",
                "occurred_at",
                "triggered_by",
                "allow_reopen",
            ),
        )

    if command == "document revision-create":
        return _selected_fields(
            args,
            (
                "revision_id",
                "project_id",
                "document_type",
                "content_hash",
                "effective_date",
                "expiry_date",
                "created_by",
            ),
        )

    if command == "document approve":
        payload = _selected_fields(
            args,
            (
                "approval_id",
                "revision_id",
                "approver_role",
                "approval_status",
                "expected_status",
                "occurred_at",
                "acted_by",
                "notes",
            ),
        )
        payload["document_revision_id"] = payload.pop(
            "revision_id"
        )
        return payload

    if command == "procurement update":
        return _selected_fields(
            args,
            (
                "procurement_id",
                "project_id",
                "procurement_type",
                "external_id",
                "status",
                "expected_version",
                "document_type",
                "triggered_by",
            ),
        )

    if command == "integration identifier-set":
        return _selected_fields(
            args,
            (
                "identifier_id",
                "merchant_id",
                "project_id",
                "identifier_type",
                "value",
                "scope",
                "is_active",
                "expected_version",
                "triggered_by",
            ),
        )

    raise ValueError(
        f"Merchant write command is not allowlisted: {command!r}"
    )


def build_read_commands(database: str) -> MerchantReadCommands:
    normalized_database = normalize_database_target(database)
    role = repository_role_for_target(normalized_database)
    repository = MerchantRepository(role=role)
    reads = MerchantReadRepository(repository)
    return MerchantReadCommands(
        reads,
        checker=MerchantProjectChecker(),
    )


def build_write_commands(database: str) -> MerchantWriteCommands:
    """Build repository-backed handlers for an explicit target."""

    try:
        from claude.agents.tools.merchant.write_adapters import (
            build_repository_write_commands,
        )
    except ModuleNotFoundError:
        from agents.tools.merchant.write_adapters import (  # type: ignore
            build_repository_write_commands,
        )

    return build_repository_write_commands(database)


def main(
    argv: Sequence[str] | None = None,
    *,
    command_factory: CommandFactory | None = None,
    write_command_factory: WriteCommandFactory | None = None,
    runtime_authorization: Any = None,
) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    database = normalize_database_target(args.database)
    command = normalize_command(
        f"{args.resource} {args.action}"
    )

    try:
        if command in READ_COMMANDS:
            factory = command_factory or build_read_commands
            commands = factory(database)
            result = dispatch_read_command(args, commands)
        elif command in WRITE_COMMANDS:
            factory = (
                write_command_factory
                or build_write_commands
            )
            write_commands = factory(database)
            result = dispatch_write_command(
                args,
                write_commands,
                database=database,
                runtime_authorization=runtime_authorization,
            )
        else:  # pragma: no cover
            raise ValueError(
                f"Merchant command is not allowlisted: {command!r}"
            )

        print(render_json(result))
        return 0
    except Exception as error:
        print(
            render_json(_error_payload(error)),
            file=sys.stderr,
        )
        return 1


def _error_payload(error: Exception) -> dict[str, Any]:
    if isinstance(error, (ValueError, MerchantRepositoryError)):
        message = " ".join(str(error).split())
        error_type = error.__class__.__name__
    else:
        message = "Merchant command failed"
        error_type = "MerchantCommandError"

    return {
        "success": False,
        "error": {
            "type": error_type,
            "message": message[:500],
        },
    }


def _upper(value: str) -> str:
    return value.strip().upper()


def _history_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "limit must be an integer"
        ) from error

    if not 1 <= limit <= MAX_HISTORY_LIMIT:
        raise argparse.ArgumentTypeError(
            f"limit must be between 1 and {MAX_HISTORY_LIMIT}"
        )

    return limit


def _uuid_filter(value: str) -> str:
    candidate = value.strip()

    try:
        normalized = uuid.UUID(candidate)
    except (AttributeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            "identifier must be a UUID"
        ) from error

    return str(normalized)


def _alert_due_date(value: str) -> date:
    candidate = value.strip()

    try:
        parsed = date.fromisoformat(candidate)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "due date must use YYYY-MM-DD"
        ) from error

    if parsed.isoformat() != candidate:
        raise argparse.ArgumentTypeError(
            "due date must use YYYY-MM-DD"
        )

    return parsed


def _selected_alert_project_id(
    args: argparse.Namespace,
) -> str | None:
    legacy_project_id = args.legacy_project_id
    filtered_project_id = args.project_id

    if (
        legacy_project_id is not None
        and filtered_project_id is not None
        and legacy_project_id != filtered_project_id
    ):
        raise ValueError(
            "project alerts positional project_id and --project-id "
            "must match"
        )

    return filtered_project_id or legacy_project_id


def _add_write_mode(parser: argparse.ArgumentParser) -> None:
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--propose",
        dest="mode",
        action="store_const",
        const="PROPOSE",
    )
    modes.add_argument(
        "--apply",
        dest="mode",
        action="store_const",
        const="APPLY",
    )
    parser.add_argument("--proposal-hash")


def _selected_fields(
    args: argparse.Namespace,
    field_names: Sequence[str],
) -> dict[str, Any]:
    return {
        field_name: getattr(args, field_name)
        for field_name in field_names
    }


def _load_contact_file(value: str) -> list[dict[str, Any]]:
    path = Path(value).expanduser()

    if not path.is_file():
        raise ValueError("Contact CSV file does not exist")

    if path.stat().st_size > MAX_CONTACT_FILE_BYTES:
        raise ValueError(
            "Contact CSV file exceeds the 1 MiB limit"
        )

    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)
            fields = _contact_file_fields(reader.fieldnames)
            rows = []

            for row_number, source in enumerate(
                reader,
                start=1,
            ):
                if row_number > MAX_CONTACT_ROWS:
                    raise ValueError(
                        "Contact CSV cannot exceed 1000 rows"
                    )

                row = _contact_file_row(
                    source,
                    fields,
                    row_number,
                )
                rows.append(row)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(
            "Contact CSV could not be read as UTF-8"
        ) from error

    if not rows:
        raise ValueError(
            "Contact CSV requires at least one data row"
        )

    return rows


def _contact_file_fields(
    source_fields: list[str] | None,
) -> tuple[str, ...]:
    if source_fields is None:
        raise ValueError("Contact CSV requires a header row")

    normalized = tuple(
        str(field).strip().lower()
        for field in source_fields
    )

    if not normalized or any(not field for field in normalized):
        raise ValueError("Contact CSV has a blank header")

    if len(set(normalized)) != len(normalized):
        raise ValueError("Contact CSV has duplicate headers")

    unknown = set(normalized) - CONTACT_FILE_FIELDS

    if unknown:
        raise ValueError(
            "Contact CSV has unsupported headers: "
            + ", ".join(sorted(unknown))
        )

    if not {"name", "email", "phone"} & set(normalized):
        raise ValueError(
            "Contact CSV requires name, email, or phone"
        )

    return normalized


def _contact_file_row(
    source: dict[str, str | None],
    fields: tuple[str, ...],
    row_number: int,
) -> dict[str, Any]:
    values = list(source.values())

    if None in source:
        raise ValueError(
            f"Contact CSV row {row_number} has extra columns"
        )

    normalized = {
        field: (
            str(values[index]).strip()
            if values[index] is not None
            else ""
        )
        for index, field in enumerate(fields)
    }

    if not any(normalized.values()):
        raise ValueError(
            f"Contact CSV row {row_number} is blank"
        )

    row: dict[str, Any] = {}

    for field, item in normalized.items():
        if field == "is_primary":
            row[field] = _csv_boolean(
                item,
                row_number,
            )
        else:
            row[field] = item or None

    return row


def _csv_boolean(value: str, row_number: int) -> bool:
    normalized = value.strip().lower()

    if normalized in {"true", "1", "yes"}:
        return True

    if normalized in {"false", "0", "no", ""}:
        return False

    raise ValueError(
        f"Contact CSV row {row_number} has invalid is_primary"
    )


def _positive_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "value must be a positive integer"
        ) from error

    if result <= 0:
        raise argparse.ArgumentTypeError(
            "value must be a positive integer"
        )

    return result


def _iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "date must use YYYY-MM-DD"
        ) from error


def _iso_datetime(value: str) -> str:
    candidate = value.strip()

    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "datetime must be ISO-8601"
        ) from error

    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "datetime must include a UTC offset"
        )

    return parsed.astimezone(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
