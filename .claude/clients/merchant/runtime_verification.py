"""Read-only verification of the initialized Merchant runtime."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from claude.agents.tools.merchant.catalog_contract import (
    CATALOG_ACCOUNT_STATUSES,
    PrivateMerchantCatalog,
)
from claude.agents.tools.merchant.catalog_plan import (
    CATALOG_NO_OP,
    CatalogPlanError,
    build_catalog_initialization_plan,
)
from claude.agents.tools.merchant.project_factory import (
    ProjectInstantiationError,
    build_project_instantiation_plan,
)
from claude.agents.tools.merchant.read_commands import (
    MerchantReadCommands,
)
from claude.agents.tools.merchant.workflow_templates import (
    STANDARD_WORKFLOW_TEMPLATES,
    standard_template_manifest,
)

from .catalog_initializer import (
    CATALOG_AUDIT_EVENT_TYPE,
    _event_id,
)
from .read_repository import MerchantReadRepository
from .runtime_catalog_plan import (
    RUNTIME_DATABASE,
    RUNTIME_HOST,
    RUNTIME_PORT,
    RUNTIME_WRITE_ROLE,
)
from .runtime_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS,
    EXPECTED_PENDING_MIGRATIONS,
)
from .runtime_readiness import BUSINESS_TABLES


EXPECTED_RECORD_COUNT = 22
EXPECTED_STATUS_COUNTS = {
    "ACTIVE": 0,
    "ONBOARDING": 22,
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PREVIEW_NAMESPACE = uuid.UUID(
    "ec0b9a3e-1fa7-51ad-a314-d5884ea85756"
)
ACTIVE_ONLY_VARIANTS = (
    "MEDIA_TOP_UP_EXISTING_DOCUMENT",
    "MEDIA_TOP_UP_NEW_DOCUMENT",
    "OPENING_NEW_CINEMA_STANDARD",
)
INTEGRATION_VARIANT = "INTEGRATION_NEW_MERCHANT_STANDARD"


class RuntimeVerificationError(RuntimeError):
    """A value-safe failure at the verification boundary."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeVerificationReport:
    """Private-value-free evidence for the initialized runtime."""

    success: bool
    checks: Mapping[str, bool]
    record_count: int
    status_counts: Mapping[str, int]
    ordinary_reads: Mapping[str, int]
    workflow_preconditions: Mapping[str, Any]
    migration_versions: tuple[int, ...]
    template_count: int
    template_step_count: int
    template_dependency_count: int
    catalog_event_count: int
    source_sha256: str
    catalog_sha256: str
    stored_catalog_sha256: str

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
            "checks": dict(self.checks),
            "failed_checks": list(self.failed_checks),
            "record_count": self.record_count,
            "status_counts": dict(self.status_counts),
            "ordinary_reads": dict(self.ordinary_reads),
            "workflow_preconditions": dict(
                self.workflow_preconditions
            ),
            "migration_versions": list(self.migration_versions),
            "template_count": self.template_count,
            "template_step_count": self.template_step_count,
            "template_dependency_count": (
                self.template_dependency_count
            ),
            "catalog_event_count": self.catalog_event_count,
            "source_sha256": self.source_sha256,
            "catalog_sha256": self.catalog_sha256,
            "stored_catalog_sha256": self.stored_catalog_sha256,
        }

    def __repr__(self) -> str:
        return (
            "RuntimeVerificationReport("
            f"success={self.success}, "
            f"record_count={self.record_count}, "
            f"status_counts={dict(self.status_counts)!r}, "
            f"failed_checks={self.failed_checks!r}, "
            f"source_sha256={self.source_sha256!r}, "
            f"catalog_sha256={self.catalog_sha256!r}, "
            f"stored_catalog_sha256={self.stored_catalog_sha256!r})"
        )


def verify_initialized_runtime(
    repository: Any,
    catalog: PrivateMerchantCatalog,
    *,
    expected_source_sha256: str,
    expected_catalog_sha256: str,
) -> RuntimeVerificationReport:
    """Verify catalog and workflow compatibility without mutation."""

    source_hash = _reviewed_hash(
        expected_source_sha256,
        "source",
    )
    catalog_hash = _reviewed_hash(
        expected_catalog_sha256,
        "catalog",
    )
    _validate_catalog(catalog, source_hash, catalog_hash)
    _validate_repository(repository)

    try:
        before = _collect_runtime_snapshot(repository)
        catalog_checks = _catalog_checks(
            catalog,
            before["merchants"],
            source_hash=source_hash,
            catalog_hash=catalog_hash,
        )
        ordinary = _exercise_ordinary_reads(
            repository,
            before["merchants"],
        )
        workflow = _workflow_precondition_checks(
            before["merchants"],
        )
        after = _collect_runtime_snapshot(repository)
    except RuntimeVerificationError:
        raise
    except Exception:
        raise RuntimeVerificationError(
            "Initialized runtime verification query failed",
            reason_code="RUNTIME_VERIFICATION_FAILED",
        ) from None

    identity = before["identity"]
    status_counts = _status_counts(before["merchants"])
    migration_versions = tuple(
        int(row["version"])
        for row in before["migrations"]
    )
    template_count = len(before["templates"])
    template_step_count = sum(
        int(row["step_count"])
        for row in before["templates"]
    )
    template_dependency_count = sum(
        int(row["dependency_count"])
        for row in before["templates"]
    )
    catalog_event_count = len(before["catalog_events"])

    checks = {
        "runtime_database_exact": (
            identity.get("database") == RUNTIME_DATABASE
        ),
        "application_role_exact": (
            identity.get("user") == RUNTIME_WRITE_ROLE
        ),
        "transaction_read_only": (
            identity.get("read_only") == "on"
        ),
        "encoding_utf8": identity.get("encoding") == "UTF8",
        "catalog_target_identical": catalog_checks[
            "target_identical"
        ],
        "stored_catalog_hash_exact": catalog_checks[
            "stored_hash_exact"
        ],
        "record_count_exact": (
            len(before["merchants"]) == EXPECTED_RECORD_COUNT
        ),
        "status_distribution_exact": (
            status_counts == EXPECTED_STATUS_COUNTS
        ),
        "migration_history_exact": _migrations_exact(
            before["migrations"]
        ),
        "standard_templates_exact": _templates_exact(
            before["templates"]
        ),
        "catalog_events_exact_and_redacted": _events_exact(
            before,
            catalog,
        ),
        "noncatalog_business_state_empty": (
            _noncatalog_business_state_empty(before["counts"])
        ),
        "ordinary_merchant_reads_exact": ordinary[
            "merchant_reads_exact"
        ],
        "ordinary_status_filters_exact": ordinary[
            "status_filters_exact"
        ],
        "ordinary_sensitive_fields_absent": ordinary[
            "sensitive_fields_absent"
        ],
        "ordinary_project_reads_empty": ordinary[
            "project_reads_empty"
        ],
        "onboarding_integration_allowed": workflow[
            "onboarding_integration_allowed"
        ],
        "onboarding_active_workflows_denied": workflow[
            "onboarding_active_workflows_denied"
        ],
        "active_workflow_contracts_available": workflow[
            "active_workflow_contracts_available"
        ],
        "active_integration_denied": workflow[
            "active_integration_denied"
        ],
        "verification_made_no_runtime_change": before == after,
    }

    return RuntimeVerificationReport(
        success=all(checks.values()),
        checks=checks,
        record_count=len(before["merchants"]),
        status_counts=status_counts,
        ordinary_reads={
            "all_merchants": ordinary["all_count"],
            "onboarding_merchants": ordinary[
                "onboarding_count"
            ],
            "active_merchants": ordinary["active_count"],
            "projects": ordinary["project_count"],
            "alerts": ordinary["alert_count"],
        },
        workflow_preconditions={
            "onboarding_runtime_records": workflow[
                "onboarding_runtime_records"
            ],
            "active_runtime_records": workflow[
                "active_runtime_records"
            ],
            "integration_preview_steps": workflow[
                "integration_preview_steps"
            ],
            "active_preview_variants": workflow[
                "active_preview_variants"
            ],
            "runtime_projects_created": 0,
        },
        migration_versions=migration_versions,
        template_count=template_count,
        template_step_count=template_step_count,
        template_dependency_count=template_dependency_count,
        catalog_event_count=catalog_event_count,
        source_sha256=source_hash,
        catalog_sha256=catalog_hash,
        stored_catalog_sha256=catalog_checks["stored_hash"],
    )


def _validate_catalog(
    catalog: Any,
    source_sha256: str,
    catalog_sha256: str,
) -> None:
    exact = (
        isinstance(catalog, PrivateMerchantCatalog)
        and catalog.record_count == EXPECTED_RECORD_COUNT
        and catalog.source_sha256 == source_sha256
        and catalog.catalog_sha256 == catalog_sha256
        and catalog.status_counts == EXPECTED_STATUS_COUNTS
    )

    if not exact:
        raise RuntimeVerificationError(
            "Private catalog does not match the initialized binding",
            reason_code="CATALOG_BINDING_MISMATCH",
        )


def _validate_repository(repository: Any) -> None:
    config = getattr(repository, "config", None)
    exact = (
        config is not None
        and getattr(config, "host", None) == RUNTIME_HOST
        and getattr(config, "port", None) == RUNTIME_PORT
        and getattr(config, "database", None) == RUNTIME_DATABASE
        and getattr(config, "user", None) == RUNTIME_WRITE_ROLE
    )

    if not exact:
        raise RuntimeVerificationError(
            "Verification repository is not the exact runtime target",
            reason_code="UNSAFE_RUNTIME_CONFIG",
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
                        id::text AS merchant_id,
                        code,
                        name,
                        region_code,
                        account_status,
                        version
                    FROM merchant_ops.merchants
                    ORDER BY code, id
                    """,
                    (),
                )
                merchants = tuple(
                    dict(row) for row in cursor.fetchall()
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

                cursor.execute(
                    """
                    SELECT
                        template.id::text AS template_id,
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
                    _template_row(row)
                    for row in cursor.fetchall()
                )

                cursor.execute(
                    """
                    SELECT
                        id::text AS id,
                        merchant_id::text AS merchant_id,
                        project_id,
                        entity_type,
                        entity_id::text AS entity_id,
                        change_summary,
                        old_values,
                        new_values,
                        triggered_by
                    FROM merchant_ops.project_events
                    WHERE event_type = %s
                    ORDER BY id
                    """,
                    (CATALOG_AUDIT_EVENT_TYPE,),
                )
                events = tuple(
                    dict(row) for row in cursor.fetchall()
                )

                counts: dict[str, int] = {}

                for table in BUSINESS_TABLES:
                    cursor.execute(
                        "SELECT COUNT(*) AS count "
                        f"FROM merchant_ops.{table}",
                        (),
                    )
                    counts[table] = int(
                        cursor.fetchone()["count"]
                    )

    return {
        "identity": identity,
        "merchants": merchants,
        "migrations": migrations,
        "templates": templates,
        "catalog_events": events,
        "counts": counts,
    }


def _catalog_checks(
    catalog: PrivateMerchantCatalog,
    merchants: Sequence[Mapping[str, Any]],
    *,
    source_hash: str,
    catalog_hash: str,
) -> dict[str, Any]:
    stored_hash = _stored_catalog_hash(merchants)

    try:
        plan = build_catalog_initialization_plan(
            catalog,
            existing_records=merchants,
            expected_source_sha256=source_hash,
            expected_catalog_sha256=catalog_hash,
        )
        target_identical = (
            plan.action == CATALOG_NO_OP
            and plan.record_count == EXPECTED_RECORD_COUNT
            and plan.target_count_before == EXPECTED_RECORD_COUNT
            and plan.target_count_after == EXPECTED_RECORD_COUNT
        )
    except CatalogPlanError:
        target_identical = False

    return {
        "target_identical": target_identical,
        "stored_hash_exact": stored_hash == catalog_hash,
        "stored_hash": stored_hash,
    }


def _exercise_ordinary_reads(
    repository: Any,
    snapshot_merchants: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    commands = MerchantReadCommands(
        MerchantReadRepository(repository)
    )
    all_merchants = commands.merchant_list()
    onboarding = commands.merchant_list(status="ONBOARDING")
    active = commands.merchant_list(status="ACTIVE")
    projects = commands.project_list()
    alerts = commands.project_alerts()
    allowed_fields = {
        "id",
        "code",
        "name",
        "region_code",
        "account_status",
        "created_at",
        "updated_at",
        "version",
        "contact_count",
    }
    snapshot_projection = tuple(
        sorted(
            (
                str(row["merchant_id"]),
                str(row["account_status"]),
                int(row["version"]),
            )
            for row in snapshot_merchants
        )
    )
    ordinary_projection = tuple(
        sorted(
            (
                str(row["id"]),
                str(row["account_status"]),
                int(row["version"]),
            )
            for row in all_merchants
        )
    )
    sensitive_fields = {
        "contact_name",
        "contact_email",
        "contact_phone",
        "content_hash",
        "identifier_value",
        "notes",
    }

    return {
        "merchant_reads_exact": (
            ordinary_projection == snapshot_projection
            and len(all_merchants) == EXPECTED_RECORD_COUNT
        ),
        "status_filters_exact": (
            len(onboarding) == EXPECTED_RECORD_COUNT
            and len(active) == 0
            and all(
                row.get("account_status") == "ONBOARDING"
                for row in onboarding
            )
        ),
        "sensitive_fields_absent": all(
            set(row).issubset(allowed_fields)
            and not (set(row) & sensitive_fields)
            and int(row.get("contact_count", -1)) == 0
            for row in all_merchants
        ),
        "project_reads_empty": projects == [] and alerts == [],
        "all_count": len(all_merchants),
        "onboarding_count": len(onboarding),
        "active_count": len(active),
        "project_count": len(projects),
        "alert_count": len(alerts),
    }


def _workflow_precondition_checks(
    merchants: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    onboarding = [
        row
        for row in merchants
        if str(row.get("account_status")) == "ONBOARDING"
    ]
    active = [
        row
        for row in merchants
        if str(row.get("account_status")) == "ACTIVE"
    ]

    if not onboarding:
        return _failed_workflow_evidence(
            onboarding_count=0,
            active_count=len(active),
        )

    merchant_id = str(onboarding[0]["merchant_id"])
    templates = {
        template.variant: template
        for template in STANDARD_WORKFLOW_TEMPLATES
    }
    integration = templates[INTEGRATION_VARIANT]
    integration_plan = build_project_instantiation_plan(
        merchant_id=merchant_id,
        merchant_status="ONBOARDING",
        template=integration,
        requires_procurement=False,
        project_id=_preview_id("onboarding-integration"),
    )
    onboarding_denials = all(
        _precondition_rejected(
            merchant_id,
            "ONBOARDING",
            templates[variant],
        )
        for variant in ACTIVE_ONLY_VARIANTS
    )
    active_plans = tuple(
        _build_active_preview(
            merchant_id,
            templates[variant],
        )
        for variant in ACTIVE_ONLY_VARIANTS
    )
    active_integration_denied = _precondition_rejected(
        merchant_id,
        "ACTIVE",
        integration,
    )

    return {
        "onboarding_integration_allowed": (
            integration_plan.project["status"] == "PLANNED"
            and integration_plan.project["merchant_id"]
            == merchant_id
            and len(integration_plan.steps) == 26
        ),
        "onboarding_active_workflows_denied": onboarding_denials,
        "active_workflow_contracts_available": (
            len(active_plans) == len(ACTIVE_ONLY_VARIANTS)
            and all(
                plan.project["status"] == "PLANNED"
                for plan in active_plans
            )
        ),
        "active_integration_denied": active_integration_denied,
        "onboarding_runtime_records": len(onboarding),
        "active_runtime_records": len(active),
        "integration_preview_steps": len(integration_plan.steps),
        "active_preview_variants": len(active_plans),
    }


def _build_active_preview(
    merchant_id: str,
    template: Any,
) -> Any:
    arguments: dict[str, Any] = {
        "merchant_id": merchant_id,
        "merchant_status": "ACTIVE",
        "template": template,
        "requires_procurement": False,
        "project_id": _preview_id(template.variant),
    }

    if template.variant == "MEDIA_TOP_UP_NEW_DOCUMENT":
        arguments["requires_procurement"] = True
        arguments["payment_period_number"] = 1
    elif template.variant == "MEDIA_TOP_UP_EXISTING_DOCUMENT":
        arguments["payment_period_number"] = 1
        arguments["reused_document_revision_id"] = _preview_id(
            "reused-document"
        )

    return build_project_instantiation_plan(**arguments)


def _precondition_rejected(
    merchant_id: str,
    status: str,
    template: Any,
) -> bool:
    try:
        build_project_instantiation_plan(
            merchant_id=merchant_id,
            merchant_status=status,
            template=template,
            requires_procurement=False,
            project_id=_preview_id(
                f"reject-{status}-{template.variant}"
            ),
        )
    except ProjectInstantiationError as error:
        return "precondition" in str(error)

    return False


def _failed_workflow_evidence(
    *,
    onboarding_count: int,
    active_count: int,
) -> dict[str, Any]:
    return {
        "onboarding_integration_allowed": False,
        "onboarding_active_workflows_denied": False,
        "active_workflow_contracts_available": False,
        "active_integration_denied": False,
        "onboarding_runtime_records": onboarding_count,
        "active_runtime_records": active_count,
        "integration_preview_steps": 0,
        "active_preview_variants": 0,
    }


def _preview_id(label: str) -> str:
    return str(uuid.uuid5(PREVIEW_NAMESPACE, label))


def _migrations_exact(
    rows: Sequence[Mapping[str, Any]],
) -> bool:
    actual = tuple(
        (
            int(row["version"]),
            str(row["description"]),
            str(row["checksum"]),
        )
        for row in rows
    )
    expected = tuple(
        (
            item.version,
            item.description,
            item.checksum,
        )
        for item in (
            *EXPECTED_APPLIED_MIGRATIONS,
            *EXPECTED_PENDING_MIGRATIONS,
        )
    )
    return actual == expected


def _templates_exact(
    rows: Sequence[Mapping[str, Any]],
) -> bool:
    expected = tuple(
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
    return tuple(rows) == expected


def _events_exact(
    snapshot: Mapping[str, Any],
    catalog: PrivateMerchantCatalog,
) -> bool:
    events = snapshot["catalog_events"]
    expected_ids = {
        str(_event_id(catalog.catalog_sha256, record.merchant_id))
        for record in catalog.records
    }
    statuses = {
        record.merchant_id: record.account_status
        for record in catalog.records
    }

    try:
        payloads_exact = all(
            row["project_id"] is None
            and str(row["entity_type"]) == "MERCHANT"
            and str(row["entity_id"]) == str(row["merchant_id"])
            and row["triggered_by"] is None
            and str(row["change_summary"])
            == "Merchant initialized from reviewed private catalog"
            and dict(row["old_values"] or {}) == {}
            and dict(row["new_values"] or {})
            == {
                "account_status": statuses[str(row["merchant_id"])],
                "catalog_sha256": catalog.catalog_sha256,
                "version": 1,
            }
            for row in events
        )
    except (KeyError, TypeError, ValueError):
        return False

    return (
        snapshot["counts"].get("project_events")
        == EXPECTED_RECORD_COUNT
        and len(events) == EXPECTED_RECORD_COUNT
        and {str(row["id"]) for row in events} == expected_ids
        and payloads_exact
    )


def _noncatalog_business_state_empty(
    counts: Mapping[str, int],
) -> bool:
    exact_keys = set(counts) == set(BUSINESS_TABLES)
    expected = {
        name: 0 for name in BUSINESS_TABLES
    }
    expected["merchants"] = EXPECTED_RECORD_COUNT
    expected["project_events"] = EXPECTED_RECORD_COUNT
    return exact_keys and dict(counts) == expected


def _status_counts(
    merchants: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    counts = Counter(
        str(row["account_status"])
        for row in merchants
    )
    return {
        status: counts.get(status, 0)
        for status in sorted(CATALOG_ACCOUNT_STATUSES)
    }


def _stored_catalog_hash(
    merchants: Sequence[Mapping[str, Any]],
) -> str:
    canonical = [
        {
            "account_status": str(row["account_status"]),
            "code": str(row["code"]),
            "merchant_id": str(row["merchant_id"]),
            "name": str(row["name"]),
            "region_code": (
                str(row["region_code"])
                if row["region_code"] is not None
                else None
            ),
        }
        for row in merchants
    ]
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _template_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "template_id": str(row["template_id"]),
        "name": str(row["name"]),
        "version": int(row["version"]),
        "variant": str(row["variant"]),
        "step_count": int(row["step_count"]),
        "dependency_count": int(row["dependency_count"]),
    }


def _reviewed_hash(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or SHA256_PATTERN.fullmatch(value) is None
    ):
        raise RuntimeVerificationError(
            f"Reviewed {label} hash must be a lowercase SHA-256",
            reason_code=f"INVALID_{label.upper()}_HASH",
        )

    return value
