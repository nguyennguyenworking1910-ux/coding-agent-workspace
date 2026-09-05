"""Pure planning for Merchant document revision lifecycles."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from claude.agents.tools.merchant.state_machine import (
    TERMINAL_PROJECT_STATUSES,
    normalize_project_status,
)


DOCUMENT_TYPE_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_]{0,99}$"
)


class DocumentEngineError(ValueError):
    """Base error for document revision planning."""


class DocumentLifecycleClosedError(DocumentEngineError):
    """Raised when a terminal project cannot accept revisions."""


class DocumentRevisionConflictError(DocumentEngineError):
    """Raised when stored revision history is inconsistent."""


@dataclass(frozen=True, slots=True)
class DocumentRevisionPlan:
    """Validated, database-independent revision mutation."""

    merchant_id: str
    project_id: str
    revision_id: str
    document_type: str
    revision_number: int
    content_hash: str
    effective_date: date | None
    expiry_date: date | None
    created_by: str | None
    previous_revision_id: str | None
    previous_revision_number: int | None
    event_type: str
    old_values: dict[str, object]
    new_values: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["effective_date"] = _serialized_date(
            self.effective_date
        )
        payload["expiry_date"] = _serialized_date(
            self.expiry_date
        )
        return payload


def propose_document_revision(
    snapshot: Mapping[str, Any],
    *,
    revision_id: str,
    document_type: str,
    content_hash: str,
    effective_date: date | None = None,
    expiry_date: date | None = None,
    created_by: str | None = None,
) -> DocumentRevisionPlan:
    """Validate and plan one immutable document revision."""

    project = dict(snapshot.get("project") or {})

    if not project:
        raise DocumentEngineError(
            "Document snapshot has no project record"
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
        raise DocumentLifecycleClosedError(
            "Document revisions cannot be created for "
            f"a {project_status} project"
        )

    normalized_revision_id = _uuid_identifier(
        revision_id,
        "revision_id",
    )
    normalized_document_type = _document_type(
        document_type
    )
    normalized_content_hash = _required_text(
        content_hash,
        "content_hash",
    )
    normalized_effective_date = _optional_date(
        effective_date,
        "effective_date",
    )
    normalized_expiry_date = _optional_date(
        expiry_date,
        "expiry_date",
    )
    normalized_created_by = (
        _uuid_identifier(created_by, "created_by")
        if created_by is not None
        else None
    )

    if (
        normalized_effective_date is not None
        and normalized_expiry_date is not None
        and normalized_expiry_date
        <= normalized_effective_date
    ):
        raise DocumentEngineError(
            "expiry_date must be later than "
            "effective_date"
        )

    revisions = [
        dict(revision)
        for revision in snapshot.get("revisions", ())
    ]
    matching_revisions = []
    seen_revision_ids = set()
    seen_revision_numbers = set()

    for revision in revisions:
        stored_revision_id = _uuid_identifier(
            revision.get("id"),
            "document_revision.id",
        )

        if stored_revision_id in seen_revision_ids:
            raise DocumentRevisionConflictError(
                "Document snapshot contains duplicate "
                f"revision id: {stored_revision_id}"
            )

        seen_revision_ids.add(stored_revision_id)

        if stored_revision_id == normalized_revision_id:
            raise DocumentRevisionConflictError(
                "New revision id already exists in the "
                "document snapshot"
            )

        stored_project_id = _uuid_identifier(
            revision.get("project_id"),
            "document_revision.project_id",
        )

        if stored_project_id != project_id:
            raise DocumentRevisionConflictError(
                "Document snapshot contains a revision "
                "from another project"
            )

        stored_document_type = _document_type(
            revision.get("document_type")
        )

        if stored_document_type != normalized_document_type:
            continue

        revision_number = _positive_integer(
            revision.get("revision_number"),
            "document_revision.revision_number",
        )

        if revision_number in seen_revision_numbers:
            raise DocumentRevisionConflictError(
                "Document snapshot contains duplicate "
                "revision numbers for document type "
                f"{normalized_document_type}"
            )

        seen_revision_numbers.add(revision_number)

        superseded_by = (
            _uuid_identifier(
                revision.get("superseded_by"),
                "document_revision.superseded_by",
            )
            if revision.get("superseded_by") is not None
            else None
        )

        if superseded_by == stored_revision_id:
            raise DocumentRevisionConflictError(
                "Document revision cannot supersede itself"
            )

        matching_revisions.append(
            {
                **revision,
                "id": stored_revision_id,
                "revision_number": revision_number,
                "superseded_by": superseded_by,
            }
        )

    active_revisions = [
        revision
        for revision in matching_revisions
        if revision["superseded_by"] is None
    ]

    if len(active_revisions) > 1:
        raise DocumentRevisionConflictError(
            "Document type has multiple active revisions"
        )

    previous_revision = (
        active_revisions[0]
        if active_revisions
        else None
    )
    highest_revision_number = max(
        (
            revision["revision_number"]
            for revision in matching_revisions
        ),
        default=0,
    )

    if (
        previous_revision is not None
        and previous_revision["revision_number"]
        != highest_revision_number
    ):
        raise DocumentRevisionConflictError(
            "Active document revision is not the latest "
            "revision number"
        )

    revision_number = highest_revision_number + 1
    previous_revision_id = (
        previous_revision["id"]
        if previous_revision is not None
        else None
    )
    previous_revision_number = (
        previous_revision["revision_number"]
        if previous_revision is not None
        else None
    )

    old_values = {
        "active_revision_number": (
            previous_revision_number
        ),
        "active_revision_signed": (
            bool(previous_revision.get("signed"))
            if previous_revision is not None
            else None
        ),
    }
    new_values = {
        "document_type": normalized_document_type,
        "revision_number": revision_number,
        "signed": False,
        "superseded_previous": (
            previous_revision is not None
        ),
    }

    return DocumentRevisionPlan(
        merchant_id=merchant_id,
        project_id=project_id,
        revision_id=normalized_revision_id,
        document_type=normalized_document_type,
        revision_number=revision_number,
        content_hash=normalized_content_hash,
        effective_date=normalized_effective_date,
        expiry_date=normalized_expiry_date,
        created_by=normalized_created_by,
        previous_revision_id=previous_revision_id,
        previous_revision_number=(
            previous_revision_number
        ),
        event_type="DOCUMENT_REVISION_CREATED",
        old_values=old_values,
        new_values=new_values,
    )


def _document_type(value: Any) -> str:
    if not isinstance(value, str):
        raise DocumentEngineError(
            "document_type must be a string"
        )

    normalized = value.strip().upper()

    if not DOCUMENT_TYPE_PATTERN.fullmatch(normalized):
        raise DocumentEngineError(
            "document_type must contain only uppercase "
            "letters, digits, and underscores"
        )

    return normalized


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise DocumentEngineError(
            f"{field_name} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise DocumentEngineError(
            f"{field_name} cannot be empty"
        )

    return normalized


def _uuid_identifier(
    value: Any,
    field_name: str,
) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise DocumentEngineError(
            f"{field_name} must be a valid UUID"
        ) from error


def _positive_integer(
    value: Any,
    field_name: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise DocumentEngineError(
            f"{field_name} must be a positive integer"
        )

    return value


def _optional_date(
    value: Any,
    field_name: str,
) -> date | None:
    if value is None:
        return None

    if not isinstance(value, date) or isinstance(
        value,
        datetime,
    ):
        raise DocumentEngineError(
            f"{field_name} must be a date or None"
        )

    return value


def _serialized_date(value: date | None) -> str | None:
    if value is None:
        return None

    return value.isoformat()
