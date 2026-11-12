"""CP12H.NL4D5A1b: migration 008 constraints on the Merchant test database.

Every test runs inside one transaction that is always rolled back: the
disposable Merchant, Project, revisions and file rows it inserts never commit.
No document revision is executed and the storage module is not involved.
Must run alone (never concurrently with another PostgreSQL test process).
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from claude.clients.merchant.migrate import _calculate_checksum, _discover_migrations
from claude.clients.merchant.repository import MerchantRepository
from tests.merchant.test_direct_execute_end_to_end import TEST_DB_CONFIGURED

pytestmark = pytest.mark.skipif(not TEST_DB_CONFIGURED, reason="Merchant test database not configured")

MIGRATION = Path(".claude/clients/merchant/migrations/008_document_file_metadata.sql")
OPERATOR = "0d5a1b00-0000-4000-8000-0000000000a0"


class _Rollback(Exception):
    pass


@pytest.fixture(scope="module")
def repository():
    repo = MerchantRepository(role="test")
    assert repo.config.database == "coding_agent_merchant_test"
    return repo


@contextmanager
def rolled_back(repository):
    """One transaction that never commits; yields (connection, fixture ids)."""
    with repository.connection() as connection:
        try:
            with connection.transaction():
                merchant = uuid.uuid4()
                connection.execute(
                    "INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
                    "VALUES (%s, %s, 'PYTEST NL4D5A1b', 'ACTIVE')",
                    (merchant, f"PYTEST_NL4D5A1B_{uuid.uuid4().hex[:8].upper()}"))
                template = connection.execute(
                    "SELECT id FROM merchant_ops.workflow_templates LIMIT 1").fetchone()["id"]
                projects = []
                for _ in range(2):
                    project = uuid.uuid4()
                    connection.execute(
                        "INSERT INTO merchant_ops.projects (id, merchant_id, project_type, workflow_variant, "
                        "workflow_template_version_id, title, status) VALUES "
                        "(%s, %s, 'OPENING_NEW_CINEMA', 'OPENING_NEW_CINEMA_STANDARD', %s, 'PYTEST', 'PLANNED')",
                        (project, merchant, template))
                    projects.append(project)
                yield connection, projects
                raise _Rollback
        except _Rollback:
            pass


def blob(seed: bytes = b"a"):
    sha = hashlib.sha256(seed).hexdigest()
    return sha, f"sha256:{sha}", f"sha256/{sha[:2]}/{sha}"


def insert_file(connection, seed=b"a", **overrides):
    sha, content_hash, key = blob(seed)
    row = {"id": uuid.uuid4(), "sha256": sha, "content_hash": content_hash, "byte_size": 100,
           "file_type": "PDF", "media_type": "application/pdf", "storage_key": key,
           "created_by": OPERATOR, "verified_at": "2026-11-12T00:00:00Z", **overrides}
    connection.execute(
        "INSERT INTO merchant_ops.document_files (id, sha256, content_hash, byte_size, file_type, "
        "media_type, storage_key, created_by, verified_at) VALUES (%(id)s, %(sha256)s, %(content_hash)s, "
        "%(byte_size)s, %(file_type)s, %(media_type)s, %(storage_key)s, %(created_by)s, %(verified_at)s)",
        row)
    return row


def insert_revision(connection, project, number=1, content_hash="legacy-free-text", **columns):
    revision = uuid.uuid4()
    names = ["id", "project_id", "document_type", "revision_number", "content_hash", *columns]
    values = [revision, project, "CONTRACT", number, content_hash, *columns.values()]
    connection.execute(
        f"INSERT INTO merchant_ops.document_revisions ({', '.join(names)}) "
        f"VALUES ({', '.join(['%s'] * len(values))})", values)
    return revision


def refused(connection, error, call, *args, **kwargs):
    with pytest.raises(error):
        with connection.transaction():                       # savepoint
            call(connection, *args, **kwargs)


def revision_row(connection, revision):
    return connection.execute(
        "SELECT content_hash, evidence_status, document_file_id, original_file_name, signed, "
        "superseded_by FROM merchant_ops.document_revisions WHERE id = %s", (revision,)).fetchone()


# ------------------------------------------------------------ migration record


def test_migration_008_is_applied_once_with_its_file_checksum(repository):
    with repository.connection(read_only=True) as connection:
        rows = connection.execute(
            "SELECT version, description, checksum FROM merchant_ops.schema_migrations "
            "ORDER BY version").fetchall()

    # Later migrations (009+) may follow; 008 is recorded exactly once.
    assert [r["version"] for r in rows][:8] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert rows[7]["description"] == "document_file_metadata"
    assert rows[7]["checksum"] == _calculate_checksum(str(MIGRATION))
    assert 8 in [v for v, _, _ in _discover_migrations()]


def test_reapplying_migration_008_is_refused_and_rolls_back(repository):
    from claude.clients.merchant.migrate import _split_sql_statements

    statements = _split_sql_statements(MIGRATION.read_text(encoding="utf-8"))
    with rolled_back(repository) as (connection, _):
        with pytest.raises(psycopg.errors.DuplicateTable):
            with connection.transaction():
                for statement in statements:
                    connection.execute(statement)
        # The failed reapplication changed nothing.
        assert connection.execute("SELECT count(*) AS n FROM merchant_ops.schema_migrations "
                                  "WHERE version = 8").fetchone()["n"] == 1


# ------------------------------------------------------------ document_files


def test_valid_file_metadata_is_accepted(repository):
    with rolled_back(repository) as (connection, _):
        row = insert_file(connection)
        stored = connection.execute("SELECT * FROM merchant_ops.document_files WHERE id = %s",
                                    (row["id"],)).fetchone()
        assert stored["content_hash"] == row["content_hash"] and stored["byte_size"] == 100


@pytest.mark.parametrize("overrides", [
    {"sha256": "A" * 64},                                   # uppercase
    {"sha256": "a" * 63},                                   # short
    {"sha256": "g" * 64},                                   # not hex
])
def test_invalid_sha256_is_refused(repository, overrides):
    with rolled_back(repository) as (connection, _):
        sha = overrides["sha256"]
        refused(connection, psycopg.errors.CheckViolation, insert_file,
                sha256=sha, content_hash=f"sha256:{sha}", storage_key=f"sha256/{sha[:2]}/{sha}")


@pytest.mark.parametrize("overrides", [
    {"content_hash": "sha256:" + "0" * 64},                 # does not derive from sha256
    {"storage_key": "sha256/zz/elsewhere"},                 # not derived from sha256
    {"storage_key": "../../escape"},
])
def test_contradictory_hash_or_storage_key_is_refused(repository, overrides):
    with rolled_back(repository) as (connection, _):
        refused(connection, psycopg.errors.CheckViolation, insert_file, **overrides)


@pytest.mark.parametrize("size", [0, -1, 26_214_401])
def test_invalid_file_size_is_refused(repository, size):
    with rolled_back(repository) as (connection, _):
        refused(connection, psycopg.errors.CheckViolation, insert_file, byte_size=size)


def test_the_exact_size_limit_is_accepted(repository):
    with rolled_back(repository) as (connection, _):
        insert_file(connection, byte_size=26_214_400)


@pytest.mark.parametrize("file_type,media_type", [
    ("GIF", "image/gif"), ("DOCM", "application/vnd.ms-word.document.macroEnabled.12"),
    ("PDF", "image/png"), ("PNG", "application/pdf"), ("pdf", "application/pdf"),
])
def test_unsupported_or_inconsistent_types_are_refused(repository, file_type, media_type):
    with rolled_back(repository) as (connection, _):
        refused(connection, psycopg.errors.CheckViolation, insert_file,
                file_type=file_type, media_type=media_type)


def test_duplicate_file_identity_is_refused(repository):
    with rolled_back(repository) as (connection, _):
        insert_file(connection)
        refused(connection, psycopg.errors.UniqueViolation, insert_file)        # same digest


def test_file_metadata_is_immutable(repository):
    with rolled_back(repository) as (connection, _):
        row = insert_file(connection)
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.transaction():
                connection.execute("UPDATE merchant_ops.document_files SET byte_size = 99 "
                                   "WHERE id = %s", (row["id"],))
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.transaction():
                connection.execute("DELETE FROM merchant_ops.document_files WHERE id = %s", (row["id"],))


# -------------------------------------------------- revisions: legacy vs managed


def test_legacy_revisions_stay_unverified_and_unchanged(repository):
    with rolled_back(repository) as (connection, (project, _)):
        sha_shaped = "sha256:" + hashlib.sha256(b"a").hexdigest()
        insert_file(connection)                                 # a file with the SAME digest exists
        legacy = insert_revision(connection, project, content_hash=sha_shaped)
        row = revision_row(connection, legacy)

        assert row["evidence_status"] == "UNVERIFIED_LEGACY"   # not trusted by hash shape or match
        assert row["document_file_id"] is None and row["content_hash"] == sha_shaped


def test_a_legacy_revision_can_never_be_upgraded(repository):
    with rolled_back(repository) as (connection, (project, _)):
        file_row = insert_file(connection)
        legacy = insert_revision(connection, project, content_hash=file_row["content_hash"])
        for assignment, value in [("evidence_status = %s", "MANAGED"),
                                  ("document_file_id = %s", file_row["id"]),
                                  ("content_hash = %s", "changed"),
                                  ("original_file_name = %s", "x.pdf")]:
            with pytest.raises(psycopg.Error):
                with connection.transaction():
                    connection.execute(f"UPDATE merchant_ops.document_revisions SET {assignment} "
                                       "WHERE id = %s", (value, legacy))
        assert revision_row(connection, legacy)["evidence_status"] == "UNVERIFIED_LEGACY"


def test_a_managed_revision_binds_to_its_matching_file(repository):
    with rolled_back(repository) as (connection, (project, _)):
        file_row = insert_file(connection)
        managed = insert_revision(connection, project, content_hash=file_row["content_hash"],
                                  evidence_status="MANAGED", document_file_id=file_row["id"],
                                  original_file_name="Hợp đồng Nguyễn.pdf")
        row = revision_row(connection, managed)

        assert (row["evidence_status"], row["document_file_id"]) == ("MANAGED", file_row["id"])


def test_wrong_hash_association_is_refused(repository):
    with rolled_back(repository) as (connection, (project, _)):
        file_row = insert_file(connection)
        refused(connection, psycopg.errors.ForeignKeyViolation, insert_revision, project,
                content_hash="sha256:" + hashlib.sha256(b"other").hexdigest(),
                evidence_status="MANAGED", document_file_id=file_row["id"])


def test_missing_managed_file_reference_is_refused(repository):
    with rolled_back(repository) as (connection, (project, _)):
        _, content_hash, _ = blob()
        refused(connection, psycopg.errors.ForeignKeyViolation, insert_revision, project,
                content_hash=content_hash, evidence_status="MANAGED", document_file_id=uuid.uuid4())


@pytest.mark.parametrize("columns", [
    {"evidence_status": "MANAGED"},                                      # managed without a file
    {"evidence_status": "VERIFIED"},                                     # unknown status
    {"original_file_name": "a.pdf"},                                     # filename on a legacy row
])
def test_inconsistent_classification_is_refused(repository, columns):
    with rolled_back(repository) as (connection, (project, _)):
        refused(connection, psycopg.errors.CheckViolation, insert_revision, project, **columns)


def test_a_file_reference_requires_managed_status(repository):
    with rolled_back(repository) as (connection, (project, _)):
        file_row = insert_file(connection)
        refused(connection, psycopg.errors.CheckViolation, insert_revision, project,
                content_hash=file_row["content_hash"], document_file_id=file_row["id"])


@pytest.mark.parametrize("name", ["../a.pdf", "a\\b.pdf", "a:b.pdf", " a.pdf", "a\x01.pdf", "x" * 201,
                                  "e" + "́" + ".pdf"])
def test_unsafe_original_filenames_are_refused(repository, name):
    with rolled_back(repository) as (connection, (project, _)):
        file_row = insert_file(connection)
        refused(connection, psycopg.errors.CheckViolation, insert_revision, project,
                content_hash=file_row["content_hash"], evidence_status="MANAGED",
                document_file_id=file_row["id"], original_file_name=name)


def test_one_blob_may_back_revisions_of_different_projects(repository):
    """Global content deduplication; ownership stays with each Project's revision."""
    with rolled_back(repository) as (connection, (project_a, project_b)):
        file_row = insert_file(connection)
        for project in (project_a, project_b):
            insert_revision(connection, project, content_hash=file_row["content_hash"],
                            evidence_status="MANAGED", document_file_id=file_row["id"])
        owners = connection.execute(
            "SELECT DISTINCT project_id FROM merchant_ops.document_revisions WHERE document_file_id = %s",
            (file_row["id"],)).fetchall()
        assert {r["project_id"] for r in owners} == {project_a, project_b}


# ------------------------------------------ preserved revision, approval, signing


def test_existing_revision_lifecycle_is_preserved(repository):
    with rolled_back(repository) as (connection, (project, _)):
        first = insert_revision(connection, project, 1)
        second = insert_revision(connection, project, 2)
        connection.execute("UPDATE merchant_ops.document_revisions SET superseded_by = %s WHERE id = %s",
                           (second, first))                        # supersede still works
        refused(connection, psycopg.errors.UniqueViolation, insert_revision, project, 2)  # uniqueness kept
        assert revision_row(connection, first)["superseded_by"] == second


def test_existing_approval_and_signing_behaviour_is_compatible(repository):
    with rolled_back(repository) as (connection, (project, _)):
        revision = insert_revision(connection, project)
        for role in ("LEGAL", "ACCOUNTING", "PARTNER"):
            connection.execute(
                "INSERT INTO merchant_ops.document_approvals (id, document_revision_id, approver_role, "
                "approval_status, approved_at) VALUES (%s, %s, %s, 'APPROVED', now())",
                (uuid.uuid4(), revision, role))
        connection.execute("UPDATE merchant_ops.document_revisions SET signed = true, signed_at = now() "
                           "WHERE id = %s", (revision,))           # the signing UPDATE still works
        row = revision_row(connection, revision)
        assert row["signed"] is True and row["evidence_status"] == "UNVERIFIED_LEGACY"


def test_foreign_keys_still_hold(repository):
    with rolled_back(repository) as (connection, _):
        refused(connection, psycopg.errors.ForeignKeyViolation, insert_revision, uuid.uuid4())


# ------------------------------------------------------------- concurrency


def test_concurrent_conflicting_inserts_cannot_both_proceed(repository):
    """While transaction A holds an uncommitted file identity, transaction B
    cannot insert the same identity: it waits on the unique index (here until
    its short lock timeout). PostgreSQL then resolves B to a unique violation
    if A commits, so at most one can ever commit. Both roll back."""
    sha, content_hash, key = blob(b"concurrent-" + uuid.uuid4().bytes)
    insert = ("INSERT INTO merchant_ops.document_files (id, sha256, content_hash, byte_size, file_type, "
              "media_type, storage_key, created_by, verified_at) VALUES "
              "(%s, %s, %s, 1, 'PNG', 'image/png', %s, %s, now())")
    held, b_finished, outcome = threading.Event(), threading.Event(), {}

    def transaction_a():
        with repository.connection() as connection:
            try:
                with connection.transaction():
                    connection.execute(insert, (uuid.uuid4(), sha, content_hash, key, OPERATOR))
                    held.set()
                    b_finished.wait(timeout=30)                      # hold until B has tried
                    raise _Rollback
            except _Rollback:
                pass

    a = threading.Thread(target=transaction_a)
    a.start()
    assert held.wait(timeout=30)
    with repository.connection() as connection:
        try:
            with connection.transaction():
                connection.execute("SET LOCAL lock_timeout = '500ms'")
                try:
                    connection.execute(insert, (uuid.uuid4(), sha, content_hash, key, OPERATOR))
                    outcome["b"] = "inserted"
                except psycopg.errors.LockNotAvailable:
                    outcome["b"] = "blocked by A's uncommitted identity"
                except psycopg.errors.UniqueViolation:
                    outcome["b"] = "unique violation"
                raise _Rollback
        except _Rollback:
            pass
        finally:
            b_finished.set()
    a.join(timeout=30)

    assert outcome["b"] == "blocked by A's uncommitted identity", outcome
    with repository.connection(read_only=True) as connection:
        assert connection.execute("SELECT count(*) AS n FROM merchant_ops.document_files "
                                  "WHERE sha256 = %s", (sha,)).fetchone()["n"] == 0


def test_a_committed_identity_refuses_a_later_conflicting_insert(repository):
    """Case A. The first insert completes (a released savepoint: committed
    relative to the enclosing transaction); the second conflicting insert then
    fails with a unique violation. A real cross-session COMMIT is deliberately
    not exercised: a committed document_files row is immutable and would
    persist in the accepted test database."""
    with rolled_back(repository) as (connection, _):
        with connection.transaction():                       # savepoint, released = completed
            insert_file(connection, seed=b"case-a")
        refused(connection, psycopg.errors.UniqueViolation, insert_file, seed=b"case-a")
        sha, _, key = blob(b"case-a")
        refused(connection, psycopg.errors.UniqueViolation, insert_file, seed=b"case-a",
                id=uuid.uuid4(), sha256=sha, storage_key=key)  # same identity, new id


def test_after_the_first_transaction_rolls_back_the_second_insert_proceeds(repository):
    """Case B. B waits on A's uncommitted identity; when A rolls back, B's
    insert succeeds (then B rolls back too)."""
    import time

    sha, content_hash, key = blob(b"case-b-" + uuid.uuid4().bytes)
    insert = ("INSERT INTO merchant_ops.document_files (id, sha256, content_hash, byte_size, file_type, "
              "media_type, storage_key, created_by, verified_at) VALUES "
              "(%s, %s, %s, 1, 'PNG', 'image/png', %s, %s, now())")
    b_pid, outcome = {}, {}

    def transaction_b():
        with repository.connection() as connection:
            try:
                with connection.transaction():
                    b_pid["pid"] = connection.execute("SELECT pg_backend_pid() AS p").fetchone()["p"]
                    connection.execute("SET LOCAL lock_timeout = '20s'")
                    connection.execute(insert, (uuid.uuid4(), sha, content_hash, key, OPERATOR))
                    outcome["b"] = "inserted"
                    raise _Rollback
            except _Rollback:
                pass
            except psycopg.Error as error:
                outcome["b"] = type(error).__name__

    with repository.connection() as connection:
        try:
            with connection.transaction():
                a_pid = connection.execute("SELECT pg_backend_pid() AS p").fetchone()["p"]
                connection.execute(insert, (uuid.uuid4(), sha, content_hash, key, OPERATOR))
                b = threading.Thread(target=transaction_b)
                b.start()
                deadline = time.monotonic() + 20
                blocked = False
                while time.monotonic() < deadline and not blocked:
                    if "pid" in b_pid:                       # pg_blocking_pids is live, not a snapshot
                        blocked = connection.execute("SELECT %s = ANY(pg_blocking_pids(%s)) AS b",
                                                     (a_pid, b_pid["pid"])).fetchone()["b"]
                    time.sleep(0.05)
                assert blocked, "B never waited on A's uncommitted identity"
                raise _Rollback                              # A rolls back while B waits
        except _Rollback:
            pass
    b.join(timeout=30)
    assert outcome.get("b") == "inserted", outcome
    with repository.connection(read_only=True) as connection:
        assert connection.execute("SELECT count(*) AS n FROM merchant_ops.document_files WHERE sha256 = %s",
                                  (sha,)).fetchone()["n"] == 0


def test_unique_file_identity_indexes_are_valid(repository):
    """Case C: two committed rows can never share an identity: the unique
    constraints are backed by valid, ready unique indexes."""
    with repository.connection(read_only=True) as connection:
        rows = {r["name"]: r for r in connection.execute(
            "SELECT c.conname AS name, i.indisunique AS u, i.indisvalid AS v, i.indisready AS r "
            "FROM pg_constraint c JOIN pg_index i ON i.indexrelid = c.conindid "
            "WHERE c.conrelid = 'merchant_ops.document_files'::regclass").fetchall()}
    for name in ("document_files_pkey", "document_files_sha256_unique", "document_files_storage_key_unique",
                 "document_files_id_content_hash_unique"):
        assert rows[name]["u"] and rows[name]["v"] and rows[name]["r"], name


# --------------------------------------------------------------- grants


def test_application_role_can_only_read_file_metadata(repository):
    with repository.connection(read_only=True) as connection:
        privileges = {r["privilege_type"] for r in connection.execute(
            "SELECT privilege_type FROM information_schema.table_privileges "
            "WHERE table_schema = 'merchant_ops' AND table_name = 'document_files' "
            "AND grantee = 'merchant_app'").fetchall()}
    assert privileges == {"SELECT"}
