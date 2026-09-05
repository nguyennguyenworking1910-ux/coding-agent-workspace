"""Pure planning for Merchant document signing."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from claude.agents.tools.merchant.gates import (
    GateValidationError,
    GateValidationResult,
    evaluate_signing_gate,
)
from claude.agents.tools.merchant.state_machine import (
    TERMINAL_PROJECT_STATUSES,
    normalize_project_status,
)


class DocumentSigningError(ValueError):
    """Base error for document signing planning."""


class DocumentSigningConflictError(DocumentSigningError):
    """Raised when document evidence is inconsistent."""


class DocumentSigningLifecycleClosedError(
    DocumentSigningError
):
    """Raised when a project cannot accept signing."""


class DocumentAlreadySignedError(
    DocumentSigningLifecycleClosedError
):
    """Raised when a revision has already been signed."""


class DocumentSigningGateError(DocumentSigningError):
    """Raised when persisted signing evidence is incomplete."""

    def __init__(
        self,
        gate_result: GateValidationResult,
    ) -> None:
        self.gate_result = gate_result
        blockers = ", ".join(
            gate_result.blocking_codes
        )
        super().__init__(
            "Document signing gate is not satisfied: "
            f"{blockers}"
        )


@dataclass(frozen=True, slots=True)
class DocumentSigningPlan:
    """Validated, database-independent signing mutation."""

    merchant_id: str
    project_id: str
    document_revision_id: str
    document_type: str
    revision_number: int
    signed_at: datetime
    signed_by: str | None
    event_type: str
    change_summary: str
    old_values: dict[str, object]
    new_values: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["signed_at"] = self.signed_at.isoformat()
        return payload


def propose_document_signing(
    snapshot: Mapping[str, Any],
    *,
    document_revision_id: str,
    occurred_at: datetime | None = None,
    signed_by: str | None = None,
) -> DocumentSigningPlan:
    """Validate and plan a one-way document signing."""

    project = dict(snapshot.get("project") or {})

    if not project:
        raise DocumentSigningError(
            "Signing snapshot has no project record"
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
        raise DocumentSigningLifecycleClosedError(
            "Documents cannot be signed for "
            f"a {project_status} project"
        )

    normalized_revision_id = _uuid_identifier(
        document_revision_id,
        "document_revision_id",
    )
    normalized_signed_by = (
        _uuid_identifier(signed_by, "signed_by")
        if signed_by is not None
        else None
    )
    normalized_revisions = _normalized_revisions(
        snapshot.get("document_revisions", ()),
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
        raise DocumentSigningError(
            "Document revision is not part of the project"
        )

    _require_latest_active_revision(
        revision,
        normalized_revisions,
    )

    if bool(revision["signed"]):
        raise DocumentAlreadySignedError(
            "Document revision is already signed"
        )

    try:
        gate_result = evaluate_signing_gate(
            {
                **project,
                "id": project_id,
                "merchant_id": merchant_id,
            },
            normalized_revisions,
            list(
                snapshot.get(
                    "document_approvals",
                    (),
                )
            ),
            list(
                snapshot.get(
                    "procurement_records",
                    (),
                )
            ),
            document_type=str(
                revision["document_type"]
            ),
        )
    except GateValidationError as error:
        raise DocumentSigningConflictError(
            "Signing snapshot contains invalid gate evidence"
        ) from error

    if gate_result.document_revision_id != (
        normalized_revision_id
    ):
        raise DocumentSigningConflictError(
            "Signing gate resolved a different document "
            "revision"
        )

    if not gate_result.all_met:
        raise DocumentSigningGateError(gate_result)

    signed_at = _normalized_datetime(occurred_at)
    document_type = str(revision["document_type"])
    revision_number = int(revision["revision_number"])
    old_values = {
        "document_type": document_type,
        "revision_number": revision_number,
        "signed": False,
        "signed_at_recorded": False,
    }
    new_values = {
        "document_type": document_type,
        "revision_number": revision_number,
        "signed": True,
        "signed_at_recorded": True,
    }

    return DocumentSigningPlan(
        merchant_id=merchant_id,
        project_id=project_id,
        document_revision_id=normalized_revision_id,
        document_type=document_type,
        revision_number=revision_number,
        signed_at=signed_at,
        signed_by=normalized_signed_by,
        event_type="DOCUMENT_SIGNED",
        change_summary="Document revision signed",
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

    for revision_value in revisions:
        revision = dict(revision_value)
        revision_id = _uuid_identifier(
            revision.get("id"),
            "document_revision.id",
        )

        if revision_id in revision_ids:
            raise DocumentSigningConflictError(
                "Signing snapshot contains a duplicate "
                "document revision id"
            )

        revision_ids.add(revision_id)
        revision_project_id = _uuid_identifier(
            revision.get("project_id"),
            "document_revision.project_id",
        )

        if revision_project_id != project_id:
            raise DocumentSigningConflictError(
                "Signing snapshot contains a revision "
                "from another project"
            )

        document_type = _required_text(
            revision.get("document_type"),
            "document_revision.document_type",
        ).upper()
        revision_number = _positive_integer(
            revision.get("revision_number"),
            "document_revision.revision_number",
        )
        type_number = (
            document_type,
            revision_number,
        )

        if type_number in type_numbers:
            raise DocumentSigningConflictError(
                "Signing snapshot contains duplicate "
                "document revision numbers"
            )

        type_numbers.add(type_number)
        superseded_by = (
            _uuid_identifier(
                revision.get("superseded_by"),
                "document_revision.superseded_by",
            )
            if revision.get("superseded_by") is not None
            else None
        )
        signed_value = revision.get("signed")

        if not isinstance(signed_value, bool):
            raise DocumentSigningConflictError(
                "Document revision signed flag must be "
                "a boolean"
            )

        signed = signed_value
        signed_at = revision.get("signed_at")

        if signed and signed_at is None:
            raise DocumentSigningConflictError(
                "Signed document revision has no timestamp"
            )

        if not signed and signed_at is not None:
            raise DocumentSigningConflictError(
                "Unsigned document revision has a signing "
                "timestamp"
            )

        normalized.append(
            {
                **revision,
                "id": revision_id,
                "project_id": revision_project_id,
                "document_type": document_type,
                "revision_number": revision_number,
                "superseded_by": superseded_by,
                "signed": signed,
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
        raise DocumentSigningConflictError(
            "Document type has multiple active revisions"
        )

    if (
        not active
        or active[0]["id"] != selected_revision["id"]
    ):
        raise DocumentSigningLifecycleClosedError(
            "Signing must target the latest active revision"
        )

    highest_revision_number = max(
        int(revision["revision_number"])
        for revision in matching
    )

    if (
        int(selected_revision["revision_number"])
        != highest_revision_number
    ):
        raise DocumentSigningConflictError(
            "Active document revision is not the latest "
            "revision number"
        )


def _normalized_datetime(
    value: datetime | None,
) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)

    if not isinstance(value, datetime):
        raise DocumentSigningError(
            "occurred_at must be a datetime or None"
        )

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DocumentSigningError(
            f"{field_name} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise DocumentSigningError(
            f"{field_name} cannot be empty"
        )

    return normalized


def _positive_integer(value: Any, field_name: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise DocumentSigningError(
            f"{field_name} must be a positive integer"
        )

    return value


def _uuid_identifier(value: Any, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise DocumentSigningError(
            f"{field_name} must be a valid UUID"
        ) from error
