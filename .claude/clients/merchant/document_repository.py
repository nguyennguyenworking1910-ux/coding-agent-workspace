"""Atomic persistence for Merchant document revisions."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from claude.agents.tools.merchant.document_engine import (
    DocumentRevisionConflictError,
    DocumentRevisionPlan,
    propose_document_revision,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    ProjectNotFoundError,
)


class DocumentPersistenceError(RuntimeError):
    """Base error for document revision persistence."""


@dataclass(frozen=True, slots=True)
class DocumentRevisionResult:
    """Summary of a committed document revision."""

    project_id: str
    revision_id: str
    document_type: str
    revision_number: int
    previous_revision_id: str | None
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MerchantDocumentRepository:
    """Create immutable document revisions atomically."""

    def __init__(
        self,
        repository: MerchantRepository,
    ) -> None:
        self.repository = repository

    def create_revision(
        self,
        *,
        project_id: str,
        document_type: str,
        content_hash: str,
        effective_date: date | None = None,
        expiry_date: date | None = None,
        created_by: str | None = None,
        revision_id: str | None = None,
    ) -> DocumentRevisionResult:
        """Create a revision and supersede its predecessor."""

        normalized_project_id = _uuid(
            project_id,
            "project_id",
        )
        normalized_revision_id = (
            _uuid(revision_id, "revision_id")
            if revision_id is not None
            else uuid.uuid4()
        )
        normalized_created_by = (
            _uuid(created_by, "created_by")
            if created_by is not None
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

                        plan = propose_document_revision(
                            {
                                "project": project,
                                "revisions": revisions,
                            },
                            revision_id=str(
                                normalized_revision_id
                            ),
                            document_type=document_type,
                            content_hash=content_hash,
                            effective_date=effective_date,
                            expiry_date=expiry_date,
                            created_by=(
                                str(normalized_created_by)
                                if normalized_created_by
                                is not None
                                else None
                            ),
                        )

                        self._insert_revision(
                            cursor,
                            plan,
                        )

                        if (
                            plan.previous_revision_id
                            is not None
                        ):
                            self._supersede_previous(
                                cursor,
                                plan,
                            )

                        event_id = uuid.uuid4()
                        self._insert_event(
                            cursor,
                            plan,
                            event_id,
                        )

        except errors.UniqueViolation as error:
            raise DocumentRevisionConflictError(
                "Document revision conflicts with an "
                "existing immutable record"
            ) from error

        return DocumentRevisionResult(
            project_id=plan.project_id,
            revision_id=plan.revision_id,
            document_type=plan.document_type,
            revision_number=plan.revision_number,
            previous_revision_id=(
                plan.previous_revision_id
            ),
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
                project.status
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
    def _insert_revision(
        cursor: Any,
        plan: DocumentRevisionPlan,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO merchant_ops.document_revisions (
                id,
                project_id,
                document_type,
                revision_number,
                content_hash,
                signed,
                signed_at,
                effective_date,
                expiry_date,
                superseded_by,
                created_at,
                created_by
            )
            VALUES (
                %s, %s, %s, %s, %s,
                FALSE, NULL, %s, %s, NULL,
                CURRENT_TIMESTAMP, %s
            )
            """,
            (
                uuid.UUID(plan.revision_id),
                uuid.UUID(plan.project_id),
                plan.document_type,
                plan.revision_number,
                plan.content_hash,
                plan.effective_date,
                plan.expiry_date,
                (
                    uuid.UUID(plan.created_by)
                    if plan.created_by is not None
                    else None
                ),
            ),
        )

    @staticmethod
    def _supersede_previous(
        cursor: Any,
        plan: DocumentRevisionPlan,
    ) -> None:
        cursor.execute(
            """
            UPDATE merchant_ops.document_revisions
            SET superseded_by = %s
            WHERE id = %s
              AND project_id = %s
              AND document_type = %s
              AND revision_number = %s
              AND superseded_by IS NULL
            """,
            (
                uuid.UUID(plan.revision_id),
                uuid.UUID(plan.previous_revision_id),
                uuid.UUID(plan.project_id),
                plan.document_type,
                plan.previous_revision_number,
            ),
        )

        if cursor.rowcount != 1:
            raise DocumentRevisionConflictError(
                "Active document revision changed before "
                "it could be superseded"
            )

    @staticmethod
    def _insert_event(
        cursor: Any,
        plan: DocumentRevisionPlan,
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
                uuid.UUID(plan.revision_id),
                "Document revision created",
                Jsonb(plan.old_values),
                Jsonb(plan.new_values),
                (
                    uuid.UUID(plan.created_by)
                    if plan.created_by is not None
                    else None
                ),
            ),
        )


def _uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise DocumentPersistenceError(
            f"{field_name} must be a valid UUID"
        ) from error
