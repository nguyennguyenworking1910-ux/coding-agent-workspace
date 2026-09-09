"""Redacted verification for the applied Checkpoint 10 runtime migration."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .runtime_alert_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS,
    EXPECTED_PENDING_MIGRATIONS,
    RUNTIME_DATABASE,
    RUNTIME_PLAN_ROLE,
    RUNTIME_REDACTED_CONNECTION,
)
from .runtime_migration_plan import MigrationBinding
from .runtime_readiness import RuntimeBackupEvidence
from .runtime_verification import (
    EXPECTED_RECORD_COUNT,
    EXPECTED_STATUS_COUNTS,
    RuntimeVerificationReport,
)


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_ALL_MIGRATIONS = (
    *EXPECTED_APPLIED_MIGRATIONS,
    *EXPECTED_PENDING_MIGRATIONS,
)


class RuntimeAlertMigrationVerificationError(RuntimeError):
    """A value-safe rejection at the post-migration boundary."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeAlertMigrationVerificationReport:
    """Private-value-free proof of the migrated runtime."""

    checks: Mapping[str, bool]
    backup_sha256: str
    source_sha256: str
    catalog_sha256: str

    @property
    def success(self) -> bool:
        return bool(self.checks) and all(self.checks.values())

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(
            name for name, passed in self.checks.items() if not passed
        )

    def safe_summary(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "checks": dict(self.checks),
            "failed_checks": list(self.failed_checks),
            "database": {
                "database": RUNTIME_DATABASE,
                "application_role": RUNTIME_PLAN_ROLE,
                "alert_role": "merchant_alert",
                "read_only": "on",
                "encoding": "UTF8",
            },
            "migration_versions": [1, 2, 3, 4],
            "migration_4_sha256": (
                EXPECTED_PENDING_MIGRATIONS[0].checksum
            ),
            "runtime_state": {
                "merchant_count": EXPECTED_RECORD_COUNT,
                "merchant_status_counts": dict(
                    EXPECTED_STATUS_COUNTS
                ),
                "template_count": 4,
                "template_step_count": 64,
                "template_dependency_count": 68,
                "catalog_event_count": 22,
                "project_count": 0,
                "alert_delivery_count": 0,
            },
            "source_sha256": self.source_sha256,
            "catalog_sha256": self.catalog_sha256,
            "backup_sha256": self.backup_sha256,
        }

    def __repr__(self) -> str:
        return (
            "RuntimeAlertMigrationVerificationReport("
            f"success={self.success}, "
            f"failed_checks={self.failed_checks!r}, "
            f"backup_sha256={self.backup_sha256!r})"
        )


def verify_runtime_alert_migration(
    checkpoint9_verification: RuntimeVerificationReport,
    migration_status: Mapping[str, Any],
    alert_health: Mapping[str, Any],
    backup: RuntimeBackupEvidence,
    *,
    expected_backup_sha256: str,
) -> RuntimeAlertMigrationVerificationReport:
    """Accept only the exact, read-only post-migration runtime state."""

    backup_hash = _reviewed_hash(expected_backup_sha256)
    source_hash = getattr(
        checkpoint9_verification, "source_sha256", ""
    )
    catalog_hash = getattr(
        checkpoint9_verification, "catalog_sha256", ""
    )
    checks = {
        "checkpoint_9_catalog_state_preserved": (
            _checkpoint9_state_preserved(checkpoint9_verification)
        ),
        "migration_history_exact": (
            _migration_status_exact(migration_status)
        ),
        "runtime_alert_role_healthy": (
            _alert_health_exact(alert_health)
        ),
        "runtime_alert_queue_empty": (
            isinstance(alert_health, Mapping)
            and alert_health.get("queues") == []
        ),
        "fresh_backup_still_bound": (
            isinstance(backup, RuntimeBackupEvidence)
            and backup.ready is True
            and backup.backup_sha256 == backup_hash
        ),
        "catalog_hash_binding_preserved": (
            isinstance(source_hash, str)
            and SHA256_PATTERN.fullmatch(source_hash) is not None
            and isinstance(catalog_hash, str)
            and SHA256_PATTERN.fullmatch(catalog_hash) is not None
            and catalog_hash
            == getattr(
                checkpoint9_verification,
                "stored_catalog_sha256",
                None,
            )
        ),
    }
    return RuntimeAlertMigrationVerificationReport(
        checks=checks,
        backup_sha256=backup_hash,
        source_sha256=source_hash,
        catalog_sha256=catalog_hash,
    )


def _checkpoint9_state_preserved(report: Any) -> bool:
    if not isinstance(report, RuntimeVerificationReport):
        return False
    expected_reads = {
        "all_merchants": 22,
        "onboarding_merchants": 22,
        "active_merchants": 0,
        "projects": 0,
        "alerts": 0,
    }
    nonmigration_checks = {
        name: passed
        for name, passed in report.checks.items()
        if name != "migration_history_exact"
    }
    return (
        report.success is False
        and report.failed_checks == ("migration_history_exact",)
        and bool(nonmigration_checks)
        and all(nonmigration_checks.values())
        and report.record_count == EXPECTED_RECORD_COUNT
        and dict(report.status_counts) == EXPECTED_STATUS_COUNTS
        and dict(report.ordinary_reads) == expected_reads
        and report.migration_versions == (1, 2, 3, 4)
        and report.template_count == 4
        and report.template_step_count == 64
        and report.template_dependency_count == 68
        and report.catalog_event_count == 22
    )


def _migration_status_exact(status: Any) -> bool:
    if not isinstance(status, Mapping):
        return False
    if not (
        status.get("success") is True
        and status.get("mode") == "status"
        and status.get("selected_target") == "runtime"
        and status.get("redacted_connection")
        == RUNTIME_REDACTED_CONNECTION
        and status.get("pending_migrations") == []
        and status.get("checksum_conflicts") == []
        and status.get("missing_local_versions") == []
        and status.get("errors") == []
    ):
        return False
    return _migration_bindings(
        status.get("applied_migrations")
    ) == EXPECTED_ALL_MIGRATIONS


def _migration_bindings(records: Any) -> tuple[MigrationBinding, ...]:
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes, bytearray))
    ):
        return ()
    bindings = []
    try:
        for record in records:
            if not isinstance(record, Mapping):
                return ()
            bindings.append(
                MigrationBinding(
                    version=int(record["version"]),
                    description=str(record["description"]),
                    checksum=str(record["checksum"]),
                )
            )
    except (KeyError, TypeError, ValueError):
        return ()
    return tuple(bindings)


def _alert_health_exact(health: Any) -> bool:
    if not isinstance(health, Mapping):
        return False
    checks = health.get("checks")
    database = health.get("database")
    return (
        health.get("success") is True
        and health.get("mode") == "health_check"
        and isinstance(checks, Mapping)
        and bool(checks)
        and all(value is True for value in checks.values())
        and health.get("failed_checks") == []
        and database
        == {
            "database": RUNTIME_DATABASE,
            "user": "merchant_alert",
            "read_only": "on",
            "encoding": "UTF8",
        }
    )


def _reviewed_hash(value: Any) -> str:
    if (
        not isinstance(value, str)
        or SHA256_PATTERN.fullmatch(value) is None
    ):
        raise RuntimeAlertMigrationVerificationError(
            "Reviewed backup hash must be a lowercase SHA-256",
            reason_code="INVALID_BACKUP_HASH",
        )
    return value
