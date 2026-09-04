"""Pure project-instantiation planning for Merchant workflows."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any

from claude.agents.tools.merchant.branches import (
    resolve_workflow_branches,
)
from claude.agents.tools.merchant.workflow import (
    WorkflowTemplateDefinition,
    template_step_uuid,
    template_uuid,
)


MERCHANT_STATUSES = frozenset(
    {
        "ONBOARDING",
        "ACTIVE",
        "INACTIVE",
        "SUSPENDED",
    }
)


class ProjectInstantiationError(ValueError):
    """Raised when a project cannot be instantiated."""


@dataclass(frozen=True, slots=True)
class ProjectInstantiationPlan:
    """Validated records for one atomic project creation."""

    project: dict[str, Any]
    steps: tuple[dict[str, Any], ...]
    dependencies: tuple[dict[str, Any], ...]
    event: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible creation plan."""

        return asdict(self)


def build_project_instantiation_plan(
    *,
    merchant_id: str,
    merchant_status: str,
    template: WorkflowTemplateDefinition,
    requires_procurement: bool,
    payment_period_number: int | None = None,
    reused_document_revision_id: str | None = None,
    title: str | None = None,
    created_by: str | None = None,
    project_id: str | None = None,
) -> ProjectInstantiationPlan:
    """Validate inputs and build all project-instance records."""

    normalized_merchant_id = _uuid_string(
        merchant_id,
        "merchant_id",
    )
    normalized_merchant_status = _merchant_status(
        merchant_status
    )
    normalized_project_id = (
        _uuid_string(project_id, "project_id")
        if project_id is not None
        else str(uuid.uuid4())
    )
    normalized_created_by = (
        _uuid_string(created_by, "created_by")
        if created_by is not None
        else None
    )
    normalized_reused_revision_id = (
        _uuid_string(
            reused_document_revision_id,
            "reused_document_revision_id",
        )
        if reused_document_revision_id is not None
        else None
    )

    if not isinstance(requires_procurement, bool):
        raise ProjectInstantiationError(
            "requires_procurement must be boolean"
        )

    normalized_title = _optional_title(title)

    _validate_merchant_precondition(
        template,
        normalized_merchant_status,
    )
    _validate_payment_period(
        template,
        payment_period_number,
    )
    _validate_reused_document(
        template,
        normalized_reused_revision_id,
    )
    _validate_procurement_scope(
        template,
        requires_procurement,
    )

    branch_resolution = resolve_workflow_branches(
        template,
        {
            "requires_procurement":
                requires_procurement
        },
    )

    project_uuid = uuid.UUID(normalized_project_id)
    template_id = str(template_uuid(template))

    project_record = {
        "id": normalized_project_id,
        "merchant_id": normalized_merchant_id,
        "project_type": template.project_type,
        "workflow_variant": template.variant,
        "workflow_template_version_id": template_id,
        "reused_document_revision_id":
            normalized_reused_revision_id,
        "title": normalized_title,
        "status": "PLANNED",
        "requires_procurement":
            requires_procurement,
        "payment_period_number":
            payment_period_number,
        "created_by": normalized_created_by,
        "version": 1,
    }

    template_steps = {
        step.key: step
        for step in template.steps
    }
    resolved_steps = {
        step.key: step
        for step in branch_resolution.steps
    }

    step_ids = {
        step_key: _project_step_uuid(
            project_uuid,
            template_step_uuid(
                template,
                step_key,
            ),
        )
        for step_key in template_steps
    }

    step_records = tuple(
        {
            "id": step_ids[step.key],
            "project_id": normalized_project_id,
            "template_step_id": str(
                template_step_uuid(
                    template,
                    step.key,
                )
            ),
            "branch_key": step.branch_key,
            "step_name": step.name,
            "status":
                resolved_steps[
                    step.key
                ].initial_status,
            "sequence_number": step.sequence_number,
            "version": 1,
        }
        for step in sorted(
            template.steps,
            key=lambda item: (
                item.sequence_number,
                item.key,
            ),
        )
    )

    dependency_records = tuple(
        {
            "id": _project_dependency_uuid(
                project_uuid,
                step_ids[
                    dependency.from_step_key
                ],
                step_ids[
                    dependency.to_step_key
                ],
                dependency.dependency_type,
            ),
            "from_step_id": step_ids[
                dependency.from_step_key
            ],
            "to_step_id": step_ids[
                dependency.to_step_key
            ],
            "dependency_type":
                dependency.dependency_type,
        }
        for dependency in branch_resolution.dependencies
    )

    event_record = {
        "id": str(uuid.uuid4()),
        "merchant_id": normalized_merchant_id,
        "project_id": normalized_project_id,
        "event_type": "PROJECT_CREATED",
        "entity_type": "PROJECT",
        "entity_id": normalized_project_id,
        "change_summary": (
            "Merchant project created from immutable "
            "workflow template"
        ),
        "old_values": None,
        "new_values": {
            "project_type": template.project_type,
            "workflow_variant": template.variant,
            "workflow_template_version_id":
                template_id,
            "status": "PLANNED",
            "requires_procurement":
                requires_procurement,
            "payment_period_number":
                payment_period_number,
            "step_count": len(step_records),
            "dependency_count":
                len(dependency_records),
        },
        "triggered_by": normalized_created_by,
    }

    return ProjectInstantiationPlan(
        project=project_record,
        steps=step_records,
        dependencies=dependency_records,
        event=event_record,
    )


def _validate_merchant_precondition(
    template: WorkflowTemplateDefinition,
    merchant_status: str,
) -> None:
    expected_status = (
        "ONBOARDING"
        if template.project_type
        == "INTEGRATION_NEW_MERCHANT"
        else "ACTIVE"
    )

    if merchant_status != expected_status:
        raise ProjectInstantiationError(
            "Merchant status does not satisfy workflow "
            f"precondition for {template.variant}: "
            f"expected {expected_status}, "
            f"received {merchant_status}"
        )


def _validate_payment_period(
    template: WorkflowTemplateDefinition,
    payment_period_number: int | None,
) -> None:
    is_media_top_up = (
        template.project_type == "MEDIA_TOP_UP"
    )

    if is_media_top_up:
        if (
            not isinstance(payment_period_number, int)
            or isinstance(payment_period_number, bool)
            or payment_period_number < 1
        ):
            raise ProjectInstantiationError(
                "MEDIA_TOP_UP requires "
                "payment_period_number >= 1"
            )

        return

    if payment_period_number is not None:
        raise ProjectInstantiationError(
            "payment_period_number is only valid for "
            "MEDIA_TOP_UP projects"
        )


def _validate_reused_document(
    template: WorkflowTemplateDefinition,
    reused_document_revision_id: str | None,
) -> None:
    requires_reused_document = (
        template.variant
        == "MEDIA_TOP_UP_EXISTING_DOCUMENT"
    )

    if (
        requires_reused_document
        and reused_document_revision_id is None
    ):
        raise ProjectInstantiationError(
            "MEDIA_TOP_UP_EXISTING_DOCUMENT requires "
            "reused_document_revision_id"
        )

    if (
        not requires_reused_document
        and reused_document_revision_id is not None
    ):
        raise ProjectInstantiationError(
            "reused_document_revision_id is only valid for "
            "MEDIA_TOP_UP_EXISTING_DOCUMENT"
        )


def _validate_procurement_scope(
    template: WorkflowTemplateDefinition,
    requires_procurement: bool,
) -> None:
    if (
        template.variant
        == "MEDIA_TOP_UP_NEW_DOCUMENT"
        and not requires_procurement
    ):
        raise ProjectInstantiationError(
            "MEDIA_TOP_UP_NEW_DOCUMENT always requires "
            "procurement"
        )

    if (
        template.variant
        == "MEDIA_TOP_UP_EXISTING_DOCUMENT"
        and requires_procurement
    ):
        raise ProjectInstantiationError(
            "MEDIA_TOP_UP_EXISTING_DOCUMENT does not "
            "include a Purchase Request branch"
        )


def _merchant_status(status: str) -> str:
    if not isinstance(status, str):
        raise ProjectInstantiationError(
            "merchant_status must be a string"
        )

    normalized = status.strip().upper()

    if normalized not in MERCHANT_STATUSES:
        raise ProjectInstantiationError(
            f"Unknown merchant status: {status!r}"
        )

    return normalized


def _optional_title(title: str | None) -> str | None:
    if title is None:
        return None

    if not isinstance(title, str):
        raise ProjectInstantiationError(
            "title must be a string or None"
        )

    normalized = title.strip()

    if not normalized:
        return None

    if len(normalized) > 500:
        raise ProjectInstantiationError(
            "title cannot exceed 500 characters"
        )

    return normalized


def _uuid_string(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise ProjectInstantiationError(
            f"{field_name} must be a valid UUID"
        ) from error


def _project_step_uuid(
    project_id: uuid.UUID,
    template_step_id: uuid.UUID,
) -> str:
    return str(
        uuid.uuid5(
            project_id,
            f"merchant-project-step:{template_step_id}",
        )
    )


def _project_dependency_uuid(
    project_id: uuid.UUID,
    from_step_id: str,
    to_step_id: str,
    dependency_type: str,
) -> str:
    return str(
        uuid.uuid5(
            project_id,
            (
                "merchant-project-dependency:"
                f"{from_step_id}:"
                f"{to_step_id}:"
                f"{dependency_type}"
            ),
        )
    )