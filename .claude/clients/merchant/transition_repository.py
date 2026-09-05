"""Atomic persistence for Merchant step transitions."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from claude.agents.tools.merchant.engine import (
    WorkflowStepNotFoundError,
    WorkflowVersionConflictError,
    propose_step_transition,
)
from claude.agents.tools.merchant.gates import (
    GateValidationResult,
)
from claude.agents.tools.merchant.project_engine import (
    propose_project_transition,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    ProjectNotFoundError,
)
from claude.agents.tools.merchant.gate_resolver import (
    database_gate_kind,
    resolve_database_gate,
)


@dataclass(frozen=True, slots=True)
class StepTransitionResult:
    """Summary of a committed step transition."""

    project_id: str
    step_id: str
    previous_status: str
    current_status: str
    previous_version: int
    current_version: int
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProjectTransitionResult:
    """Summary of a committed project transition."""

    project_id: str
    previous_status: str
    current_status: str
    previous_version: int
    current_version: int
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MerchantStepTransitionRepository:
    """Validate and persist one step transition atomically."""

    def __init__(
        self,
        repository: MerchantRepository,
    ) -> None:
        self.repository = repository

    def transition_step(
        self,
        *,
        step_id: str,
        target_status: str,
        expected_version: int,
        occurred_at: datetime | None = None,
        triggered_by: str | None = None,
        allow_reopen: bool = False,
        gate_required: bool = False,
        gate_result: GateValidationResult | None = None,
    ) -> StepTransitionResult:
        """Lock project state, validate, update, and audit."""

        normalized_step_id = _uuid(
            step_id,
            "step_id",
        )
        normalized_triggered_by = (
            _uuid(triggered_by, "triggered_by")
            if triggered_by is not None
            else None
        )

        with self.repository.connection() as connection:
            with connection.transaction():
                with connection.cursor(
                    row_factory=dict_row,
                ) as cursor:
                    project = self._lock_project_for_step(
                        cursor,
                        normalized_step_id,
                    )
                    steps = self._lock_project_steps(
                        cursor,
                        project["id"],
                    )
                    dependencies = (
                        self._read_project_dependencies(
                            cursor,
                            project["id"],
                        )
                    )

                    current_step = next(
                        (
                            step
                            for step in steps
                            if str(step["id"])
                            == str(normalized_step_id)
                        ),
                        None,
                    )

                    if current_step is None:
                        raise WorkflowStepNotFoundError(
                            "Locked project snapshot does "
                            "not contain step: "
                            f"{normalized_step_id}"
                        )

                    stored_step_type = str(
                        current_step.get(
                            "step_type",
                            "",
                        )
                    ).strip().upper()

                    stored_gate_required = (
                        stored_step_type
                        == "APPROVAL_GATE"
                    )

                    effective_gate_required = (
                        gate_required
                        or stored_gate_required
                    )

                    effective_gate_result = gate_result

                    persisted_gate_kind = (
                        database_gate_kind(
                            current_step
                        )
                    )

                    if persisted_gate_kind is not None:
                        revisions = (
                            self._read_document_revisions(
                                cursor,
                                project["id"],
                            )
                        )
                        approvals = (
                            self._read_document_approvals(
                                cursor,
                                project["id"],
                            )
                        )
                        procurement_records = (
                            self._read_procurement_records(
                                cursor,
                                project["id"],
                            )
                        )

                        effective_gate_result = (
                            resolve_database_gate(
                                step=current_step,
                                project=project,
                                revisions=revisions,
                                approvals=approvals,
                                procurement_records=(
                                    procurement_records
                                ),
                            )
                        )

                    transition_plan = (
                        propose_step_transition(
                            {
                                "project": project,
                                "steps": steps,
                                "dependencies":
                                    dependencies,
                            },
                            str(normalized_step_id),
                            target_status,
                            expected_version=(
                                expected_version
                            ),
                            occurred_at=occurred_at,
                            allow_reopen=allow_reopen,
                            gate_required=(effective_gate_required),
                            gate_result=(
                                effective_gate_result
                            ),
                        )
                    )

                    cursor.execute(
                        """
                        UPDATE merchant_ops.project_steps
                        SET
                            status = %s,
                            actual_start = %s,
                            actual_completion = %s,
                            updated_at = CURRENT_TIMESTAMP,
                            version = %s
                        WHERE id = %s
                          AND project_id = %s
                          AND status = %s
                          AND version = %s
                        """,
                        (
                            transition_plan.target_status,
                            transition_plan.actual_start,
                            transition_plan.actual_completion,
                            transition_plan.new_version,
                            normalized_step_id,
                            uuid.UUID(
                                transition_plan.project_id
                            ),
                            transition_plan.current_status,
                            transition_plan.expected_version,
                        ),
                    )

                    if cursor.rowcount != 1:
                        raise WorkflowVersionConflictError(
                            "Project step changed before "
                            "transition could be applied"
                        )

                    event_id = uuid.uuid4()

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
                            %s, %s, %s, %s, 'STEP',
                            %s, %s, %s, %s, %s,
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            event_id,
                            uuid.UUID(
                                transition_plan.merchant_id
                            ),
                            uuid.UUID(
                                transition_plan.project_id
                            ),
                            transition_plan.event_type,
                            normalized_step_id,
                            (
                                "Project step status changed "
                                f"from "
                                f"{transition_plan.current_status} "
                                f"to "
                                f"{transition_plan.target_status}"
                            ),
                            Jsonb(
                                transition_plan.old_values
                            ),
                            Jsonb(
                                transition_plan.new_values
                            ),
                            normalized_triggered_by,
                        ),
                    )

        return StepTransitionResult(
            project_id=transition_plan.project_id,
            step_id=transition_plan.step_id,
            previous_status=(
                transition_plan.current_status
            ),
            current_status=(
                transition_plan.target_status
            ),
            previous_version=(
                transition_plan.expected_version
            ),
            current_version=transition_plan.new_version,
            event_id=str(event_id),
            event_type=transition_plan.event_type,
        )

    @staticmethod
    def _lock_project_for_step(
        cursor: Any,
        step_id: uuid.UUID,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT
                project.id,
                project.merchant_id,
                project.requires_procurement
            FROM merchant_ops.project_steps AS step
            JOIN merchant_ops.projects AS project
              ON project.id = step.project_id
            WHERE step.id = %s
            FOR UPDATE OF project
            """,
            (step_id,),
        )

        project = cursor.fetchone()

        if project is None:
            raise WorkflowStepNotFoundError(
                f"Project step not found: {step_id}"
            )

        return dict(project)

    @staticmethod
    def _lock_project_steps(
        cursor: Any,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                step.id,
                step.project_id,
                step.template_step_id,
                step.branch_key,
                step.step_name,
                template_step.step_type,
                step.status,
                step.sequence_number,
                step.actual_start,
                step.actual_completion,
                step.version
            FROM merchant_ops.project_steps AS step
            JOIN merchant_ops.workflow_template_steps
                AS template_step
              ON template_step.id = step.template_step_id
            WHERE step.project_id = %s
            ORDER BY step.sequence_number, step.id
            FOR UPDATE OF step
            """,
            (project_id,),
        )

        return [
            dict(record)
            for record in cursor.fetchall()
        ]

    @staticmethod
    def _read_project_dependencies(
        cursor: Any,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                dependency.id,
                dependency.from_step_id,
                dependency.to_step_id,
                dependency.dependency_type
            FROM
                merchant_ops.project_step_dependencies
                    AS dependency
            JOIN merchant_ops.project_steps AS source
              ON source.id = dependency.from_step_id
            JOIN merchant_ops.project_steps AS destination
              ON destination.id =
                 dependency.to_step_id
            WHERE source.project_id = %s
              AND destination.project_id = %s
            ORDER BY
                dependency.from_step_id,
                dependency.to_step_id,
                dependency.id
            """,
            (
                project_id,
                project_id,
            ),
        )

        return [
            dict(record)
            for record in cursor.fetchall()
        ]

    @staticmethod
    def _read_document_revisions(
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
                revision.created_at
            FROM merchant_ops.document_revisions
                AS revision
            WHERE revision.project_id = %s
            ORDER BY
                revision.document_type,
                revision.revision_number,
                revision.id
            FOR SHARE OF revision
            """,
            (project_id,),
        )

        return [
            dict(record)
            for record in cursor.fetchall()
        ]

    @staticmethod
    def _read_document_approvals(
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
                approval.notes
            FROM merchant_ops.document_approvals
                AS approval
            JOIN merchant_ops.document_revisions
                AS revision
              ON revision.id =
                 approval.document_revision_id
            WHERE revision.project_id = %s
            ORDER BY
                revision.revision_number,
                approval.approver_role,
                approval.id
            FOR SHARE OF approval, revision
            """,
            (project_id,),
        )

        return [
            dict(record)
            for record in cursor.fetchall()
        ]

    @staticmethod
    def _read_procurement_records(
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
                procurement.created_at,
                procurement.id
            FOR SHARE OF procurement
            """,
            (project_id,),
        )

        return [
            dict(record)
            for record in cursor.fetchall()
        ]


class MerchantProjectTransitionRepository:
    """Validate and persist one project transition atomically."""

    def __init__(
        self,
        repository: MerchantRepository,
    ) -> None:
        self.repository = repository

    def transition_project(
        self,
        *,
        project_id: str,
        target_status: str,
        expected_version: int,
        occurred_at: datetime | None = None,
        triggered_by: str | None = None,
        allow_reopen: bool = False,
    ) -> ProjectTransitionResult:
        """Lock project state, validate, update, and audit."""

        normalized_project_id = _uuid(
            project_id,
            "project_id",
        )
        normalized_triggered_by = (
            _uuid(triggered_by, "triggered_by")
            if triggered_by is not None
            else None
        )

        with self.repository.connection() as connection:
            with connection.transaction():
                with connection.cursor(
                    row_factory=dict_row,
                ) as cursor:
                    project = self._lock_project(
                        cursor,
                        normalized_project_id,
                    )
                    steps = self._lock_project_steps(
                        cursor,
                        normalized_project_id,
                    )

                    transition_plan = (
                        propose_project_transition(
                            {
                                "project": project,
                                "steps": steps,
                            },
                            target_status,
                            expected_version=(
                                expected_version
                            ),
                            occurred_at=occurred_at,
                            allow_reopen=allow_reopen,
                        )
                    )

                    cursor.execute(
                        """
                        UPDATE merchant_ops.projects
                        SET
                            status = %s,
                            started_at = %s,
                            completed_at = %s,
                            updated_at = CURRENT_TIMESTAMP,
                            version = %s
                        WHERE id = %s
                          AND merchant_id = %s
                          AND status = %s
                          AND version = %s
                        """,
                        (
                            transition_plan.target_status,
                            transition_plan.started_at,
                            transition_plan.completed_at,
                            transition_plan.new_version,
                            normalized_project_id,
                            uuid.UUID(
                                transition_plan.merchant_id
                            ),
                            transition_plan.current_status,
                            transition_plan.expected_version,
                        ),
                    )

                    if cursor.rowcount != 1:
                        raise WorkflowVersionConflictError(
                            "Project changed before transition "
                            "could be applied"
                        )

                    event_id = uuid.uuid4()

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
                            %s, %s, %s, %s, 'PROJECT',
                            %s, %s, %s, %s, %s,
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            event_id,
                            uuid.UUID(
                                transition_plan.merchant_id
                            ),
                            normalized_project_id,
                            transition_plan.event_type,
                            normalized_project_id,
                            (
                                "Project status changed from "
                                f"{transition_plan.current_status} "
                                "to "
                                f"{transition_plan.target_status}"
                            ),
                            Jsonb(
                                transition_plan.old_values
                            ),
                            Jsonb(
                                transition_plan.new_values
                            ),
                            normalized_triggered_by,
                        ),
                    )

        return ProjectTransitionResult(
            project_id=transition_plan.project_id,
            previous_status=(
                transition_plan.current_status
            ),
            current_status=(
                transition_plan.target_status
            ),
            previous_version=(
                transition_plan.expected_version
            ),
            current_version=transition_plan.new_version,
            event_id=str(event_id),
            event_type=transition_plan.event_type,
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
                project.started_at,
                project.completed_at,
                project.version
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
    def _lock_project_steps(
        cursor: Any,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                step.id,
                step.project_id,
                step.status
            FROM merchant_ops.project_steps AS step
            WHERE step.project_id = %s
            ORDER BY step.sequence_number, step.id
            FOR UPDATE OF step
            """,
            (project_id,),
        )

        return [
            dict(record)
            for record in cursor.fetchall()
        ]


def _uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(
            f"{field_name} must be a valid UUID"
        ) from error
