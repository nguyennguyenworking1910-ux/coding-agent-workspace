"""Static tests for the initial Merchant schema migration."""

from __future__ import annotations

import re
from pathlib import Path

from claude.clients.merchant import migrate


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

MIGRATION_PATH = (
    REPOSITORY_ROOT
    / ".claude"
    / "clients"
    / "merchant"
    / "migrations"
    / "0001_initial_schema.sql"
)

EXPECTED_TABLES = {
    "merchants",
    "merchant_contacts",
    "workflow_templates",
    "workflow_template_steps",
    "workflow_template_dependencies",
    "projects",
    "project_steps",
    "project_step_dependencies",
    "document_revisions",
    "document_approvals",
    "procurement_records",
    "integration_identifiers",
    "project_events",
    "alert_deliveries",
}


def read_migration() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_runner_discovers_initial_migration():
    discovered = migrate._discover_migrations()

    matching = [
        migration
        for migration in discovered
        if migration[0] == 1
    ]

    assert len(matching) == 1
    assert matching[0][1] == "initial_schema"
    assert Path(matching[0][2]).resolve() == (
        MIGRATION_PATH.resolve()
    )


def test_migration_contains_expected_tables():
    migration_sql = read_migration()

    tables = set(
        re.findall(
            r"CREATE\s+TABLE\s+merchant_ops\.([a-z_]+)",
            migration_sql,
            flags=re.IGNORECASE,
        )
    )

    assert tables == EXPECTED_TABLES


def test_bootstrap_migration_table_is_not_recreated():
    migration_sql = read_migration()

    assert not re.search(
        r"CREATE\s+TABLE\s+"
        r"merchant_ops\.schema_migrations",
        migration_sql,
        flags=re.IGNORECASE,
    )


def test_migration_uses_uuid_and_timezone_aware_columns():
    migration_sql = read_migration().upper()

    assert " UUID" in migration_sql
    assert "TIMESTAMPTZ" in migration_sql
    assert "SCHEDULED_COMPLETION DATE" in migration_sql
    assert "BUSINESS_DUE_DATE DATE" in migration_sql


def test_alert_delivery_schema_supports_worker():
    migration_sql = read_migration()

    required_fragments = [
        "project_step_id UUID",
        "deduplication_key VARCHAR(255) NOT NULL",
        "delivery_attempt_count INT NOT NULL DEFAULT 0",
        "UNIQUE (\n            deduplication_key,\n"
        "            delivery_channel\n        )",
    ]

    for fragment in required_fragments:
        assert fragment in migration_sql


def test_migration_contains_required_constraints():
    migration_sql = read_migration()

    required_constraints = [
        "projects_status_check",
        "project_steps_status_check",
        "project_step_dependencies_no_self_check",
        "document_revisions_signing_check",
        "document_approvals_status_check",
        "integration_identifiers_scope_check",
        "project_events_valid_entity_check",
        "alert_deliveries_condition_check",
        "alert_deliveries_deduplication_unique",
    ]

    for constraint in required_constraints:
        assert constraint in migration_sql


def test_alert_role_has_required_non_pii_access():
    migration_sql = read_migration()

    alert_grants = re.findall(
        r"GRANT\b.*?\bTO\s+merchant_alert\s*;",
        migration_sql,
        flags=re.IGNORECASE | re.DOTALL,
    )

    combined_grants = "\n".join(alert_grants).lower()

    assert "projects" in combined_grants
    assert "project_steps" in combined_grants
    assert "document_revisions" in combined_grants
    assert "document_approvals" in combined_grants
    assert "procurement_records" in combined_grants
    assert "alert_deliveries" in combined_grants

    assert "merchant_contacts" not in combined_grants
    assert "integration_identifiers" not in combined_grants


def test_application_and_alert_roles_cannot_create_schema_objects():
    migration_sql = read_migration()

    assert not re.search(
        r"GRANT\s+CREATE.*?TO\s+merchant_app",
        migration_sql,
        flags=re.IGNORECASE | re.DOTALL,
    )

    assert not re.search(
        r"GRANT\s+CREATE.*?TO\s+merchant_alert",
        migration_sql,
        flags=re.IGNORECASE | re.DOTALL,
    )


def test_migration_contains_no_destructive_statements():
    migration_sql = read_migration()

    destructive_patterns = [
        r"\bDROP\s+TABLE\b",
        r"\bDROP\s+SCHEMA\b",
        r"\bTRUNCATE\b",
        r"\bDELETE\s+FROM\b",
    ]

    for pattern in destructive_patterns:
        assert not re.search(
            pattern,
            migration_sql,
            flags=re.IGNORECASE,
        )


def test_sql_splitter_parses_complete_migration():
    migration_sql = read_migration()

    statements = migrate._split_sql_statements(
        migration_sql
    )

    assert len(statements) >= 30

    assert any(
        "CREATE TABLE merchant_ops.merchants" in statement
        for statement in statements
    )
    assert any(
        "CREATE TABLE merchant_ops.alert_deliveries"
        in statement
        for statement in statements
    )
    assert any(
        "FOR UPDATE SKIP LOCKED" not in statement
        for statement in statements
    )


def test_migration_is_valid_utf8_and_has_stable_checksum():
    raw_bytes = MIGRATION_PATH.read_bytes()
    decoded = raw_bytes.decode("utf-8")

    assert decoded
    assert len(migrate._calculate_checksum(
        str(MIGRATION_PATH)
    )) == 64