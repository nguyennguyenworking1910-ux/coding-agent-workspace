"""Transactional persistence for Merchant workflow projects."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from claude.agents.tools.merchant.project_factory import (
    ProjectInstantiationPlan,
    build_project_instantiation_plan,
)
from claude.agents.tools.merchant.workflow import (
    WorkflowTemplateDefinition,
    template_step_uuid,
    template_uuid,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
)


class WorkflowPersistenceError(RuntimeError):
    """Base error for workflow persistence."""


class MerchantNotFoundError(WorkflowPersistenceError):
    """Raised when the selected merchant does not exist."""


class WorkflowTemplateNotInstalledError(
    WorkflowPersistenceError
):
    """Raised when the immutable template is not installed."""


class ProjectCreationConflictError(
    WorkflowPersistenceError
):
    """Raised when project creation conflicts with stored data."""


class ReusedDocumentValidationError(
    WorkflowPersistenceError
):
    """Raised when a reused document is not eligible."""


@dataclass(frozen=True, slots=True)
class ProjectCreationResult:
    """Summary of a committed project creation."""

    project_id: str
    merchant_id: str
    workflow_variant: str
    status: str
    steps_inserted: int
    dependencies_inserted: int
    event_id: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MerchantWorkflowRepository:
    """Persist workflow projects through MerchantRepository."""

    def __init__(
        self,
        repository: MerchantRepository,
    ) -> None:
        self.repository = repository

    def create_project(
        self,
        *,
        merchant_id: str,
        template: WorkflowTemplateDefinition,
        requires_procurement: bool,
        payment_period_number: int | None = None,
        reused_document_revision_id: str | None = None,
        title: str | None = None,
        created_by: str | None = None,
        project_id: str | None = None,
    ) -> ProjectCreationResult:
        """Create one complete project instance atomically."""

        normalized_merchant_id = _uuid(
            merchant_id,
            "merchant_id",
        )

        try:
            with self.repository.connection() as connection:
                with connection.transaction():
                    with connection.cursor(
                        row_factory=dict_row,
                    ) as cursor:
                        merchant_status = (
                            self._merchant_status(
                                cursor,
                                normalized_merchant_id,
                            )
                        )

                        self._assert_template_installed(
                            cursor,
                            template,
                        )

                        plan = (
                            build_project_instantiation_plan(
                                merchant_id=str(
                                    normalized_merchant_id
                                ),
                                merchant_status=(
                                    merchant_status
                                ),
                                template=template,
                                requires_procurement=(
                                    requires_procurement
                                ),
                                payment_period_number=(
                                    payment_period_number
                                ),
                                reused_document_revision_id=(
                                    reused_document_revision_id
                                ),
                                title=title,
                                created_by=created_by,
                                project_id=project_id,
                            )
                        )

                        self._assert_project_id_available(
                            cursor,
                            plan.project["id"],
                        )

                        if (
                            plan.project[
                                "reused_document_revision_id"
                            ]
                            is not None
                        ):
                            self._assert_reused_document(
                                cursor,
                                normalized_merchant_id,
                                plan.project[
                                    "reused_document_revision_id"
                                ],
                            )

                        self._insert_project(
                            cursor,
                            plan,
                        )
                        self._insert_steps(
                            cursor,
                            plan,
                        )
                        self._insert_dependencies(
                            cursor,
                            plan,
                        )
                        self._insert_event(
                            cursor,
                            plan,
                        )

        except errors.UniqueViolation as error:
            raise ProjectCreationConflictError(
                "Project creation conflicts with an "
                "existing immutable record"
            ) from error

        return ProjectCreationResult(
            project_id=plan.project["id"],
            merchant_id=plan.project["merchant_id"],
            workflow_variant=(
                plan.project["workflow_variant"]
            ),
            status=plan.project["status"],
            steps_inserted=len(plan.steps),
            dependencies_inserted=len(
                plan.dependencies
            ),
            event_id=plan.event["id"],
        )

    @staticmethod
    def _merchant_status(
        cursor: Any,
        merchant_id: uuid.UUID,
    ) -> str:
        cursor.execute(
            """
            SELECT account_status
            FROM merchant_ops.merchants
            WHERE id = %s
            FOR SHARE
            """,
            (merchant_id,),
        )

        merchant = cursor.fetchone()

        if merchant is None:
            raise MerchantNotFoundError(
                f"Merchant not found: {merchant_id}"
            )

        return str(
            merchant["account_status"]
        ).strip().upper()

    @staticmethod
    def _assert_template_installed(
        cursor: Any,
        template: WorkflowTemplateDefinition,
    ) -> None:
        stable_template_id = template_uuid(template)

        cursor.execute(
            """
            SELECT
                id,
                name,
                version,
                variant,
                is_active
            FROM merchant_ops.workflow_templates
            WHERE id = %s
            FOR SHARE
            """,
            (stable_template_id,),
        )

        stored = cursor.fetchone()

        if stored is None:
            raise WorkflowTemplateNotInstalledError(
                "Workflow template is not installed: "
                f"{template.name!r} version "
                f"{template.version}"
            )

        expected_metadata = {
            "id": str(stable_template_id),
            "name": template.name,
            "version": template.version,
            "variant": template.variant,
            "is_active": template.is_active,
        }
        actual_metadata = {
            "id": str(stored["id"]),
            "name": stored["name"],
            "version": stored["version"],
            "variant": stored["variant"],
            "is_active": stored["is_active"],
        }

        if actual_metadata != expected_metadata:
            raise WorkflowTemplateNotInstalledError(
                "Stored workflow template metadata does "
                "not match the immutable definition"
            )

        if not stored["is_active"]:
            raise WorkflowTemplateNotInstalledError(
                "Workflow template is not active: "
                f"{template.name!r} version "
                f"{template.version}"
            )

        cursor.execute(
            """
            SELECT id
            FROM merchant_ops.workflow_template_steps
            WHERE template_id = %s
            ORDER BY id
            """,
            (stable_template_id,),
        )

        stored_step_ids = {
            str(record["id"])
            for record in cursor.fetchall()
        }
        expected_step_ids = {
            str(
                template_step_uuid(
                    template,
                    step.key,
                )
            )
            for step in template.steps
        }

        if stored_step_ids != expected_step_ids:
            raise WorkflowTemplateNotInstalledError(
                "Stored workflow template steps do not "
                "match the immutable definition"
            )

    @staticmethod
    def _assert_project_id_available(
        cursor: Any,
        project_id: str,
    ) -> None:
        cursor.execute(
            """
            SELECT id
            FROM merchant_ops.projects
            WHERE id = %s
            """,
            (uuid.UUID(project_id),),
        )

        if cursor.fetchone() is not None:
            raise ProjectCreationConflictError(
                f"Project already exists: {project_id}"
            )

    @staticmethod
    def _assert_reused_document(
        cursor: Any,
        merchant_id: uuid.UUID,
        revision_id: str,
    ) -> None:
        normalized_revision_id = _uuid(
            revision_id,
            "reused_document_revision_id",
        )

        cursor.execute(
            """
            SELECT
                revision.id,
                revision.signed,
                revision.signed_at,
                revision.superseded_by
            FROM merchant_ops.document_revisions
                AS revision
            JOIN merchant_ops.projects AS source_project
              ON source_project.id = revision.project_id
            WHERE revision.id = %s
              AND source_project.merchant_id = %s
            FOR SHARE OF revision, source_project
            """,
            (
                normalized_revision_id,
                merchant_id,
            ),
        )

        revision = cursor.fetchone()

        if revision is None:
            raise ReusedDocumentValidationError(
                "Reused document revision was not found "
                "for the selected merchant"
            )

        if (
            not revision["signed"]
            or revision["signed_at"] is None
        ):
            raise ReusedDocumentValidationError(
                "Reused document revision must be signed"
            )

        if revision["superseded_by"] is not None:
            raise ReusedDocumentValidationError(
                "Reused document revision has been "
                "superseded"
            )

    @staticmethod
    def _insert_project(
        cursor: Any,
        plan: ProjectInstantiationPlan,
    ) -> None:
        project = plan.project

        cursor.execute(
            """
            INSERT INTO merchant_ops.projects (
                id,
                merchant_id,
                project_type,
                workflow_variant,
                workflow_template_version_id,
                reused_document_revision_id,
                title,
                status,
                requires_procurement,
                started_at,
                completed_at,
                created_at,
                updated_at,
                created_by,
                version,
                payment_period_number
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                NULL, NULL,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                %s, %s, %s
            )
            """,
            (
                uuid.UUID(project["id"]),
                uuid.UUID(project["merchant_id"]),
                project["project_type"],
                project["workflow_variant"],
                uuid.UUID(
                    project[
                        "workflow_template_version_id"
                    ]
                ),
                (
                    uuid.UUID(
                        project[
                            "reused_document_revision_id"
                        ]
                    )
                    if project[
                        "reused_document_revision_id"
                    ]
                    else None
                ),
                project["title"],
                project["status"],
                project["requires_procurement"],
                (
                    uuid.UUID(project["created_by"])
                    if project["created_by"]
                    else None
                ),
                project["version"],
                project["payment_period_number"],
            ),
        )

    @staticmethod
    def _insert_steps(
        cursor: Any,
        plan: ProjectInstantiationPlan,
    ) -> None:
        query = """
            INSERT INTO merchant_ops.project_steps (
                id,
                project_id,
                template_step_id,
                branch_key,
                step_name,
                status,
                sequence_number,
                scheduled_start,
                scheduled_completion,
                actual_start,
                actual_completion,
                assigned_to,
                notes,
                created_at,
                updated_at,
                version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                NULL, NULL, NULL, NULL, NULL, NULL,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                %s
            )
        """

        for step in plan.steps:
            cursor.execute(
                query,
                (
                    uuid.UUID(step["id"]),
                    uuid.UUID(step["project_id"]),
                    uuid.UUID(
                        step["template_step_id"]
                    ),
                    step["branch_key"],
                    step["step_name"],
                    step["status"],
                    step["sequence_number"],
                    step["version"],
                ),
            )

    @staticmethod
    def _insert_dependencies(
        cursor: Any,
        plan: ProjectInstantiationPlan,
    ) -> None:
        query = """
            INSERT INTO
                merchant_ops.project_step_dependencies (
                    id,
                    from_step_id,
                    to_step_id,
                    dependency_type,
                    created_at
                )
            VALUES (
                %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
        """

        for dependency in plan.dependencies:
            cursor.execute(
                query,
                (
                    uuid.UUID(dependency["id"]),
                    uuid.UUID(
                        dependency["from_step_id"]
                    ),
                    uuid.UUID(
                        dependency["to_step_id"]
                    ),
                    dependency["dependency_type"],
                ),
            )

    @staticmethod
    def _insert_event(
        cursor: Any,
        plan: ProjectInstantiationPlan,
    ) -> None:
        event = plan.event

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
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
            """,
            (
                uuid.UUID(event["id"]),
                uuid.UUID(event["merchant_id"]),
                uuid.UUID(event["project_id"]),
                event["event_type"],
                event["entity_type"],
                uuid.UUID(event["entity_id"]),
                event["change_summary"],
                (
                    Jsonb(event["old_values"])
                    if event["old_values"] is not None
                    else None
                ),
                Jsonb(event["new_values"]),
                (
                    uuid.UUID(event["triggered_by"])
                    if event["triggered_by"]
                    else None
                ),
            ),
        )


def _uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise WorkflowPersistenceError(
            f"{field_name} must be a valid UUID"
        ) from error