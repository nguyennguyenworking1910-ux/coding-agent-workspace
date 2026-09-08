"""Read-only binding for private runtime catalog initialization."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from claude.agents.tools.merchant.catalog_contract import (
    PrivateMerchantCatalog,
)
from claude.agents.tools.merchant.catalog_plan import (
    CATALOG_INSERT,
    CatalogInitializationPlan,
    build_catalog_initialization_plan,
)

from .runtime_readiness import (
    BUSINESS_TABLES,
    CATALOG_INITIALIZATION_READY,
    RuntimeReadinessReport,
)
from .runtime_template_plan import (
    EXPECTED_FULL_TEMPLATE_SHA256,
    EXPECTED_READINESS_TEMPLATE_SHA256,
)


RUNTIME_CATALOG_PLAN_VERSION = 1
RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 5434
RUNTIME_DATABASE = "coding_agent_merchant"
RUNTIME_WRITE_ROLE = "merchant_app"
CATALOG_AUTHORIZATION_PHRASE = (
    "PRIVATE_CATALOG_22_AUTHORIZED"
)
CATALOG_AUDIT_EVENT_TYPE = "MERCHANT_CATALOG_INITIALIZED"
EXPECTED_RECORD_COUNT = 22
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RuntimeCatalogPlanError(RuntimeError):
    """A value-safe rejection at the runtime catalog boundary."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeCatalogInitializationPlan:
    """Immutable runtime binding around a private catalog plan."""

    catalog_plan: CatalogInitializationPlan
    backup_sha256: str
    runtime_plan_sha256: str

    def safe_summary(self) -> dict[str, Any]:
        catalog_summary = self.catalog_plan.safe_summary()
        return {
            "success": True,
            "plan_version": RUNTIME_CATALOG_PLAN_VERSION,
            "target": {
                "host": RUNTIME_HOST,
                "port": RUNTIME_PORT,
                "database": RUNTIME_DATABASE,
                "write_role": RUNTIME_WRITE_ROLE,
            },
            "action": catalog_summary["action"],
            "record_count": catalog_summary["record_count"],
            "status_counts": catalog_summary["status_counts"],
            "target_count_before": catalog_summary[
                "target_count_before"
            ],
            "target_count_after": catalog_summary[
                "target_count_after"
            ],
            "source_sha256": catalog_summary["source_sha256"],
            "catalog_sha256": catalog_summary["catalog_sha256"],
            "catalog_plan_sha256": catalog_summary["plan_sha256"],
            "template_manifest_sha256": (
                EXPECTED_FULL_TEMPLATE_SHA256
            ),
            "backup_sha256": self.backup_sha256,
            "runtime_plan_sha256": self.runtime_plan_sha256,
            "requires_authorization": True,
            "authorization_phrase": CATALOG_AUTHORIZATION_PHRASE,
            "execution_contract": {
                "transaction_mode": "SINGLE_ATOMIC_TRANSACTION",
                "idempotency": "IDENTICAL_SOURCE_NO_OP",
                "conflict_behavior": "FAIL_CLOSED",
                "merchant_inserts": EXPECTED_RECORD_COUNT,
                "audit_event_inserts": EXPECTED_RECORD_COUNT,
                "audit_event_type": CATALOG_AUDIT_EVENT_TYPE,
                "contact_inserts": 0,
                "project_inserts": 0,
            },
        }

    def __repr__(self) -> str:
        return (
            "RuntimeCatalogInitializationPlan("
            f"action={self.catalog_plan.action!r}, "
            f"record_count={self.catalog_plan.record_count}, "
            f"source_sha256={self.catalog_plan.source_sha256!r}, "
            f"catalog_sha256={self.catalog_plan.catalog_sha256!r}, "
            f"catalog_plan_sha256={self.catalog_plan.plan_sha256!r}, "
            f"backup_sha256={self.backup_sha256!r}, "
            f"runtime_plan_sha256={self.runtime_plan_sha256!r})"
        )


def build_runtime_catalog_initialization_plan(
    readiness: RuntimeReadinessReport,
    catalog: PrivateMerchantCatalog,
    *,
    existing_records: Sequence[Mapping[str, Any]],
    expected_source_sha256: str,
    expected_catalog_sha256: str,
    expected_backup_sha256: str,
) -> RuntimeCatalogInitializationPlan:
    """Bind exact readiness and target state to one private catalog."""

    backup_hash = _reviewed_hash(
        expected_backup_sha256,
        "backup",
    )
    _validate_readiness(readiness, backup_hash)
    catalog_plan = build_catalog_initialization_plan(
        catalog,
        existing_records=existing_records,
        expected_source_sha256=expected_source_sha256,
        expected_catalog_sha256=expected_catalog_sha256,
    )

    if (
        catalog_plan.action != CATALOG_INSERT
        or catalog_plan.record_count != EXPECTED_RECORD_COUNT
        or catalog_plan.target_count_before != 0
        or catalog_plan.target_count_after != EXPECTED_RECORD_COUNT
    ):
        raise RuntimeCatalogPlanError(
            "Runtime catalog target is not the reviewed empty state",
            reason_code="CATALOG_INSERT_PLAN_MISMATCH",
        )

    runtime_plan_hash = _runtime_plan_hash(
        catalog_plan=catalog_plan,
        backup_sha256=backup_hash,
    )
    return RuntimeCatalogInitializationPlan(
        catalog_plan=catalog_plan,
        backup_sha256=backup_hash,
        runtime_plan_sha256=runtime_plan_hash,
    )


def _validate_readiness(
    readiness: Any,
    backup_sha256: str,
) -> None:
    if not isinstance(readiness, RuntimeReadinessReport):
        raise RuntimeCatalogPlanError(
            "Catalog planning requires validated runtime readiness",
            reason_code="INVALID_READINESS_REPORT",
        )

    exact = (
        readiness.success is True
        and readiness.state == CATALOG_INITIALIZATION_READY
        and readiness.database == RUNTIME_DATABASE
        and readiness.user == RUNTIME_WRITE_ROLE
        and readiness.encoding == "UTF8"
        and readiness.read_only == "on"
        and readiness.schema_owner == "merchant_owner"
        and readiness.applied_versions == (1, 2, 3)
        and readiness.pending_versions == ()
        and readiness.stored_template_count == 4
        and readiness.expected_template_sha256
        == EXPECTED_READINESS_TEMPLATE_SHA256
        and readiness.standard_templates_match is True
        and set(readiness.business_counts) == set(BUSINESS_TABLES)
        and all(
            count == 0
            for count in readiness.business_counts.values()
        )
        and readiness.backup.ready is True
        and readiness.backup.backup_sha256 == backup_sha256
    )

    if not exact:
        raise RuntimeCatalogPlanError(
            "Runtime state is not exact for catalog initialization",
            reason_code="READINESS_STATE_MISMATCH",
        )


def _reviewed_hash(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or SHA256_PATTERN.fullmatch(value) is None
    ):
        raise RuntimeCatalogPlanError(
            f"Reviewed {label} hash must be a lowercase SHA-256",
            reason_code=f"INVALID_{label.upper()}_HASH",
        )

    return value


def _runtime_plan_hash(
    *,
    catalog_plan: CatalogInitializationPlan,
    backup_sha256: str,
) -> str:
    document = {
        "plan_version": RUNTIME_CATALOG_PLAN_VERSION,
        "target": {
            "host": RUNTIME_HOST,
            "port": RUNTIME_PORT,
            "database": RUNTIME_DATABASE,
            "write_role": RUNTIME_WRITE_ROLE,
        },
        "action": catalog_plan.action,
        "record_count": catalog_plan.record_count,
        "status_counts": catalog_plan.status_counts,
        "target_count_before": catalog_plan.target_count_before,
        "target_count_after": catalog_plan.target_count_after,
        "source_sha256": catalog_plan.source_sha256,
        "catalog_sha256": catalog_plan.catalog_sha256,
        "catalog_plan_sha256": catalog_plan.plan_sha256,
        "template_manifest_sha256": EXPECTED_FULL_TEMPLATE_SHA256,
        "backup_sha256": backup_sha256,
        "execution_contract": {
            "transaction_mode": "SINGLE_ATOMIC_TRANSACTION",
            "idempotency": "IDENTICAL_SOURCE_NO_OP",
            "conflict_behavior": "FAIL_CLOSED",
            "merchant_inserts": EXPECTED_RECORD_COUNT,
            "audit_event_inserts": EXPECTED_RECORD_COUNT,
            "audit_event_type": CATALOG_AUDIT_EVENT_TYPE,
            "contact_inserts": 0,
            "project_inserts": 0,
        },
    }
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
