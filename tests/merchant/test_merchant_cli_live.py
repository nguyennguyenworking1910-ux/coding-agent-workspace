"""Opt-in live lifecycle for the Merchant JSON CLI."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from psycopg.rows import dict_row

from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
    TEST_DATABASE,
)


LIVE_TESTS_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_LIVE_TESTS",
        "",
    ).strip()
    == "1"
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = (
    REPOSITORY_ROOT
    / ".claude"
    / "agents"
    / "tools"
    / "merchant"
    / "cli.py"
)
REDACTED_VALUE = "[REDACTED]"


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_LIVE_TESTS=1 to run the "
        "Merchant test-database CLI lifecycle"
    ),
)
def test_merchant_cli_live_propose_apply_read_and_cleanup(
    tmp_path: Path,
):
    """Prove binding, persistence, redaction, audit, and cleanup."""

    config = RepositoryConfig.from_env("test")
    assert config.database == TEST_DATABASE
    assert config.database.endswith("_test")
    assert config.user == "merchant_test"
    assert config.host == "127.0.0.1"
    assert config.port == 5434

    repository = MerchantRepository(config)
    identifiers = _temporary_identifiers()
    token = uuid.uuid4().hex[:12].upper()
    merchant_code = f"CLI_{token}"
    merchant_name = f"Rạp kiểm thử CLI {token}"
    project_title = f"CLI live workflow {token}"
    contact_name = f"Liên hệ riêng {token}"
    contact_email = f"cli-{token.lower()}@example.test"
    contact_phone = f"TEST-{token}"
    identifier_value = f"PRIVATE-PRODUCT-{token}"
    contact_file = tmp_path / "contacts.csv"
    cleanup_counts = None

    _write_contact_csv(
        contact_file,
        contact_id=identifiers["contact_id"],
        name=contact_name,
        email=contact_email,
        phone=contact_phone,
    )

    try:
        assert _database_identity(repository) == {
            "database": TEST_DATABASE,
            "user": "merchant_test",
            "read_only": "on",
        }
        assert _record_counts(repository, identifiers) == (
            _empty_record_counts()
        )

        merchant_arguments = (
            "--database",
            "test",
            "merchant",
            "create",
            "--merchant-id",
            str(identifiers["merchant_id"]),
            "--code",
            merchant_code,
            "--name",
            merchant_name,
            "--region",
            "VN",
        )
        proposed_merchant = _successful_cli(
            *merchant_arguments,
            "--propose",
        )

        assert proposed_merchant["mode"] == "PROPOSE"
        assert proposed_merchant["command"] == "merchant create"
        assert proposed_merchant["database"] == "test"
        assert proposed_merchant["requires_confirmation"] is True
        assert proposed_merchant["payload"]["merchant_id"] == str(
            identifiers["merchant_id"]
        )
        assert _record_counts(repository, identifiers) == (
            _empty_record_counts()
        )

        tampered = list(merchant_arguments)
        tampered[tampered.index(merchant_name)] = (
            merchant_name + " TAMPERED"
        )
        tampered_result = _invoke_cli(
            *tampered,
            "--apply",
            "--proposal-hash",
            proposed_merchant["proposal_hash"],
        )
        assert tampered_result["exit_code"] == 1
        assert tampered_result["payload"]["success"] is False
        assert tampered_result["payload"]["error"]["type"] == (
            "ProposalHashError"
        )
        assert _record_counts(repository, identifiers) == (
            _empty_record_counts()
        )

        applied_merchant = _successful_cli(
            *merchant_arguments,
            "--apply",
            "--proposal-hash",
            proposed_merchant["proposal_hash"],
        )
        assert applied_merchant["mode"] == "APPLY"
        assert applied_merchant["result"]["merchant_id"] == str(
            identifiers["merchant_id"]
        )
        assert applied_merchant["result"]["version"] == 1

        replayed_merchant = _invoke_cli(
            *merchant_arguments,
            "--apply",
            "--proposal-hash",
            proposed_merchant["proposal_hash"],
        )
        assert replayed_merchant["exit_code"] == 1
        assert replayed_merchant["payload"]["success"] is False
        assert _record_counts(repository, identifiers)[
            "merchants"
        ] == 1
        assert _record_counts(repository, identifiers)[
            "project_events"
        ] == 1

        contact_arguments = (
            "--database",
            "test",
            "contact",
            "import",
            "--merchant-id",
            str(identifiers["merchant_id"]),
            "--file",
            str(contact_file),
            "--expected-version",
            "1",
        )
        proposed_contacts = _successful_cli(
            *contact_arguments,
            "--propose",
        )
        proposed_contacts_json = json.dumps(
            proposed_contacts,
            ensure_ascii=False,
        )
        proposed_contact = proposed_contacts["payload"][
            "contacts"
        ][0]

        assert proposed_contact["contact_id"] == str(
            identifiers["contact_id"]
        )
        assert proposed_contact["name"] == REDACTED_VALUE
        assert proposed_contact["email"] == REDACTED_VALUE
        assert proposed_contact["phone"] == REDACTED_VALUE
        assert contact_name not in proposed_contacts_json
        assert contact_email not in proposed_contacts_json
        assert contact_phone not in proposed_contacts_json
        assert _record_counts(repository, identifiers)[
            "merchant_contacts"
        ] == 0

        applied_contacts = _successful_cli(
            *contact_arguments,
            "--apply",
            "--proposal-hash",
            proposed_contacts["proposal_hash"],
        )
        assert applied_contacts["result"]["contacts_imported"] == 1
        assert applied_contacts["result"][
            "previous_merchant_version"
        ] == 1
        assert applied_contacts["result"][
            "current_merchant_version"
        ] == 2
        assert contact_name not in json.dumps(
            applied_contacts,
            ensure_ascii=False,
        )

        project_arguments = (
            "--database",
            "test",
            "project",
            "create",
            "--project-id",
            str(identifiers["project_id"]),
            "--merchant-id",
            str(identifiers["merchant_id"]),
            "--type",
            "INTEGRATION_NEW_MERCHANT",
            "--variant",
            "INTEGRATION_NEW_MERCHANT_STANDARD",
            "--requires-procurement",
            "--title",
            project_title,
        )
        proposed_project = _successful_cli(
            *project_arguments,
            "--propose",
        )

        assert proposed_project["payload"]["project_id"] == str(
            identifiers["project_id"]
        )
        assert proposed_project["payload"]["requires_procurement"] is (
            True
        )
        assert _record_counts(repository, identifiers)["projects"] == 0

        applied_project = _successful_cli(
            *project_arguments,
            "--apply",
            "--proposal-hash",
            proposed_project["proposal_hash"],
        )
        assert applied_project["result"]["project_id"] == str(
            identifiers["project_id"]
        )
        assert applied_project["result"]["status"] == "PLANNED"
        assert applied_project["result"]["steps_inserted"] == 26
        assert applied_project["result"][
            "dependencies_inserted"
        ] == 29

        identifier_arguments = (
            "--database",
            "test",
            "integration",
            "identifier-set",
            str(identifiers["merchant_id"]),
            str(identifiers["project_id"]),
            "--identifier-id",
            str(identifiers["identifier_id"]),
            "--type",
            "PRODUCT_ID",
            "--value",
            identifier_value,
            "--scope",
            "UAT",
        )
        proposed_identifier = _successful_cli(
            *identifier_arguments,
            "--propose",
        )
        proposed_identifier_json = json.dumps(
            proposed_identifier,
            ensure_ascii=False,
        )

        assert proposed_identifier["payload"]["value"] == (
            REDACTED_VALUE
        )
        assert identifier_value not in proposed_identifier_json
        assert _record_counts(repository, identifiers)[
            "integration_identifiers"
        ] == 0

        applied_identifier = _successful_cli(
            *identifier_arguments,
            "--apply",
            "--proposal-hash",
            proposed_identifier["proposal_hash"],
        )
        assert applied_identifier["result"]["identifier_id"] == str(
            identifiers["identifier_id"]
        )
        assert applied_identifier["result"]["operation"] == "INSERT"
        assert identifier_value not in json.dumps(
            applied_identifier,
            ensure_ascii=False,
        )

        replayed_identifier = _invoke_cli(
            *identifier_arguments,
            "--apply",
            "--proposal-hash",
            proposed_identifier["proposal_hash"],
        )
        assert replayed_identifier["exit_code"] == 1
        assert replayed_identifier["payload"]["success"] is False
        assert _record_counts(repository, identifiers)[
            "integration_identifiers"
        ] == 1
        assert _record_counts(repository, identifiers)[
            "project_events"
        ] == 4

        merchants = _successful_cli(
            "--database",
            "test",
            "merchant",
            "list",
        )
        stored_merchant = next(
            merchant
            for merchant in merchants
            if merchant["id"] == str(identifiers["merchant_id"])
        )
        assert stored_merchant["code"] == merchant_code
        assert stored_merchant["name"] == merchant_name
        assert stored_merchant["version"] == 2
        assert stored_merchant["contact_count"] == 1

        projects = _successful_cli(
            "--database",
            "test",
            "project",
            "list",
            "--merchant-id",
            str(identifiers["merchant_id"]),
        )
        assert len(projects) == 1
        assert projects[0]["id"] == str(identifiers["project_id"])
        assert projects[0]["title"] == project_title

        detail = _successful_cli(
            "--database",
            "test",
            "project",
            "show",
            str(identifiers["project_id"]),
        )
        detail_json = json.dumps(detail, ensure_ascii=False)
        stored_contact = detail["merchant_contacts"][0]
        stored_identifier = detail["integration_identifiers"][0]

        assert detail["project"]["id"] == str(
            identifiers["project_id"]
        )
        assert len(detail["steps"]) == 26
        assert len(detail["dependencies"]) == 29
        assert stored_contact["contact_name"] == REDACTED_VALUE
        assert stored_contact["contact_email"] == REDACTED_VALUE
        assert stored_contact["contact_phone"] == REDACTED_VALUE
        assert stored_identifier["identifier_value"] == REDACTED_VALUE
        assert contact_name not in detail_json
        assert contact_email not in detail_json
        assert contact_phone not in detail_json
        assert identifier_value not in detail_json

        history = _successful_cli(
            "--database",
            "test",
            "project",
            "history",
            str(identifiers["project_id"]),
            "--limit",
            "10",
        )
        assert [event["event_type"] for event in history] == [
            "PROJECT_CREATED",
            "INTEGRATION_IDENTIFIER_SET",
        ]
        assert identifier_value not in json.dumps(
            history,
            ensure_ascii=False,
        )

        private_state = _private_state(repository, identifiers)
        assert private_state["contact"] == {
            "name": contact_name,
            "email": contact_email,
            "phone": contact_phone,
        }
        assert private_state["identifier_value"] == identifier_value
        assert private_state["project"] == {
            "status": "PLANNED",
            "workflow_variant": (
                "INTEGRATION_NEW_MERCHANT_STANDARD"
            ),
        }
        assert private_state["event_types"] == Counter(
            {
                "MERCHANT_CREATED": 1,
                "MERCHANT_CONTACTS_IMPORTED": 1,
                "PROJECT_CREATED": 1,
                "INTEGRATION_IDENTIFIER_SET": 1,
            }
        )
        assert contact_name not in private_state["audit_json"]
        assert contact_email not in private_state["audit_json"]
        assert contact_phone not in private_state["audit_json"]
        assert identifier_value not in private_state["audit_json"]

        assert _record_counts(repository, identifiers) == {
            "merchants": 1,
            "merchant_contacts": 1,
            "projects": 1,
            "project_steps": 26,
            "project_step_dependencies": 29,
            "integration_identifiers": 1,
            "project_events": 4,
            "alert_deliveries": 0,
        }
    finally:
        cleanup_counts = _cleanup_temporary_records(
            repository,
            identifiers,
        )

    assert cleanup_counts == {
        "alert_deliveries": 0,
        "integration_identifiers": 1,
        "project_events": 4,
        "project_step_dependencies": 29,
        "project_steps": 26,
        "projects": 1,
        "merchant_contacts": 1,
        "merchants": 1,
    }
    assert _record_counts(repository, identifiers) == (
        _empty_record_counts()
    )


def _temporary_identifiers() -> dict[str, uuid.UUID]:
    return {
        "merchant_id": uuid.uuid4(),
        "contact_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "identifier_id": uuid.uuid4(),
    }


def _write_contact_csv(
    path: Path,
    *,
    contact_id: uuid.UUID,
    name: str,
    email: str,
    phone: str,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "contact_id",
                "contact_type",
                "name",
                "email",
                "phone",
                "privacy_classification",
                "is_primary",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "contact_id": str(contact_id),
                "contact_type": "PRIMARY",
                "name": name,
                "email": email,
                "phone": phone,
                "privacy_classification": "PII",
                "is_primary": "true",
            }
        )


def _invoke_cli(*arguments: str) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(CLI_PATH), *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    output = completed.stdout if completed.returncode == 0 else (
        completed.stderr
    )

    assert output.strip(), (
        f"Merchant CLI returned no JSON; stderr={completed.stderr!r}"
    )

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise AssertionError(
            "Merchant CLI output was not one JSON document: "
            f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
        ) from error

    return {
        "exit_code": completed.returncode,
        "payload": payload,
    }


def _successful_cli(*arguments: str) -> Any:
    result = _invoke_cli(*arguments)
    assert result["exit_code"] == 0, result["payload"]
    return result["payload"]


def _database_identity(
    repository: MerchantRepository,
) -> dict[str, Any]:
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        current_database() AS database,
                        current_user AS user,
                        current_setting(
                            'transaction_read_only'
                        ) AS read_only
                    """
                )
                return dict(cursor.fetchone())


def _record_counts(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, int]:
    merchant_id = identifiers["merchant_id"]
    project_id = identifiers["project_id"]
    queries = {
        "merchants": (
            "SELECT COUNT(*) AS count FROM merchant_ops.merchants "
            "WHERE id = %s",
            (merchant_id,),
        ),
        "merchant_contacts": (
            "SELECT COUNT(*) AS count "
            "FROM merchant_ops.merchant_contacts "
            "WHERE merchant_id = %s",
            (merchant_id,),
        ),
        "projects": (
            "SELECT COUNT(*) AS count FROM merchant_ops.projects "
            "WHERE id = %s",
            (project_id,),
        ),
        "project_steps": (
            "SELECT COUNT(*) AS count "
            "FROM merchant_ops.project_steps "
            "WHERE project_id = %s",
            (project_id,),
        ),
        "project_step_dependencies": (
            "SELECT COUNT(*) AS count "
            "FROM merchant_ops.project_step_dependencies "
            "WHERE from_step_id IN ("
            "SELECT id FROM merchant_ops.project_steps "
            "WHERE project_id = %s"
            ") OR to_step_id IN ("
            "SELECT id FROM merchant_ops.project_steps "
            "WHERE project_id = %s"
            ")",
            (project_id, project_id),
        ),
        "integration_identifiers": (
            "SELECT COUNT(*) AS count "
            "FROM merchant_ops.integration_identifiers "
            "WHERE id = %s",
            (identifiers["identifier_id"],),
        ),
        "project_events": (
            "SELECT COUNT(*) AS count "
            "FROM merchant_ops.project_events "
            "WHERE merchant_id = %s",
            (merchant_id,),
        ),
        "alert_deliveries": (
            "SELECT COUNT(*) AS count "
            "FROM merchant_ops.alert_deliveries "
            "WHERE project_id = %s",
            (project_id,),
        ),
    }
    counts = {}

    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                for name, (query, parameters) in queries.items():
                    cursor.execute(query, parameters)
                    counts[name] = int(cursor.fetchone()["count"])

    return counts


def _empty_record_counts() -> dict[str, int]:
    return {
        "merchants": 0,
        "merchant_contacts": 0,
        "projects": 0,
        "project_steps": 0,
        "project_step_dependencies": 0,
        "integration_identifiers": 0,
        "project_events": 0,
        "alert_deliveries": 0,
    }


def _private_state(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, Any]:
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT name, email, phone
                    FROM merchant_ops.merchant_contacts
                    WHERE id = %s
                    """,
                    (identifiers["contact_id"],),
                )
                contact = dict(cursor.fetchone())

                cursor.execute(
                    """
                    SELECT identifier_value
                    FROM merchant_ops.integration_identifiers
                    WHERE id = %s
                    """,
                    (identifiers["identifier_id"],),
                )
                identifier_value = cursor.fetchone()[
                    "identifier_value"
                ]

                cursor.execute(
                    """
                    SELECT status, workflow_variant
                    FROM merchant_ops.projects
                    WHERE id = %s
                    """,
                    (identifiers["project_id"],),
                )
                project = dict(cursor.fetchone())

                cursor.execute(
                    """
                    SELECT
                        event_type,
                        change_summary,
                        old_values,
                        new_values
                    FROM merchant_ops.project_events
                    WHERE merchant_id = %s
                    ORDER BY created_at, id
                    """,
                    (identifiers["merchant_id"],),
                )
                events = [dict(row) for row in cursor.fetchall()]

    return {
        "contact": contact,
        "identifier_value": identifier_value,
        "project": project,
        "event_types": Counter(
            event["event_type"] for event in events
        ),
        "audit_json": json.dumps(events, default=str),
    }


def _cleanup_temporary_records(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, int]:
    merchant_id = identifiers["merchant_id"]
    project_id = identifiers["project_id"]
    deletions = (
        (
            "alert_deliveries",
            "DELETE FROM merchant_ops.alert_deliveries "
            "WHERE project_id = %s",
            (project_id,),
        ),
        (
            "integration_identifiers",
            "DELETE FROM merchant_ops.integration_identifiers "
            "WHERE merchant_id = %s",
            (merchant_id,),
        ),
        (
            "project_events",
            "DELETE FROM merchant_ops.project_events "
            "WHERE merchant_id = %s",
            (merchant_id,),
        ),
        (
            "project_step_dependencies",
            "DELETE FROM merchant_ops.project_step_dependencies "
            "WHERE from_step_id IN ("
            "SELECT id FROM merchant_ops.project_steps "
            "WHERE project_id = %s"
            ") OR to_step_id IN ("
            "SELECT id FROM merchant_ops.project_steps "
            "WHERE project_id = %s"
            ")",
            (project_id, project_id),
        ),
        (
            "project_steps",
            "DELETE FROM merchant_ops.project_steps "
            "WHERE project_id = %s",
            (project_id,),
        ),
        (
            "projects",
            "DELETE FROM merchant_ops.projects WHERE id = %s",
            (project_id,),
        ),
        (
            "merchant_contacts",
            "DELETE FROM merchant_ops.merchant_contacts "
            "WHERE merchant_id = %s",
            (merchant_id,),
        ),
        (
            "merchants",
            "DELETE FROM merchant_ops.merchants WHERE id = %s",
            (merchant_id,),
        ),
    )
    counts = {}

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                for name, query, parameters in deletions:
                    cursor.execute(query, parameters)
                    counts[name] = cursor.rowcount

    return counts
