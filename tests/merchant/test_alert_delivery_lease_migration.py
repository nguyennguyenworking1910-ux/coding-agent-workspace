"""Structural contract for Merchant migration 0004."""

from __future__ import annotations

import re
from pathlib import Path

from claude.clients.merchant.migrate import (
    _calculate_checksum,
    _discover_migrations,
    _split_sql_statements,
)
from claude.clients.merchant.runtime_readiness import (
    _local_migration_manifest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPOSITORY_ROOT
    / ".claude"
    / "clients"
    / "merchant"
    / "migrations"
    / "0004_add_alert_delivery_leases.sql"
)

MIGRATION_CHECKSUM = (
    "5d305951e7970d982f3d839bc0bb1363"
    "d96beb16312445b07cdbde777109e110"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def normalized_sql() -> str:
    return " ".join(migration_sql().split()).upper()


def test_alert_delivery_lease_migration_checksum_is_frozen():
    assert _calculate_checksum(str(MIGRATION)) == MIGRATION_CHECKSUM


def test_generic_runner_discovers_migrations_one_through_four():
    assert [
        (version, description)
        for version, description, _ in _discover_migrations()
    ] == [
        (1, "initial_schema"),
        (2, "add_project_payment_period"),
        (3, "add_cli_write_grants"),
        (4, "add_alert_delivery_leases"),
    ]


def test_checkpoint_9_readiness_remains_frozen_at_one_through_three():
    assert tuple(
        item["version"] for item in _local_migration_manifest()
    ) == (1, 2, 3)


def test_migration_adds_exact_claim_and_provider_columns():
    sql = normalized_sql()

    for column_definition in (
        "ADD COLUMN CLAIM_TOKEN UUID",
        "ADD COLUMN CLAIM_EXPIRES_AT TIMESTAMPTZ",
        "ADD COLUMN NEXT_ATTEMPT_AT TIMESTAMPTZ",
        "ADD COLUMN LAST_ATTEMPT_AT TIMESTAMPTZ",
        "ADD COLUMN PROVIDER_MESSAGE_ID VARCHAR(255)",
    ):
        assert column_definition in sql


def test_migration_adds_claimed_and_dead_letter_statuses():
    sql = normalized_sql()

    assert "DROP CONSTRAINT ALERT_DELIVERIES_STATUS_CHECK" in sql
    assert "'CLAIMED'" in sql
    assert "'DEAD_LETTER'" in sql
    assert "'ACKNOWLEDGED'" in sql


def test_claim_state_constraint_requires_complete_ownership():
    sql = normalized_sql()

    assert "ALERT_DELIVERIES_CLAIM_STATE_CHECK" in sql
    assert "DELIVERY_STATUS = 'CLAIMED'" in sql
    assert "CLAIM_TOKEN IS NOT NULL" in sql
    assert "CLAIM_EXPIRES_AT IS NOT NULL" in sql
    assert "LAST_ATTEMPT_AT IS NOT NULL" in sql
    assert "CLAIM_EXPIRES_AT > LAST_ATTEMPT_AT" in sql
    assert "DELIVERY_ATTEMPT_COUNT >= 1" in sql
    assert "DELIVERY_STATUS <> 'CLAIMED'" in sql
    assert "CLAIM_TOKEN IS NULL" in sql
    assert "CLAIM_EXPIRES_AT IS NULL" in sql


def test_retry_dead_letter_and_provider_constraints_are_present():
    sql = normalized_sql()

    assert "ALERT_DELIVERIES_NEXT_ATTEMPT_STATE_CHECK" in sql
    assert "DELIVERY_STATUS IN ('PENDING', 'FAILED')" in sql
    assert "ALERT_DELIVERIES_DEAD_LETTER_STATE_CHECK" in sql
    assert "ALERT_DELIVERIES_PROVIDER_MESSAGE_STATE_CHECK" in sql
    assert "DELIVERY_STATUS IN ('SENT', 'ACKNOWLEDGED')" in sql
    assert "CHAR_LENGTH(PROVIDER_MESSAGE_ID) BETWEEN 1 AND 255" in sql


def test_claim_index_is_replaced_with_lease_aware_order():
    sql = normalized_sql()

    assert "DROP INDEX MERCHANT_OPS.ALERT_DELIVERIES_CLAIM_IDX" in sql
    assert "CREATE INDEX ALERT_DELIVERIES_CLAIM_IDX" in sql
    assert re.search(
        r"DELIVERY_CHANNEL, DELIVERY_STATUS, NEXT_ATTEMPT_AT, "
        r"CLAIM_EXPIRES_AT, CREATED_AT, ID",
        sql,
    )


def test_migration_only_backfills_alert_coordination_state():
    statements = _split_sql_statements(migration_sql())

    assert len(statements) == 5
    assert sum(
        statement.lstrip().upper().startswith("UPDATE ")
        for statement in statements
    ) == 1
    assert "UPDATE MERCHANT_OPS.ALERT_DELIVERIES" in normalized_sql()
    assert "SET LAST_ATTEMPT_AT = UPDATED_AT" in normalized_sql()
    assert re.search(r"\b(INSERT|DELETE|TRUNCATE)\b", normalized_sql()) is None
    assert "MERCHANT_OPS.MERCHANTS" not in normalized_sql()
    assert "MERCHANT_OPS.PROJECTS" not in normalized_sql()
    assert "MERCHANT_OPS.PROJECT_EVENTS" not in normalized_sql()
