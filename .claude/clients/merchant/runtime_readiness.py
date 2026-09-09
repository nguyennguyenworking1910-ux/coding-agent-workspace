"""Read-only readiness assessment for private Merchant initialization."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from claude.agents.tools.merchant.workflow_templates import (
    standard_template_manifest,
)


RUNTIME_DATABASE = "coding_agent_merchant"
RUNTIME_APPLICATION_ROLE = "merchant_app"
RUNTIME_OWNER_ROLE = "merchant_owner"
RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 5434
SCHEMA_NAME = "merchant_ops"

RUNTIME_MIGRATIONS_READY = "RUNTIME_MIGRATIONS_READY"
TEMPLATE_INITIALIZATION_READY = "TEMPLATE_INITIALIZATION_READY"
CATALOG_INITIALIZATION_READY = "CATALOG_INITIALIZATION_READY"
NOT_READY = "NOT_READY"

EXPECTED_TABLES = frozenset(
    {
        "alert_deliveries",
        "document_approvals",
        "document_revisions",
        "integration_identifiers",
        "merchant_contacts",
        "merchants",
        "procurement_records",
        "project_events",
        "project_step_dependencies",
        "project_steps",
        "projects",
        "schema_migrations",
        "workflow_template_dependencies",
        "workflow_template_steps",
        "workflow_templates",
    }
)

BUSINESS_TABLES = (
    "merchants",
    "merchant_contacts",
    "projects",
    "project_steps",
    "project_step_dependencies",
    "document_revisions",
    "document_approvals",
    "procurement_records",
    "integration_identifiers",
    "project_events",
    "alert_deliveries",
)

ALLOWED_MERCHANT_STATUSES = frozenset(
    {
        "ONBOARDING",
        "ACTIVE",
    }
)

MIGRATIONS_DIRECTORY = Path(__file__).parent / "migrations"
EXPECTED_MIGRATION_VERSIONS = (1, 2, 3)
KNOWN_LOCAL_MIGRATION_VERSIONS = (1, 2, 3, 4)
MAX_BACKUP_AGE = timedelta(hours=24)
MAX_BACKUP_FUTURE_SKEW = timedelta(minutes=5)
BACKUP_MAGIC = b"PGDMP"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RuntimeReadinessError(RuntimeError):
    """A value-safe failure at the runtime readiness boundary."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class RuntimeBackupError(RuntimeReadinessError):
    """Raised when local backup evidence is incomplete or invalid."""


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeBackupEvidence:
    """Non-secret evidence for one fresh runtime backup."""

    backup_sha256: str
    size_bytes: int
    created_at_utc: datetime
    format: str
    restore_list_verified: bool
    recovery_procedure_reviewed: bool
    roles_recoverable: bool

    @property
    def ready(self) -> bool:
        return (
            self.format == "POSTGRESQL_CUSTOM"
            and self.size_bytes > len(BACKUP_MAGIC)
            and self.restore_list_verified is True
            and self.recovery_procedure_reviewed is True
            and self.roles_recoverable is True
        )

    def safe_summary(self) -> dict[str, Any]:
        return {
            "backup_sha256": self.backup_sha256,
            "size_bytes": self.size_bytes,
            "created_at_utc": self.created_at_utc.isoformat(),
            "format": self.format,
            "restore_list_verified": self.restore_list_verified,
            "recovery_procedure_reviewed": (
                self.recovery_procedure_reviewed
            ),
            "roles_recoverable": self.roles_recoverable,
        }

    def __repr__(self) -> str:
        return (
            "RuntimeBackupEvidence("
            f"backup_sha256={self.backup_sha256!r}, "
            f"size_bytes={self.size_bytes}, "
            f"created_at_utc={self.created_at_utc.isoformat()!r}, "
            f"ready={self.ready})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeReadinessReport:
    """Redacted decision report for the next authorized runtime gate."""

    success: bool
    state: str
    checks: Mapping[str, bool]
    database: str
    user: str
    encoding: str
    read_only: str
    schema_owner: str | None
    applied_versions: tuple[int, ...]
    pending_versions: tuple[int, ...]
    migration_3_sha256: str
    business_counts: Mapping[str, int]
    merchant_status_counts: Mapping[str, int]
    stored_template_count: int
    expected_template_sha256: str
    stored_template_sha256: str
    source_sha256: str
    catalog_sha256: str
    backup: RuntimeBackupEvidence

    @property
    def migration_3_required(self) -> bool:
        return 3 in self.pending_versions

    @property
    def runtime_migrations_required(self) -> bool:
        return bool(self.pending_versions)

    @property
    def template_initialization_required(self) -> bool:
        return self.state == TEMPLATE_INITIALIZATION_READY

    @property
    def standard_templates_match(self) -> bool:
        return (
            self.expected_template_sha256
            == self.stored_template_sha256
        )

    @property
    def catalog_initialization_ready(self) -> bool:
        return self.state == CATALOG_INITIALIZATION_READY

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, passed in self.checks.items()
            if not passed
        )

    def safe_summary(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "state": self.state,
            "checks": dict(self.checks),
            "failed_checks": list(self.failed_checks),
            "database": {
                "database": self.database,
                "user": self.user,
                "encoding": self.encoding,
                "read_only": self.read_only,
                "schema_owner": self.schema_owner,
            },
            "applied_versions": list(self.applied_versions),
            "pending_versions": list(self.pending_versions),
            "migration_3_sha256": self.migration_3_sha256,
            "migration_3_required": self.migration_3_required,
            "runtime_migrations_required": (
                self.runtime_migrations_required
            ),
            "template_initialization_required": (
                self.template_initialization_required
            ),
            "catalog_initialization_ready": (
                self.catalog_initialization_ready
            ),
            "business_counts": dict(self.business_counts),
            "merchant_status_counts": dict(
                self.merchant_status_counts
            ),
            "stored_template_count": self.stored_template_count,
            "standard_templates_match": (
                self.standard_templates_match
            ),
            "expected_template_sha256": (
                self.expected_template_sha256
            ),
            "stored_template_sha256": self.stored_template_sha256,
            "source_sha256": self.source_sha256,
            "catalog_sha256": self.catalog_sha256,
            "backup": self.backup.safe_summary(),
        }

    def __repr__(self) -> str:
        return (
            "RuntimeReadinessReport("
            f"success={self.success}, "
            f"state={self.state!r}, "
            f"applied_versions={self.applied_versions!r}, "
            f"pending_versions={self.pending_versions!r}, "
            f"failed_checks={self.failed_checks!r})"
        )


def inspect_runtime_backup(
    source_path: str | os.PathLike[str],
    *,
    restore_list_verified: bool,
    recovery_procedure_reviewed: bool,
    roles_recoverable: bool,
    now: datetime | None = None,
) -> RuntimeBackupEvidence:
    """Inspect one private custom-format backup without exposing its path."""

    if restore_list_verified is not True:
        raise RuntimeBackupError(
            "Runtime backup archive listing has not been verified",
            reason_code="BACKUP_LIST_NOT_VERIFIED",
        )

    if recovery_procedure_reviewed is not True:
        raise RuntimeBackupError(
            "Runtime recovery procedure has not been reviewed",
            reason_code="RECOVERY_NOT_REVIEWED",
        )

    if roles_recoverable is not True:
        raise RuntimeBackupError(
            "Runtime database roles are not recoverable",
            reason_code="ROLES_NOT_RECOVERABLE",
        )

    try:
        path = Path(source_path)
    except (TypeError, ValueError):
        raise RuntimeBackupError(
            "Runtime backup path is invalid",
            reason_code="INVALID_BACKUP_PATH",
        ) from None

    try:
        if not path.is_file():
            raise RuntimeBackupError(
                "Runtime backup source is not a file",
                reason_code="BACKUP_NOT_FILE",
            )

        stat = path.stat()
        digest = hashlib.sha256()

        with path.open("rb") as stream:
            magic = stream.read(len(BACKUP_MAGIC))
            digest.update(magic)

            while True:
                chunk = stream.read(1024 * 1024)

                if not chunk:
                    break

                digest.update(chunk)
    except RuntimeBackupError:
        raise
    except OSError:
        raise RuntimeBackupError(
            "Runtime backup could not be inspected",
            reason_code="BACKUP_INSPECTION_FAILED",
        ) from None

    if magic != BACKUP_MAGIC:
        raise RuntimeBackupError(
            "Runtime backup must use PostgreSQL custom format",
            reason_code="INVALID_BACKUP_FORMAT",
        )

    current_time = _aware_utc(now or datetime.now(timezone.utc))
    created_at = datetime.fromtimestamp(
        stat.st_mtime,
        tz=timezone.utc,
    )
    age = current_time - created_at

    if age < -MAX_BACKUP_FUTURE_SKEW:
        raise RuntimeBackupError(
            "Runtime backup timestamp is unexpectedly in the future",
            reason_code="BACKUP_FROM_FUTURE",
        )

    if age > MAX_BACKUP_AGE:
        raise RuntimeBackupError(
            "Runtime backup is older than the readiness window",
            reason_code="BACKUP_TOO_OLD",
        )

    evidence = RuntimeBackupEvidence(
        backup_sha256=digest.hexdigest(),
        size_bytes=stat.st_size,
        created_at_utc=created_at,
        format="POSTGRESQL_CUSTOM",
        restore_list_verified=True,
        recovery_procedure_reviewed=True,
        roles_recoverable=True,
    )

    if not evidence.ready:
        raise RuntimeBackupError(
            "Runtime backup evidence is incomplete",
            reason_code="INCOMPLETE_BACKUP_EVIDENCE",
        )

    return evidence


def check_runtime_readiness(
    repository: Any,
    *,
    expected_source_sha256: str,
    expected_catalog_sha256: str,
    backup_evidence: RuntimeBackupEvidence,
) -> RuntimeReadinessReport:
    """Collect and assess runtime state through one read-only connection."""

    source_hash = _reviewed_hash(
        expected_source_sha256,
        "source",
    )
    catalog_hash = _reviewed_hash(
        expected_catalog_sha256,
        "catalog",
    )

    if not isinstance(backup_evidence, RuntimeBackupEvidence):
        raise RuntimeReadinessError(
            "Runtime readiness requires validated backup evidence",
            reason_code="INVALID_BACKUP_EVIDENCE",
        )

    config = getattr(repository, "config", None)

    if config is None:
        raise RuntimeReadinessError(
            "Runtime readiness requires repository configuration",
            reason_code="MISSING_REPOSITORY_CONFIG",
        )

    config_is_exact = (
        getattr(config, "host", None) == RUNTIME_HOST
        and getattr(config, "port", None) == RUNTIME_PORT
        and getattr(config, "database", None) == RUNTIME_DATABASE
        and getattr(config, "user", None) == RUNTIME_APPLICATION_ROLE
    )

    if not config_is_exact:
        raise RuntimeReadinessError(
            "Runtime repository configuration is not the exact target",
            reason_code="UNSAFE_RUNTIME_CONFIG",
        )

    local_migrations = _local_migration_manifest()

    try:
        snapshot = _collect_runtime_snapshot(repository)
    except RuntimeReadinessError:
        raise
    except Exception:
        raise RuntimeReadinessError(
            "Runtime readiness query failed",
            reason_code="READINESS_QUERY_FAILED",
        ) from None

    return _assess_runtime_snapshot(
        snapshot,
        local_migrations=local_migrations,
        source_sha256=source_hash,
        catalog_sha256=catalog_hash,
        backup_evidence=backup_evidence,
        config_is_exact=config_is_exact,
    )


def _collect_runtime_snapshot(repository: Any) -> dict[str, Any]:
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
                    SELECT
                        namespace.nspname AS schema_name,
                        owner.rolname AS schema_owner
                    FROM pg_catalog.pg_namespace AS namespace
                    JOIN pg_catalog.pg_roles AS owner
                      ON owner.oid = namespace.nspowner
                    WHERE namespace.nspname = %s
                    """,
                    (SCHEMA_NAME,),
                )
                schema_row = cursor.fetchone()
                schema = (
                    dict(schema_row)
                    if schema_row is not None
                    else None
                )

                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """,
                    (SCHEMA_NAME,),
                )
                tables = tuple(
                    str(row["table_name"])
                    for row in cursor.fetchall()
                )

                cursor.execute(
                    """
                    SELECT version, description, checksum
                    FROM merchant_ops.schema_migrations
                    ORDER BY version
                    """,
                    (),
                )
                migrations = tuple(
                    dict(row) for row in cursor.fetchall()
                )

                business_counts: dict[str, int] = {}

                for table in BUSINESS_TABLES:
                    cursor.execute(
                        "SELECT COUNT(*) AS count "
                        f"FROM merchant_ops.{table}",
                        (),
                    )
                    business_counts[table] = int(
                        cursor.fetchone()["count"]
                    )

                cursor.execute(
                    """
                    SELECT account_status, COUNT(*) AS count
                    FROM merchant_ops.merchants
                    GROUP BY account_status
                    ORDER BY account_status
                    """,
                    (),
                )
                status_counts = {
                    str(row["account_status"]): int(row["count"])
                    for row in cursor.fetchall()
                }

                cursor.execute(
                    """
                    SELECT
                        template.id AS template_id,
                        template.name,
                        template.version,
                        template.variant,
                        COUNT(DISTINCT step.id) AS step_count,
                        (
                            SELECT COUNT(*)
                            FROM merchant_ops
                                .workflow_template_dependencies
                                AS dependency
                            JOIN merchant_ops.workflow_template_steps
                                AS source_step
                              ON source_step.id =
                                 dependency.from_step_id
                            WHERE source_step.template_id = template.id
                        ) AS dependency_count
                    FROM merchant_ops.workflow_templates AS template
                    LEFT JOIN merchant_ops.workflow_template_steps AS step
                      ON step.template_id = template.id
                    GROUP BY
                        template.id,
                        template.name,
                        template.version,
                        template.variant
                    ORDER BY template.name, template.version
                    """,
                    (),
                )
                templates = tuple(
                    _normalized_template_row(row)
                    for row in cursor.fetchall()
                )

    return {
        "identity": identity,
        "schema": schema,
        "tables": tables,
        "migrations": migrations,
        "business_counts": business_counts,
        "status_counts": status_counts,
        "templates": templates,
    }


def _assess_runtime_snapshot(
    snapshot: Mapping[str, Any],
    *,
    local_migrations: Sequence[Mapping[str, Any]],
    source_sha256: str,
    catalog_sha256: str,
    backup_evidence: RuntimeBackupEvidence,
    config_is_exact: bool,
) -> RuntimeReadinessReport:
    identity = dict(snapshot.get("identity") or {})
    schema = snapshot.get("schema")
    schema_record = dict(schema) if schema is not None else {}
    tables = frozenset(snapshot.get("tables") or ())
    business_counts = {
        str(name): int(count)
        for name, count in dict(
            snapshot.get("business_counts") or {}
        ).items()
    }
    status_counts = {
        str(status): int(count)
        for status, count in dict(
            snapshot.get("status_counts") or {}
        ).items()
    }
    stored_templates = tuple(snapshot.get("templates") or ())
    expected_templates = _expected_template_rows()

    local_by_version = {
        int(item["version"]): dict(item)
        for item in local_migrations
    }
    applied_migrations = tuple(snapshot.get("migrations") or ())
    applied_versions = tuple(
        int(item["version"]) for item in applied_migrations
    )
    pending_versions = tuple(
        version
        for version in EXPECTED_MIGRATION_VERSIONS
        if version not in applied_versions
    )

    migration_history_consistent = (
        applied_versions in ((1,), (1, 2), (1, 2, 3))
        and all(
            version in local_by_version
            and str(item.get("description"))
            == str(local_by_version[version]["description"])
            and str(item.get("checksum"))
            == str(local_by_version[version]["checksum"])
            for version, item in zip(
                applied_versions,
                applied_migrations,
                strict=True,
            )
        )
    )
    supported_migration_state = (
        (applied_versions == (1,) and pending_versions == (2, 3))
        or (applied_versions == (1, 2) and pending_versions == (3,))
        or (
            applied_versions == (1, 2, 3)
            and pending_versions == ()
        )
    )
    counts_complete = set(business_counts) == set(BUSINESS_TABLES)
    business_state_empty = (
        counts_complete
        and all(count == 0 for count in business_counts.values())
    )
    statuses_safe = (
        set(status_counts).issubset(ALLOWED_MERCHANT_STATUSES)
        and sum(status_counts.values())
        == business_counts.get("merchants", -1)
    )
    templates_empty = stored_templates == ()
    templates_match = stored_templates == expected_templates
    templates_safe = templates_empty or templates_match

    checks = {
        "repository_config_exact": config_is_exact,
        "runtime_database_exact": identity.get("database")
        == RUNTIME_DATABASE,
        "application_role_exact": identity.get("user")
        == RUNTIME_APPLICATION_ROLE,
        "transaction_read_only": identity.get("read_only") == "on",
        "encoding_utf8": identity.get("encoding") == "UTF8",
        "schema_exists": schema_record.get("schema_name")
        == SCHEMA_NAME,
        "schema_owner_exact": schema_record.get("schema_owner")
        == RUNTIME_OWNER_ROLE,
        "schema_tables_exact": tables == EXPECTED_TABLES,
        "migration_history_consistent": (
            migration_history_consistent
        ),
        "migration_state_supported": supported_migration_state,
        "business_counts_complete": counts_complete,
        "business_state_empty": business_state_empty,
        "merchant_statuses_safe": statuses_safe,
        "standard_templates_safe": templates_safe,
        "backup_evidence_ready": backup_evidence.ready,
        "catalog_hashes_bound": (
            SHA256_PATTERN.fullmatch(source_sha256) is not None
            and SHA256_PATTERN.fullmatch(catalog_sha256) is not None
        ),
    }
    success = all(checks.values())

    if not success:
        state = NOT_READY
    elif pending_versions:
        state = RUNTIME_MIGRATIONS_READY
    elif templates_empty:
        state = TEMPLATE_INITIALIZATION_READY
    else:
        state = CATALOG_INITIALIZATION_READY

    return RuntimeReadinessReport(
        success=success,
        state=state,
        checks=checks,
        database=str(identity.get("database") or ""),
        user=str(identity.get("user") or ""),
        encoding=str(identity.get("encoding") or ""),
        read_only=str(identity.get("read_only") or ""),
        schema_owner=(
            str(schema_record["schema_owner"])
            if schema_record.get("schema_owner") is not None
            else None
        ),
        applied_versions=applied_versions,
        pending_versions=pending_versions,
        migration_3_sha256=str(local_by_version[3]["checksum"]),
        business_counts=business_counts,
        merchant_status_counts=status_counts,
        stored_template_count=len(stored_templates),
        expected_template_sha256=_manifest_hash(
            expected_templates
        ),
        stored_template_sha256=_manifest_hash(
            stored_templates
        ),
        source_sha256=source_sha256,
        catalog_sha256=catalog_sha256,
        backup=backup_evidence,
    )


def _local_migration_manifest() -> tuple[dict[str, Any], ...]:
    paths = sorted(MIGRATIONS_DIRECTORY.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    manifest = []

    for path in paths:
        match = re.fullmatch(
            r"(?P<version>[0-9]{4})_(?P<description>[a-z0-9_]+)\.sql",
            path.name,
        )

        if match is None:
            raise RuntimeReadinessError(
                "Local Merchant migration name is invalid",
                reason_code="INVALID_LOCAL_MIGRATION",
            )

        manifest.append(
            {
                "version": int(match.group("version")),
                "description": match.group("description"),
                "checksum": hashlib.sha256(
                    path.read_bytes()
                ).hexdigest(),
            }
        )

    versions = tuple(item["version"] for item in manifest)

    if versions != KNOWN_LOCAL_MIGRATION_VERSIONS:
        raise RuntimeReadinessError(
            "Local Merchant migration manifest is not exactly 1, 2, 3, 4",
            reason_code="INVALID_LOCAL_MIGRATION_SET",
        )

    # Checkpoint 9 readiness is a historical contract frozen at migrations
    # 1-3. Migration 4 belongs to the separately authorized Checkpoint 10
    # alert-worker rollout and must not retroactively alter catalog planning.
    return tuple(
        item
        for item in manifest
        if item["version"] in EXPECTED_MIGRATION_VERSIONS
    )


def _expected_template_rows() -> tuple[dict[str, Any], ...]:
    return tuple(
        sorted(
            (
                {
                    "template_id": str(item["template_id"]),
                    "name": str(item["name"]),
                    "version": int(item["version"]),
                    "variant": str(item["variant"]),
                    "step_count": int(item["step_count"]),
                    "dependency_count": int(
                        item["dependency_count"]
                    ),
                }
                for item in standard_template_manifest()
            ),
            key=lambda item: (item["name"], item["version"]),
        )
    )


def _normalized_template_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "template_id": str(row["template_id"]),
        "name": str(row["name"]),
        "version": int(row["version"]),
        "variant": str(row["variant"]),
        "step_count": int(row["step_count"]),
        "dependency_count": int(row["dependency_count"]),
    }


def _manifest_hash(records: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(
        list(records),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reviewed_hash(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or SHA256_PATTERN.fullmatch(value) is None
    ):
        raise RuntimeReadinessError(
            f"Reviewed {label} hash must be a lowercase SHA-256",
            reason_code=f"INVALID_{label.upper()}_HASH",
        )

    return value


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise RuntimeBackupError(
            "Runtime backup comparison time must be timezone-aware",
            reason_code="INVALID_BACKUP_TIME",
        )

    return value.astimezone(timezone.utc)
