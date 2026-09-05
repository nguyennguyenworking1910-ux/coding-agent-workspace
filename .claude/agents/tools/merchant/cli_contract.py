"""Pure safety and serialization contracts for the Merchant CLI."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any


CONTRACT_VERSION = 1
REDACTED_VALUE = "[REDACTED]"
PROPOSAL_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

READ_COMMANDS = frozenset(
    {
        "merchant list",
        "project alerts",
        "project blockers",
        "project history",
        "project list",
        "project show",
    }
)

WRITE_COMMANDS = frozenset(
    {
        "contact import",
        "document approve",
        "document revision-create",
        "integration identifier-set",
        "merchant create",
        "procurement update",
        "project create",
        "project update",
        "step update",
    }
)

ALL_COMMANDS = READ_COMMANDS | WRITE_COMMANDS

SENSITIVE_FIELD_NAMES = frozenset(
    {
        "contact_name",
        "contact_email",
        "contact_phone",
        "content_hash",
        "email",
        "email_address",
        "identifier_value",
        "notes",
        "phone",
        "phone_number",
    }
)

COMMAND_SENSITIVE_FIELDS = {
    "contact import": frozenset({"name"}),
    "integration identifier-set": frozenset({"value"}),
}


class MerchantCliContractError(ValueError):
    """Base error for Merchant CLI contract validation."""


class DatabaseTargetError(MerchantCliContractError):
    """Raised when the selected database target is invalid."""


class CommandNotAllowedError(MerchantCliContractError):
    """Raised when a command is outside the fixed CLI allowlist."""


class ProposalHashError(MerchantCliContractError):
    """Raised when an apply request is not bound to its proposal."""


class RuntimeWriteDeniedError(MerchantCliContractError):
    """Raised when a runtime mutation lacks trusted authorization."""


@dataclass(frozen=True, slots=True)
class CommandProposal:
    """One deterministic, confirmation-ready write proposal."""

    command: str
    database: str
    payload: Mapping[str, Any]
    proposal_hash: str

    def to_dict(self) -> dict[str, Any]:
        extra_sensitive_fields = COMMAND_SENSITIVE_FIELDS.get(
            self.command,
            frozenset(),
        )

        return {
            "contract_version": CONTRACT_VERSION,
            "mode": "PROPOSE",
            "command": self.command,
            "database": self.database,
            "payload": redact_payload(
                self.payload,
                extra_sensitive_fields=(
                    extra_sensitive_fields
                ),
            ),
            "proposal_hash": self.proposal_hash,
            "requires_confirmation": True,
        }


def normalize_database_target(value: Any) -> str:
    """Return the only supported database target names."""

    if not isinstance(value, str):
        raise DatabaseTargetError(
            "database must be 'test' or 'runtime'"
        )

    normalized = value.strip().lower()

    if normalized not in {"test", "runtime"}:
        raise DatabaseTargetError(
            "database must be 'test' or 'runtime'"
        )

    return normalized


def repository_role_for_target(database: Any) -> str:
    """Map a CLI target to the least-privileged repository role."""

    normalized = normalize_database_target(database)
    return "test" if normalized == "test" else "app"


def normalize_command(value: Any) -> str:
    """Normalize and allowlist one two-part Merchant command."""

    if not isinstance(value, str):
        raise CommandNotAllowedError(
            "command must be a string"
        )

    normalized = " ".join(value.strip().lower().split())

    if normalized not in ALL_COMMANDS:
        raise CommandNotAllowedError(
            f"Merchant command is not allowlisted: {normalized!r}"
        )

    return normalized


def require_apply_authorization(
    command: Any,
    database: Any,
    *,
    runtime_authorized: bool = False,
) -> None:
    """Fail closed unless a write target is explicitly safe."""

    normalized_command = normalize_command(command)
    normalized_database = normalize_database_target(database)

    if normalized_command not in WRITE_COMMANDS:
        raise CommandNotAllowedError(
            "Apply mode only supports write commands"
        )

    if normalized_database == "runtime":
        if runtime_authorized is not True:
            raise RuntimeWriteDeniedError(
                "Runtime writes require trusted authorization"
            )


def to_json_value(value: Any) -> Any:
    """Convert supported values to deterministic JSON data."""

    if value is None or isinstance(
        value,
        (str, int, bool),
    ):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise MerchantCliContractError(
                "JSON numbers must be finite"
            )

        return value

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, datetime):
        normalized = value

        if normalized.tzinfo is None:
            normalized = normalized.replace(
                tzinfo=timezone.utc
            )
        else:
            normalized = normalized.astimezone(
                timezone.utc
            )

        return normalized.isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, Enum):
        return to_json_value(value.value)

    if is_dataclass(value) and not isinstance(
        value,
        type,
    ):
        return {
            field.name: to_json_value(
                getattr(value, field.name)
            )
            for field in fields(value)
        }

    if isinstance(value, Mapping):
        normalized = {}

        for key, item in value.items():
            if not isinstance(key, str):
                raise MerchantCliContractError(
                    "JSON object keys must be strings"
                )

            normalized[key] = to_json_value(item)

        return normalized

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [to_json_value(item) for item in value]

    raise MerchantCliContractError(
        "Unsupported JSON value type: "
        f"{type(value).__name__}"
    )


def redact_payload(
    value: Any,
    *,
    extra_sensitive_fields: Sequence[str] = (),
) -> Any:
    """Return a recursively redacted JSON-compatible copy."""

    normalized = to_json_value(value)
    sensitive_fields = SENSITIVE_FIELD_NAMES | {
        field.strip().lower()
        for field in extra_sensitive_fields
    }

    return _redact_json_value(
        normalized,
        sensitive_fields,
    )


def render_json(value: Any) -> str:
    """Render deterministic, UTF-8-friendly CLI JSON."""

    return json.dumps(
        to_json_value(value),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def proposal_hash(
    command: Any,
    database: Any,
    payload: Mapping[str, Any],
) -> str:
    """Bind a write command, target, and exact payload."""

    normalized_command = normalize_command(command)

    if normalized_command not in WRITE_COMMANDS:
        raise CommandNotAllowedError(
            "Only write commands can create proposals"
        )

    normalized_database = normalize_database_target(database)
    normalized_payload = _normalized_payload(payload)
    canonical = json.dumps(
        {
            "contract_version": CONTRACT_VERSION,
            "command": normalized_command,
            "database": normalized_database,
            "payload": normalized_payload,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    return hashlib.sha256(canonical).hexdigest()


def build_proposal(
    command: Any,
    database: Any,
    payload: Mapping[str, Any],
) -> CommandProposal:
    """Build one deterministic proposal response."""

    normalized_command = normalize_command(command)
    normalized_database = normalize_database_target(database)
    normalized_payload = _normalized_payload(payload)

    return CommandProposal(
        command=normalized_command,
        database=normalized_database,
        payload=_freeze_json_value(normalized_payload),
        proposal_hash=proposal_hash(
            normalized_command,
            normalized_database,
            normalized_payload,
        ),
    )


def verify_proposal_hash(
    supplied_hash: Any,
    command: Any,
    database: Any,
    payload: Mapping[str, Any],
) -> None:
    """Require an exact constant-time proposal-hash match."""

    if not isinstance(supplied_hash, str):
        raise ProposalHashError(
            "proposal_hash must be a SHA-256 hex string"
        )

    normalized_hash = supplied_hash.strip().lower()

    if not PROPOSAL_HASH_PATTERN.fullmatch(
        normalized_hash
    ):
        raise ProposalHashError(
            "proposal_hash must be a SHA-256 hex string"
        )

    expected_hash = proposal_hash(
        command,
        database,
        payload,
    )

    if not hmac.compare_digest(
        normalized_hash,
        expected_hash,
    ):
        raise ProposalHashError(
            "Apply payload does not match the proposal"
        )


def _normalized_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MerchantCliContractError(
            "proposal payload must be an object"
        )

    normalized = to_json_value(payload)

    if not isinstance(normalized, dict):
        raise MerchantCliContractError(
            "proposal payload must be an object"
        )

    return normalized


def _redact_json_value(
    value: Any,
    sensitive_fields: set[str] | frozenset[str],
) -> Any:
    if isinstance(value, dict):
        redacted = {}

        for key, item in value.items():
            normalized_key = key.strip().lower()

            if (
                item is not None
                and _is_sensitive_field(
                    normalized_key,
                    sensitive_fields,
                )
            ):
                redacted[key] = REDACTED_VALUE
            else:
                redacted[key] = _redact_json_value(
                    item,
                    sensitive_fields,
                )

        return redacted

    if isinstance(value, list):
        return [
            _redact_json_value(item, sensitive_fields)
            for item in value
        ]

    return value


def _freeze_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {
                key: _freeze_json_value(item)
                for key, item in value.items()
            }
        )

    if isinstance(value, list):
        return tuple(
            _freeze_json_value(item)
            for item in value
        )

    return value


def _is_sensitive_field(
    field_name: str,
    sensitive_fields: set[str] | frozenset[str],
) -> bool:
    return (
        field_name in sensitive_fields
        or field_name.endswith("_email")
        or field_name.endswith("_phone")
    )
