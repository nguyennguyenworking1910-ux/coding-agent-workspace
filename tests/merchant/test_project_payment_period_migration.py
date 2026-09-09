"""Contract tests for Merchant migration 0002."""

from __future__ import annotations

import re
from pathlib import Path

from claude.clients.merchant.migrate import (
    _calculate_checksum,
    _discover_migrations,
    _split_sql_statements,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIRECTORY = (
    REPOSITORY_ROOT
    / ".claude"
    / "clients"
    / "merchant"
    / "migrations"
)

INITIAL_MIGRATION = (
    MIGRATIONS_DIRECTORY / "0001_initial_schema.sql"
)
PAYMENT_PERIOD_MIGRATION = (
    MIGRATIONS_DIRECTORY
    / "0002_add_project_payment_period.sql"
)

INITIAL_CHECKSUM = (
    "8ff45d352766953f18ec0378c74cc280"
    "571641d40bcf5f4e27c5bedc700e51f1"
)
PAYMENT_PERIOD_CHECKSUM = (
    "e7729b83ae1bbf121e0d94fd095ee4b0"
    "7e18092c72195653fd00c16b3c2fa666"
)


def migration_sql() -> str:
    return PAYMENT_PERIOD_MIGRATION.read_text(
        encoding="utf-8"
    )


def normalized_sql() -> str:
    return " ".join(migration_sql().split())


def test_applied_initial_migration_remains_frozen():
    assert _calculate_checksum(
        str(INITIAL_MIGRATION)
    ) == INITIAL_CHECKSUM


def test_payment_period_migration_checksum_is_frozen():
    assert _calculate_checksum(
        str(PAYMENT_PERIOD_MIGRATION)
    ) == PAYMENT_PERIOD_CHECKSUM


def test_migrations_are_discovered_in_version_order():
    migrations = _discover_migrations()

    assert [
        (version, description)
        for version, description, _ in migrations
    ] == [
        (1, "initial_schema"),
        (2, "add_project_payment_period"),
        (3, "add_cli_write_grants"),
        (4, "add_alert_delivery_leases"),
    ]


def test_migration_contains_two_projects_alterations():
    statements = _split_sql_statements(migration_sql())

    assert len(statements) == 2

    for statement in statements:
        assert re.match(
            r"^ALTER\s+TABLE\s+"
            r"merchant_ops\.projects\b",
            statement,
            flags=re.IGNORECASE,
        )


def test_migration_adds_payment_period_column():
    sql_text = normalized_sql()

    assert re.search(
        r"ADD\s+COLUMN\s+"
        r"payment_period_number\s+INTEGER",
        sql_text,
        flags=re.IGNORECASE,
    )


def test_scope_constraint_handles_null_explicitly():
    sql_text = normalized_sql()

    assert "projects_payment_period_scope_check" in sql_text
    assert "project_type = 'MEDIA_TOP_UP'" in sql_text
    assert "payment_period_number IS NOT NULL" in sql_text
    assert "payment_period_number >= 1" in sql_text
    assert "project_type <> 'MEDIA_TOP_UP'" in sql_text
    assert "payment_period_number IS NULL" in sql_text


def test_migration_has_no_data_or_destructive_statements():
    statements = _split_sql_statements(migration_sql())

    forbidden_pattern = re.compile(
        r"\b("
        r"DROP|TRUNCATE|DELETE|UPDATE|INSERT"
        r")\b",
        flags=re.IGNORECASE,
    )

    for statement in statements:
        assert forbidden_pattern.search(statement) is None
