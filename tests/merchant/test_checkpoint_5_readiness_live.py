"""Opt-in read-only readiness proof for Merchant Checkpoint 5."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql
from psycopg.rows import dict_row

from claude.agents.tools.merchant.workflow_templates import (
    standard_template_manifest,
)
from claude.clients.merchant.migrate import (
    _calculate_checksum,
    _discover_migrations,
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

REQUIRED_INDEXES = {
    "integration_identifiers_binding_unique_idx",
    "integration_identifiers_environment_value_unique_idx",
    "procurement_records_project_type_unique_idx",
}

REQUIRED_WRITE_PRIVILEGES = {
    "insert_merchants",
    "insert_merchant_contacts",
    "insert_project_step_dependencies",
    "insert_document_revisions",
    "insert_integration_identifiers",
    "update_merchants_updated_at",
    "update_merchants_version",
    "update_document_revisions_superseded_by",
    "update_identifiers_identifier_value",
    "update_identifiers_is_active",
    "update_identifiers_updated_at",
    "update_identifiers_version",
}

FORBIDDEN_WRITE_PRIVILEGES = {
    "delete_merchants",
    "delete_merchant_contacts",
    "delete_document_revisions",
    "delete_integration_identifiers",
    "table_update_merchant_contacts",
    "table_update_integration_identifiers",
}


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_LIVE_TESTS=1 to run the "
        "Merchant test-database readiness proof"
    ),
)
def test_checkpoint_5_read_only_readiness():
    """Prove migrations, empty state, templates, indexes, and grants."""

    config = RepositoryConfig.from_env("test")
    assert config.database == TEST_DATABASE
    assert config.database.endswith("_test")
    assert config.user == "merchant_test"
    assert config.host == "127.0.0.1"
    assert config.port == 5434

    repository = MerchantRepository(config)
    local_migrations = _local_migration_manifest()

    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                identity = _database_identity(cursor)
                applied_migrations = _applied_migrations(cursor)
                business_counts = _business_counts(cursor)
                stored_templates = _stored_template_manifest(cursor)
                indexes = _required_indexes(cursor)
                write_privileges = _write_privileges(cursor)

    local_by_version = {
        migration["version"]: migration
        for migration in local_migrations
    }
    applied_by_version = {
        migration["version"]: migration
        for migration in applied_migrations
    }
    local_versions = sorted(local_by_version)
    applied_versions = [
        migration["version"]
        for migration in applied_migrations
    ]
    pending_versions = sorted(
        set(local_by_version) - set(applied_by_version)
    )
    missing_local_versions = sorted(
        set(applied_by_version) - set(local_by_version)
    )
    checksum_conflicts = sorted(
        version
        for version in set(local_by_version) & set(applied_by_version)
        if local_by_version[version]["checksum"]
        != applied_by_version[version]["checksum"]
    )
    description_conflicts = sorted(
        version
        for version in set(local_by_version) & set(applied_by_version)
        if local_by_version[version]["description"]
        != applied_by_version[version]["description"]
    )

    expected_templates = _expected_stored_template_manifest()
    index_by_name = {
        index["indexname"]: index["indexdef"]
        for index in indexes
    }
    required_privileges = {
        name: bool(write_privileges[name])
        for name in sorted(REQUIRED_WRITE_PRIVILEGES)
    }
    forbidden_privileges = {
        name: bool(write_privileges[name])
        for name in sorted(FORBIDDEN_WRITE_PRIVILEGES)
    }
    checks = {
        "correct_test_database": identity["database"]
        == TEST_DATABASE,
        "correct_test_user": identity["user"] == "merchant_test",
        "read_only_enforced": identity["read_only"] == "on",
        "migration_versions_match_local": applied_versions
        == local_versions,
        "no_pending_migrations": not pending_versions,
        "no_missing_local_migrations": not missing_local_versions,
        "no_checksum_conflicts": not checksum_conflicts,
        "no_description_conflicts": not description_conflicts,
        "business_state_is_empty": all(
            count == 0
            for count in business_counts.values()
        ),
        "standard_templates_match": stored_templates
        == expected_templates,
        "migration_3_indexes_present": set(index_by_name)
        == REQUIRED_INDEXES,
        "migration_3_indexes_are_unique": all(
            "CREATE UNIQUE INDEX" in definition.upper()
            for definition in index_by_name.values()
        ),
        "identifier_binding_is_null_safe": (
            "NULLS NOT DISTINCT"
            in index_by_name.get(
                "integration_identifiers_binding_unique_idx",
                "",
            ).upper()
        ),
        "environment_identifier_index_is_partial": (
            " WHERE "
            in index_by_name.get(
                "integration_identifiers_environment_value_unique_idx",
                "",
            ).upper()
        ),
        "required_cli_write_privileges_present": all(
            required_privileges.values()
        ),
        "forbidden_cli_write_privileges_absent": not any(
            forbidden_privileges.values()
        ),
    }
    report = {
        "success": all(checks.values()),
        "checks": checks,
        "database": identity,
        "applied_versions": applied_versions,
        "local_versions": local_versions,
        "pending_versions": pending_versions,
        "missing_local_versions": missing_local_versions,
        "checksum_conflicts": checksum_conflicts,
        "description_conflicts": description_conflicts,
        "business_counts": business_counts,
        "standard_template_count": len(stored_templates),
        "standard_template_manifest": standard_template_manifest(),
        "stored_template_manifest": stored_templates,
        "migration_3_indexes": indexes,
        "required_write_privileges": required_privileges,
        "forbidden_write_privileges": forbidden_privileges,
    }

    print(json.dumps(report, indent=2, default=str))
    failed_checks = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    assert report["success"], (
        "Checkpoint 5 readiness failed: "
        + ", ".join(failed_checks)
    )


def _local_migration_manifest() -> list[dict[str, Any]]:
    return [
        {
            "version": version,
            "description": description,
            "checksum": _calculate_checksum(path),
            "path": str(Path(path).name),
        }
        for version, description, path in _discover_migrations()
    ]


def _database_identity(cursor: Any) -> dict[str, Any]:
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


def _applied_migrations(cursor: Any) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            version,
            description,
            checksum,
            executed_at,
            execution_time_ms
        FROM merchant_ops.schema_migrations
        ORDER BY version
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def _business_counts(cursor: Any) -> dict[str, int]:
    counts = {}

    for table in BUSINESS_TABLES:
        cursor.execute(
            sql.SQL(
                "SELECT COUNT(*) AS count FROM merchant_ops.{}"
            ).format(sql.Identifier(table))
        )
        counts[table] = int(cursor.fetchone()["count"])

    return counts


def _stored_template_manifest(
    cursor: Any,
) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            template.id AS template_id,
            template.name,
            template.version,
            template.variant,
            COUNT(DISTINCT step.id) AS step_count,
            (
                SELECT COUNT(*)
                FROM merchant_ops.workflow_template_dependencies
                    AS dependency
                JOIN merchant_ops.workflow_template_steps
                    AS source_step
                  ON source_step.id = dependency.from_step_id
                WHERE source_step.template_id = template.id
            ) AS dependency_count
        FROM merchant_ops.workflow_templates AS template
        LEFT JOIN merchant_ops.workflow_template_steps AS step
          ON step.template_id = template.id
        GROUP BY
            template.id,
            template.name,
            template.version,
            template.variant
        ORDER BY template.name, template.version
        """
    )
    return sorted(
        (
            {
                "template_id": str(row["template_id"]),
                "name": row["name"],
                "version": int(row["version"]),
                "variant": row["variant"],
                "step_count": int(row["step_count"]),
                "dependency_count": int(row["dependency_count"]),
            }
            for row in cursor.fetchall()
        ),
        key=lambda item: (item["name"], item["version"]),
    )


def _expected_stored_template_manifest() -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "template_id": item["template_id"],
                "name": item["name"],
                "version": item["version"],
                "variant": item["variant"],
                "step_count": item["step_count"],
                "dependency_count": item["dependency_count"],
            }
            for item in standard_template_manifest()
        ),
        key=lambda item: (item["name"], item["version"]),
    )


def _required_indexes(cursor: Any) -> list[dict[str, str]]:
    cursor.execute(
        """
        SELECT indexname, indexdef
        FROM pg_catalog.pg_indexes
        WHERE schemaname = 'merchant_ops'
          AND indexname = ANY(%s)
        ORDER BY indexname
        """,
        (sorted(REQUIRED_INDEXES),),
    )
    return [dict(row) for row in cursor.fetchall()]


def _write_privileges(cursor: Any) -> dict[str, bool]:
    cursor.execute(
        """
        SELECT
            has_table_privilege(
                'merchant_app',
                'merchant_ops.merchants',
                'INSERT'
            ) AS insert_merchants,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.merchant_contacts',
                'INSERT'
            ) AS insert_merchant_contacts,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.project_step_dependencies',
                'INSERT'
            ) AS insert_project_step_dependencies,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.document_revisions',
                'INSERT'
            ) AS insert_document_revisions,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.integration_identifiers',
                'INSERT'
            ) AS insert_integration_identifiers,
            has_column_privilege(
                'merchant_app',
                'merchant_ops.merchants',
                'updated_at',
                'UPDATE'
            ) AS update_merchants_updated_at,
            has_column_privilege(
                'merchant_app',
                'merchant_ops.merchants',
                'version',
                'UPDATE'
            ) AS update_merchants_version,
            has_column_privilege(
                'merchant_app',
                'merchant_ops.document_revisions',
                'superseded_by',
                'UPDATE'
            ) AS update_document_revisions_superseded_by,
            has_column_privilege(
                'merchant_app',
                'merchant_ops.integration_identifiers',
                'identifier_value',
                'UPDATE'
            ) AS update_identifiers_identifier_value,
            has_column_privilege(
                'merchant_app',
                'merchant_ops.integration_identifiers',
                'is_active',
                'UPDATE'
            ) AS update_identifiers_is_active,
            has_column_privilege(
                'merchant_app',
                'merchant_ops.integration_identifiers',
                'updated_at',
                'UPDATE'
            ) AS update_identifiers_updated_at,
            has_column_privilege(
                'merchant_app',
                'merchant_ops.integration_identifiers',
                'version',
                'UPDATE'
            ) AS update_identifiers_version,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.merchants',
                'DELETE'
            ) AS delete_merchants,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.merchant_contacts',
                'DELETE'
            ) AS delete_merchant_contacts,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.document_revisions',
                'DELETE'
            ) AS delete_document_revisions,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.integration_identifiers',
                'DELETE'
            ) AS delete_integration_identifiers,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.merchant_contacts',
                'UPDATE'
            ) AS table_update_merchant_contacts,
            has_table_privilege(
                'merchant_app',
                'merchant_ops.integration_identifiers',
                'UPDATE'
            ) AS table_update_integration_identifiers
        """
    )
    return {
        key: bool(value)
        for key, value in dict(cursor.fetchone()).items()
    }
