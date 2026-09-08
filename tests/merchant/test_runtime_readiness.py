"""Checkpoint 9.3 read-only runtime readiness contract tests."""

from __future__ import annotations

import inspect
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude.clients.merchant import runtime_readiness
from claude.clients.merchant.runtime_readiness import (
    BUSINESS_TABLES,
    CATALOG_INITIALIZATION_READY,
    EXPECTED_TABLES,
    NOT_READY,
    RUNTIME_MIGRATIONS_READY,
    TEMPLATE_INITIALIZATION_READY,
    RuntimeBackupError,
    RuntimeReadinessError,
    _assess_runtime_snapshot,
    _expected_template_rows,
    _local_migration_manifest,
    check_runtime_readiness,
    inspect_runtime_backup,
)


SOURCE_HASH = "1" * 64
CATALOG_HASH = "2" * 64
NOW = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)


def _backup(**overrides):
    values = {
        "backup_sha256": "3" * 64,
        "size_bytes": 4096,
        "created_at_utc": NOW,
        "format": "POSTGRESQL_CUSTOM",
        "restore_list_verified": True,
        "recovery_procedure_reviewed": True,
        "roles_recoverable": True,
    }
    values.update(overrides)
    return runtime_readiness.RuntimeBackupEvidence(**values)


def _snapshot(applied_versions=(1,), *, templates=()):
    local = {
        item["version"]: item
        for item in _local_migration_manifest()
    }
    return {
        "identity": {
            "database": "coding_agent_merchant",
            "user": "merchant_app",
            "read_only": "on",
            "encoding": "UTF8",
        },
        "schema": {
            "schema_name": "merchant_ops",
            "schema_owner": "merchant_owner",
        },
        "tables": tuple(sorted(EXPECTED_TABLES)),
        "migrations": tuple(
            {
                "version": version,
                "description": local[version]["description"],
                "checksum": local[version]["checksum"],
            }
            for version in applied_versions
        ),
        "business_counts": {
            table: 0 for table in BUSINESS_TABLES
        },
        "status_counts": {},
        "templates": templates,
    }


def _report(snapshot=None, backup=None):
    return _assess_runtime_snapshot(
        snapshot or _snapshot(),
        local_migrations=_local_migration_manifest(),
        source_sha256=SOURCE_HASH,
        catalog_sha256=CATALOG_HASH,
        backup_evidence=backup or _backup(),
        config_is_exact=True,
    )


def test_migration_1_baseline_produces_runtime_upgrade_report():
    report = _report()

    assert report.success is True
    assert report.state == RUNTIME_MIGRATIONS_READY
    assert report.applied_versions == (1,)
    assert report.pending_versions == (2, 3)
    assert report.runtime_migrations_required is True
    assert report.migration_3_required is True
    assert report.template_initialization_required is False
    assert report.catalog_initialization_ready is False
    assert len(report.migration_3_sha256) == 64
    assert report.failed_checks == ()


def test_migrations_1_and_2_still_require_migration_3():
    report = _report(_snapshot((1, 2)))

    assert report.success is True
    assert report.state == RUNTIME_MIGRATIONS_READY
    assert report.applied_versions == (1, 2)
    assert report.pending_versions == (3,)
    assert report.migration_3_required is True


def test_complete_migrations_with_no_templates_are_template_ready():
    report = _report(_snapshot((1, 2, 3)))

    assert report.success is True
    assert report.state == TEMPLATE_INITIALIZATION_READY
    assert report.applied_versions == (1, 2, 3)
    assert report.pending_versions == ()
    assert report.runtime_migrations_required is False
    assert report.template_initialization_required is True
    assert report.catalog_initialization_ready is False


def test_complete_migrations_and_templates_are_catalog_ready():
    report = _report(
        _snapshot(
            (1, 2, 3),
            templates=_expected_template_rows(),
        )
    )

    assert report.success is True
    assert report.state == CATALOG_INITIALIZATION_READY
    assert report.applied_versions == (1, 2, 3)
    assert report.pending_versions == ()
    assert report.migration_3_required is False
    assert report.catalog_initialization_ready is True


@pytest.mark.parametrize(
    ("field", "value", "check"),
    (
        ("database", "coding_agent_merchant_test", "runtime_database_exact"),
        ("user", "merchant_owner", "application_role_exact"),
        ("read_only", "off", "transaction_read_only"),
        ("encoding", "LATIN1", "encoding_utf8"),
    ),
)
def test_database_identity_mismatch_fails_closed(
    field,
    value,
    check,
):
    snapshot = _snapshot()
    snapshot["identity"][field] = value
    report = _report(snapshot)

    assert report.success is False
    assert report.state == NOT_READY
    assert report.checks[check] is False


@pytest.mark.parametrize(
    ("field", "value", "check"),
    (
        ("schema_name", "public", "schema_exists"),
        ("schema_owner", "merchant_app", "schema_owner_exact"),
    ),
)
def test_schema_identity_mismatch_fails_closed(
    field,
    value,
    check,
):
    snapshot = _snapshot()
    snapshot["schema"][field] = value
    report = _report(snapshot)

    assert report.success is False
    assert report.checks[check] is False


def test_missing_or_extra_schema_table_fails_closed():
    missing = _snapshot()
    missing["tables"] = tuple(sorted(EXPECTED_TABLES - {"merchants"}))
    extra = _snapshot()
    extra["tables"] = tuple(sorted(EXPECTED_TABLES | {"private_extra"}))

    assert _report(missing).checks["schema_tables_exact"] is False
    assert _report(extra).checks["schema_tables_exact"] is False


@pytest.mark.parametrize(
    "versions",
    (
        (),
        (2,),
        (1, 3),
        (1, 2, 2),
        (1, 2, 3, 4),
    ),
)
def test_unsupported_migration_history_fails_closed(versions):
    snapshot = _snapshot()
    local = {
        item["version"]: item
        for item in _local_migration_manifest()
    }
    snapshot["migrations"] = tuple(
        {
            "version": version,
            "description": local.get(
                version,
                {"description": "unexpected"},
            )["description"],
            "checksum": local.get(
                version,
                {"checksum": "9" * 64},
            )["checksum"],
        }
        for version in versions
    )
    report = _report(snapshot)

    assert report.success is False
    assert report.state == NOT_READY
    assert report.checks["migration_state_supported"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("checksum", "9" * 64),
        ("description", "changed_description"),
    ),
)
def test_migration_checksum_or_description_drift_fails(
    field,
    value,
):
    snapshot = _snapshot()
    snapshot["migrations"][0][field] = value
    report = _report(snapshot)

    assert report.success is False
    assert report.checks["migration_history_consistent"] is False


def test_nonempty_business_state_fails_without_row_values():
    snapshot = _snapshot()
    snapshot["business_counts"]["merchants"] = 1
    snapshot["status_counts"] = {"ONBOARDING": 1}
    report = _report(snapshot)
    rendered = json.dumps(report.safe_summary(), sort_keys=True)

    assert report.success is False
    assert report.checks["business_state_empty"] is False
    assert "merchant-private-code" not in rendered
    assert "merchant-private-name" not in rendered


def test_unknown_merchant_status_fails_closed():
    snapshot = _snapshot()
    snapshot["business_counts"]["merchants"] = 1
    snapshot["status_counts"] = {"SUSPENDED": 1}
    report = _report(snapshot)

    assert report.checks["merchant_statuses_safe"] is False
    assert report.success is False


def test_incomplete_business_count_manifest_fails_closed():
    snapshot = _snapshot()
    snapshot["business_counts"].pop("project_events")
    report = _report(snapshot)

    assert report.checks["business_counts_complete"] is False
    assert report.checks["business_state_empty"] is False


def test_template_drift_fails_with_hash_only_report():
    snapshot = _snapshot()
    changed = [
        dict(item) for item in _expected_template_rows()
    ]
    changed[0]["step_count"] += 1
    snapshot["templates"] = tuple(changed)
    report = _report(snapshot)

    assert report.success is False
    assert report.checks["standard_templates_safe"] is False
    assert report.standard_templates_match is False
    assert (
        report.expected_template_sha256
        != report.stored_template_sha256
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("format", "PLAIN_SQL"),
        ("size_bytes", 0),
        ("restore_list_verified", False),
        ("recovery_procedure_reviewed", False),
        ("roles_recoverable", False),
    ),
)
def test_incomplete_backup_evidence_blocks_readiness(field, value):
    report = _report(backup=_backup(**{field: value}))

    assert report.success is False
    assert report.checks["backup_evidence_ready"] is False


def test_safe_report_contains_only_counts_hashes_and_identity():
    report = _report()
    summary = report.safe_summary()
    rendered = json.dumps(summary, sort_keys=True)

    assert "records" not in summary
    assert "private-catalog" not in rendered
    assert "password" not in rendered.lower()
    assert summary["source_sha256"] == SOURCE_HASH
    assert summary["catalog_sha256"] == CATALOG_HASH
    assert summary["backup"]["backup_sha256"] == "3" * 64


def test_report_and_backup_representations_are_redacted():
    report = _report()

    assert "private" not in repr(report).lower()
    assert "path" not in repr(report.backup).lower()
    assert "password" not in repr(report).lower()


def test_custom_backup_inspection_returns_fresh_hash_only_evidence():
    with tempfile.TemporaryDirectory() as directory:
        private_path = Path(directory) / "private-runtime-backup.dump"
        private_path.write_bytes(b"PGDMP" + b"safe-fictitious" * 20)
        timestamp = NOW.timestamp()
        os.utime(private_path, (timestamp, timestamp))

        evidence = inspect_runtime_backup(
            private_path,
            restore_list_verified=True,
            recovery_procedure_reviewed=True,
            roles_recoverable=True,
            now=NOW,
        )

    rendered = json.dumps(evidence.safe_summary(), sort_keys=True)
    assert evidence.ready is True
    assert evidence.format == "POSTGRESQL_CUSTOM"
    assert len(evidence.backup_sha256) == 64
    assert "private-runtime-backup" not in rendered


@pytest.mark.parametrize(
    ("content", "reason_code"),
    (
        (b"", "INVALID_BACKUP_FORMAT"),
        (b"PLAIN SQL", "INVALID_BACKUP_FORMAT"),
    ),
)
def test_non_custom_backup_format_is_rejected_without_path(
    content,
    reason_code,
):
    with tempfile.TemporaryDirectory() as directory:
        private_path = Path(directory) / "private-name.dump"
        private_path.write_bytes(content)

        with pytest.raises(RuntimeBackupError) as error:
            inspect_runtime_backup(
                private_path,
                restore_list_verified=True,
                recovery_procedure_reviewed=True,
                roles_recoverable=True,
                now=NOW,
            )

    assert error.value.reason_code == reason_code
    assert "private-name" not in str(error.value)


@pytest.mark.parametrize(
    ("created_at", "reason_code"),
    (
        (NOW - timedelta(hours=25), "BACKUP_TOO_OLD"),
        (NOW + timedelta(minutes=6), "BACKUP_FROM_FUTURE"),
    ),
)
def test_backup_timestamp_must_be_current(created_at, reason_code):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "runtime.dump"
        path.write_bytes(b"PGDMPpayload")
        timestamp = created_at.timestamp()
        os.utime(path, (timestamp, timestamp))

        with pytest.raises(RuntimeBackupError) as error:
            inspect_runtime_backup(
                path,
                restore_list_verified=True,
                recovery_procedure_reviewed=True,
                roles_recoverable=True,
                now=NOW,
            )

    assert error.value.reason_code == reason_code


@pytest.mark.parametrize(
    ("field", "reason_code"),
    (
        ("restore_list_verified", "BACKUP_LIST_NOT_VERIFIED"),
        ("recovery_procedure_reviewed", "RECOVERY_NOT_REVIEWED"),
        ("roles_recoverable", "ROLES_NOT_RECOVERABLE"),
    ),
)
def test_backup_review_flags_must_be_exact_true(field, reason_code):
    arguments = {
        "restore_list_verified": True,
        "recovery_procedure_reviewed": True,
        "roles_recoverable": True,
        field: False,
    }

    with pytest.raises(RuntimeBackupError) as error:
        inspect_runtime_backup(
            "private-path-not-read",
            now=NOW,
            **arguments,
        )

    assert error.value.reason_code == reason_code
    assert "private-path-not-read" not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value", "reason_code"),
    (
        ("source", None, "INVALID_SOURCE_HASH"),
        ("source", "A" * 64, "INVALID_SOURCE_HASH"),
        ("catalog", "short", "INVALID_CATALOG_HASH"),
    ),
)
def test_reviewed_catalog_hashes_are_exact(field, value, reason_code):
    repository = _FakeRepository(_snapshot())
    arguments = {
        "expected_source_sha256": SOURCE_HASH,
        "expected_catalog_sha256": CATALOG_HASH,
        "backup_evidence": _backup(),
    }
    arguments[f"expected_{field}_sha256"] = value

    with pytest.raises(RuntimeReadinessError) as error:
        check_runtime_readiness(repository, **arguments)

    assert error.value.reason_code == reason_code
    assert repository.connection_modes == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("host", "localhost"),
        ("port", 5432),
        ("database", "coding_agent_merchant_test"),
        ("user", "merchant_owner"),
    ),
)
def test_repository_target_must_be_exact_before_connection(field, value):
    repository = _FakeRepository(_snapshot())
    setattr(repository.config, field, value)

    with pytest.raises(
        RuntimeReadinessError,
        match="not the exact target",
    ) as error:
        check_runtime_readiness(
            repository,
            expected_source_sha256=SOURCE_HASH,
            expected_catalog_sha256=CATALOG_HASH,
            backup_evidence=_backup(),
        )

    assert error.value.reason_code == "UNSAFE_RUNTIME_CONFIG"
    assert repository.connection_modes == []


def test_runtime_collection_uses_one_read_only_connection():
    repository = _FakeRepository(_snapshot())
    report = check_runtime_readiness(
        repository,
        expected_source_sha256=SOURCE_HASH,
        expected_catalog_sha256=CATALOG_HASH,
        backup_evidence=_backup(),
    )

    assert report.success is True
    assert repository.connection_modes == [True]
    assert repository.fake_connection.transaction_count == 1
    assert all(
        not query.lstrip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP")
        )
        for query, _ in repository.fake_connection.cursor_instance.calls
    )


def test_database_failure_is_redacted():
    repository = _FailingRepository()

    with pytest.raises(
        RuntimeReadinessError,
        match="readiness query failed",
    ) as error:
        check_runtime_readiness(
            repository,
            expected_source_sha256=SOURCE_HASH,
            expected_catalog_sha256=CATALOG_HASH,
            backup_evidence=_backup(),
        )

    assert error.value.reason_code == "READINESS_QUERY_FAILED"
    assert "private-database-detail" not in str(error.value)


def test_gate_9_3_module_contains_no_database_writes():
    source = inspect.getsource(runtime_readiness)

    assert "INSERT INTO" not in source
    assert "UPDATE merchant_ops" not in source
    assert "DELETE FROM" not in source
    assert "ALTER TABLE" not in source
    assert "CREATE TABLE" not in source
    assert "commit(" not in source


class _FakeCursor:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []
        self.current_rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, parameters=()):
        normalized = " ".join(str(query).split())
        self.calls.append((normalized, parameters))

        if "current_database() AS database" in normalized:
            self.current_rows = [self.snapshot["identity"]]
        elif "FROM pg_catalog.pg_namespace" in normalized:
            schema = self.snapshot["schema"]
            self.current_rows = [] if schema is None else [schema]
        elif "FROM information_schema.tables" in normalized:
            self.current_rows = [
                {"table_name": name}
                for name in self.snapshot["tables"]
            ]
        elif "FROM merchant_ops.schema_migrations" in normalized:
            self.current_rows = list(self.snapshot["migrations"])
        elif "SELECT COUNT(*) AS count FROM merchant_ops." in normalized:
            table = normalized.rsplit(".", 1)[1]
            self.current_rows = [
                {"count": self.snapshot["business_counts"][table]}
            ]
        elif "GROUP BY account_status" in normalized:
            self.current_rows = [
                {"account_status": status, "count": count}
                for status, count in sorted(
                    self.snapshot["status_counts"].items()
                )
            ]
        elif "FROM merchant_ops.workflow_templates AS template" in normalized:
            self.current_rows = list(self.snapshot["templates"])
        else:
            raise AssertionError(f"Unexpected query: {normalized}")

    def fetchone(self):
        return self.current_rows[0] if self.current_rows else None

    def fetchall(self):
        return list(self.current_rows)


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _FakeConnection:
    def __init__(self, snapshot):
        self.cursor_instance = _FakeCursor(snapshot)
        self.transaction_count = 0

    def transaction(self):
        self.transaction_count += 1
        return _FakeTransaction()

    def cursor(self):
        return self.cursor_instance


class _FakeRepository:
    def __init__(self, snapshot):
        self.config = SimpleNamespace(
            host="127.0.0.1",
            port=5434,
            database="coding_agent_merchant",
            user="merchant_app",
        )
        self.fake_connection = _FakeConnection(snapshot)
        self.connection_modes = []

    @contextmanager
    def connection(self, *, read_only=False):
        self.connection_modes.append(read_only)
        yield self.fake_connection


class _FailingRepository:
    def __init__(self):
        self.config = SimpleNamespace(
            host="127.0.0.1",
            port=5434,
            database="coding_agent_merchant",
            user="merchant_app",
        )

    @contextmanager
    def connection(self, *, read_only=False):
        raise RuntimeError("private-database-detail")
        yield
