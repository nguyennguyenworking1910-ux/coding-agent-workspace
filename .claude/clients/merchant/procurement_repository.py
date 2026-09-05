"""Atomic persistence for Merchant procurement records."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from claude.agents.tools.merchant.procurement_engine import (
    ProcurementConflictError,
    ProcurementMutationPlan,
    propose_procurement_mutation,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    ProjectNotFoundError,
)


class ProcurementPersistenceError(RuntimeError):
    """Base error for procurement persistence."""


@dataclass(frozen=True, slots=True)
class ProcurementMutationResult:
    """Summary of a committed procurement mutation."""

    project_id: str
    procurement_id: str
    procurement_type: str
    status: str | None
    previous_version: int | None
    current_version: int
    operation: str
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MerchantProcurementRepository:
    """Create and update procurement records atomically."""

    def __init__(
        self,
        repository: MerchantRepository,
    ) -> None:
        self.repository = repository

    def record_procurement(
        self,
        *,
        project_id: str,
        procurement_type: str,
        external_id: str | None = None,
        status: str | None = None,
        expected_version: int | None = None,
        document_type: str | None = None,
        triggered_by: str | None = None,
        procurement_id: str | None = None,
    ) -> ProcurementMutationResult:
        """Create or update one project procurement record."""

        normalized_project_id = _uuid(
            project_id,
            "project_id",
        )
        candidate_procurement_id = (
            _uuid(procurement_id, "procurement_id")
            if procurement_id is not None
            else uuid.uuid4()
        )
        normalized_triggered_by = (
            _uuid(triggered_by, "triggered_by")
            if triggered_by is not None
            else None
        )

        try:
            with self.repository.connection() as connection:
                with connection.transaction():
                    with connection.cursor(
                        row_factory=dict_row,
                    ) as cursor:
                        project = self._lock_project(
                            cursor,
                            normalized_project_id,
                        )
                        revisions = self._lock_revisions(
                            cursor,
                            normalized_project_id,
                        )
                        procurement_records = (
                            self._lock_procurement_records(
                                cursor,
                                normalized_project_id,
                            )
                        )

                        plan = propose_procurement_mutation(
                            {
                                "project": project,
                                "document_revisions": (
                                    revisions
                                ),
                                "procurement_records": (
                                    procurement_records
                                ),
                            },
                            procurement_id=str(
                                candidate_procurement_id
                            ),
                            procurement_type=(
                                procurement_type
                            ),
                            external_id=external_id,
                            status=status,
                            expected_version=(
                                expected_version
                            ),
                            document_type=document_type,
                            triggered_by=(
                                str(normalized_triggered_by)
                                if normalized_triggered_by
                                is not None
                                else None
                            ),
                        )

                        if plan.operation == "INSERT":
                            self._insert_procurement(
                                cursor,
                                plan,
                            )
                        elif plan.operation == "UPDATE":
                            self._update_procurement(
                                cursor,
                                plan,
                            )
                        else:  # pragma: no cover
                            raise ProcurementPersistenceError(
                                "Unsupported procurement "
                                f"operation: {plan.operation}"
                            )

                        event_id = uuid.uuid4()
                        self._insert_event(
                            cursor,
                            plan,
                            event_id,
                        )

        except errors.UniqueViolation as error:
            raise ProcurementConflictError(
                "Procurement record conflicts with an "
                "existing project record"
            ) from error

        return ProcurementMutationResult(
            project_id=plan.project_id,
            procurement_id=plan.procurement_id,
            procurement_type=plan.procurement_type,
            status=plan.status,
            previous_version=plan.current_version,
            current_version=plan.new_version,
            operation=plan.operation,
            event_id=str(event_id),
            event_type=plan.event_type,
        )

    @staticmethod
    def _lock_project(
        cursor: Any,
        project_id: uuid.UUID,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT
                project.id,
                project.merchant_id,
                project.status,
                project.requires_procurement
            FROM merchant_ops.projects AS project
            WHERE project.id = %s
            FOR UPDATE OF project
            """,
            (project_id,),
        )

        project = cursor.fetchone()

        if project is None:
            raise ProjectNotFoundError(
                f"Merchant project not found: {project_id}"
            )

        return dict(project)

    @staticmethod
    def _lock_revisions(
        cursor: Any,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                revision.id,
                revision.project_id,
                revision.document_type,
                revision.revision_number,
                revision.content_hash,
                revision.signed,
                revision.signed_at,
                revision.effective_date,
                revision.expiry_date,
                revision.superseded_by,
                revision.created_at,
                revision.created_by
            FROM merchant_ops.document_revisions
                AS revision
            WHERE revision.project_id = %s
            ORDER BY
                revision.document_type,
                revision.revision_number,
                revision.id
            FOR UPDATE OF revision
            """,
            (project_id,),
        )

        return [
            dict(record)
            for record in cursor.fetchall()
        ]

    @staticmethod
    def _lock_procurement_records(
        cursor: Any,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                procurement.id,
                procurement.project_id,
                procurement.procurement_type,
                procurement.external_id,
                procurement.status,
                procurement.created_at,
                procurement.updated_at,
                procurement.version
            FROM merchant_ops.procurement_records
                AS procurement
            WHERE procurement.project_id = %s
            ORDER BY
                procurement.procurement_type,
                procurement.id
            FOR UPDATE OF procurement
            """,
            (project_id,),
        )

        return [
            dict(record)
            for record in cursor.fetchall()
        ]

    @staticmethod
    def _insert_procurement(
        cursor: Any,
        plan: ProcurementMutationPlan,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO merchant_ops.procurement_records (
                id,
                project_id,
                procurement_type,
                external_id,
                status,
                created_at,
                updated_at,
                version
            )
            VALUES (
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                1
            )
            """,
            (
                uuid.UUID(plan.procurement_id),
                uuid.UUID(plan.project_id),
                plan.procurement_type,
                plan.external_id,
                plan.status,
            ),
        )

    @staticmethod
    def _update_procurement(
        cursor: Any,
        plan: ProcurementMutationPlan,
    ) -> None:
        cursor.execute(
            """
            UPDATE merchant_ops.procurement_records
            SET
                external_id = %s,
                status = %s,
                updated_at = CURRENT_TIMESTAMP,
                version = %s
            WHERE id = %s
              AND project_id = %s
              AND procurement_type = %s
              AND version = %s
            """,
            (
                plan.external_id,
                plan.status,
                plan.new_version,
                uuid.UUID(plan.procurement_id),
                uuid.UUID(plan.project_id),
                plan.procurement_type,
                plan.current_version,
            ),
        )

        if cursor.rowcount != 1:
            raise ProcurementConflictError(
                "Procurement record changed before the "
                "mutation could be applied"
            )

    @staticmethod
    def _insert_event(
        cursor: Any,
        plan: ProcurementMutationPlan,
        event_id: uuid.UUID,
    ) -> None:
        cursor.execute(
            """
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
                %s, %s, %s, %s, 'PROCUREMENT',
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
            """,
            (
                event_id,
                uuid.UUID(plan.merchant_id),
                uuid.UUID(plan.project_id),
                plan.event_type,
                uuid.UUID(plan.procurement_id),
                plan.change_summary,
                Jsonb(plan.old_values),
                Jsonb(plan.new_values),
                (
                    uuid.UUID(plan.triggered_by)
                    if plan.triggered_by is not None
                    else None
                ),
            ),
        )


def _uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ProcurementPersistenceError(
            f"{field_name} must be a valid UUID"
        ) from error
