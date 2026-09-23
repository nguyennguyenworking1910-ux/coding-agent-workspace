from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


REQUIRED_WRITE_FIELDS = MappingProxyType(
    {
        "merchant create": (
            "code",
            "name",
        ),
        "merchant activate": (
            "merchant_id",
            "expected_version",
            "reason",
            "triggered_by",
        ),
        "merchant activate-all": (
            "from_status",
            "expected_count",
            "reason",
            "triggered_by",
        ),
        "contact import": (
            "merchant_id",
            "file",
            "expected_version",
        ),
        "project create": (
            "merchant_id",
            "project_type",
            "workflow_variant",
        ),
        "project update": (
            "project_id",
            "status",
            "expected_version",
        ),
        "step update": (
            "step_id",
            "status",
            "expected_version",
        ),
        "document revision-create": (
            "project_id",
            "document_type",
            "content_hash",
        ),
        "document approve": (
            "revision_id",
            "approver_role",
            "approval_status",
        ),
        "procurement update": (
            "project_id",
            "procurement_type",
        ),
        "integration identifier-set": (
            "merchant_id",
            "identifier_type",
            "value",
            "scope",
        ),
    }
)


@dataclass(frozen=True)
class CompletenessResult:
    command: str
    complete: bool
    missing_fields: tuple[str, ...]
    missing_one_of: tuple[
        tuple[str, ...],
        ...
    ] = ()


@dataclass(frozen=True)
class StatefulCompletenessContext:
    current_record_exists: bool | None = None
    active_document_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClarificationPayload:
    outcome: str
    missing_fields: tuple[str, ...]
    missing_one_of: tuple[
        tuple[str, ...],
        ...
    ]
    question: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "missing_fields": list(
                self.missing_fields
            ),
            "missing_one_of": [
                list(group)
                for group
                in self.missing_one_of
            ],
            "question": self.question,
        }


def _joined_fields(
    fields: tuple[str, ...],
) -> str:
    if not fields:
        return ""

    if len(fields) == 1:
        return fields[0]

    if len(fields) == 2:
        return (
            f"{fields[0]} and "
            f"{fields[1]}"
        )

    return (
        ", ".join(
            fields[:-1]
        )
        + f", and {fields[-1]}"
    )


def _is_missing(value: Any) -> bool:
    if value is None:
        return True

    return (
        isinstance(value, str)
        and not value.strip()
    )


def validate_stateful_write_completeness(
    command: str,
    values: Mapping[str, Any],
    context: StatefulCompletenessContext,
) -> CompletenessResult:
    """Apply requirements that depend on authoritative current state."""

    static_result = validate_write_completeness(
        command,
        values,
    )

    normalized_command = (
        static_result.command
    )

    missing_fields = list(
        static_result.missing_fields
    )

    missing_one_of: list[
        tuple[str, ...]
    ] = list(
        static_result.missing_one_of
    )

    # -------------------------------------------------
    # Procurement
    # -------------------------------------------------

    if (
        normalized_command
        == "procurement update"
    ):
        if (
            context.current_record_exists
            is False
        ):
            # Engine contract:
            # a new procurement record requires
            # status OR external_id.
            if (
                _is_missing(
                    values.get(
                        "status"
                    )
                )
                and _is_missing(
                    values.get(
                        "external_id"
                    )
                )
            ):
                missing_one_of.append(
                    (
                        "status",
                        "external_id",
                    )
                )

        elif (
            context.current_record_exists
            is True
        ):
            # Existing procurement mutations use
            # optimistic concurrency.
            if _is_missing(
                values.get(
                    "expected_version"
                )
            ):
                missing_fields.append(
                    "expected_version"
                )

        procurement_type = str(
            values.get(
                "procurement_type"
            )
            or ""
        ).strip().upper()

        active_types = tuple(
            sorted(
                {
                    str(value).strip().upper()
                    for value
                    in context.active_document_types
                    if str(value).strip()
                }
            )
        )

        if (
            procurement_type
            in {
                "PURCHASE_ORDER",
                "PAYMENT_REQUEST",
            }
            and len(active_types) > 1
            and _is_missing(
                values.get(
                    "document_type"
                )
            )
        ):
            missing_fields.append(
                "document_type"
            )

    # -------------------------------------------------
    # Integration identifier
    # -------------------------------------------------

    if (
        normalized_command
        == "integration identifier-set"
        and context.current_record_exists
        is True
        and _is_missing(
            values.get(
                "expected_version"
            )
        )
    ):
        missing_fields.append(
            "expected_version"
        )

    # Preserve deterministic order and remove duplicates.
    normalized_missing = tuple(
        dict.fromkeys(
            missing_fields
        )
    )

    normalized_one_of = tuple(
        dict.fromkeys(
            missing_one_of
        )
    )

    return CompletenessResult(
        command=normalized_command,
        complete=(
            not normalized_missing
            and not normalized_one_of
        ),
        missing_fields=normalized_missing,
        missing_one_of=normalized_one_of,
    )


def validate_write_completeness(
    command: str,
    values: Mapping[str, Any],
) -> CompletenessResult:
    """Deterministically report missing required fields for a write."""

    normalized_command = str(
        command or ""
    ).strip().lower()

    required_fields = REQUIRED_WRITE_FIELDS.get(
        normalized_command
    )

    if required_fields is None:
        raise ValueError(
            f"No completeness contract configured for command: "
            f"{normalized_command}"
        )

    missing: list[str] = []

    for field in required_fields:
        value = values.get(field)

        if value is None:
            missing.append(field)
            continue

        if (
            isinstance(value, str)
            and not value.strip()
        ):
            missing.append(field)

    missing_fields = tuple(
        missing
    )

    return CompletenessResult(
        command=normalized_command,
        complete=not missing_fields,
        missing_fields=missing_fields,
        missing_one_of=(),
    )


def build_clarification_payload(
    result: CompletenessResult,
) -> ClarificationPayload | None:
    """Build one deterministic clarification from completeness evidence."""

    if result.complete:
        return None

    clauses: list[str] = []

    if result.missing_fields:
        clauses.append(
            "Please provide "
            + _joined_fields(
                result.missing_fields
            )
        )

    for group in result.missing_one_of:
        clauses.append(
            "Please provide at least one of "
            + _joined_fields(
                group
            )
        )

    if not clauses:
        raise ValueError(
            "Incomplete result has no missing-field evidence"
        )

    question = "; ".join(
        clauses
    ) + "."

    return ClarificationPayload(
        outcome="REQUIRES_CLARIFICATION",
        missing_fields=result.missing_fields,
        missing_one_of=result.missing_one_of,
        question=question,
    )