"""Opt-in read-only verification after Gate 9.4 migrations."""

from __future__ import annotations

import json
import os

import pytest

from claude.agents.tools.merchant.catalog_contract import (
    load_private_catalog,
)
from claude.clients.merchant import migrate
from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
)
from claude.clients.merchant.runtime_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS,
    EXPECTED_PENDING_MIGRATIONS,
)
from claude.clients.merchant.runtime_readiness import (
    BUSINESS_TABLES,
    TEMPLATE_INITIALIZATION_READY,
    check_runtime_readiness,
    inspect_runtime_backup,
)


LIVE_VERIFICATION_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_RUNTIME_MIGRATION_VERIFICATION",
        "",
    ).strip()
    == "1"
)

EXPECTED_INDEXES = frozenset(
    {
        "integration_identifiers_binding_unique_idx",
        "integration_identifiers_environment_value_unique_idx",
        "procurement_records_project_type_unique_idx",
    }
)
EXPECTED_INSERT_TABLES = frozenset(
    {
        "merchants",
        "merchant_contacts",
        "project_step_dependencies",
        "document_revisions",
        "integration_identifiers",
    }
)
EXPECTED_COLUMN_UPDATES = frozenset(
    {
        ("merchants", "updated_at"),
        ("merchants", "version"),
        ("document_revisions", "superseded_by"),
        ("integration_identifiers", "identifier_value"),
        ("integration_identifiers", "is_active"),
        ("integration_identifiers", "updated_at"),
        ("integration_identifiers", "version"),
    }
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_VERIFICATION_ENABLED,
    reason=(
        "Set MERCHANT_RUN_RUNTIME_MIGRATION_VERIFICATION=1 "
        "for the read-only Gate 9.4 verification"
    ),
)
def test_checkpoint_9_runtime_migrations_are_exact():
    source_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SOURCE_SHA256"
    )
    catalog_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SHA256"
    )
    catalog = load_private_catalog(
        _required_environment("MERCHANT_PRIVATE_CATALOG_PATH")
    )

    assert catalog.source_sha256 == source_hash
    assert catalog.catalog_sha256 == catalog_hash

    backup = inspect_runtime_backup(
        _required_environment("MERCHANT_RUNTIME_BACKUP_FILE"),
        restore_list_verified=_required_flag(
            "MERCHANT_RUNTIME_BACKUP_LIST_VERIFIED"
        ),
        recovery_procedure_reviewed=_required_flag(
            "MERCHANT_RUNTIME_RECOVERY_REVIEWED"
        ),
        roles_recoverable=_required_flag(
            "MERCHANT_RUNTIME_ROLES_RECOVERABLE"
        ),
    )
    repository = MerchantRepository(
        RepositoryConfig.from_env("app")
    )
    readiness = check_runtime_readiness(
        repository,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
        backup_evidence=backup,
    )
    status = migrate.get_status(
        repository.config.host,
        repository.config.port,
        repository.config.database,
        repository.config.user,
        repository.config.password,
    )
    schema = _migration_schema_evidence(repository)

    expected_migrations = (
        *EXPECTED_APPLIED_MIGRATIONS,
        *EXPECTED_PENDING_MIGRATIONS,
    )
    expected_checksums = {
        item.version: item.checksum
        for item in expected_migrations
    }
    applied_checksums = {
        int(item["version"]): str(item["checksum"])
        for item in status["applied_migrations"]
    }

    checks = {
        "readiness_success": readiness.success is True,
        "template_initialization_is_next": (
            readiness.state == TEMPLATE_INITIALIZATION_READY
        ),
        "migrations_exact": (
            readiness.applied_versions == (1, 2, 3)
            and readiness.pending_versions == ()
            and status.get("success") is True
            and status.get("pending_migrations") == []
            and applied_checksums == expected_checksums
        ),
        "application_read_only": (
            schema["identity"]
            == {
                "database": "coding_agent_merchant",
                "user": "merchant_app",
                "read_only": "on",
                "encoding": "UTF8",
            }
        ),
        "payment_period_column_exact": (
            schema["payment_period_column"]
            == {
                "data_type": "integer",
                "is_nullable": "YES",
            }
        ),
        "payment_period_constraint_exact": (
            _payment_constraint_is_exact(
                schema["payment_period_constraint"]
            )
        ),
        "unique_indexes_exact": (
            schema["unique_indexes"] == EXPECTED_INDEXES
        ),
        "insert_grants_exact": (
            schema["insert_tables"] == EXPECTED_INSERT_TABLES
        ),
        "column_update_grants_exact": (
            schema["column_updates"]
            == EXPECTED_COLUMN_UPDATES
        ),
        "business_tables_empty": (
            set(readiness.business_counts) == set(BUSINESS_TABLES)
            and all(
                count == 0
                for count in readiness.business_counts.values()
            )
        ),
        "standard_templates_unchanged": (
            readiness.stored_template_count == 0
        ),
    }
    summary = {
        "success": all(checks.values()),
        "state": readiness.state,
        "checks": checks,
        "applied_versions": list(readiness.applied_versions),
        "pending_versions": list(readiness.pending_versions),
        "business_counts": dict(readiness.business_counts),
        "stored_template_count": readiness.stored_template_count,
        "backup_sha256": backup.backup_sha256,
    }

    print(json.dumps(summary, indent=2))
    assert summary["success"], (
        "Runtime migration verification failed: "
        + ", ".join(
            name for name, passed in checks.items() if not passed
        )
    )


def _migration_schema_evidence(
    repository: MerchantRepository,
) -> dict[str, object]:
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        current_database() AS database,
                        current_user AS user,
                        current_setting(
                            'transaction_read_only'
                        ) AS read_only,
                        current_setting(
                            'server_encoding'
                        ) AS encoding
                    """,
                    (),
                )
                identity = dict(cursor.fetchone())

                cursor.execute(
                    """
                    SELECT data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = %s
                    """,
                    (
                        "merchant_ops",
                        "projects",
                        "payment_period_number",
                    ),
                )
                column_row = cursor.fetchone()
                payment_period_column = (
                    dict(column_row) if column_row else None
                )

                cursor.execute(
                    """
                    SELECT pg_get_constraintdef(
                        constraint_record.oid
                    ) AS definition
                    FROM pg_catalog.pg_constraint
                        AS constraint_record
                    JOIN pg_catalog.pg_class AS table_record
                      ON table_record.oid =
                         constraint_record.conrelid
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = table_record.relnamespace
                    WHERE namespace.nspname = %s
                      AND table_record.relname = %s
                      AND constraint_record.conname = %s
                    """,
                    (
                        "merchant_ops",
                        "projects",
                        "projects_payment_period_scope_check",
                    ),
                )
                constraint_row = cursor.fetchone()
                payment_period_constraint = (
                    str(constraint_row["definition"])
                    if constraint_row
                    else ""
                )

                cursor.execute(
                    """
                    SELECT index_record.relname AS index_name
                    FROM pg_catalog.pg_index AS index_metadata
                    JOIN pg_catalog.pg_class AS index_record
                      ON index_record.oid =
                         index_metadata.indexrelid
                    JOIN pg_catalog.pg_class AS table_record
                      ON table_record.oid =
                         index_metadata.indrelid
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = table_record.relnamespace
                    WHERE namespace.nspname = %s
                      AND index_record.relname = ANY(%s)
                      AND index_metadata.indisunique IS TRUE
                    ORDER BY index_record.relname
                    """,
                    ("merchant_ops", list(EXPECTED_INDEXES)),
                )
                unique_indexes = frozenset(
                    str(row["index_name"])
                    for row in cursor.fetchall()
                )

                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.table_privileges
                    WHERE table_schema = %s
                      AND grantee = %s
                      AND privilege_type = 'INSERT'
                      AND table_name = ANY(%s)
                    ORDER BY table_name
                    """,
                    (
                        "merchant_ops",
                        "merchant_app",
                        list(EXPECTED_INSERT_TABLES),
                    ),
                )
                insert_tables = frozenset(
                    str(row["table_name"])
                    for row in cursor.fetchall()
                )

                cursor.execute(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.column_privileges
                    WHERE table_schema = %s
                      AND grantee = %s
                      AND privilege_type = 'UPDATE'
                      AND table_name = ANY(%s)
                    ORDER BY table_name, column_name
                    """,
                    (
                        "merchant_ops",
                        "merchant_app",
                        [
                            "merchants",
                            "document_revisions",
                            "integration_identifiers",
                        ],
                    ),
                )
                column_updates = frozenset(
                    (
                        str(row["table_name"]),
                        str(row["column_name"]),
                    )
                    for row in cursor.fetchall()
                )

    return {
        "identity": identity,
        "payment_period_column": payment_period_column,
        "payment_period_constraint": payment_period_constraint,
        "unique_indexes": unique_indexes,
        "insert_tables": insert_tables,
        "column_updates": column_updates,
    }


def _payment_constraint_is_exact(definition: object) -> bool:
    normalized = " ".join(str(definition).upper().split())
    return all(
        fragment in normalized
        for fragment in (
            "CHECK",
            "PROJECT_TYPE",
            "MEDIA_TOP_UP",
            "PAYMENT_PERIOD_NUMBER IS NOT NULL",
            "PAYMENT_PERIOD_NUMBER >= 1",
            "PAYMENT_PERIOD_NUMBER IS NULL",
        )
    )


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()

    if not value:
        raise AssertionError(f"Missing required environment: {name}")

    return value


def _required_flag(name: str) -> bool:
    value = _required_environment(name)

    if value != "1":
        raise AssertionError(f"{name} must be exactly 1")

    return True
