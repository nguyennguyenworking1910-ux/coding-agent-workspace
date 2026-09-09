"""Fail-closed planning for the Checkpoint 10 runtime lease migration."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .runtime_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS as CHECKPOINT_9_APPLIED,
    EXPECTED_PENDING_MIGRATIONS as CHECKPOINT_9_PENDING,
    MigrationBinding,
)
from .runtime_readiness import RuntimeBackupEvidence
from .runtime_verification import (
    EXPECTED_RECORD_COUNT,
    EXPECTED_STATUS_COUNTS,
    RuntimeVerificationReport,
)


DEPLOYMENT_PLAN_VERSION = 1
RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 5434
RUNTIME_DATABASE = "coding_agent_merchant"
RUNTIME_PLAN_ROLE = "merchant_app"
RUNTIME_APPLY_ROLE = "merchant_owner"
RUNTIME_REDACTED_CONNECTION = (
    "postgresql://merchant_app@127.0.0.1:5434/"
    "coding_agent_merchant"
)
MIGRATION_AUTHORIZATION_PHRASE = (
    "ALERT_LEASE_MIGRATION_4_AUTHORIZED"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_APPLIED_MIGRATIONS = (
    *CHECKPOINT_9_APPLIED,
    *CHECKPOINT_9_PENDING,
)
EXPECTED_PENDING_MIGRATIONS = (
    MigrationBinding(
        version=4,
        description="add_alert_delivery_leases",
        checksum=(
            "5d305951e7970d982f3d839bc0bb1363d"
            "96beb16312445b07cdbde777109e110"
        ),
    ),
)


class RuntimeAlertMigrationPlanError(RuntimeError):
    """A value-safe rejection at the runtime migration boundary."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeAlertMigrationDeploymentPlan:
    """Immutable review evidence; this object cannot apply migrations."""

    applied_migrations: tuple[MigrationBinding, ...]
    pending_migrations: tuple[MigrationBinding, ...]
    backup_sha256: str
    source_sha256: str
    catalog_sha256: str
    plan_sha256: str

    @property
    def requires_authorization(self) -> bool:
        return self.pending_migrations == EXPECTED_PENDING_MIGRATIONS

    def safe_summary(self) -> dict[str, Any]:
        return {
            "success": True,
            "plan_version": DEPLOYMENT_PLAN_VERSION,
            "target": {
                "host": RUNTIME_HOST,
                "port": RUNTIME_PORT,
                "database": RUNTIME_DATABASE,
                "plan_role": RUNTIME_PLAN_ROLE,
                "apply_role": RUNTIME_APPLY_ROLE,
            },
            "applied_migrations": [
                item.safe_summary()
                for item in self.applied_migrations
            ],
            "pending_migrations": [
                item.safe_summary()
                for item in self.pending_migrations
            ],
            "runtime_state": {
                "merchant_count": EXPECTED_RECORD_COUNT,
                "merchant_status_counts": dict(
                    EXPECTED_STATUS_COUNTS
                ),
                "template_count": 4,
                "template_step_count": 64,
                "template_dependency_count": 68,
                "catalog_event_count": 22,
                "noncatalog_business_rows": 0,
                "alert_delivery_count": 0,
            },
            "source_sha256": self.source_sha256,
            "catalog_sha256": self.catalog_sha256,
            "backup_sha256": self.backup_sha256,
            "plan_sha256": self.plan_sha256,
            "requires_authorization": self.requires_authorization,
            "authorization_phrase": MIGRATION_AUTHORIZATION_PHRASE,
            "execution_contract": {
                "runner_sessions": 1,
                "migration_order": [4],
                "transaction_scope": "ONE_PER_MIGRATION",
                "advisory_lock": True,
                "forward_only": True,
                "catalog_changes": 0,
                "template_changes": 0,
                "business_record_changes": 0,
                "alert_delivery_backfill_rows": 0,
            },
        }

    def __repr__(self) -> str:
        return (
            "RuntimeAlertMigrationDeploymentPlan("
            "applied_versions=(1, 2, 3), "
            "pending_versions=(4,), "
            f"backup_sha256={self.backup_sha256!r}, "
            f"plan_sha256={self.plan_sha256!r})"
        )


def build_runtime_alert_migration_deployment_plan(
    verification: RuntimeVerificationReport,
    migration_plan: Mapping[str, Any],
    backup: RuntimeBackupEvidence,
    *,
    expected_backup_sha256: str,
) -> RuntimeAlertMigrationDeploymentPlan:
    """Bind a fresh backup and exact runtime state to migration 4 only."""

    backup_hash = _reviewed_hash(expected_backup_sha256)
    _validate_verification(verification)
    _validate_backup(backup, backup_hash)

    if not isinstance(migration_plan, Mapping):
        raise RuntimeAlertMigrationPlanError(
            "Runtime migration plan must be a mapping",
            reason_code="INVALID_PLAN",
        )

    _validate_plan_envelope(migration_plan)
    applied = _migration_bindings(
        migration_plan.get("applied_migrations"),
        label="applied",
    )
    pending = _migration_bindings(
        migration_plan.get("pending_migrations"),
        label="pending",
    )

    if applied != EXPECTED_APPLIED_MIGRATIONS:
        raise RuntimeAlertMigrationPlanError(
            "Applied migrations differ from the Checkpoint 9 boundary",
            reason_code="APPLIED_BASELINE_MISMATCH",
        )

    if pending != EXPECTED_PENDING_MIGRATIONS:
        raise RuntimeAlertMigrationPlanError(
            "Pending migrations are not exactly reviewed version 4",
            reason_code="PENDING_MIGRATIONS_MISMATCH",
        )

    plan_hash = _deployment_hash(
        applied=applied,
        pending=pending,
        backup_sha256=backup_hash,
        source_sha256=verification.source_sha256,
        catalog_sha256=verification.catalog_sha256,
    )
    return RuntimeAlertMigrationDeploymentPlan(
        applied_migrations=applied,
        pending_migrations=pending,
        backup_sha256=backup_hash,
        source_sha256=verification.source_sha256,
        catalog_sha256=verification.catalog_sha256,
        plan_sha256=plan_hash,
    )


def _validate_verification(verification: Any) -> None:
    expected_reads = {
        "all_merchants": 22,
        "onboarding_merchants": 22,
        "active_merchants": 0,
        "projects": 0,
        "alerts": 0,
    }
    exact = (
        isinstance(verification, RuntimeVerificationReport)
        and verification.success is True
        and verification.failed_checks == ()
        and verification.record_count == EXPECTED_RECORD_COUNT
        and dict(verification.status_counts)
        == EXPECTED_STATUS_COUNTS
        and dict(verification.ordinary_reads) == expected_reads
        and verification.migration_versions == (1, 2, 3)
        and verification.template_count == 4
        and verification.template_step_count == 64
        and verification.template_dependency_count == 68
        and verification.catalog_event_count == 22
        and verification.catalog_sha256
        == verification.stored_catalog_sha256
        and SHA256_PATTERN.fullmatch(
            verification.source_sha256
        )
        is not None
        and SHA256_PATTERN.fullmatch(
            verification.catalog_sha256
        )
        is not None
    )

    if not exact:
        raise RuntimeAlertMigrationPlanError(
            "Runtime no longer matches the verified Checkpoint 9 state",
            reason_code="RUNTIME_STATE_MISMATCH",
        )


def _validate_backup(
    backup: Any,
    expected_backup_sha256: str,
) -> None:
    exact = (
        isinstance(backup, RuntimeBackupEvidence)
        and backup.ready is True
        and backup.backup_sha256 == expected_backup_sha256
    )

    if not exact:
        raise RuntimeAlertMigrationPlanError(
            "Fresh runtime backup evidence is not exact",
            reason_code="BACKUP_EVIDENCE_MISMATCH",
        )


def _validate_plan_envelope(plan: Mapping[str, Any]) -> None:
    exact = (
        plan.get("success") is True
        and plan.get("mode") == "plan"
        and plan.get("selected_target") == "runtime"
        and plan.get("redacted_connection")
        == RUNTIME_REDACTED_CONNECTION
        and plan.get("errors") == []
        and plan.get("checksum_conflicts") == []
        and plan.get("missing_local_versions") == []
    )

    if not exact:
        raise RuntimeAlertMigrationPlanError(
            "Read-only migration plan envelope is not exact",
            reason_code="PLAN_ENVELOPE_MISMATCH",
        )


def _migration_bindings(
    records: Any,
    *,
    label: str,
) -> tuple[MigrationBinding, ...]:
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes, bytearray))
    ):
        raise RuntimeAlertMigrationPlanError(
            f"Runtime {label} migrations must be a sequence",
            reason_code=f"INVALID_{label.upper()}_MIGRATIONS",
        )

    bindings: list[MigrationBinding] = []

    for record in records:
        if not isinstance(record, Mapping):
            raise RuntimeAlertMigrationPlanError(
                f"Runtime {label} migration entry is invalid",
                reason_code=f"INVALID_{label.upper()}_MIGRATION",
            )

        version = record.get("version")
        description = record.get("description")
        checksum = record.get("checksum")
        if isinstance(version, bool) or not isinstance(version, int):
            raise RuntimeAlertMigrationPlanError(
                f"Runtime {label} migration version is invalid",
                reason_code=f"INVALID_{label.upper()}_VERSION",
            )
        if not isinstance(description, str) or not description:
            raise RuntimeAlertMigrationPlanError(
                f"Runtime {label} migration description is invalid",
                reason_code=f"INVALID_{label.upper()}_DESCRIPTION",
            )
        if (
            not isinstance(checksum, str)
            or SHA256_PATTERN.fullmatch(checksum) is None
        ):
            raise RuntimeAlertMigrationPlanError(
                f"Runtime {label} migration checksum is invalid",
                reason_code=f"INVALID_{label.upper()}_CHECKSUM",
            )
        bindings.append(
            MigrationBinding(version, description, checksum)
        )

    versions = tuple(item.version for item in bindings)
    if len(set(versions)) != len(versions):
        raise RuntimeAlertMigrationPlanError(
            f"Runtime {label} migration versions are duplicated",
            reason_code=f"DUPLICATE_{label.upper()}_VERSION",
        )
    return tuple(bindings)


def _reviewed_hash(value: Any) -> str:
    if (
        not isinstance(value, str)
        or SHA256_PATTERN.fullmatch(value) is None
    ):
        raise RuntimeAlertMigrationPlanError(
            "Reviewed backup hash must be a lowercase SHA-256",
            reason_code="INVALID_BACKUP_HASH",
        )
    return value


def _deployment_hash(
    *,
    applied: Sequence[MigrationBinding],
    pending: Sequence[MigrationBinding],
    backup_sha256: str,
    source_sha256: str,
    catalog_sha256: str,
) -> str:
    document = {
        "plan_version": DEPLOYMENT_PLAN_VERSION,
        "target": {
            "host": RUNTIME_HOST,
            "port": RUNTIME_PORT,
            "database": RUNTIME_DATABASE,
            "plan_role": RUNTIME_PLAN_ROLE,
            "apply_role": RUNTIME_APPLY_ROLE,
        },
        "applied_migrations": [
            item.safe_summary() for item in applied
        ],
        "pending_migrations": [
            item.safe_summary() for item in pending
        ],
        "source_sha256": source_sha256,
        "catalog_sha256": catalog_sha256,
        "backup_sha256": backup_sha256,
        "execution_contract": {
            "runner_sessions": 1,
            "migration_order": [4],
            "transaction_scope": "ONE_PER_MIGRATION",
            "advisory_lock": True,
            "forward_only": True,
            "catalog_changes": 0,
            "template_changes": 0,
            "business_record_changes": 0,
            "alert_delivery_backfill_rows": 0,
        },
    }
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
