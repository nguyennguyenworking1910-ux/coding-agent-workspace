"""Atomic persistence for Merchant document signing."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from claude.agents.tools.merchant.signing_engine import (
    DocumentSigningConflictError,
    DocumentSigningPlan,
    propose_document_signing,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
)


class SigningPersistenceError(RuntimeError):
    """Base error for document signing persistence."""


class SigningRevisionNotFoundError(SigningPersistenceError):
    """Raised when a signing revision does not exist."""


@dataclass(frozen=True, slots=True)
class DocumentSigningResult:
    """Summary of a committed document signing."""

    project_id: str
    document_revision_id: str
    document_type: str
    revision_number: int
    signed_at: datetime
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["signed_at"] = self.signed_at.isoformat()
        return payload


class MerchantSigningRepository:
    """Sign the latest eligible document revision atomically."""

    def __init__(
        self,
        repository: MerchantRepository,
    ) -> None:
        self.repository = repository

    def sign_document(
        self,
        *,
        document_revision_id: str,
        occurred_at: datetime | None = None,
        signed_by: str | None = None,
    ) -> DocumentSigningResult:
        """Validate persisted evidence, sign, and audit."""

        normalized_revision_id = _uuid(
            document_revision_id,
            "document_revision_id",
        )
        normalized_signed_by = (
            _uuid(signed_by, "signed_by")
            if signed_by is not None
            else None
        )

        with self.repository.connection() as connection:
            with connection.transaction():
                with connection.cursor(
                    row_factory=dict_row,
                ) as cursor:
                    project = self._lock_project(
                        cursor,
                        normalized_revision_id,
                    )
                    project_id = uuid.UUID(
                        str(project["id"])
                    )
                    revisions = self._lock_revisions(
                        cursor,
                        project_id,
                    )
                    approvals = self._lock_approvals(
                        cursor,
                        project_id,
                    )
                    procurement_records = (
                        self._lock_procurement_records(
                            cursor,
                            project_id,
                        )
                    )

                    plan = propose_document_signing(
                        {
                            "project": project,
                            "document_revisions": revisions,
                            "document_approvals": approvals,
                            "procurement_records": (
                                procurement_records
                            ),
                        },
                        document_revision_id=str(
                            normalized_revision_id
                        ),
                        occurred_at=occurred_at,
                        signed_by=(
                            str(normalized_signed_by)
                            if normalized_signed_by
                            is not None
                            else None
                        ),
                    )

                    self._sign_revision(
                        cursor,
                        plan,
                    )

                    event_id = uuid.uuid4()
                    self._insert_event(
                        cursor,
                        plan,
                        event_id,
                    )

        return DocumentSigningResult(
            project_id=plan.project_id,
            document_revision_id=(
                plan.document_revision_id
            ),
            document_type=plan.document_type,
            revision_number=plan.revision_number,
            signed_at=plan.signed_at,
            event_id=str(event_id),
            event_type=plan.event_type,
        )

    @staticmethod
    def _lock_project(
        cursor: Any,
        document_revision_id: uuid.UUID,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT
                project.id,
                project.merchant_id,
                project.status,
                project.requires_procurement
            FROM merchant_ops.projects AS project
            JOIN merchant_ops.document_revisions
                AS revision
              ON revision.project_id = project.id
            WHERE revision.id = %s
            FOR UPDATE OF project
            """,
            (document_revision_id,),
        )

        project = cursor.fetchone()

        if project is None:
            raise SigningRevisionNotFoundError(
                "Document revision not found: "
                f"{document_revision_id}"
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
    def _lock_approvals(
        cursor: Any,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                approval.id,
                approval.document_revision_id,
                approval.approver_role,
                approval.approval_status,
                approval.approved_at,
                approval.approved_by,
                approval.notes,
                approval.created_at
            FROM merchant_ops.document_approvals
                AS approval
            JOIN merchant_ops.document_revisions
                AS revision
              ON revision.id = approval.document_revision_id
            WHERE revision.project_id = %s
            ORDER BY
                revision.document_type,
                revision.revision_number,
                approval.approver_role,
                approval.id
            FOR UPDATE OF approval
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
    def _sign_revision(
        cursor: Any,
        plan: DocumentSigningPlan,
    ) -> None:
        cursor.execute(
            """
            UPDATE merchant_ops.document_revisions
            SET
                signed = TRUE,
                signed_at = %s
            WHERE id = %s
              AND project_id = %s
              AND document_type = %s
              AND revision_number = %s
              AND signed = FALSE
              AND signed_at IS NULL
              AND superseded_by IS NULL
            """,
            (
                plan.signed_at,
                uuid.UUID(plan.document_revision_id),
                uuid.UUID(plan.project_id),
                plan.document_type,
                plan.revision_number,
            ),
        )

        if cursor.rowcount != 1:
            raise DocumentSigningConflictError(
                "Document revision changed before signing "
                "could be applied"
            )

    @staticmethod
    def _insert_event(
        cursor: Any,
        plan: DocumentSigningPlan,
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
                %s, %s, %s, %s, 'DOCUMENT',
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
            """,
            (
                event_id,
                uuid.UUID(plan.merchant_id),
                uuid.UUID(plan.project_id),
                plan.event_type,
                uuid.UUID(plan.document_revision_id),
                plan.change_summary,
                Jsonb(plan.old_values),
                Jsonb(plan.new_values),
                (
                    uuid.UUID(plan.signed_by)
                    if plan.signed_by is not None
                    else None
                ),
            ),
        )


def _uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise SigningPersistenceError(
            f"{field_name} must be a valid UUID"
        ) from error
