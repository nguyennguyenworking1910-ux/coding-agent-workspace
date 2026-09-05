"""Pure planning for Merchant document approval mutations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from claude.agents.tools.merchant.gates import (
    APPROVAL_STATUSES,
    APPROVER_ROLES,
)
from claude.agents.tools.merchant.state_machine import (
    TERMINAL_PROJECT_STATUSES,
    normalize_project_status,
)


FINAL_APPROVAL_STATUSES = frozenset(
    {
        "APPROVED",
        "REJECTED",
    }
)

APPROVAL_EVENT_TYPES = {
    "PENDING": "DOCUMENT_APPROVAL_REQUESTED",
    "APPROVED": "DOCUMENT_APPROVED",
    "REJECTED": "DOCUMENT_REJECTED",
}

APPROVAL_CHANGE_SUMMARIES = {
    "PENDING": "Document approval requested",
    "APPROVED": "Document revision approved",
    "REJECTED": "Document revision rejected",
}


class ApprovalEngineError(ValueError):
    """Base error for document approval planning."""


class ApprovalConflictError(ApprovalEngineError):
    """Raised when approval state changed or is inconsistent."""


class ApprovalLifecycleClosedError(ApprovalEngineError):
    """Raised when approval mutations are no longer allowed."""


class ApprovalRevisionNotActiveError(
    ApprovalLifecycleClosedError
):
    """Raised when a revision is not the latest active revision."""


class ApprovalFinalizedError(ApprovalLifecycleClosedError):
    """Raised when an existing approval is already final."""


@dataclass(frozen=True, slots=True)
class ApprovalMutationPlan:
    """Validated, database-independent approval mutation."""

    merchant_id: str
    project_id: str
    document_revision_id: str
    approval_id: str
    document_type: str
    revision_number: int
    approver_role: str
    current_status: str | None
    target_status: str
    operation: str
    approved_at: datetime | None
    approved_by: str | None
    notes: str | None
    triggered_by: str | None
    event_type: str
    change_summary: str
    old_values: dict[str, object]
    new_values: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["approved_at"] = (
            self.approved_at.isoformat()
            if self.approved_at is not None
            else None
        )
        return payload


def propose_document_approval(
    snapshot: Mapping[str, Any],
    *,
    document_revision_id: str,
    approval_id: str,
    approver_role: str,
    approval_status: str,
    expected_status: str | None = None,
    occurred_at: datetime | None = None,
    acted_by: str | None = None,
    notes: str | None = None,
) -> ApprovalMutationPlan:
    """Validate and plan one document approval mutation."""

    project = dict(snapshot.get("project") or {})

    if not project:
        raise ApprovalEngineError(
            "Approval snapshot has no project record"
        )

    merchant_id = _uuid_identifier(
        project.get("merchant_id"),
        "project.merchant_id",
    )
    project_id = _uuid_identifier(
        project.get("id"),
        "project.id",
    )
    project_status = normalize_project_status(
        str(project.get("status", ""))
    )

    if project_status in TERMINAL_PROJECT_STATUSES:
        raise ApprovalLifecycleClosedError(
            "Document approvals cannot change for "
            f"a {project_status} project"
        )

    normalized_revision_id = _uuid_identifier(
        document_revision_id,
        "document_revision_id",
    )
    candidate_approval_id = _uuid_identifier(
        approval_id,
        "approval_id",
    )
    normalized_role = _approval_role(approver_role)
    target_status = _approval_status(
        approval_status,
        "approval_status",
    )
    normalized_expected_status = (
        _approval_status(
            expected_status,
            "expected_status",
        )
        if expected_status is not None
        else None
    )
    normalized_acted_by = (
        _uuid_identifier(acted_by, "acted_by")
        if acted_by is not None
        else None
    )
    normalized_notes = _optional_text(notes, "notes")

    if occurred_at is not None and not isinstance(
        occurred_at,
        datetime,
    ):
        raise ApprovalEngineError(
            "occurred_at must be a datetime or None"
        )

    normalized_revisions = _normalized_revisions(
        snapshot.get("revisions", ()),
        project_id,
    )
    revision = next(
        (
            record
            for record in normalized_revisions
            if record["id"] == normalized_revision_id
        ),
        None,
    )

    if revision is None:
        raise ApprovalEngineError(
            "Document revision is not part of the project"
        )

    _require_latest_active_revision(
        revision,
        normalized_revisions,
    )

    if bool(revision.get("signed")):
        raise ApprovalLifecycleClosedError(
            "Signed document revisions cannot change approvals"
        )

    current_approval, stored_approval_ids = _approval_state(
        snapshot.get("approvals", ()),
        normalized_revisions,
        normalized_revision_id,
        normalized_role,
    )

    if current_approval is None:
        if normalized_expected_status is not None:
            raise ApprovalConflictError(
                "Approval does not exist but expected_status "
                "was provided"
            )

        if candidate_approval_id in stored_approval_ids:
            raise ApprovalConflictError(
                "New approval id already exists in the "
                "approval snapshot"
            )

        operation = "INSERT"
        resolved_approval_id = candidate_approval_id
        current_status = None
    else:
        current_status = str(
            current_approval["approval_status"]
        )

        if normalized_expected_status is None:
            raise ApprovalConflictError(
                "expected_status is required to update an "
                "existing approval"
            )

        if normalized_expected_status != current_status:
            raise ApprovalConflictError(
                "Approval status changed before the mutation "
                "could be planned"
            )

        if current_status in FINAL_APPROVAL_STATUSES:
            raise ApprovalFinalizedError(
                "Finalized approval decisions cannot be changed"
            )

        if target_status == current_status:
            raise ApprovalConflictError(
                "Approval target status must differ from its "
                "current status"
            )

        if target_status not in FINAL_APPROVAL_STATUSES:
            raise ApprovalEngineError(
                "A pending approval may only become APPROVED "
                "or REJECTED"
            )

        operation = "UPDATE"
        resolved_approval_id = str(
            current_approval["id"]
        )

    approved_at = (
        _normalized_datetime(occurred_at)
        if target_status == "APPROVED"
        else None
    )
    approved_by = (
        normalized_acted_by
        if target_status == "APPROVED"
        else None
    )
    document_type = str(revision["document_type"])
    revision_number = int(revision["revision_number"])

    old_values = {
        "document_type": document_type,
        "revision_number": revision_number,
        "approver_role": normalized_role,
        "approval_status": current_status,
    }
    new_values = {
        "document_type": document_type,
        "revision_number": revision_number,
        "approver_role": normalized_role,
        "approval_status": target_status,
    }

    return ApprovalMutationPlan(
        merchant_id=merchant_id,
        project_id=project_id,
        document_revision_id=normalized_revision_id,
        approval_id=resolved_approval_id,
        document_type=document_type,
        revision_number=revision_number,
        approver_role=normalized_role,
        current_status=current_status,
        target_status=target_status,
        operation=operation,
        approved_at=approved_at,
        approved_by=approved_by,
        notes=normalized_notes,
        triggered_by=normalized_acted_by,
        event_type=APPROVAL_EVENT_TYPES[target_status],
        change_summary=(
            APPROVAL_CHANGE_SUMMARIES[target_status]
        ),
        old_values=old_values,
        new_values=new_values,
    )


def _normalized_revisions(
    revisions: Sequence[Mapping[str, Any]],
    project_id: str,
) -> list[dict[str, Any]]:
    normalized = []
    revision_ids = set()
    type_numbers = set()

    for revision in revisions:
        record = dict(revision)
        revision_id = _uuid_identifier(
            record.get("id"),
            "document_revision.id",
        )

        if revision_id in revision_ids:
            raise ApprovalConflictError(
                "Approval snapshot contains a duplicate "
                "document revision id"
            )

        revision_ids.add(revision_id)

        stored_project_id = _uuid_identifier(
            record.get("project_id"),
            "document_revision.project_id",
        )

        if stored_project_id != project_id:
            raise ApprovalConflictError(
                "Approval snapshot contains a revision from "
                "another project"
            )

        document_type = _required_text(
            record.get("document_type"),
            "document_revision.document_type",
        ).upper()
        revision_number = _positive_integer(
            record.get("revision_number"),
            "document_revision.revision_number",
        )
        type_number = (
            document_type,
            revision_number,
        )

        if type_number in type_numbers:
            raise ApprovalConflictError(
                "Approval snapshot contains duplicate document "
                "revision numbers"
            )

        type_numbers.add(type_number)

        superseded_by = (
            _uuid_identifier(
                record.get("superseded_by"),
                "document_revision.superseded_by",
            )
            if record.get("superseded_by") is not None
            else None
        )

        normalized.append(
            {
                **record,
                "id": revision_id,
                "project_id": stored_project_id,
                "document_type": document_type,
                "revision_number": revision_number,
                "superseded_by": superseded_by,
            }
        )

    return normalized


def _require_latest_active_revision(
    selected_revision: Mapping[str, Any],
    revisions: Sequence[Mapping[str, Any]],
) -> None:
    document_type = selected_revision["document_type"]
    matching = [
        revision
        for revision in revisions
        if revision["document_type"] == document_type
    ]
    active = [
        revision
        for revision in matching
        if revision["superseded_by"] is None
    ]

    if len(active) > 1:
        raise ApprovalConflictError(
            "Document type has multiple active revisions"
        )

    if (
        not active
        or active[0]["id"] != selected_revision["id"]
    ):
        raise ApprovalRevisionNotActiveError(
            "Approval must target the latest active revision"
        )

    highest_revision_number = max(
        int(revision["revision_number"])
        for revision in matching
    )

    if (
        int(selected_revision["revision_number"])
        != highest_revision_number
    ):
        raise ApprovalConflictError(
            "Active document revision is not the latest "
            "revision number"
        )


def _approval_state(
    approvals: Sequence[Mapping[str, Any]],
    revisions: Sequence[Mapping[str, Any]],
    selected_revision_id: str,
    selected_role: str,
) -> tuple[dict[str, Any] | None, set[str]]:
    revision_ids = {
        str(revision["id"])
        for revision in revisions
    }
    approval_ids = set()
    revision_roles = set()
    current = None

    for approval in approvals:
        record = dict(approval)
        approval_id = _uuid_identifier(
            record.get("id"),
            "document_approval.id",
        )

        if approval_id in approval_ids:
            raise ApprovalConflictError(
                "Approval snapshot contains a duplicate "
                "approval id"
            )

        approval_ids.add(approval_id)

        revision_id = _uuid_identifier(
            record.get("document_revision_id"),
            "document_approval.document_revision_id",
        )

        if revision_id not in revision_ids:
            raise ApprovalConflictError(
                "Approval snapshot contains an approval for "
                "an unknown document revision"
            )

        role = _approval_role(record.get("approver_role"))
        status = _approval_status(
            record.get("approval_status"),
            "document_approval.approval_status",
        )
        revision_role = (revision_id, role)

        if revision_role in revision_roles:
            raise ApprovalConflictError(
                "Approval snapshot contains duplicate roles "
                "for a document revision"
            )

        revision_roles.add(revision_role)

        approved_at = record.get("approved_at")

        if status == "APPROVED" and approved_at is None:
            raise ApprovalConflictError(
                "Approved document approval has no timestamp"
            )

        if status != "APPROVED" and approved_at is not None:
            raise ApprovalConflictError(
                "Non-approved document approval has an "
                "approval timestamp"
            )

        normalized = {
            **record,
            "id": approval_id,
            "document_revision_id": revision_id,
            "approver_role": role,
            "approval_status": status,
        }

        if (
            revision_id == selected_revision_id
            and role == selected_role
        ):
            current = normalized

    return current, approval_ids


def _approval_role(value: Any) -> str:
    normalized = _required_text(
        value,
        "approver_role",
    ).upper()

    if normalized not in APPROVER_ROLES:
        raise ApprovalEngineError(
            f"Unsupported approver role: {normalized!r}"
        )

    return normalized


def _approval_status(value: Any, field_name: str) -> str:
    normalized = _required_text(
        value,
        field_name,
    ).upper()

    if normalized not in APPROVAL_STATUSES:
        raise ApprovalEngineError(
            f"Unsupported approval status: {normalized!r}"
        )

    return normalized


def _uuid_identifier(value: Any, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise ApprovalEngineError(
            f"{field_name} must be a valid UUID"
        ) from error


def _positive_integer(value: Any, field_name: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ApprovalEngineError(
            f"{field_name} must be a positive integer"
        )

    return value


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ApprovalEngineError(
            f"{field_name} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ApprovalEngineError(
            f"{field_name} cannot be empty"
        )

    return normalized


def _optional_text(
    value: Any,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    normalized = _required_text(value, field_name)
    return normalized


def _normalized_datetime(
    value: datetime | None,
) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)

    if not isinstance(value, datetime):
        raise ApprovalEngineError(
            "occurred_at must be a datetime or None"
        )

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)
