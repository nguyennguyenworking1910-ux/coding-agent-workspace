"""CP12H.NL4D-S1: migration 009 (METADATA_ONLY revisions) on the Merchant test database.

Every test runs inside one transaction that is always rolled back (the
NL4D5A1b fixtures): nothing commits. No revision, approval or signing write
path is exercised. Must run alone (never concurrently with another
PostgreSQL test process).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import psycopg
import pytest

from claude.clients.merchant.migrate import _calculate_checksum, _split_sql_statements
from tests.merchant.test_direct_execute_end_to_end import TEST_DB_CONFIGURED
from tests.merchant.test_nl4d5a1b_migration_008_postgres import (
    insert_file,
    insert_revision,
    refused,
    revision_row,
    rolled_back,
)

pytestmark = pytest.mark.skipif(not TEST_DB_CONFIGURED, reason="Merchant test database not configured")

MIGRATION = Path(".claude/clients/merchant/migrations/009_metadata_only_revisions.sql")


@pytest.fixture(scope="module")
def repository():
    from claude.clients.merchant.repository import MerchantRepository

    repo = MerchantRepository(role="test")
    assert repo.config.database == "coding_agent_merchant_test"
    return repo


def metadata_only(connection, project, number=1, **columns):
    """Insert a METADATA_ONLY revision with its required content marker."""
    revision = uuid.uuid4()
    columns = {"content_hash": f"metadata-only:{revision}", "evidence_status": "METADATA_ONLY", **columns}
    names = ["id", "project_id", "document_type", "revision_number", *columns]
    values = [revision, project, "CONTRACT", number, *columns.values()]
    connection.execute(
        f"INSERT INTO merchant_ops.document_revisions ({', '.join(names)}) "
        f"VALUES ({', '.join(['%s'] * len(values))})", values)
    return revision


# ------------------------------------------------------------ migration record


def test_migration_009_is_applied_once_with_its_file_checksum(repository):
    with repository.connection(read_only=True) as connection:
        rows = connection.execute("SELECT version, description, checksum FROM merchant_ops.schema_migrations "
                                  "ORDER BY version").fetchall()
    assert [r["version"] for r in rows] == list(range(1, 10))
    assert rows[8]["description"] == "metadata_only_revisions"
    assert rows[8]["checksum"] == _calculate_checksum(str(MIGRATION))


def test_reapplying_migration_009_is_refused_and_rolls_back(repository):
    statements = _split_sql_statements(MIGRATION.read_text(encoding="utf-8"))
    assert len(statements) == 1
    with rolled_back(repository) as (connection, _):
        with pytest.raises(psycopg.errors.DuplicateObject):
            with connection.transaction():
                connection.execute(statements[0])
        assert connection.execute("SELECT count(*) AS n FROM merchant_ops.schema_migrations "
                                  "WHERE version = 9").fetchone()["n"] == 1


def test_constraints_are_exact_and_validated(repository):
    with repository.connection(read_only=True) as connection:
        rows = {r["conname"]: r for r in connection.execute(
            "SELECT conname, convalidated, pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conrelid = 'merchant_ops.document_revisions'::regclass").fetchall()}
    status = rows["document_revisions_evidence_status_check"]["def"]
    assert set(re.findall(r"'([^']*)'", status)) == {"UNVERIFIED_LEGACY", "METADATA_ONLY", "MANAGED"}
    assert "metadata-only:" in rows["document_revisions_metadata_only_content_check"]["def"]
    for name in ("document_revisions_managed_file_check", "document_revisions_original_file_name_check",
                 "document_revisions_document_file_fk"):           # migration 008 constraints kept
        assert name in rows
    assert all(r["convalidated"] for r in rows.values())


# --------------------------------------------------------------- classification


def test_a_metadata_only_revision_is_accepted(repository):
    with rolled_back(repository) as (connection, (project, _)):
        revision = metadata_only(connection, project)
        row = revision_row(connection, revision)
        assert row["evidence_status"] == "METADATA_ONLY"
        assert row["content_hash"] == f"metadata-only:{revision}"
        assert row["document_file_id"] is None and row["original_file_name"] is None


def test_the_default_classification_is_still_unverified_legacy(repository):
    with rolled_back(repository) as (connection, (project, _)):
        assert revision_row(connection, insert_revision(connection, project))["evidence_status"] \
            == "UNVERIFIED_LEGACY"


@pytest.mark.parametrize("content_hash", [
    "sha256:" + hashlib.sha256(b"a").hexdigest(),          # looks like verified content
    "free text",
    "metadata-only:" + str(uuid.uuid4()),                  # another revision's marker
    "",
])
def test_a_metadata_only_revision_cannot_carry_a_content_hash(repository, content_hash):
    with rolled_back(repository) as (connection, (project, _)):
        refused(connection, psycopg.errors.CheckViolation, metadata_only, project, content_hash=content_hash)


def test_a_metadata_only_revision_cannot_reference_a_file(repository):
    with rolled_back(repository) as (connection, (project, _)):
        file_row = insert_file(connection)
        refused(connection, psycopg.errors.CheckViolation, metadata_only, project,
                document_file_id=file_row["id"])


def test_a_metadata_only_revision_cannot_carry_an_original_filename(repository):
    with rolled_back(repository) as (connection, (project, _)):
        refused(connection, psycopg.errors.CheckViolation, metadata_only, project, original_file_name="a.pdf")


def test_unknown_classifications_are_still_refused(repository):
    with rolled_back(repository) as (connection, (project, _)):
        for status in ("VERIFIED", "metadata_only", "SIGNED"):
            refused(connection, psycopg.errors.CheckViolation, insert_revision, project,
                    evidence_status=status)


def test_managed_revisions_still_bind_to_their_file(repository):
    with rolled_back(repository) as (connection, (project, _)):
        file_row = insert_file(connection)
        managed = insert_revision(connection, project, content_hash=file_row["content_hash"],
                                  evidence_status="MANAGED", document_file_id=file_row["id"])
        assert revision_row(connection, managed)["evidence_status"] == "MANAGED"
        refused(connection, psycopg.errors.CheckViolation, insert_revision, project, 2,
                content_hash=file_row["content_hash"], evidence_status="MANAGED")       # no file


# --------------------------------------------------------- no silent upgrade


@pytest.mark.parametrize("assignment", [
    "evidence_status = 'MANAGED'",
    "evidence_status = 'UNVERIFIED_LEGACY'",
    "content_hash = 'sha256:' || repeat('a', 64)",
])
def test_a_metadata_only_revision_can_never_be_reclassified(repository, assignment):
    with rolled_back(repository) as (connection, (project, _)):
        revision = metadata_only(connection, project)
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.transaction():
                connection.execute(f"UPDATE merchant_ops.document_revisions SET {assignment} WHERE id = %s",
                                   (revision,))
        assert revision_row(connection, revision)["evidence_status"] == "METADATA_ONLY"


def test_a_metadata_only_revision_cannot_be_upgraded_with_a_matching_file(repository):
    with rolled_back(repository) as (connection, (project, _)):
        file_row = insert_file(connection)
        revision = metadata_only(connection, project)
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.transaction():
                connection.execute(
                    "UPDATE merchant_ops.document_revisions SET evidence_status = 'MANAGED', "
                    "document_file_id = %s, content_hash = %s WHERE id = %s",
                    (file_row["id"], file_row["content_hash"], revision))


def test_a_legacy_revision_cannot_become_metadata_only(repository):
    with rolled_back(repository) as (connection, (project, _)):
        legacy = insert_revision(connection, project)
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.transaction():
                connection.execute(
                    "UPDATE merchant_ops.document_revisions SET evidence_status = 'METADATA_ONLY', "
                    "content_hash = 'metadata-only:' || id::text WHERE id = %s", (legacy,))
        assert revision_row(connection, legacy)["evidence_status"] == "UNVERIFIED_LEGACY"


# ------------------------------------- the existing lifecycle on a METADATA_ONLY revision


def test_approval_signing_and_supersede_still_work_on_metadata_only(repository):
    with rolled_back(repository) as (connection, (project, _)):
        first = metadata_only(connection, project, 1)
        for role in ("LEGAL", "ACCOUNTING", "PARTNER"):
            connection.execute(
                "INSERT INTO merchant_ops.document_approvals (id, document_revision_id, approver_role, "
                "approval_status, approved_at) VALUES (%s, %s, %s, 'APPROVED', now())",
                (uuid.uuid4(), first, role))
        connection.execute("UPDATE merchant_ops.document_revisions SET signed = true, signed_at = now() "
                           "WHERE id = %s", (first,))
        second = metadata_only(connection, project, 2)
        connection.execute("UPDATE merchant_ops.document_revisions SET superseded_by = %s WHERE id = %s",
                           (second, first))
        row = revision_row(connection, first)
        assert row["signed"] is True and row["superseded_by"] == second
        assert row["evidence_status"] == "METADATA_ONLY"
