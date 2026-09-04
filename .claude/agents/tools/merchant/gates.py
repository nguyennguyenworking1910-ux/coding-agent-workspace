"""Pure approval and signing gate validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


APPROVER_ROLES = frozenset(
    {
        "LEGAL",
        "ACCOUNTING",
        "PARTNER",
    }
)

APPROVAL_STATUSES = frozenset(
    {
        "PENDING",
        "APPROVED",
        "REJECTED",
    }
)

SIGNING_REQUIRED_ROLES = (
    "LEGAL",
    "ACCOUNTING",
    "PARTNER",
)


class GateValidationError(ValueError):
    """Raised when gate input data is structurally invalid."""


@dataclass(frozen=True, slots=True)
class GateValidationResult:
    """Result of an approval or signing gate evaluation."""

    gate_name: str
    project_id: str
    document_revision_id: str | None
    all_met: bool
    blocking_codes: tuple[str, ...]
    approved_roles: tuple[str, ...]
    missing_roles: tuple[str, ...]
    requires_procurement: bool
    purchase_request_present: bool
    already_signed: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible gate result."""

        return asdict(self)


def latest_document_revision(
    project_id: str,
    revisions: Sequence[Mapping[str, Any]],
    *,
    document_type: str | None = None,
) -> Mapping[str, Any] | None:
    """Return the latest non-superseded project revision."""

    normalized_project_id = _identifier(
        project_id,
        "project_id",
    )
    normalized_document_type = (
        _normalized_text(document_type)
        if document_type is not None
        else None
    )

    candidates = []

    for revision in revisions:
        revision_project_id = _identifier(
            revision.get("project_id"),
            "document_revision.project_id",
        )

        if revision_project_id != normalized_project_id:
            continue

        revision_type = _normalized_text(
            revision.get("document_type")
        )

        if (
            normalized_document_type is not None
            and revision_type != normalized_document_type
        ):
            continue

        if revision.get("superseded_by") is not None:
            continue

        revision_number = revision.get("revision_number")

        if (
            not isinstance(revision_number, int)
            or isinstance(revision_number, bool)
            or revision_number <= 0
        ):
            raise GateValidationError(
                "Document revision_number must be "
                "a positive integer"
            )

        _identifier(
            revision.get("id"),
            "document_revision.id",
        )
        candidates.append(revision)

    if not candidates:
        return None

    active_types = {
        _normalized_text(
            revision.get("document_type")
        )
        for revision in candidates
    }

    if (
        normalized_document_type is None
        and len(active_types) > 1
    ):
        raise GateValidationError(
            "document_type is required when a project "
            "has multiple active document types"
        )

    return max(
        candidates,
        key=lambda revision: (
            int(revision["revision_number"]),
            _identifier(
                revision.get("id"),
                "document_revision.id",
            ),
        ),
    )


def evaluate_approval_gate(
    project_id: str,
    revisions: Sequence[Mapping[str, Any]],
    approvals: Sequence[Mapping[str, Any]],
    *,
    required_roles: Sequence[str],
    document_type: str | None = None,
) -> GateValidationResult:
    """Validate approvals on the latest active revision."""

    normalized_project_id = _identifier(
        project_id,
        "project_id",
    )
    roles = _required_roles(required_roles)
    revision = latest_document_revision(
        normalized_project_id,
        revisions,
        document_type=document_type,
    )

    if revision is None:
        return GateValidationResult(
            gate_name="DOCUMENT_APPROVAL",
            project_id=normalized_project_id,
            document_revision_id=None,
            all_met=False,
            blocking_codes=("MISSING_DOCUMENT_REVISION",),
            approved_roles=(),
            missing_roles=roles,
            requires_procurement=False,
            purchase_request_present=False,
            already_signed=False,
        )

    revision_id = _identifier(
        revision.get("id"),
        "document_revision.id",
    )
    approval_by_role = _approval_index(
        approvals,
        revision_id,
    )

    approved_roles = tuple(
        role
        for role in roles
        if _approval_is_complete(
            approval_by_role.get(role)
        )
    )
    missing_roles = tuple(
        role
        for role in roles
        if role not in approved_roles
    )

    blocking_codes = []

    if missing_roles:
        blocking_codes.append("MISSING_REQUIRED_APPROVALS")

    return GateValidationResult(
        gate_name="DOCUMENT_APPROVAL",
        project_id=normalized_project_id,
        document_revision_id=revision_id,
        all_met=not blocking_codes,
        blocking_codes=tuple(blocking_codes),
        approved_roles=approved_roles,
        missing_roles=missing_roles,
        requires_procurement=False,
        purchase_request_present=False,
        already_signed=bool(revision.get("signed")),
    )


def evaluate_signing_gate(
    project: Mapping[str, Any],
    revisions: Sequence[Mapping[str, Any]],
    approvals: Sequence[Mapping[str, Any]],
    procurement_records: Sequence[Mapping[str, Any]],
    *,
    document_type: str | None = None,
) -> GateValidationResult:
    """Validate every prerequisite for document signing."""

    project_id = _identifier(
        project.get("id"),
        "project.id",
    )
    requires_procurement = bool(
        project.get("requires_procurement")
    )

    approval_result = evaluate_approval_gate(
        project_id,
        revisions,
        approvals,
        required_roles=SIGNING_REQUIRED_ROLES,
        document_type=document_type,
    )

    if approval_result.document_revision_id is None:
        return GateValidationResult(
            gate_name="DOCUMENT_SIGNING",
            project_id=project_id,
            document_revision_id=None,
            all_met=False,
            blocking_codes=approval_result.blocking_codes,
            approved_roles=(),
            missing_roles=approval_result.missing_roles,
            requires_procurement=requires_procurement,
            purchase_request_present=False,
            already_signed=False,
        )

    revision = latest_document_revision(
        project_id,
        revisions,
        document_type=document_type,
    )

    if revision is None:
        raise GateValidationError(
            "Latest revision disappeared during validation"
        )

    already_signed = bool(revision.get("signed"))
    purchase_request_present = (
        _has_valid_purchase_request(
            project_id,
            procurement_records,
        )
    )

    blocking_codes = list(
        approval_result.blocking_codes
    )

    if (
        requires_procurement
        and not purchase_request_present
    ):
        blocking_codes.append(
            "MISSING_PURCHASE_REQUEST"
        )

    if already_signed:
        blocking_codes.append(
            "DOCUMENT_ALREADY_SIGNED"
        )

    return GateValidationResult(
        gate_name="DOCUMENT_SIGNING",
        project_id=project_id,
        document_revision_id=(
            approval_result.document_revision_id
        ),
        all_met=not blocking_codes,
        blocking_codes=tuple(blocking_codes),
        approved_roles=approval_result.approved_roles,
        missing_roles=approval_result.missing_roles,
        requires_procurement=requires_procurement,
        purchase_request_present=purchase_request_present,
        already_signed=already_signed,
    )


def _approval_index(
    approvals: Sequence[Mapping[str, Any]],
    revision_id: str,
) -> dict[str, Mapping[str, Any]]:
    approval_by_role = {}

    for approval in approvals:
        approval_revision_id = _identifier(
            approval.get("document_revision_id"),
            "document_approval.document_revision_id",
        )

        if approval_revision_id != revision_id:
            continue

        role = _normalized_text(
            approval.get("approver_role")
        )

        if role not in APPROVER_ROLES:
            raise GateValidationError(
                f"Unsupported approver role: {role!r}"
            )

        status = _normalized_text(
            approval.get("approval_status")
        )

        if status not in APPROVAL_STATUSES:
            raise GateValidationError(
                f"Unsupported approval status: {status!r}"
            )

        if role in approval_by_role:
            raise GateValidationError(
                "Duplicate approval role for revision: "
                f"{role}"
            )

        approval_by_role[role] = approval

    return approval_by_role


def _approval_is_complete(
    approval: Mapping[str, Any] | None,
) -> bool:
    if approval is None:
        return False

    status = _normalized_text(
        approval.get("approval_status")
    )

    return (
        status == "APPROVED"
        and approval.get("approved_at") is not None
    )


def _has_valid_purchase_request(
    project_id: str,
    procurement_records: Sequence[Mapping[str, Any]],
) -> bool:
    for record in procurement_records:
        record_project_id = _identifier(
            record.get("project_id"),
            "procurement_record.project_id",
        )

        if record_project_id != project_id:
            continue

        procurement_type = _normalized_text(
            record.get("procurement_type")
        )

        if procurement_type != "PURCHASE_REQUEST":
            continue

        external_id = record.get("external_id")

        if (
            isinstance(external_id, str)
            and external_id.strip()
        ):
            return True

    return False


def _required_roles(
    required_roles: Sequence[str],
) -> tuple[str, ...]:
    normalized_roles = tuple(
        _normalized_text(role)
        for role in required_roles
    )

    if not normalized_roles:
        raise GateValidationError(
            "At least one approval role is required"
        )

    if len(normalized_roles) != len(
        set(normalized_roles)
    ):
        raise GateValidationError(
            "Required approval roles must be unique"
        )

    unsupported = sorted(
        set(normalized_roles) - APPROVER_ROLES
    )

    if unsupported:
        raise GateValidationError(
            "Unsupported required approval roles: "
            + ", ".join(unsupported)
        )

    return normalized_roles


def _identifier(value: Any, field_name: str) -> str:
    if value is None:
        raise GateValidationError(
            f"{field_name} is required"
        )

    normalized = str(value).strip()

    if not normalized:
        raise GateValidationError(
            f"{field_name} cannot be empty"
        )

    return normalized


def _normalized_text(value: Any) -> str:
    if not isinstance(value, str):
        raise GateValidationError(
            "Expected a non-empty string value"
        )

    normalized = value.strip().upper()

    if not normalized:
        raise GateValidationError(
            "Expected a non-empty string value"
        )

    return normalized