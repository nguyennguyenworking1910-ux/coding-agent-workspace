"""CP12H.MASTER: migration 010 (operator-recorded decisions, operator-attested
signing) on the Merchant test database.

Every test runs inside one transaction that is always rolled back (the
NL4D5A1b fixtures). Must run alone (never concurrently with another
PostgreSQL test process).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from claude.clients.merchant.migrate import _calculate_checksum, _split_sql_statements
from tests.merchant.test_direct_execute_end_to_end import TEST_DB_CONFIGURED
from tests.merchant.test_nl4d5a1b_migration_008_postgres import insert_revision, refused, rolled_back

pytestmark = pytest.mark.skipif(not TEST_DB_CONFIGURED, reason="Merchant test database not configured")

MIGRATION = Path(".claude/clients/merchant/migrations/010_operator_attested_lifecycle.sql")
OPERATOR = "0d5a1b00-0000-4000-8000-0000000000a0"


@pytest.fixture(scope="module")
def repository():
    from claude.clients.merchant.repository import MerchantRepository

    repo = MerchantRepository(role="test")
    assert repo.config.database == "coding_agent_merchant_test"
    return repo


def approval(connection, revision, role="LEGAL", status="APPROVED", **columns):
    approval_id = uuid.uuid4()
    names = ["id", "document_revision_id", "approver_role", "approval_status", "approved_at", *columns]
    values = [approval_id, revision, role, status, "2026-11-10T00:00:00+07:00" if status == "APPROVED" else None,
              *columns.values()]
    connection.execute(f"INSERT INTO merchant_ops.document_approvals ({', '.join(names)}) "
                       f"VALUES ({', '.join(['%s'] * len(values))})", values)
    return approval_id


def update(connection, table, assignment, row_id, *args):
    connection.execute(f"UPDATE merchant_ops.{table} SET {assignment} WHERE id = %s", (*args, row_id))


def test_migration_010_is_applied_once_with_its_file_checksum(repository):
    with repository.connection(read_only=True) as connection:
        rows = {r["version"]: r for r in connection.execute(
            "SELECT version, description, checksum FROM merchant_ops.schema_migrations").fetchall()}
    assert sorted(rows)[:10] == list(range(1, 11))  # later migrations may follow
    assert rows[10]["description"] == "operator_attested_lifecycle"
    assert rows[10]["checksum"] == _calculate_checksum(str(MIGRATION))


def test_reapplying_migration_010_is_refused(repository):
    statements = _split_sql_statements(MIGRATION.read_text(encoding="utf-8"))
    with rolled_back(repository) as (connection, _):
        with pytest.raises(psycopg.errors.DuplicateColumn):
            with connection.transaction():
                for statement in statements:
                    connection.execute(statement)


def test_a_recorded_decision_names_its_recorder_not_an_approver(repository):
    with rolled_back(repository) as (connection, (project, _)):
        revision = insert_revision(connection, project)
        row_id = approval(connection, revision, recorded_by=OPERATOR, decided_at="2026-11-10T00:00:00+07:00")
        row = connection.execute("SELECT approved_by, recorded_by::text AS r, decided_at FROM "
                                 "merchant_ops.document_approvals WHERE id = %s", (row_id,)).fetchone()
        assert row["approved_by"] is None and row["r"] == OPERATOR and row["decided_at"] is not None


def test_a_decision_date_belongs_only_to_a_decision(repository):
    with rolled_back(repository) as (connection, (project, _)):
        revision = insert_revision(connection, project)
        refused(connection, psycopg.errors.CheckViolation, approval, revision, status="PENDING",
                decided_at="2026-11-10T00:00:00+07:00")


@pytest.mark.parametrize("status", ["APPROVED", "REJECTED"])
@pytest.mark.parametrize("assignment,value", [
    ("approval_status = %s", "PENDING"),
    ("approval_status = %s", "APPROVED"),
    ("notes = %s", "edited"),
    ("recorded_by = %s", OPERATOR),
])
def test_a_recorded_decision_is_final(repository, status, assignment, value):
    with rolled_back(repository) as (connection, (project, _)):
        revision = insert_revision(connection, project)
        row_id = approval(connection, revision, status=status)
        refused(connection, psycopg.errors.IntegrityConstraintViolation, update,
                "document_approvals", assignment, row_id, value)


def test_a_pending_approval_can_still_be_decided_once(repository):
    with rolled_back(repository) as (connection, (project, _)):
        revision = insert_revision(connection, project)
        row_id = approval(connection, revision, status="PENDING")
        update(connection, "document_approvals",
               "approval_status = 'REJECTED', recorded_by = %s, decided_at = now()", row_id, OPERATOR)
        refused(connection, psycopg.errors.IntegrityConstraintViolation, update,
                "document_approvals", "approval_status = %s", row_id, "APPROVED")


def test_attested_signing_requires_a_signed_revision(repository):
    with rolled_back(repository) as (connection, (project, _)):
        revision = insert_revision(connection, project)
        refused(connection, psycopg.errors.CheckViolation, update, "document_revisions",
                "signing_attestation = %s", revision, "OPERATOR_ATTESTED_SIGNED")
        refused(connection, psycopg.errors.CheckViolation, update, "document_revisions",
                "signed = true, signed_at = now(), signing_attestation = %s", revision, "VERIFIED")
        update(connection, "document_revisions",
               "signed = true, signed_at = now(), signing_attestation = %s", revision,
               "OPERATOR_ATTESTED_SIGNED")


@pytest.mark.parametrize("assignment,value", [
    ("signed = false, signed_at = NULL, signing_attestation = %s", None),
    ("signed_at = %s", "2020-01-01T00:00:00Z"),
    ("signing_attestation = %s", None),
])
def test_a_signed_revision_stays_signed_as_recorded(repository, assignment, value):
    with rolled_back(repository) as (connection, (project, _)):
        revision = insert_revision(connection, project)
        update(connection, "document_revisions",
               "signed = true, signed_at = now(), signing_attestation = 'OPERATOR_ATTESTED_SIGNED'", revision)
        refused(connection, psycopg.errors.IntegrityConstraintViolation, update,
                "document_revisions", assignment, revision, value)


def test_a_signed_revision_can_still_be_superseded_by_the_engine_path(repository):
    with rolled_back(repository) as (connection, (project, _)):
        first = insert_revision(connection, project, 1)
        update(connection, "document_revisions", "signed = true, signed_at = now()", first)
        second = insert_revision(connection, project, 2)
        update(connection, "document_revisions", "superseded_by = %s", first, second)


def test_existing_data_is_untouched(repository):
    with repository.connection(read_only=True) as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM merchant_ops.document_approvals WHERE recorded_by IS NOT NULL "
            "OR decided_at IS NOT NULL").fetchone()["n"] == 0
        assert connection.execute(
            "SELECT count(*) AS n FROM merchant_ops.document_revisions WHERE signing_attestation IS NOT NULL"
        ).fetchone()["n"] == 0
