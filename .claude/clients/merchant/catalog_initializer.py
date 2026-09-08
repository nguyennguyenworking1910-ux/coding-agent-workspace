"""Atomic, hash-bound initialization of the private Merchant catalog."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from psycopg.types.json import Jsonb

from claude.agents.tools.merchant.catalog_contract import (
    CATALOG_ACCOUNT_STATUSES,
    PrivateMerchantCatalog,
)
from claude.agents.tools.merchant.catalog_plan import (
    CATALOG_INSERT,
    CATALOG_NO_OP,
    build_catalog_initialization_plan,
)
from claude.agents.tools.merchant.workflow_templates import (
    standard_template_manifest,
)

from .runtime_catalog_plan import (
    CATALOG_AUDIT_EVENT_TYPE,
    EXPECTED_RECORD_COUNT,
    RUNTIME_DATABASE,
    RUNTIME_HOST,
    RUNTIME_PORT,
    RUNTIME_WRITE_ROLE,
    RuntimeCatalogInitializationPlan,
    _runtime_plan_hash,
)
from .runtime_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS,
    EXPECTED_PENDING_MIGRATIONS,
)


CATALOG_LOCK_KEY = "merchant-runtime-catalog-initialization-v1"
CATALOG_EVENT_NAMESPACE = uuid.UUID(
    "b0f5e347-f111-5bb7-85c3-2430bad9f589"
)


class RuntimeCatalogInitializationError(RuntimeError):
    """A value-safe failure at the catalog persistence boundary."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeCatalogInitializationResult:
    """Non-private evidence from one initialization attempt."""

    action: str
    merchants_inserted: int
    merchants_unchanged: int
    audit_events_inserted: int
    merchant_count: int
    status_counts: Mapping[str, int]
    source_sha256: str
    catalog_sha256: str
    catalog_plan_sha256: str
    runtime_plan_sha256: str

    def safe_summary(self) -> dict[str, Any]:
        return asdict(self)

    def __repr__(self) -> str:
        return (
            "RuntimeCatalogInitializationResult("
            f"action={self.action!r}, "
            f"merchants_inserted={self.merchants_inserted}, "
            f"merchants_unchanged={self.merchants_unchanged}, "
            f"audit_events_inserted={self.audit_events_inserted}, "
            f"merchant_count={self.merchant_count}, "
            f"status_counts={dict(self.status_counts)!r}, "
            f"source_sha256={self.source_sha256!r}, "
            f"catalog_sha256={self.catalog_sha256!r}, "
            f"catalog_plan_sha256={self.catalog_plan_sha256!r}, "
            f"runtime_plan_sha256={self.runtime_plan_sha256!r})"
        )


class RuntimeCatalogInitializer:
    """Persist one reviewed catalog through one database transaction."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def initialize(
        self,
        plan: RuntimeCatalogInitializationPlan,
    ) -> RuntimeCatalogInitializationResult:
        """Insert an empty target or prove an identical-source no-op."""

        if not isinstance(plan, RuntimeCatalogInitializationPlan):
            raise RuntimeCatalogInitializationError(
                "Catalog initialization requires a validated runtime plan",
                reason_code="INVALID_RUNTIME_PLAN",
            )

        self._validate_repository_config()
        catalog = _catalog_from_plan(plan)

        try:
            with self.repository.connection() as connection:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        self._acquire_lock(cursor)
                        self._validate_runtime_identity(cursor)
                        self._validate_migrations(cursor)
                        self._validate_templates(cursor)
                        existing = self._read_catalog(cursor)
                        current_plan = build_catalog_initialization_plan(
                            catalog,
                            existing_records=existing,
                            expected_source_sha256=(
                                plan.catalog_plan.source_sha256
                            ),
                            expected_catalog_sha256=(
                                plan.catalog_plan.catalog_sha256
                            ),
                        )

                        if current_plan.action == CATALOG_INSERT:
                            self._validate_empty_business_state(cursor)
                            self._insert_records(cursor, plan)
                            inserted = EXPECTED_RECORD_COUNT
                            unchanged = 0
                            events_inserted = EXPECTED_RECORD_COUNT
                        elif current_plan.action == CATALOG_NO_OP:
                            inserted = 0
                            unchanged = EXPECTED_RECORD_COUNT
                            events_inserted = 0
                        else:  # pragma: no cover
                            raise RuntimeCatalogInitializationError(
                                "Catalog plan action is unsupported",
                                reason_code="UNSUPPORTED_PLAN_ACTION",
                            )

                        evidence = self._verify_committed_shape(
                            cursor,
                            plan,
                        )
        except RuntimeCatalogInitializationError:
            raise
        except Exception:
            raise RuntimeCatalogInitializationError(
                "Private Merchant catalog transaction failed",
                reason_code="CATALOG_TRANSACTION_FAILED",
            ) from None

        return RuntimeCatalogInitializationResult(
            action=current_plan.action,
            merchants_inserted=inserted,
            merchants_unchanged=unchanged,
            audit_events_inserted=events_inserted,
            merchant_count=evidence["merchant_count"],
            status_counts=evidence["status_counts"],
            source_sha256=plan.catalog_plan.source_sha256,
            catalog_sha256=plan.catalog_plan.catalog_sha256,
            catalog_plan_sha256=plan.catalog_plan.plan_sha256,
            runtime_plan_sha256=plan.runtime_plan_sha256,
        )

    def _validate_repository_config(self) -> None:
        config = getattr(self.repository, "config", None)
        exact = (
            config is not None
            and getattr(config, "host", None) == RUNTIME_HOST
            and getattr(config, "port", None) == RUNTIME_PORT
            and getattr(config, "database", None) == RUNTIME_DATABASE
            and getattr(config, "user", None) == RUNTIME_WRITE_ROLE
        )

        if not exact:
            raise RuntimeCatalogInitializationError(
                "Catalog repository is not the exact runtime target",
                reason_code="UNSAFE_REPOSITORY_CONFIG",
            )

    @staticmethod
    def _acquire_lock(cursor: Any) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (CATALOG_LOCK_KEY,),
        )

    @staticmethod
    def _validate_runtime_identity(cursor: Any) -> None:
        cursor.execute(
            """
            SELECT
                current_database() AS database,
                current_user AS user,
                current_setting('transaction_read_only') AS read_only,
                current_setting('server_encoding') AS encoding
            """,
            (),
        )
        identity = dict(cursor.fetchone())

        if identity != {
            "database": RUNTIME_DATABASE,
            "user": RUNTIME_WRITE_ROLE,
            "read_only": "off",
            "encoding": "UTF8",
        }:
            raise RuntimeCatalogInitializationError(
                "Runtime transaction identity is not exact",
                reason_code="UNSAFE_RUNTIME_IDENTITY",
            )

    @staticmethod
    def _validate_migrations(cursor: Any) -> None:
        cursor.execute(
            """
            SELECT version, description, checksum
            FROM merchant_ops.schema_migrations
            ORDER BY version
            """,
            (),
        )
        actual = tuple(
            (
                int(row["version"]),
                str(row["description"]),
                str(row["checksum"]),
            )
            for row in cursor.fetchall()
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

        if actual != expected:
            raise RuntimeCatalogInitializationError(
                "Runtime migration history changed before initialization",
                reason_code="MIGRATION_STATE_MISMATCH",
            )

    @staticmethod
    def _validate_templates(cursor: Any) -> None:
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
                    FROM merchant_ops.workflow_template_dependencies
                        AS dependency
                    JOIN merchant_ops.workflow_template_steps
                        AS source_step
                      ON source_step.id = dependency.from_step_id
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
        actual = tuple(
            sorted(
                (
                    {
                        "template_id": str(row["template_id"]),
                        "name": str(row["name"]),
                        "version": int(row["version"]),
                        "variant": str(row["variant"]),
                        "step_count": int(row["step_count"]),
                        "dependency_count": int(
                            row["dependency_count"]
                        ),
                    }
                    for row in cursor.fetchall()
                ),
                key=lambda item: (item["name"], item["version"]),
            )
        )
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

        if actual != expected:
            raise RuntimeCatalogInitializationError(
                "Standard templates changed before initialization",
                reason_code="TEMPLATE_STATE_MISMATCH",
            )

    @staticmethod
    def _read_catalog(cursor: Any) -> list[dict[str, Any]]:
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
            FOR UPDATE
            """,
            (),
        )
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _validate_empty_business_state(cursor: Any) -> None:
        for table in (
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
        ):
            cursor.execute(
                "SELECT COUNT(*) AS count "
                f"FROM merchant_ops.{table}",
                (),
            )

            if int(cursor.fetchone()["count"]) != 0:
                raise RuntimeCatalogInitializationError(
                    "Runtime business state is not empty",
                    reason_code="BUSINESS_STATE_NOT_EMPTY",
                )

    @staticmethod
    def _insert_records(
        cursor: Any,
        plan: RuntimeCatalogInitializationPlan,
    ) -> None:
        merchant_query = """
            INSERT INTO merchant_ops.merchants (
                id,
                code,
                name,
                region_code,
                account_status,
                created_at,
                updated_at,
                created_by,
                version
            )
            VALUES (
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                NULL,
                1
            )
        """
        event_query = """
            INSERT INTO merchant_ops.project_events (
                id,
                merchant_id,
                project_id,
                event_type,
                entity_type,
                entity_id,
                change_summary,
                old_values,
                new_values,
                triggered_by,
                created_at
            )
            VALUES (
                %s, %s, NULL, %s, 'MERCHANT',
                %s, %s, %s, %s, NULL,
                CURRENT_TIMESTAMP
            )
        """

        for record in plan.catalog_plan.records:
            merchant_id = uuid.UUID(record.merchant_id)
            cursor.execute(
                merchant_query,
                (
                    merchant_id,
                    record.code,
                    record.name,
                    record.region_code,
                    record.account_status,
                ),
            )
            cursor.execute(
                event_query,
                (
                    _event_id(
                        plan.catalog_plan.catalog_sha256,
                        record.merchant_id,
                    ),
                    merchant_id,
                    CATALOG_AUDIT_EVENT_TYPE,
                    merchant_id,
                    "Merchant initialized from reviewed private catalog",
                    Jsonb({}),
                    Jsonb(
                        {
                            "account_status": record.account_status,
                            "catalog_sha256": (
                                plan.catalog_plan.catalog_sha256
                            ),
                            "version": 1,
                        }
                    ),
                ),
            )

    @staticmethod
    def _verify_committed_shape(
        cursor: Any,
        plan: RuntimeCatalogInitializationPlan,
    ) -> dict[str, Any]:
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
            status: 0 for status in sorted(CATALOG_ACCOUNT_STATUSES)
        }

        for row in cursor.fetchall():
            status_counts[str(row["account_status"])] = int(
                row["count"]
            )
        merchant_count = sum(status_counts.values())
        expected_status_counts = plan.catalog_plan.status_counts

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
        event_rows = tuple(dict(row) for row in cursor.fetchall())
        actual_event_ids = {str(row["id"]) for row in event_rows}
        expected_event_ids = {
            str(
                _event_id(
                    plan.catalog_plan.catalog_sha256,
                    record.merchant_id,
                )
            )
            for record in plan.catalog_plan.records
        }
        statuses_by_id = {
            record.merchant_id: record.account_status
            for record in plan.catalog_plan.records
        }
        event_payloads_safe = all(
            row["project_id"] is None
            and str(row["entity_type"]) == "MERCHANT"
            and str(row["entity_id"]) == str(row["merchant_id"])
            and row["triggered_by"] is None
            and str(row["change_summary"])
            == "Merchant initialized from reviewed private catalog"
            and dict(row["old_values"] or {}) == {}
            and dict(row["new_values"] or {})
            == {
                "account_status": statuses_by_id[
                    str(row["merchant_id"])
                ],
                "catalog_sha256": (
                    plan.catalog_plan.catalog_sha256
                ),
                "version": 1,
            }
            for row in event_rows
        )

        if (
            merchant_count != EXPECTED_RECORD_COUNT
            or status_counts != expected_status_counts
            or actual_event_ids != expected_event_ids
            or not event_payloads_safe
        ):
            raise RuntimeCatalogInitializationError(
                "Committed catalog evidence is incomplete",
                reason_code="CATALOG_EVIDENCE_MISMATCH",
            )

        return {
            "merchant_count": merchant_count,
            "status_counts": status_counts,
        }


def _catalog_from_plan(
    plan: RuntimeCatalogInitializationPlan,
) -> PrivateMerchantCatalog:
    catalog_plan = plan.catalog_plan
    catalog = PrivateMerchantCatalog(
        records=catalog_plan.records,
        source_sha256=catalog_plan.source_sha256,
        catalog_sha256=catalog_plan.catalog_sha256,
    )
    rebuilt = build_catalog_initialization_plan(
        catalog,
        existing_records=(),
        expected_source_sha256=catalog_plan.source_sha256,
        expected_catalog_sha256=catalog_plan.catalog_sha256,
    )

    if (
        catalog_plan.action != CATALOG_INSERT
        or catalog_plan.record_count != EXPECTED_RECORD_COUNT
        or catalog_plan.target_count_before != 0
        or catalog_plan.target_count_after != EXPECTED_RECORD_COUNT
        or rebuilt != catalog_plan
        or plan.runtime_plan_sha256
        != _runtime_plan_hash(
            catalog_plan=catalog_plan,
            backup_sha256=plan.backup_sha256,
        )
    ):
        raise RuntimeCatalogInitializationError(
            "Runtime catalog plan binding is invalid",
            reason_code="INVALID_CATALOG_PLAN_BINDING",
        )

    return catalog


def _event_id(
    catalog_sha256: str,
    merchant_id: str,
) -> uuid.UUID:
    return uuid.uuid5(
        CATALOG_EVENT_NAMESPACE,
        f"{catalog_sha256}:{merchant_id}",
    )
