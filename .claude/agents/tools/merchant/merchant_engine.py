"""Pure planning for Merchant and contact mutations."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any


MERCHANT_CODE_PATTERN = re.compile(
    r"^[A-Z0-9][A-Z0-9_-]{0,49}$"
)
REGION_CODE_PATTERN = re.compile(
    r"^[A-Z0-9][A-Z0-9_-]{0,9}$"
)

CONTACT_TYPES = frozenset(
    {
        "PRIMARY",
        "BILLING",
        "TECHNICAL",
    }
)
PRIVACY_CLASSIFICATIONS = frozenset(
    {
        "PII",
        "SENSITIVE",
        "INTERNAL",
    }
)

MAX_CONTACT_IMPORT_ROWS = 1_000
CONTACT_NAME_LIMIT = 500
CONTACT_EMAIL_LIMIT = 320
CONTACT_PHONE_LIMIT = 50


class MerchantEngineError(ValueError):
    """Base error for Merchant mutation planning."""


class MerchantConflictError(MerchantEngineError):
    """Raised when a Merchant mutation conflicts with current state."""


class MerchantVersionConflictError(MerchantConflictError):
    """Raised when the expected Merchant version is stale."""


@dataclass(frozen=True, slots=True)
class MerchantCreationPlan:
    """Validated, database-independent Merchant creation."""

    merchant_id: str
    code: str
    name: str
    region_code: str | None
    account_status: str
    created_by: str | None
    version: int
    event_type: str
    change_summary: str
    old_values: dict[str, object]
    new_values: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContactRecordPlan:
    """One validated internal contact record."""

    contact_id: str
    contact_type: str | None
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    privacy_classification: str
    is_primary: bool
    version: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContactImportPlan:
    """Validated contact import with redacted audit metadata."""

    merchant_id: str
    records: tuple[ContactRecordPlan, ...]
    expected_version: int
    new_merchant_version: int
    triggered_by: str | None
    event_type: str
    change_summary: str
    old_values: dict[str, object]
    new_values: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MerchantActivationPlan:
    """Validated merchant activation with audit metadata."""

    merchant_id: str
    current_status: str
    target_status: str
    expected_version: int
    new_merchant_version: int
    reason: str
    triggered_by: str | None
    event_type: str
    change_summary: str
    old_values: dict[str, object]
    new_values: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MerchantBatchActivationManifest:
    """Deterministic manifest of merchants for batch activation verification."""

    merchants: tuple[dict[str, object], ...]  # Each: {id, code, current_status, version}
    payload_hash: str
    confirmation_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "merchants": list(self.merchants),
            "payload_hash": self.payload_hash,
            "confirmation_hash": self.confirmation_hash,
        }


@dataclass(frozen=True, slots=True)
class MerchantBatchActivationPlan:
    """Batch activation plan for multiple merchants with deterministic ordering."""

    merchants: tuple[MerchantActivationPlan, ...]
    manifest: MerchantBatchActivationManifest
    from_status: str
    target_status: str
    reason: str
    triggered_by: str | None
    event_type: str
    change_summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "merchants": [plan.to_dict() for plan in self.merchants],
            "manifest": self.manifest.to_dict(),
            "from_status": self.from_status,
            "target_status": self.target_status,
            "reason": self.reason,
            "triggered_by": self.triggered_by,
            "event_type": self.event_type,
            "change_summary": self.change_summary,
        }


def propose_merchant_creation(
    *,
    merchant_id: str,
    code: str,
    name: str,
    region_code: str | None = None,
    created_by: str | None = None,
) -> MerchantCreationPlan:
    """Validate and plan one Merchant creation."""

    normalized_id = _uuid_identifier(
        merchant_id,
        "merchant_id",
    )
    normalized_code = _merchant_code(code)
    normalized_name = _required_text(
        name,
        "name",
        maximum=500,
    )
    normalized_region = _optional_region_code(region_code)
    normalized_created_by = (
        _uuid_identifier(created_by, "created_by")
        if created_by is not None
        else None
    )
    new_values: dict[str, object] = {
        "code": normalized_code,
        "name": normalized_name,
        "region_code": normalized_region,
        "account_status": "ONBOARDING",
        "version": 1,
    }

    return MerchantCreationPlan(
        merchant_id=normalized_id,
        code=normalized_code,
        name=normalized_name,
        region_code=normalized_region,
        account_status="ONBOARDING",
        created_by=normalized_created_by,
        version=1,
        event_type="MERCHANT_CREATED",
        change_summary=(
            f"Merchant {normalized_code} created"
        ),
        old_values={},
        new_values=new_values,
    )


def propose_contact_import(
    merchant: Mapping[str, Any],
    *,
    contacts: Sequence[Mapping[str, Any]],
    expected_version: int,
    triggered_by: str | None = None,
) -> ContactImportPlan:
    """Validate a contact batch against locked Merchant state."""

    normalized_expected_version = _positive_integer(
        expected_version,
        "expected_version",
    )
    merchant_id = _uuid_identifier(
        merchant.get("id"),
        "merchant.id",
    )
    current_version = _positive_integer(
        merchant.get("version"),
        "merchant.version",
    )

    if normalized_expected_version != current_version:
        raise MerchantVersionConflictError(
            "Merchant version changed before contacts "
            "could be imported"
        )

    normalized_triggered_by = (
        _uuid_identifier(triggered_by, "triggered_by")
        if triggered_by is not None
        else None
    )
    records = _contact_records(contacts)
    new_version = current_version + 1
    primary_count = sum(
        1 for record in records if record.is_primary
    )

    return ContactImportPlan(
        merchant_id=merchant_id,
        records=records,
        expected_version=current_version,
        new_merchant_version=new_version,
        triggered_by=normalized_triggered_by,
        event_type="MERCHANT_CONTACTS_IMPORTED",
        change_summary=(
            f"Imported {len(records)} merchant contact(s)"
        ),
        old_values={
            "merchant_version": current_version,
        },
        new_values={
            "contacts_imported": len(records),
            "primary_contacts_imported": primary_count,
            "merchant_version": new_version,
        },
    )


def propose_merchant_batch_activation(
    merchants: Sequence[Mapping[str, Any]],
    *,
    reason: str,
    triggered_by: str | None = None,
) -> MerchantBatchActivationPlan:
    """Validate and plan batch merchant activation with manifest binding."""

    if not merchants:
        raise MerchantEngineError(
            "batch activation requires at least one merchant"
        )

    normalized_reason = _required_text(
        reason,
        "reason",
        maximum=500,
    )
    normalized_triggered_by = (
        _uuid_identifier(triggered_by, "triggered_by")
        if triggered_by is not None
        else None
    )

    # Verify all merchants are ONBOARDING
    merchant_list = list(merchants)
    for merchant in merchant_list:
        current_status = merchant.get("account_status", "").upper()
        if current_status != "ONBOARDING":
            raise MerchantConflictError(
                f"All merchants must be ONBOARDING; found {current_status}"
            )

    # Sort deterministically by merchant ID
    sorted_merchants = sorted(
        merchant_list,
        key=lambda m: str(m.get("id", "")),
    )

    # Create individual activation plans
    plans = []
    for merchant in sorted_merchants:
        plan = propose_merchant_activation(
            merchant,
            expected_version=merchant.get("version", 0),
            reason=normalized_reason,
            triggered_by=normalized_triggered_by,
        )
        plans.append(plan)

    # Build deterministic manifest
    manifest_entries = []
    for merchant in sorted_merchants:
        manifest_entries.append({
            "id": str(merchant.get("id", "")),
            "code": str(merchant.get("code", "")),
            "current_status": str(merchant.get("account_status", "")),
            "version": int(merchant.get("version", 0)),
        })

    manifest = MerchantBatchActivationManifest(
        merchants=tuple(manifest_entries),
        payload_hash="",  # Will be computed in CLI layer
        confirmation_hash="",  # Will be computed in CLI layer
    )

    return MerchantBatchActivationPlan(
        merchants=tuple(plans),
        manifest=manifest,
        from_status="ONBOARDING",
        target_status="ACTIVE",
        reason=normalized_reason,
        triggered_by=normalized_triggered_by,
        event_type="MERCHANT_BATCH_ACTIVATED",
        change_summary=(
            f"Batch activation: {len(plans)} merchants from ONBOARDING to ACTIVE"
        ),
    )


def propose_merchant_activation(
    merchant: Mapping[str, Any],
    *,
    expected_version: int,
    reason: str,
    triggered_by: str | None = None,
) -> MerchantActivationPlan:
    """Validate and plan one merchant activation."""

    normalized_expected_version = _positive_integer(
        expected_version,
        "expected_version",
    )
    merchant_id = _uuid_identifier(
        merchant.get("id"),
        "merchant.id",
    )
    current_version = _positive_integer(
        merchant.get("version"),
        "merchant.version",
    )
    current_status = _required_text(
        merchant.get("account_status"),
        "account_status",
        maximum=50,
    )

    if normalized_expected_version != current_version:
        raise MerchantVersionConflictError(
            "Merchant version changed before activation "
            "could proceed"
        )

    if current_status != "ONBOARDING":
        raise MerchantConflictError(
            f"Merchant cannot be activated from {current_status} status; "
            "only ONBOARDING merchants can be activated"
        )

    normalized_reason = _required_text(
        reason,
        "reason",
        maximum=500,
    )
    normalized_triggered_by = (
        _uuid_identifier(triggered_by, "triggered_by")
        if triggered_by is not None
        else None
    )
    new_version = current_version + 1

    return MerchantActivationPlan(
        merchant_id=merchant_id,
        current_status=current_status,
        target_status="ACTIVE",
        expected_version=current_version,
        new_merchant_version=new_version,
        reason=normalized_reason,
        triggered_by=normalized_triggered_by,
        event_type="MERCHANT_ACTIVATED",
        change_summary=(
            f"Merchant activated from {current_status} to ACTIVE"
        ),
        old_values={
            "account_status": current_status,
            "version": current_version,
        },
        new_values={
            "account_status": "ACTIVE",
            "version": new_version,
        },
    )


def _contact_records(
    contacts: Sequence[Mapping[str, Any]],
) -> tuple[ContactRecordPlan, ...]:
    if isinstance(contacts, (str, bytes, bytearray)):
        raise MerchantEngineError(
            "contacts must be a sequence of objects"
        )

    if not isinstance(contacts, Sequence):
        raise MerchantEngineError(
            "contacts must be a sequence of objects"
        )

    if not contacts:
        raise MerchantEngineError(
            "contact import requires at least one row"
        )

    if len(contacts) > MAX_CONTACT_IMPORT_ROWS:
        raise MerchantEngineError(
            "contact import cannot exceed "
            f"{MAX_CONTACT_IMPORT_ROWS} rows"
        )

    records = tuple(
        _contact_record(contact, index)
        for index, contact in enumerate(contacts, start=1)
    )
    identifiers = [record.contact_id for record in records]

    if len(set(identifiers)) != len(identifiers):
        raise MerchantConflictError(
            "contact import contains duplicate contact IDs"
        )

    return records


def _contact_record(
    contact: Mapping[str, Any],
    row_number: int,
) -> ContactRecordPlan:
    if not isinstance(contact, Mapping):
        raise MerchantEngineError(
            f"contact row {row_number} must be an object"
        )

    allowed_fields = {
        "id",
        "contact_id",
        "contact_type",
        "name",
        "contact_name",
        "email",
        "contact_email",
        "phone",
        "contact_phone",
        "privacy_classification",
        "is_primary",
    }
    unknown_fields = set(contact) - allowed_fields

    if unknown_fields:
        raise MerchantEngineError(
            f"contact row {row_number} has unknown fields: "
            f"{', '.join(sorted(str(field) for field in unknown_fields))}"
        )

    contact_id = contact.get("contact_id", contact.get("id"))
    normalized_id = _uuid_identifier(
        contact_id,
        f"contact row {row_number} id",
    )
    contact_type = _optional_choice(
        contact.get("contact_type"),
        f"contact row {row_number} contact_type",
        CONTACT_TYPES,
    )
    contact_name = _contact_value(
        _aliased_value(contact, "name", "contact_name", row_number),
        f"contact row {row_number} name",
        CONTACT_NAME_LIMIT,
    )
    contact_email = _contact_value(
        _aliased_value(contact, "email", "contact_email", row_number),
        f"contact row {row_number} email",
        CONTACT_EMAIL_LIMIT,
    )
    contact_phone = _contact_value(
        _aliased_value(contact, "phone", "contact_phone", row_number),
        f"contact row {row_number} phone",
        CONTACT_PHONE_LIMIT,
    )

    if all(
        value is None
        for value in (
            contact_name,
            contact_email,
            contact_phone,
        )
    ):
        raise MerchantEngineError(
            f"contact row {row_number} requires name, email, or phone"
        )

    privacy = _optional_choice(
        contact.get("privacy_classification", "PII"),
        f"contact row {row_number} privacy_classification",
        PRIVACY_CLASSIFICATIONS,
    )
    is_primary = contact.get("is_primary", False)

    if not isinstance(is_primary, bool):
        raise MerchantEngineError(
            f"contact row {row_number} is_primary must be boolean"
        )

    return ContactRecordPlan(
        contact_id=normalized_id,
        contact_type=contact_type,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        privacy_classification=privacy or "PII",
        is_primary=is_primary,
        version=1,
    )


def _aliased_value(
    contact: Mapping[str, Any],
    short_name: str,
    explicit_name: str,
    row_number: int,
) -> Any:
    if short_name in contact and explicit_name in contact:
        if contact[short_name] != contact[explicit_name]:
            raise MerchantConflictError(
                f"contact row {row_number} has conflicting "
                f"{short_name} fields"
            )

    return contact.get(
        explicit_name,
        contact.get(short_name),
    )


def _merchant_code(value: Any) -> str:
    if not isinstance(value, str):
        raise MerchantEngineError(
            "code must be a string"
        )

    normalized = value.strip().upper()

    if not MERCHANT_CODE_PATTERN.fullmatch(normalized):
        raise MerchantEngineError(
            "code must contain 1-50 uppercase letters, "
            "numbers, underscores, or hyphens"
        )

    return normalized


def _optional_region_code(value: Any) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise MerchantEngineError(
            "region_code must be a string or null"
        )

    normalized = value.strip().upper()

    if not REGION_CODE_PATTERN.fullmatch(normalized):
        raise MerchantEngineError(
            "region_code must contain 1-10 uppercase letters, "
            "numbers, underscores, or hyphens"
        )

    return normalized


def _required_text(
    value: Any,
    field_name: str,
    *,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise MerchantEngineError(
            f"{field_name} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise MerchantEngineError(
            f"{field_name} cannot be blank"
        )

    if len(normalized) > maximum:
        raise MerchantEngineError(
            f"{field_name} cannot exceed {maximum} characters"
        )

    return normalized


def _contact_value(
    value: Any,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise MerchantEngineError(
            f"{field_name} must be a string or null"
        )

    normalized = value.strip()

    if not normalized:
        return None

    if len(normalized) > maximum:
        raise MerchantEngineError(
            f"{field_name} cannot exceed {maximum} characters"
        )

    return normalized


def _optional_choice(
    value: Any,
    field_name: str,
    choices: frozenset[str],
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise MerchantEngineError(
            f"{field_name} must be one of: "
            f"{', '.join(sorted(choices))}"
        )

    normalized = value.strip().upper()

    if normalized not in choices:
        raise MerchantEngineError(
            f"{field_name} must be one of: "
            f"{', '.join(sorted(choices))}"
        )

    return normalized


def _positive_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MerchantEngineError(
            f"{field_name} must be a positive integer"
        )

    if value <= 0:
        raise MerchantEngineError(
            f"{field_name} must be a positive integer"
        )

    return value


def _uuid_identifier(value: Any, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise MerchantEngineError(
            f"{field_name} must be a valid UUID"
        ) from error
