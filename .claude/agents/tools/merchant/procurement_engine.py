"""Pure planning for Merchant procurement record mutations."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from claude.agents.tools.merchant.state_machine import (
    TERMINAL_PROJECT_STATUSES,
    normalize_project_status,
)


PROCUREMENT_TYPES = frozenset(
    {
        "PURCHASE_REQUEST",
        "PURCHASE_ORDER",
        "PAYMENT_REQUEST",
    }
)

PROCUREMENT_STATUS_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_]{0,49}$"
)


class ProcurementEngineError(ValueError):
    """Base error for procurement mutation planning."""


class ProcurementConflictError(ProcurementEngineError):
    """Raised when procurement state changed or is inconsistent."""


class ProcurementLifecycleClosedError(
    ProcurementEngineError
):
    """Raised when a terminal project cannot change procurement."""


class ProcurementDependencyError(ProcurementEngineError):
    """Raised when prerequisite evidence is missing."""


@dataclass(frozen=True, slots=True)
class ProcurementMutationPlan:
    """Validated, database-independent procurement mutation."""

    merchant_id: str
    project_id: str
    procurement_id: str
    procurement_type: str
    external_id: str | None
    status: str | None
    current_external_id: str | None
    current_status: str | None
    current_version: int | None
    new_version: int
    operation: str
    triggered_by: str | None
    event_type: str
    change_summary: str
    old_values: dict[str, object]
    new_values: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def propose_procurement_mutation(
    snapshot: Mapping[str, Any],
    *,
    procurement_id: str,
    procurement_type: str,
    external_id: str | None = None,
    status: str | None = None,
    expected_version: int | None = None,
    document_type: str | None = None,
    triggered_by: str | None = None,
) -> ProcurementMutationPlan:
    """Validate and plan one procurement create or update."""

    project = dict(snapshot.get("project") or {})

    if not project:
        raise ProcurementEngineError(
            "Procurement snapshot has no project record"
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
        raise ProcurementLifecycleClosedError(
            "Procurement records cannot change for "
            f"a {project_status} project"
        )

    candidate_procurement_id = _uuid_identifier(
        procurement_id,
        "procurement_id",
    )
    normalized_type = _procurement_type(
        procurement_type
    )
    normalized_external_id = _optional_external_id(
        external_id
    )
    normalized_status = _optional_status(status)
    normalized_document_type = (
        _required_text(
            document_type,
            "document_type",
        ).upper()
        if document_type is not None
        else None
    )
    normalized_triggered_by = (
        _uuid_identifier(
            triggered_by,
            "triggered_by",
        )
        if triggered_by is not None
        else None
    )

    records = _normalized_procurement_records(
        snapshot.get("procurement_records", ()),
        project_id,
    )
    existing = next(
        (
            record
            for record in records
            if record["procurement_type"]
            == normalized_type
        ),
        None,
    )

    if existing is None:
        if expected_version is not None:
            raise ProcurementConflictError(
                "Procurement record does not exist but "
                "expected_version was provided"
            )

        if any(
            record["id"] == candidate_procurement_id
            for record in records
        ):
            raise ProcurementConflictError(
                "New procurement id already exists in the "
                "procurement snapshot"
            )

        if (
            normalized_external_id is None
            and normalized_status is None
        ):
            raise ProcurementEngineError(
                "A new procurement record requires status "
                "or external_id"
            )

        resolved_procurement_id = (
            candidate_procurement_id
        )
        current_external_id = None
        current_status = None
        current_version = None
        new_version = 1
        operation = "INSERT"
    else:
        normalized_expected_version = _positive_integer(
            expected_version,
            "expected_version",
        )
        current_version = int(existing["version"])

        if normalized_expected_version != current_version:
            raise ProcurementConflictError(
                "Procurement version changed before the "
                "mutation could be planned"
            )

        resolved_procurement_id = str(existing["id"])
        current_external_id = existing["external_id"]
        current_status = existing["status"]

        if (
            normalized_external_id == current_external_id
            and normalized_status == current_status
        ):
            raise ProcurementConflictError(
                "Procurement mutation does not change "
                "external_id or status"
            )

        new_version = current_version + 1
        operation = "UPDATE"

    _validate_dependencies(
        project=project,
        project_id=project_id,
        procurement_type=normalized_type,
        document_type=normalized_document_type,
        revisions=snapshot.get(
            "document_revisions",
            (),
        ),
        procurement_records=records,
    )

    old_values = {
        "procurement_type": normalized_type,
        "status": current_status,
        "external_id_recorded": (
            current_external_id is not None
        ),
        "version": current_version,
    }
    new_values = {
        "procurement_type": normalized_type,
        "status": normalized_status,
        "external_id_recorded": (
            normalized_external_id is not None
        ),
        "version": new_version,
    }
    event_type = (
        "PROCUREMENT_CREATED"
        if operation == "INSERT"
        else "PROCUREMENT_UPDATED"
    )
    change_summary = (
        "Procurement record created"
        if operation == "INSERT"
        else "Procurement record updated"
    )

    return ProcurementMutationPlan(
        merchant_id=merchant_id,
        project_id=project_id,
        procurement_id=resolved_procurement_id,
        procurement_type=normalized_type,
        external_id=normalized_external_id,
        status=normalized_status,
        current_external_id=current_external_id,
        current_status=current_status,
        current_version=current_version,
        new_version=new_version,
        operation=operation,
        triggered_by=normalized_triggered_by,
        event_type=event_type,
        change_summary=change_summary,
        old_values=old_values,
        new_values=new_values,
    )


def _normalized_procurement_records(
    records: Sequence[Mapping[str, Any]],
    project_id: str,
) -> list[dict[str, Any]]:
    normalized = []
    record_ids = set()
    record_types = set()

    for record_value in records:
        record = dict(record_value)
        record_id = _uuid_identifier(
            record.get("id"),
            "procurement_record.id",
        )

        if record_id in record_ids:
            raise ProcurementConflictError(
                "Procurement snapshot contains a duplicate "
                "record id"
            )

        record_ids.add(record_id)

        stored_project_id = _uuid_identifier(
            record.get("project_id"),
            "procurement_record.project_id",
        )

        if stored_project_id != project_id:
            raise ProcurementConflictError(
                "Procurement snapshot contains a record "
                "from another project"
            )

        stored_type = _procurement_type(
            record.get("procurement_type")
        )

        if stored_type in record_types:
            raise ProcurementConflictError(
                "Procurement snapshot contains multiple "
                f"{stored_type} records"
            )

        record_types.add(stored_type)
        normalized.append(
            {
                **record,
                "id": record_id,
                "project_id": stored_project_id,
                "procurement_type": stored_type,
                "external_id": _optional_external_id(
                    record.get("external_id")
                ),
                "status": _optional_status(
                    record.get("status")
                ),
                "version": _positive_integer(
                    record.get("version"),
                    "procurement_record.version",
                ),
            }
        )

    return normalized


def _validate_dependencies(
    *,
    project: Mapping[str, Any],
    project_id: str,
    procurement_type: str,
    document_type: str | None,
    revisions: Sequence[Mapping[str, Any]],
    procurement_records: Sequence[Mapping[str, Any]],
) -> None:
    if procurement_type == "PURCHASE_REQUEST":
        return

    _require_signed_document(
        project_id,
        revisions,
        document_type=document_type,
    )

    if procurement_type == "PURCHASE_ORDER":
        if bool(project.get("requires_procurement")):
            _require_recorded_external_id(
                procurement_records,
                "PURCHASE_REQUEST",
                "Purchase Order requires a recorded "
                "Purchase Request number",
            )
        return

    _require_recorded_external_id(
        procurement_records,
        "PURCHASE_ORDER",
        "Payment Request requires a recorded "
        "Purchase Order number",
    )


def _require_signed_document(
    project_id: str,
    revisions: Sequence[Mapping[str, Any]],
    *,
    document_type: str | None,
) -> None:
    normalized_revisions = []
    revision_ids = set()
    type_numbers = set()

    for revision_value in revisions:
        revision = dict(revision_value)
        revision_project_id = _uuid_identifier(
            revision.get("project_id"),
            "document_revision.project_id",
        )

        if revision_project_id != project_id:
            raise ProcurementConflictError(
                "Procurement snapshot contains a revision "
                "from another project"
            )

        revision_id = _uuid_identifier(
            revision.get("id"),
            "document_revision.id",
        )

        if revision_id in revision_ids:
            raise ProcurementConflictError(
                "Procurement snapshot contains a duplicate "
                "document revision id"
            )

        revision_ids.add(revision_id)
        stored_document_type = _required_text(
            revision.get("document_type"),
            "document_revision.document_type",
        ).upper()
        revision_number = _positive_integer(
            revision.get("revision_number"),
            "document_revision.revision_number",
        )
        type_number = (
            stored_document_type,
            revision_number,
        )

        if type_number in type_numbers:
            raise ProcurementConflictError(
                "Procurement snapshot contains duplicate "
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

        normalized_revisions.append(
            {
                **revision,
                "id": revision_id,
                "document_type": stored_document_type,
                "revision_number": revision_number,
                "superseded_by": superseded_by,
            }
        )

    active_revisions = [
        revision
        for revision in normalized_revisions
        if revision["superseded_by"] is None
    ]

    active_types = {
        revision["document_type"]
        for revision in active_revisions
    }

    if document_type is None and len(active_types) > 1:
        raise ProcurementConflictError(
            "document_type is required when a project has "
            "multiple active document types"
        )

    candidates = [
        revision
        for revision in active_revisions
        if (
            document_type is None
            or revision["document_type"] == document_type
        )
    ]

    if not candidates:
        raise ProcurementDependencyError(
            "Procurement operation requires an active "
            "document revision"
        )

    if len(candidates) > 1:
        raise ProcurementConflictError(
            "Document type has multiple active revisions"
        )

    revision = candidates[0]
    matching_type_revisions = [
        record
        for record in normalized_revisions
        if record["document_type"]
        == revision["document_type"]
    ]
    highest_revision_number = max(
        int(record["revision_number"])
        for record in matching_type_revisions
    )

    if (
        int(revision["revision_number"])
        != highest_revision_number
    ):
        raise ProcurementConflictError(
            "Active document revision is not the latest "
            "revision number"
        )

    if (
        not bool(revision.get("signed"))
        or revision.get("signed_at") is None
    ):
        raise ProcurementDependencyError(
            "Procurement operation requires a signed "
            "active document revision"
        )


def _require_recorded_external_id(
    records: Sequence[Mapping[str, Any]],
    procurement_type: str,
    message: str,
) -> None:
    matching = next(
        (
            record
            for record in records
            if record["procurement_type"]
            == procurement_type
        ),
        None,
    )

    if (
        matching is None
        or matching.get("external_id") is None
    ):
        raise ProcurementDependencyError(message)


def _procurement_type(value: Any) -> str:
    normalized = _required_text(
        value,
        "procurement_type",
    ).upper()

    if normalized not in PROCUREMENT_TYPES:
        raise ProcurementEngineError(
            f"Unsupported procurement type: {normalized!r}"
        )

    return normalized


def _optional_status(value: Any) -> str | None:
    if value is None:
        return None

    normalized = _required_text(
        value,
        "status",
    ).upper()

    if not PROCUREMENT_STATUS_PATTERN.fullmatch(
        normalized
    ):
        raise ProcurementEngineError(
            "status must contain only uppercase letters, "
            "digits, and underscores"
        )

    return normalized


def _optional_external_id(value: Any) -> str | None:
    if value is None:
        return None

    normalized = _required_text(
        value,
        "external_id",
    )

    if len(normalized) > 100:
        raise ProcurementEngineError(
            "external_id cannot exceed 100 characters"
        )

    return normalized


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProcurementEngineError(
            f"{field_name} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ProcurementEngineError(
            f"{field_name} cannot be empty"
        )

    return normalized


def _positive_integer(value: Any, field_name: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ProcurementEngineError(
            f"{field_name} must be a positive integer"
        )

    return value


def _uuid_identifier(value: Any, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise ProcurementEngineError(
            f"{field_name} must be a valid UUID"
        ) from error
