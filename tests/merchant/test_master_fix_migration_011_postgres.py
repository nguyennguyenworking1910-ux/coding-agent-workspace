"""CP12H.MASTER-FIX: migration 011 (reused signed revision binding) on the
Merchant test database. Every test runs in one rolled-back transaction.
Must run alone (never concurrently with another PostgreSQL test process)."""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from claude.clients.merchant.migrate import _calculate_checksum
from tests.merchant.test_direct_execute_end_to_end import TEST_DB_CONFIGURED
from tests.merchant.test_nl4d5a1b_migration_008_postgres import insert_revision, refused, rolled_back

pytestmark = pytest.mark.skipif(not TEST_DB_CONFIGURED, reason="Merchant test database not configured")

MIGRATION = Path(".claude/clients/merchant/migrations/011_reused_revision_binding.sql")


@pytest.fixture(scope="module")
def repository():
    from claude.clients.merchant.repository import MerchantRepository

    repo = MerchantRepository(role="test")
    assert repo.config.database == "coding_agent_merchant_test"
    return repo


def signed(connection, project, number=1, document_type="CONTRACT"):
    revision = uuid.uuid4()
    connection.execute(
        "INSERT INTO merchant_ops.document_revisions (id, project_id, document_type, revision_number, "
        "content_hash, signed, signed_at) VALUES (%s, %s, %s, %s, 'legacy', TRUE, now())",
        (revision, project, document_type, number))
    return revision


def media_project(connection, merchant_of, reused):
    merchant = connection.execute("SELECT merchant_id FROM merchant_ops.projects WHERE id = %s",
                                  (merchant_of,)).fetchone()["merchant_id"]
    template = connection.execute("SELECT id FROM merchant_ops.workflow_templates LIMIT 1").fetchone()["id"]
    project = uuid.uuid4()
    connection.execute(
        "INSERT INTO merchant_ops.projects (id, merchant_id, project_type, workflow_variant, "
        "workflow_template_version_id, title, status, payment_period_number, reused_document_revision_id) "
        "VALUES (%s, %s, 'MEDIA_TOP_UP', 'MEDIA_TOP_UP_EXISTING_DOCUMENT', %s, %s, 'PLANNED', 1, %s)",
        (project, merchant, template, f"PYTEST media {project.hex[:6]}", reused))
    return project


def other_merchant_project(connection):
    merchant = uuid.uuid4()
    connection.execute("INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
                       "VALUES (%s, %s, 'PYTEST other', 'ACTIVE')",
                       (merchant, f"PYTEST_MFIX_{uuid.uuid4().hex[:8].upper()}"))
    template = connection.execute("SELECT id FROM merchant_ops.workflow_templates LIMIT 1").fetchone()["id"]
    project = uuid.uuid4()
    connection.execute(
        "INSERT INTO merchant_ops.projects (id, merchant_id, project_type, workflow_variant, "
        "workflow_template_version_id, title, status) VALUES (%s, %s, 'OPENING_NEW_CINEMA', "
        "'OPENING_NEW_CINEMA_STANDARD', %s, 'PYTEST other', 'PLANNED')", (project, merchant, template))
    return project


def test_migration_011_is_applied_once_with_its_file_checksum(repository):
    with repository.connection(read_only=True) as connection:
        rows = {r["version"]: r for r in connection.execute(
            "SELECT version, description, checksum FROM merchant_ops.schema_migrations").fetchall()}
    assert sorted(rows)[:11] == list(range(1, 12))
    assert rows[11]["description"] == "reused_revision_binding"
    assert rows[11]["checksum"] == _calculate_checksum(str(MIGRATION))


def test_a_signed_contract_of_another_project_of_the_merchant_can_be_bound(repository):
    with rolled_back(repository) as (connection, (source, _)):
        revision = signed(connection, source)
        project = media_project(connection, source, revision)
        bound = connection.execute("SELECT reused_document_revision_id AS r FROM merchant_ops.projects "
                                   "WHERE id = %s", (project,)).fetchone()["r"]
        assert bound == revision
        # Nothing was copied: the source revision is the only one and unchanged.
        assert connection.execute("SELECT count(*) AS n FROM merchant_ops.document_revisions "
                                  "WHERE id = %s AND project_id = %s AND signed", (revision, source)
                                  ).fetchone()["n"] == 1


@pytest.mark.parametrize("make", [
    lambda c, s: insert_revision(c, s),                                            # unsigned
    lambda c, s: signed(c, s, document_type="ADDENDUM"),                           # not a contract
    lambda c, s: signed(c, other_merchant_project(c)),                             # another Merchant
    lambda c, s: uuid.uuid4(),                                                     # missing
], ids=["unsigned", "not-contract", "other-merchant", "missing"])
def test_an_ineligible_revision_cannot_be_bound(repository, make):
    with rolled_back(repository) as (connection, (source, _)):
        revision = make(connection, source)
        with pytest.raises((psycopg.errors.IntegrityConstraintViolation, psycopg.errors.ForeignKeyViolation)):
            with connection.transaction():
                media_project(connection, source, revision)


def test_a_superseded_signed_revision_cannot_be_bound(repository):
    with rolled_back(repository) as (connection, (source, _)):
        first = signed(connection, source, 1)
        second = signed(connection, source, 2)
        connection.execute("UPDATE merchant_ops.document_revisions SET superseded_by = %s WHERE id = %s",
                           (second, first))
        refused(connection, psycopg.errors.IntegrityConstraintViolation, media_project, source, first)
        media_project(connection, source, second)


@pytest.mark.parametrize("assignment", ["%s", "NULL"])
def test_the_binding_is_fixed_at_creation(repository, assignment):
    with rolled_back(repository) as (connection, (source, sibling)):
        revision = signed(connection, source)
        project = media_project(connection, source, revision)
        other = signed(connection, source, 2)
        values = (other, project) if assignment == "%s" else (project,)
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.transaction():
                connection.execute(
                    f"UPDATE merchant_ops.projects SET reused_document_revision_id = {assignment} "
                    "WHERE id = %s", values)
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.transaction():                       # nor added later
                connection.execute("UPDATE merchant_ops.projects SET reused_document_revision_id = %s "
                                   "WHERE id = %s", (revision, sibling))


def test_other_project_updates_are_unaffected(repository):
    with rolled_back(repository) as (connection, (source, _)):
        project = media_project(connection, source, signed(connection, source))
        connection.execute("UPDATE merchant_ops.projects SET status = 'IN_PROGRESS', version = version + 1 "
                           "WHERE id = %s", (project,))
