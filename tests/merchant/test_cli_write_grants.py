"""Structural tests for least-privilege Merchant CLI grants."""

from pathlib import Path

from claude.clients.merchant.migrate import (
    _calculate_checksum,
)


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "clients"
    / "merchant"
    / "migrations"
    / "0003_add_cli_write_grants.sql"
)
MIGRATION_CHECKSUM = (
    "209179ad284a62b9c3d47558bf4cd5093"
    "389d693559af3855257ae9c02439575"
)


def test_cli_write_migration_checksum_is_frozen():
    assert _calculate_checksum(str(MIGRATION)) == (
        MIGRATION_CHECKSUM
    )


def test_cli_write_grants_are_narrow_and_complete():
    sql = MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(sql.split()).upper()

    for table in (
        "MERCHANT_OPS.MERCHANTS",
        "MERCHANT_OPS.MERCHANT_CONTACTS",
        "MERCHANT_OPS.PROJECT_STEP_DEPENDENCIES",
        "MERCHANT_OPS.DOCUMENT_REVISIONS",
        "MERCHANT_OPS.INTEGRATION_IDENTIFIERS",
    ):
        assert table in normalized

    assert "TO MERCHANT_APP" in normalized
    assert "UPDATE (UPDATED_AT, VERSION)" in normalized
    assert "UPDATE (SUPERSEDED_BY)" in normalized
    assert "IDENTIFIER_VALUE" in normalized
    assert "IS_ACTIVE" in normalized
    assert "DELETE" not in normalized
    assert "TRUNCATE" not in normalized
    assert "DROP" not in normalized
    assert "MERCHANT_OWNER" not in normalized


def test_identifier_binding_has_null_safe_uniqueness():
    sql = MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(sql.split()).upper()

    assert (
        "CREATE UNIQUE INDEX "
        "INTEGRATION_IDENTIFIERS_BINDING_UNIQUE_IDX"
    ) in normalized
    assert (
        "MERCHANT_ID, PROJECT_ID, IDENTIFIER_TYPE, SCOPE"
    ) in normalized
    assert "NULLS NOT DISTINCT" in normalized


def test_uat_and_production_values_cannot_collide():
    sql = MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(sql.split()).upper()

    assert (
        "CREATE UNIQUE INDEX "
        "INTEGRATION_IDENTIFIERS_ENVIRONMENT_VALUE_UNIQUE_IDX"
    ) in normalized
    assert "IDENTIFIER_TYPE, IDENTIFIER_VALUE" in normalized
    assert "WHERE SCOPE IN ('UAT', 'PRODUCTION')" in normalized


def test_procurement_type_is_unique_per_project():
    sql = MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(sql.split()).upper()

    assert (
        "CREATE UNIQUE INDEX "
        "PROCUREMENT_RECORDS_PROJECT_TYPE_UNIQUE_IDX"
    ) in normalized
    assert "PROJECT_ID, PROCUREMENT_TYPE" in normalized
