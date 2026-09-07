"""Opt-in live lifecycle for the Checkpoint 8 alert read boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql
from psycopg.rows import dict_row

from claude.agents.tools.merchant.deadline_policy import (
    DeadlinePolicy,
)
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

BUSINESS_TABLES = (
    "merchants",
    "merchant_contacts",
    "projects",
    "project_steps",
    "project_step_dependencies",
    "document_revisions",
    "document_approvals",
    "procurement_records",
    "integration_identifiers",
    "project_events",
    "alert_deliveries",
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_LIVE_TESTS=1 to run the "
        "Checkpoint 8 test-database alert lifecycle"
    ),
)
def test_checkpoint_8_alert_read_live_lifecycle():
    """Prove global filters, determinism, no delivery, and cleanup."""

    config = RepositoryConfig.from_env("test")
    assert config.database == TEST_DATABASE
    assert config.database.endswith("_test")
    assert config.user == "merchant_test"
    assert config.host == "127.0.0.1"
    assert config.port == 5434

    repository = MerchantRepository(config)
    identifiers = _temporary_identifiers()
    business_date = DeadlinePolicy().resolve_business_date()
    checks: dict[str, bool] = {}
    observations: dict[str, Any] = {}
    cleanup_counts: dict[str, int] = {}

    try:
        identity = _database_identity(repository)
        initial_counts = _business_counts(repository)

        assert identity == {
            "database": TEST_DATABASE,
            "user": "merchant_test",
            "read_only": "on",
        }
        assert all(
            count == 0
            for count in initial_counts.values()
        ), "Merchant test database must be empty before lifecycle"

        _insert_temporary_alert_projects(
            repository,
            identifiers,
            business_date=business_date,
        )
        state_before_reads = _temporary_state(
            repository,
            identifiers,
        )

        global_first = _successful_cli(
            "--database",
            "test",
            "project",
            "alerts",
        )
        global_second = _successful_cli(
            "--database",
            "test",
            "project",
            "alerts",
        )
        merchant_filtered = _successful_cli(
            "--database",
            "test",
            "project",
            "alerts",
            "--merchant-id",
            str(identifiers["target_merchant_id"]),
        )
        project_filtered = _successful_cli(
            "--database",
            "test",
            "project",
            "alerts",
            "--project-id",
            str(identifiers["target_project_id"]),
        )
        legacy_project = _successful_cli(
            "--database",
            "test",
            "project",
            "alerts",
            str(identifiers["target_project_id"]),
        )
        overdue_only = _successful_cli(
            "--database",
            "test",
            "project",
            "alerts",
            "--project-id",
            str(identifiers["target_project_id"]),
            "--alert-type",
            "overdue",
        )
        due_before = _successful_cli(
            "--database",
            "test",
            "project",
            "alerts",
            "--project-id",
            str(identifiers["target_project_id"]),
            "--due-date-before",
            business_date.isoformat(),
        )
        combined_filters = _successful_cli(
            "--database",
            "test",
            "project",
            "alerts",
            "--merchant-id",
            str(identifiers["target_merchant_id"]),
            "--project-id",
            str(identifiers["target_project_id"]),
            "--alert-type",
            "due_soon",
        )

        state_after_reads = _temporary_state(
            repository,
            identifiers,
        )
        target_project_id = str(
            identifiers["target_project_id"]
        )
        other_project_id = str(
            identifiers["other_project_id"]
        )
        global_projects = Counter(
            alert["project_id"] for alert in global_first
        )
        target_alert_types = Counter(
            alert["alert_type"] for alert in project_filtered
        )

        checks = {
            "correct_test_database": (
                identity["database"] == TEST_DATABASE
            ),
            "correct_test_user": (
                identity["user"] == "merchant_test"
            ),
            "read_only_connection_verified": (
                identity["read_only"] == "on"
            ),
            "database_was_empty": all(
                count == 0
                for count in initial_counts.values()
            ),
            "global_query_is_deterministic": (
                global_first == global_second
            ),
            "global_query_found_both_projects": (
                global_projects
                == Counter(
                    {
                        target_project_id: 3,
                        other_project_id: 1,
                    }
                )
            ),
            "target_alert_types_are_exact": (
                target_alert_types
                == Counter(
                    {
                        "OVERDUE": 1,
                        "BLOCKED": 1,
                        "DUE_SOON": 1,
                    }
                )
            ),
            "merchant_filter_is_exact": (
                merchant_filtered == project_filtered
            ),
            "project_filter_is_exact": (
                len(project_filtered) == 3
                and all(
                    alert["project_id"] == target_project_id
                    for alert in project_filtered
                )
            ),
            "legacy_project_syntax_is_compatible": (
                legacy_project == project_filtered
            ),
            "alert_type_filter_is_exact": (
                len(overdue_only) == 1
                and overdue_only[0]["alert_type"] == "OVERDUE"
                and overdue_only[0]["project_id"]
                == target_project_id
            ),
            "due_date_filter_is_inclusive": (
                len(due_before) == 1
                and due_before[0]["alert_type"] == "OVERDUE"
                and due_before[0]["business_due_date"]
                == (business_date - timedelta(days=1)).isoformat()
            ),
            "combined_filters_are_exact": (
                len(combined_filters) == 1
                and combined_filters[0]["alert_type"]
                == "DUE_SOON"
                and combined_filters[0]["project_id"]
                == target_project_id
            ),
            "alert_reads_changed_no_workflow_state": (
                state_after_reads == state_before_reads
            ),
            "alert_reads_created_no_deliveries": (
                state_after_reads["alert_delivery_count"] == 0
            ),
            "alert_reads_created_no_events": (
                state_after_reads["project_event_count"] == 0
            ),
        }
        observations = {
            "database": identity,
            "business_date": business_date,
            "initial_business_counts": initial_counts,
            "global_alert_count": len(global_first),
            "global_project_counts": dict(global_projects),
            "target_alert_type_counts": dict(target_alert_types),
            "state_before_reads": state_before_reads,
            "state_after_reads": state_after_reads,
        }
    finally:
        cleanup_counts = _cleanup_temporary_records(
            repository,
            identifiers,
        )

    final_counts = _business_counts(repository)
    expected_cleanup_counts = {
        "alert_deliveries": 0,
        "integration_identifiers": 0,
        "document_approvals": 0,
        "document_revisions": 0,
        "procurement_records": 0,
        "project_events": 0,
        "project_step_dependencies": 0,
        "project_steps": 3,
        "projects": 2,
        "merchant_contacts": 0,
        "merchants": 2,
        "workflow_template_dependencies": 0,
        "workflow_template_steps": 3,
        "workflow_templates": 1,
    }
    checks["only_expected_records_were_cleaned"] = (
        cleanup_counts == expected_cleanup_counts
    )
    checks["database_is_empty_after_cleanup"] = all(
        count == 0 for count in final_counts.values()
    )
    observations["cleanup_counts"] = cleanup_counts
    observations["final_business_counts"] = final_counts

    report = {
        "success": all(checks.values()),
        "checks": checks,
        "observations": observations,
    }
    print(json.dumps(report, indent=2, default=str))
    failed_checks = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    assert report["success"], (
        "Checkpoint 8 alert lifecycle failed: "
        + ", ".join(failed_checks)
    )


def _temporary_identifiers() -> dict[str, uuid.UUID]:
    return {
        "target_merchant_id": uuid.uuid4(),
        "other_merchant_id": uuid.uuid4(),
        "template_id": uuid.uuid4(),
        "overdue_template_step_id": uuid.uuid4(),
        "blocked_template_step_id": uuid.uuid4(),
        "other_template_step_id": uuid.uuid4(),
        "target_project_id": uuid.uuid4(),
        "other_project_id": uuid.uuid4(),
        "overdue_step_id": uuid.uuid4(),
        "blocked_step_id": uuid.uuid4(),
        "other_step_id": uuid.uuid4(),
    }


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


def _business_counts(
    repository: MerchantRepository,
) -> dict[str, int]:
    counts = {}

    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                for table in BUSINESS_TABLES:
                    cursor.execute(
                        sql.SQL(
                            "SELECT COUNT(*) AS count "
                            "FROM merchant_ops.{}"
                        ).format(sql.Identifier(table))
                    )
                    counts[table] = int(
                        cursor.fetchone()["count"]
                    )

    return counts


def _insert_temporary_alert_projects(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
    *,
    business_date,
) -> None:
    token = identifiers["template_id"].hex[:12].upper()
    template_name = f"LIVE_ALERT_READ_{token}"

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO merchant_ops.merchants (
                        id,
                        code,
                        name,
                        account_status,
                        version
                    )
                    VALUES (%s, %s, %s, 'ACTIVE', 1)
                    """,
                    (
                        (
                            identifiers["target_merchant_id"],
                            f"ALERT_TARGET_{token}",
                            "Fictitious alert target merchant",
                        ),
                        (
                            identifiers["other_merchant_id"],
                            f"ALERT_OTHER_{token}",
                            "Fictitious alert comparison merchant",
                        ),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.workflow_templates (
                        id,
                        name,
                        version,
                        description,
                        variant,
                        is_active
                    )
                    VALUES (%s, %s, 1, %s, %s, TRUE)
                    """,
                    (
                        identifiers["template_id"],
                        template_name,
                        "Fictitious Checkpoint 8 alert lifecycle",
                        template_name,
                    ),
                )
                cursor.executemany(
                    """
                    INSERT INTO
                        merchant_ops.workflow_template_steps (
                            id,
                            template_id,
                            sequence_number,
                            branch_key,
                            step_type,
                            name,
                            is_optional
                        )
                    VALUES (%s, %s, %s, %s, 'SEQUENTIAL', %s, FALSE)
                    """,
                    (
                        (
                            identifiers["overdue_template_step_id"],
                            identifiers["template_id"],
                            1,
                            "target_overdue",
                            "Fictitious overdue step",
                        ),
                        (
                            identifiers["blocked_template_step_id"],
                            identifiers["template_id"],
                            2,
                            "target_blocked",
                            "Fictitious blocked step",
                        ),
                        (
                            identifiers["other_template_step_id"],
                            identifiers["template_id"],
                            3,
                            "other_due_soon",
                            "Fictitious comparison step",
                        ),
                    ),
                )
                cursor.executemany(
                    """
                    INSERT INTO merchant_ops.projects (
                        id,
                        merchant_id,
                        project_type,
                        workflow_variant,
                        workflow_template_version_id,
                        title,
                        status,
                        requires_procurement,
                        version,
                        payment_period_number
                    )
                    VALUES (
                        %s, %s, 'MEDIA_TOP_UP', %s, %s, %s,
                        'IN_PROGRESS', FALSE, 1, 1
                    )
                    """,
                    (
                        (
                            identifiers["target_project_id"],
                            identifiers["target_merchant_id"],
                            template_name,
                            identifiers["template_id"],
                            "Fictitious target alert project",
                        ),
                        (
                            identifiers["other_project_id"],
                            identifiers["other_merchant_id"],
                            template_name,
                            identifiers["template_id"],
                            "Fictitious comparison alert project",
                        ),
                    ),
                )
                cursor.executemany(
                    """
                    INSERT INTO merchant_ops.project_steps (
                        id,
                        project_id,
                        template_step_id,
                        branch_key,
                        step_name,
                        status,
                        sequence_number,
                        scheduled_start,
                        scheduled_completion,
                        version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, 1
                    )
                    """,
                    (
                        (
                            identifiers["overdue_step_id"],
                            identifiers["target_project_id"],
                            identifiers["overdue_template_step_id"],
                            "target_overdue",
                            "Fictitious overdue step",
                            "READY",
                            1,
                            business_date - timedelta(days=5),
                            business_date - timedelta(days=1),
                        ),
                        (
                            identifiers["blocked_step_id"],
                            identifiers["target_project_id"],
                            identifiers["blocked_template_step_id"],
                            "target_blocked",
                            "Fictitious blocked step",
                            "BLOCKED",
                            2,
                            business_date,
                            business_date + timedelta(days=2),
                        ),
                        (
                            identifiers["other_step_id"],
                            identifiers["other_project_id"],
                            identifiers["other_template_step_id"],
                            "other_due_soon",
                            "Fictitious comparison step",
                            "READY",
                            3,
                            business_date,
                            business_date + timedelta(days=3),
                        ),
                    ),
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
    output = (
        completed.stdout
        if completed.returncode == 0
        else completed.stderr
    )

    assert output.strip(), (
        f"Merchant CLI returned no JSON; stderr={completed.stderr!r}"
    )

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise AssertionError(
            "Merchant CLI output was not one JSON document: "
            f"stdout={completed.stdout!r}, "
            f"stderr={completed.stderr!r}"
        ) from error

    return {
        "exit_code": completed.returncode,
        "payload": payload,
    }


def _successful_cli(*arguments: str) -> Any:
    result = _invoke_cli(*arguments)
    assert result["exit_code"] == 0, result["payload"]
    return result["payload"]


def _temporary_state(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, Any]:
    project_ids = (
        identifiers["target_project_id"],
        identifiers["other_project_id"],
    )

    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        merchant_id,
                        status,
                        version,
                        updated_at
                    FROM merchant_ops.projects
                    WHERE id = ANY(%s::uuid[])
                    ORDER BY id
                    """,
                    (list(project_ids),),
                )
                projects = [
                    dict(record) for record in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    SELECT
                        id,
                        project_id,
                        status,
                        scheduled_completion,
                        version,
                        updated_at
                    FROM merchant_ops.project_steps
                    WHERE project_id = ANY(%s::uuid[])
                    ORDER BY project_id, sequence_number, id
                    """,
                    (list(project_ids),),
                )
                steps = [
                    dict(record) for record in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM merchant_ops.project_events
                    WHERE project_id = ANY(%s::uuid[])
                    """,
                    (list(project_ids),),
                )
                project_event_count = int(
                    cursor.fetchone()["count"]
                )
                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM merchant_ops.alert_deliveries
                    WHERE project_id = ANY(%s::uuid[])
                    """,
                    (list(project_ids),),
                )
                alert_delivery_count = int(
                    cursor.fetchone()["count"]
                )

    return {
        "projects": projects,
        "steps": steps,
        "project_event_count": project_event_count,
        "alert_delivery_count": alert_delivery_count,
    }


def _cleanup_temporary_records(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, int]:
    merchant_ids = (
        identifiers["target_merchant_id"],
        identifiers["other_merchant_id"],
    )
    project_ids = (
        identifiers["target_project_id"],
        identifiers["other_project_id"],
    )
    template_id = identifiers["template_id"]
    deletions = (
        (
            "alert_deliveries",
            "DELETE FROM merchant_ops.alert_deliveries "
            "WHERE project_id = ANY(%s::uuid[])",
            (list(project_ids),),
        ),
        (
            "integration_identifiers",
            "DELETE FROM merchant_ops.integration_identifiers "
            "WHERE project_id = ANY(%s::uuid[]) "
            "OR merchant_id = ANY(%s::uuid[])",
            (list(project_ids), list(merchant_ids)),
        ),
        (
            "document_approvals",
            "DELETE FROM merchant_ops.document_approvals "
            "WHERE document_revision_id IN ("
            "SELECT id FROM merchant_ops.document_revisions "
            "WHERE project_id = ANY(%s::uuid[]))",
            (list(project_ids),),
        ),
        (
            "document_revisions",
            "DELETE FROM merchant_ops.document_revisions "
            "WHERE project_id = ANY(%s::uuid[])",
            (list(project_ids),),
        ),
        (
            "procurement_records",
            "DELETE FROM merchant_ops.procurement_records "
            "WHERE project_id = ANY(%s::uuid[])",
            (list(project_ids),),
        ),
        (
            "project_events",
            "DELETE FROM merchant_ops.project_events "
            "WHERE project_id = ANY(%s::uuid[]) "
            "OR merchant_id = ANY(%s::uuid[])",
            (list(project_ids), list(merchant_ids)),
        ),
        (
            "project_step_dependencies",
            "DELETE FROM merchant_ops.project_step_dependencies "
            "WHERE from_step_id IN ("
            "SELECT id FROM merchant_ops.project_steps "
            "WHERE project_id = ANY(%s::uuid[])) "
            "OR to_step_id IN ("
            "SELECT id FROM merchant_ops.project_steps "
            "WHERE project_id = ANY(%s::uuid[]))",
            (list(project_ids), list(project_ids)),
        ),
        (
            "project_steps",
            "DELETE FROM merchant_ops.project_steps "
            "WHERE project_id = ANY(%s::uuid[])",
            (list(project_ids),),
        ),
        (
            "projects",
            "DELETE FROM merchant_ops.projects "
            "WHERE id = ANY(%s::uuid[])",
            (list(project_ids),),
        ),
        (
            "merchant_contacts",
            "DELETE FROM merchant_ops.merchant_contacts "
            "WHERE merchant_id = ANY(%s::uuid[])",
            (list(merchant_ids),),
        ),
        (
            "merchants",
            "DELETE FROM merchant_ops.merchants "
            "WHERE id = ANY(%s::uuid[])",
            (list(merchant_ids),),
        ),
        (
            "workflow_template_dependencies",
            "DELETE FROM "
            "merchant_ops.workflow_template_dependencies "
            "WHERE from_step_id IN ("
            "SELECT id FROM merchant_ops.workflow_template_steps "
            "WHERE template_id = %s) "
            "OR to_step_id IN ("
            "SELECT id FROM merchant_ops.workflow_template_steps "
            "WHERE template_id = %s)",
            (template_id, template_id),
        ),
        (
            "workflow_template_steps",
            "DELETE FROM merchant_ops.workflow_template_steps "
            "WHERE template_id = %s",
            (template_id,),
        ),
        (
            "workflow_templates",
            "DELETE FROM merchant_ops.workflow_templates "
            "WHERE id = %s",
            (template_id,),
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
