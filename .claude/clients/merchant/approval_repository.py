"""Atomic persistence for Merchant document approvals."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from claude.agents.tools.merchant.approval_engine import (
    ApprovalConflictError,
    ApprovalMutationPlan,
    propose_document_approval,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
)


class ApprovalPersistenceError(RuntimeError):
    """Base error for document approval persistence."""


class ApprovalRevisionNotFoundError(
    ApprovalPersistenceError
):
    """Raised when an approval revision does not exist."""


@dataclass(frozen=True, slots=True)
class ApprovalMutationResult:
    """Summary of a committed document approval mutation."""

    project_id: str
    document_revision_id: str
    approval_id: str
    approver_role: str
    previous_status: str | None
    current_status: str
    operation: str
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MerchantApprovalRepository:
    """Record document approval decisions atomically."""

    def __init__(
        self,
        repository: MerchantRepository,
    ) -> None:
        self.repository = repository

    def record_approval(
        self,
        *,
        document_revision_id: str,
        approver_role: str,
        approval_status: str,
        expected_status: str | None = None,
        occurred_at: datetime | None = None,
        acted_by: str | None = None,
        notes: str | None = None,
        approval_id: str | None = None,
        recorded_by: str | None = None,
        precondition: Any = None,
    ) -> ApprovalMutationResult:
        """Create or finalize one revision-specific approval.

        CP12H.MASTER: ``recorded_by`` is the trusted local operator who records
        a decision on the approver's behalf. It is stored as the recorder
        (``recorded_by``, the event's ``triggered_by``) and never as the
        approver: ``approved_by`` stays NULL and ``acted_by`` must be absent.
        ``decided_at`` is the stated decision time (or now). These columns
        (migration 010) are written only when ``recorded_by`` is given.
        ``precondition(connection)`` runs after the locks; raising refuses
        the whole transaction.
        """

        if recorded_by is not None and acted_by is not None:
            raise ApprovalPersistenceError(
                "A recorded decision never names the recorder as the approver"
            )

        normalized_revision_id = _uuid(
            document_revision_id,
            "document_revision_id",
        )
        candidate_approval_id = (
            _uuid(approval_id, "approval_id")
            if approval_id is not None
            else uuid.uuid4()
        )
        normalized_acted_by = (
            _uuid(acted_by, "acted_by")
            if acted_by is not None
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

                        if precondition is not None:
                            precondition(connection)

                        plan = propose_document_approval(
                            {
                                "project": project,
                                "revisions": revisions,
                                "approvals": approvals,
                            },
                            document_revision_id=str(
                                normalized_revision_id
                            ),
                            approval_id=str(
                                candidate_approval_id
                            ),
                            approver_role=approver_role,
                            approval_status=approval_status,
                            expected_status=expected_status,
                            occurred_at=occurred_at,
                            acted_by=(
                                str(normalized_acted_by)
                                if normalized_acted_by
                                is not None
                                else None
                            ),
                            notes=notes,
                        )

                        recorder = None
                        if recorded_by is not None:
                            decided_at = (
                                plan.approved_at
                                or occurred_at
                                or datetime.now(timezone.utc)
                            )
                            recorder = (_uuid(recorded_by, "recorded_by"), decided_at)
                            plan = replace(
                                plan,
                                triggered_by=str(recorder[0]),
                                new_values={
                                    **plan.new_values,
                                    "attestation": "OPERATOR_RECORDED",
                                    "decided_at": decided_at.isoformat(),
                                },
                            )

                        if plan.operation == "INSERT":
                            self._insert_approval(
                                cursor,
                                plan,
                                recorder,
                            )
                        elif plan.operation == "UPDATE":
                            self._update_approval(
                                cursor,
                                plan,
                                recorder,
                            )
                        else:  # pragma: no cover
                            raise ApprovalPersistenceError(
                                "Unsupported approval operation: "
                                f"{plan.operation}"
                            )

                        event_id = uuid.uuid4()
                        self._insert_event(
                            cursor,
                            plan,
                            event_id,
                        )

        except errors.UniqueViolation as error:
            raise ApprovalConflictError(
                "Document approval conflicts with an "
                "existing revision-role record"
            ) from error

        return ApprovalMutationResult(
            project_id=plan.project_id,
            document_revision_id=(
                plan.document_revision_id
            ),
            approval_id=plan.approval_id,
            approver_role=plan.approver_role,
            previous_status=plan.current_status,
            current_status=plan.target_status,
            operation=plan.operation,
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
                project.status
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
            raise ApprovalRevisionNotFoundError(
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
    def _insert_approval(
        cursor: Any,
        plan: ApprovalMutationPlan,
        recorder: tuple[uuid.UUID, datetime] | None = None,
    ) -> None:
        extra_columns, extra_values = (
            (", recorded_by, decided_at", ", %s, %s") if recorder else ("", "")
        )
        cursor.execute(
            f"""
            INSERT INTO merchant_ops.document_approvals (
                id,
                document_revision_id,
                approver_role,
                approval_status,
                approved_at,
                approved_by,
                notes,
                created_at{extra_columns}
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP{extra_values}
            )
            """,
            (
                uuid.UUID(plan.approval_id),
                uuid.UUID(plan.document_revision_id),
                plan.approver_role,
                plan.target_status,
                plan.approved_at,
                (
                    uuid.UUID(plan.approved_by)
                    if plan.approved_by is not None
                    else None
                ),
                plan.notes,
                *(recorder or ()),
            ),
        )

    @staticmethod
    def _update_approval(
        cursor: Any,
        plan: ApprovalMutationPlan,
        recorder: tuple[uuid.UUID, datetime] | None = None,
    ) -> None:
        extra = ", recorded_by = %s, decided_at = %s" if recorder else ""
        cursor.execute(
            f"""
            UPDATE merchant_ops.document_approvals
            SET
                approval_status = %s,
                approved_at = %s,
                approved_by = %s,
                notes = %s{extra}
            WHERE id = %s
              AND document_revision_id = %s
              AND approver_role = %s
              AND approval_status = %s
            """,
            (
                plan.target_status,
                plan.approved_at,
                (
                    uuid.UUID(plan.approved_by)
                    if plan.approved_by is not None
                    else None
                ),
                plan.notes,
                *(recorder or ()),
                uuid.UUID(plan.approval_id),
                uuid.UUID(plan.document_revision_id),
                plan.approver_role,
                plan.current_status,
            ),
        )

        if cursor.rowcount != 1:
            raise ApprovalConflictError(
                "Document approval changed before the "
                "mutation could be applied"
            )

    @staticmethod
    def _insert_event(
        cursor: Any,
        plan: ApprovalMutationPlan,
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
        raise ApprovalPersistenceError(
            f"{field_name} must be a valid UUID"
        ) from error
