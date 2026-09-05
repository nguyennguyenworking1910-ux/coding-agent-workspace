"""Pure planning for Merchant integration identifier mutations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any


IDENTIFIER_TYPES = frozenset(
    {
        "AGENT",
        "MASTER_MID",
        "MID",
        "MERCHANT_CODE",
        "PARTNER_CODE",
        "PRODUCT_ID",
        "ORDER_GROUP_ID",
        "STORE_ID",
        "JIRA_TICKET",
    }
)

IDENTIFIER_SCOPES = frozenset(
    {
        "MASTER",
        "UAT",
        "PRODUCTION",
    }
)

MAX_IDENTIFIER_VALUE_LENGTH = 500


class IdentifierEngineError(ValueError):
    """Base error for integration identifier planning."""


class IdentifierConflictError(IdentifierEngineError):
    """Raised when current integration state conflicts with a request."""


class IdentifierVersionConflictError(IdentifierConflictError):
    """Raised when an expected identifier version is stale."""


@dataclass(frozen=True, slots=True)
class IdentifierMutationPlan:
    """Validated identifier mutation with redacted audit metadata."""

    identifier_id: str
    merchant_id: str
    project_id: str | None
    identifier_type: str
    identifier_value: str
    scope: str
    is_active: bool
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


def propose_identifier_mutation(
    *,
    merchant_id: str,
    project_id: str | None,
    identifier_type: str,
    identifier_value: str,
    scope: str,
    current_identifier: Mapping[str, Any] | None,
    identifier_id: str | None = None,
    is_active: bool = True,
    expected_version: int | None = None,
    triggered_by: str | None = None,
) -> IdentifierMutationPlan:
    """Validate an insert or optimistic update without database access."""

    normalized_merchant_id = _uuid_identifier(
        merchant_id,
        "merchant_id",
    )
    normalized_project_id = (
        _uuid_identifier(project_id, "project_id")
        if project_id is not None
        else None
    )
    normalized_type = _choice(
        identifier_type,
        "identifier_type",
        IDENTIFIER_TYPES,
    )
    normalized_scope = _choice(
        scope,
        "scope",
        IDENTIFIER_SCOPES,
    )
    normalized_value = _identifier_value(identifier_value)

    if not isinstance(is_active, bool):
        raise IdentifierEngineError(
            "is_active must be boolean"
        )

    normalized_triggered_by = (
        _uuid_identifier(triggered_by, "triggered_by")
        if triggered_by is not None
        else None
    )

    if current_identifier is None:
        if expected_version is not None:
            raise IdentifierConflictError(
                "Identifier does not exist but expected_version "
                "was provided"
            )

        normalized_identifier_id = _uuid_identifier(
            identifier_id,
            "identifier_id",
        )
        current_version = None
        new_version = 1
        operation = "INSERT"
        previous_active = None
        value_changed = True
    else:
        current = _current_identifier(
            current_identifier,
            merchant_id=normalized_merchant_id,
            project_id=normalized_project_id,
            identifier_type=normalized_type,
            scope=normalized_scope,
        )
        normalized_identifier_id = current["identifier_id"]

        if identifier_id is not None:
            candidate_identifier_id = _uuid_identifier(
                identifier_id,
                "identifier_id",
            )

            if candidate_identifier_id != normalized_identifier_id:
                raise IdentifierConflictError(
                    "Requested identifier ID does not match the "
                    "current binding"
                )

        current_version = current["version"]

        if expected_version is None:
            raise IdentifierConflictError(
                "Existing integration identifier requires "
                "expected_version"
            )

        normalized_expected_version = _positive_integer(
            expected_version,
            "expected_version",
        )

        if normalized_expected_version != current_version:
            raise IdentifierVersionConflictError(
                "Integration identifier version changed before "
                "the mutation could be planned"
            )

        previous_active = current["is_active"]
        value_changed = (
            current["identifier_value"] != normalized_value
        )

        if (
            not value_changed
            and previous_active == is_active
        ):
            raise IdentifierConflictError(
                "Integration identifier mutation does not change "
                "value or active status"
            )

        new_version = current_version + 1
        operation = "UPDATE"

    old_values: dict[str, object] = {
        "identifier_type": normalized_type,
        "scope": normalized_scope,
        "is_active": previous_active,
        "value_recorded": current_identifier is not None,
        "version": current_version,
    }
    new_values: dict[str, object] = {
        "identifier_type": normalized_type,
        "scope": normalized_scope,
        "is_active": is_active,
        "value_recorded": True,
        "value_changed": value_changed,
        "version": new_version,
    }

    return IdentifierMutationPlan(
        identifier_id=normalized_identifier_id,
        merchant_id=normalized_merchant_id,
        project_id=normalized_project_id,
        identifier_type=normalized_type,
        identifier_value=normalized_value,
        scope=normalized_scope,
        is_active=is_active,
        current_version=current_version,
        new_version=new_version,
        operation=operation,
        triggered_by=normalized_triggered_by,
        event_type="INTEGRATION_IDENTIFIER_SET",
        change_summary=(
            "Integration identifier "
            f"{normalized_type}/{normalized_scope} set"
        ),
        old_values=old_values,
        new_values=new_values,
    )


def _current_identifier(
    record: Mapping[str, Any],
    *,
    merchant_id: str,
    project_id: str | None,
    identifier_type: str,
    scope: str,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise IdentifierEngineError(
            "current_identifier must be an object or null"
        )

    current_project_id = (
        _uuid_identifier(
            record.get("project_id"),
            "current_identifier.project_id",
        )
        if record.get("project_id") is not None
        else None
    )
    normalized = {
        "identifier_id": _uuid_identifier(
            record.get("id"),
            "current_identifier.id",
        ),
        "merchant_id": _uuid_identifier(
            record.get("merchant_id"),
            "current_identifier.merchant_id",
        ),
        "project_id": current_project_id,
        "identifier_type": _choice(
            record.get("identifier_type"),
            "current_identifier.identifier_type",
            IDENTIFIER_TYPES,
        ),
        "identifier_value": _identifier_value(
            record.get("identifier_value")
        ),
        "scope": _choice(
            record.get("scope"),
            "current_identifier.scope",
            IDENTIFIER_SCOPES,
        ),
        "is_active": record.get("is_active"),
        "version": _positive_integer(
            record.get("version"),
            "current_identifier.version",
        ),
    }

    if not isinstance(normalized["is_active"], bool):
        raise IdentifierEngineError(
            "current_identifier.is_active must be boolean"
        )

    expected_binding = (
        merchant_id,
        project_id,
        identifier_type,
        scope,
    )
    current_binding = (
        normalized["merchant_id"],
        normalized["project_id"],
        normalized["identifier_type"],
        normalized["scope"],
    )

    if current_binding != expected_binding:
        raise IdentifierConflictError(
            "Current integration identifier belongs to a "
            "different binding"
        )

    return normalized


def _choice(
    value: Any,
    field_name: str,
    choices: frozenset[str],
) -> str:
    if not isinstance(value, str):
        raise IdentifierEngineError(
            f"{field_name} must be one of: "
            f"{', '.join(sorted(choices))}"
        )

    normalized = value.strip().upper()

    if normalized not in choices:
        raise IdentifierEngineError(
            f"{field_name} must be one of: "
            f"{', '.join(sorted(choices))}"
        )

    return normalized


def _identifier_value(value: Any) -> str:
    if not isinstance(value, str):
        raise IdentifierEngineError(
            "identifier_value must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise IdentifierEngineError(
            "identifier_value cannot be blank"
        )

    if len(normalized) > MAX_IDENTIFIER_VALUE_LENGTH:
        raise IdentifierEngineError(
            "identifier_value cannot exceed "
            f"{MAX_IDENTIFIER_VALUE_LENGTH} characters"
        )

    return normalized


def _positive_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IdentifierEngineError(
            f"{field_name} must be a positive integer"
        )

    if value <= 0:
        raise IdentifierEngineError(
            f"{field_name} must be a positive integer"
        )

    return value


def _uuid_identifier(value: Any, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise IdentifierEngineError(
            f"{field_name} must be a valid UUID"
        ) from error
