"""Fail-closed planning for the Checkpoint 9 runtime migrations."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .runtime_readiness import (
    BUSINESS_TABLES,
    RUNTIME_MIGRATIONS_READY,
    RuntimeReadinessReport,
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
    "MIGRATIONS_2_3_AUTHORIZED"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class MigrationBinding:
    """One reviewed migration without a filesystem path."""

    version: int
    description: str
    checksum: str

    def safe_summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "description": self.description,
            "checksum": self.checksum,
        }


EXPECTED_APPLIED_MIGRATIONS = (
    MigrationBinding(
        version=1,
        description="initial_schema",
        checksum=(
            "8ff45d352766953f18ec0378c74cc280"
            "571641d40bcf5f4e27c5bedc700e51f1"
        ),
    ),
)

EXPECTED_PENDING_MIGRATIONS = (
    MigrationBinding(
        version=2,
        description="add_project_payment_period",
        checksum=(
            "e7729b83ae1bbf121e0d94fd095ee4b0"
            "7e18092c72195653fd00c16b3c2fa666"
        ),
    ),
    MigrationBinding(
        version=3,
        description="add_cli_write_grants",
        checksum=(
            "209179ad284a62b9c3d47558bf4cd5093"
            "389d693559af3855257ae9c02439575"
        ),
    ),
)


class RuntimeMigrationPlanError(RuntimeError):
    """A value-safe rejection at the migration plan boundary."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeMigrationDeploymentPlan:
    """An immutable, non-executable migration review surface."""

    applied_migrations: tuple[MigrationBinding, ...]
    pending_migrations: tuple[MigrationBinding, ...]
    backup_sha256: str
    plan_sha256: str

    @property
    def requires_authorization(self) -> bool:
        return bool(self.pending_migrations)

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
            "backup_sha256": self.backup_sha256,
            "plan_sha256": self.plan_sha256,
            "requires_authorization": self.requires_authorization,
            "authorization_phrase": (
                MIGRATION_AUTHORIZATION_PHRASE
            ),
            "execution_contract": {
                "runner_sessions": 1,
                "migration_order": [2, 3],
                "transaction_scope": "ONE_PER_MIGRATION",
                "advisory_lock": True,
                "forward_only": True,
                "template_changes": 0,
                "catalog_changes": 0,
            },
        }

    def __repr__(self) -> str:
        applied_versions = tuple(
            item.version for item in self.applied_migrations
        )
        pending_versions = tuple(
            item.version for item in self.pending_migrations
        )
        return (
            "RuntimeMigrationDeploymentPlan("
            f"applied_versions={applied_versions!r}, "
            f"pending_versions={pending_versions!r}, "
            f"backup_sha256={self.backup_sha256!r}, "
            f"plan_sha256={self.plan_sha256!r})"
        )


def build_runtime_migration_deployment_plan(
    readiness: RuntimeReadinessReport,
    migration_plan: Mapping[str, Any],
    *,
    expected_backup_sha256: str,
) -> RuntimeMigrationDeploymentPlan:
    """Bind the live read-only plan to the reviewed Gate 9.4 scope."""

    backup_hash = _reviewed_hash(expected_backup_sha256)
    _validate_readiness(readiness, backup_hash)

    if not isinstance(migration_plan, Mapping):
        raise RuntimeMigrationPlanError(
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
        raise RuntimeMigrationPlanError(
            "Applied migration baseline differs from Gate 9.3",
            reason_code="APPLIED_BASELINE_MISMATCH",
        )

    if pending != EXPECTED_PENDING_MIGRATIONS:
        raise RuntimeMigrationPlanError(
            "Pending migrations are not exactly reviewed versions 2 and 3",
            reason_code="PENDING_MIGRATIONS_MISMATCH",
        )

    plan_hash = _deployment_hash(
        applied=applied,
        pending=pending,
        backup_sha256=backup_hash,
    )

    return RuntimeMigrationDeploymentPlan(
        applied_migrations=applied,
        pending_migrations=pending,
        backup_sha256=backup_hash,
        plan_sha256=plan_hash,
    )


def _validate_readiness(
    readiness: Any,
    backup_sha256: str,
) -> None:
    if not isinstance(readiness, RuntimeReadinessReport):
        raise RuntimeMigrationPlanError(
            "Gate 9.4 requires a validated runtime readiness report",
            reason_code="INVALID_READINESS_REPORT",
        )

    exact = (
        readiness.success is True
        and readiness.state == RUNTIME_MIGRATIONS_READY
        and readiness.database == RUNTIME_DATABASE
        and readiness.user == RUNTIME_PLAN_ROLE
        and readiness.encoding == "UTF8"
        and readiness.read_only == "on"
        and readiness.schema_owner == RUNTIME_APPLY_ROLE
        and readiness.applied_versions == (1,)
        and readiness.pending_versions == (2, 3)
        and readiness.stored_template_count == 0
        and set(readiness.business_counts) == set(BUSINESS_TABLES)
        and all(
            count == 0
            for count in readiness.business_counts.values()
        )
        and readiness.backup.ready is True
        and readiness.backup.backup_sha256 == backup_sha256
    )

    if not exact:
        raise RuntimeMigrationPlanError(
            "Runtime readiness no longer matches the reviewed Gate 9.3 state",
            reason_code="READINESS_STATE_MISMATCH",
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
        raise RuntimeMigrationPlanError(
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
        raise RuntimeMigrationPlanError(
            f"Runtime {label} migrations must be a sequence",
            reason_code=f"INVALID_{label.upper()}_MIGRATIONS",
        )

    bindings: list[MigrationBinding] = []

    for record in records:
        if not isinstance(record, Mapping):
            raise RuntimeMigrationPlanError(
                f"Runtime {label} migration entry is invalid",
                reason_code=f"INVALID_{label.upper()}_MIGRATION",
            )

        version = record.get("version")
        description = record.get("description")
        checksum = record.get("checksum")

        if isinstance(version, bool) or not isinstance(version, int):
            raise RuntimeMigrationPlanError(
                f"Runtime {label} migration version is invalid",
                reason_code=f"INVALID_{label.upper()}_VERSION",
            )

        if not isinstance(description, str) or not description:
            raise RuntimeMigrationPlanError(
                f"Runtime {label} migration description is invalid",
                reason_code=f"INVALID_{label.upper()}_DESCRIPTION",
            )

        if (
            not isinstance(checksum, str)
            or SHA256_PATTERN.fullmatch(checksum) is None
        ):
            raise RuntimeMigrationPlanError(
                f"Runtime {label} migration checksum is invalid",
                reason_code=f"INVALID_{label.upper()}_CHECKSUM",
            )

        bindings.append(
            MigrationBinding(
                version=version,
                description=description,
                checksum=checksum,
            )
        )

    versions = tuple(item.version for item in bindings)

    if len(set(versions)) != len(versions):
        raise RuntimeMigrationPlanError(
            f"Runtime {label} migration versions are duplicated",
            reason_code=f"DUPLICATE_{label.upper()}_VERSION",
        )

    return tuple(bindings)


def _reviewed_hash(value: Any) -> str:
    if (
        not isinstance(value, str)
        or SHA256_PATTERN.fullmatch(value) is None
    ):
        raise RuntimeMigrationPlanError(
            "Reviewed backup hash must be a lowercase SHA-256",
            reason_code="INVALID_BACKUP_HASH",
        )

    return value


def _deployment_hash(
    *,
    applied: Sequence[MigrationBinding],
    pending: Sequence[MigrationBinding],
    backup_sha256: str,
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
        "backup_sha256": backup_sha256,
        "execution_contract": {
            "runner_sessions": 1,
            "migration_order": [2, 3],
            "transaction_scope": "ONE_PER_MIGRATION",
            "advisory_lock": True,
            "forward_only": True,
            "template_changes": 0,
            "catalog_changes": 0,
        },
    }
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
