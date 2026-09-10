"""Pure safety and serialization contracts for the Merchant CLI."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any


CONTRACT_VERSION = 1
CONFIRMATION_VERSION = 1
CONFIRMATION_OPERATION = "merchant_apply"
REDACTED_VALUE = "[REDACTED]"
PROPOSAL_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CONFIRMATION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_CONFIRMATION_TOKEN_LENGTH = 4096
DEFAULT_RUNTIME_AUTHORIZATION_TTL_SECONDS = 60.0
MAX_RUNTIME_AUTHORIZATION_TTL_SECONDS = 300.0
_RUNTIME_AUTHORIZATION_ISSUER_SEAL = object()

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
        "merchant activate",
        "merchant activate-all",
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


class ConfirmationEnvelopeError(MerchantCliContractError):
    """Raised when Merchant confirmation metadata is unsafe or malformed."""


class RuntimeAuthorizationConsumedError(RuntimeWriteDeniedError):
    """Raised when a one-use runtime capability is replayed."""


class RuntimeAuthorizationExpiredError(RuntimeWriteDeniedError):
    """Raised when a runtime capability outlives its bounded TTL."""


class RuntimeApplyAuthorization:
    """Opaque, expiring, one-use authority for one exact runtime apply.

    Instances cannot be constructed, copied, pickled, serialized, or converted
    to a CLI token. Trusted orchestration receives an instance in memory from
    ``issue_runtime_apply_authorization`` and passes that same object through
    the internal Python call chain.
    """

    __slots__ = (
        "_clock",
        "_confirmation",
        "_consumed",
        "_expires_at",
        "_lock",
    )

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeWriteDeniedError(
            "Runtime authorization can be issued only by trusted orchestration"
        )

    @classmethod
    def _issued(
        cls,
        confirmation: Mapping[str, Any],
        *,
        expires_at: float,
        clock: Callable[[], float],
        issuer_seal: object,
    ) -> "RuntimeApplyAuthorization":
        if issuer_seal is not _RUNTIME_AUTHORIZATION_ISSUER_SEAL:
            raise RuntimeWriteDeniedError(
                "Runtime authorization issuer is not trusted"
            )

        authority = object.__new__(cls)
        authority._clock = clock
        authority._confirmation = MappingProxyType(
            dict(confirmation)
        )
        authority._consumed = False
        authority._expires_at = expires_at
        authority._lock = threading.Lock()
        return authority

    @property
    def consumed(self) -> bool:
        with self._lock:
            return self._consumed

    @property
    def confirmation_hash(self) -> str:
        return str(self._confirmation["confirmation_hash"])

    def __repr__(self) -> str:
        status = "consumed" if self.consumed else "unspent"
        return (
            "<RuntimeApplyAuthorization "
            f"command={self._confirmation['command']!r} "
            "database='runtime' "
            f"status={status!r}>"
        )

    def __copy__(self) -> "RuntimeApplyAuthorization":
        raise TypeError("Runtime authorization cannot be copied")

    def __deepcopy__(
        self,
        _memo: dict[int, Any],
    ) -> "RuntimeApplyAuthorization":
        raise TypeError("Runtime authorization cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> Any:
        raise TypeError("Runtime authorization cannot be serialized")

    def _consume(
        self,
        *,
        command: Any,
        database: Any,
        payload: Mapping[str, Any],
        proposal_hash: Any,
    ) -> None:
        with self._lock:
            if self._consumed:
                raise RuntimeAuthorizationConsumedError(
                    "Runtime authorization has already been consumed"
                )

            # Every attempt consumes the capability, including an expired or
            # mismatched attempt. That prevents corrected retries from turning
            # one confirmed action into multiple mutation attempts.
            self._consumed = True

            try:
                current_time = float(self._clock())
            except (TypeError, ValueError, OverflowError) as error:
                raise RuntimeWriteDeniedError(
                    "Runtime authorization clock became invalid"
                ) from error

            if (
                not math.isfinite(current_time)
                or current_time >= self._expires_at
            ):
                raise RuntimeAuthorizationExpiredError(
                    "Runtime authorization has expired"
                )

            try:
                candidate = build_confirmation_envelope(
                    command,
                    database,
                    payload,
                    supplied_proposal_hash=proposal_hash,
                )
            except MerchantCliContractError as error:
                raise RuntimeWriteDeniedError(
                    "Runtime apply does not match the confirmed proposal"
                ) from error

            if candidate.to_dict() != dict(self._confirmation):
                raise RuntimeWriteDeniedError(
                    "Runtime apply does not match the confirmed proposal"
                )


@dataclass(frozen=True, slots=True)
class MerchantConfirmationEnvelope:
    """Redacted user confirmation bound to one exact Merchant proposal."""

    contract_version: int
    confirmation_version: int
    operation: str
    command: str
    database_target: str
    expected_version: int | None
    payload_hash: str
    proposal_hash: str
    confirmation_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "confirmation_version": self.confirmation_version,
            "operation": self.operation,
            "command": self.command,
            "database_target": self.database_target,
            "expected_version": self.expected_version,
            "payload_hash": self.payload_hash,
            "proposal_hash": self.proposal_hash,
            "confirmation_hash": self.confirmation_hash,
        }

    def to_token(self) -> str:
        """Return a deterministic URL-safe token containing no raw payload."""

        canonical = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return base64.urlsafe_b64encode(canonical).decode(
            "ascii"
        ).rstrip("=")


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
        confirmation = build_confirmation_envelope(
            self.command,
            self.database,
            self.payload,
            supplied_proposal_hash=self.proposal_hash,
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
            "confirmation": confirmation.to_dict(),
            "confirmation_token": confirmation.to_token(),
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
    runtime_authorization: Any = None,
    payload: Mapping[str, Any] | None = None,
    proposal_hash: Any = None,
) -> None:
    """Fail closed unless a write target is explicitly safe."""

    normalized_command = normalize_command(command)
    normalized_database = normalize_database_target(database)

    if normalized_command not in WRITE_COMMANDS:
        raise CommandNotAllowedError(
            "Apply mode only supports write commands"
        )

    if normalized_database == "runtime":
        if type(runtime_authorization) is not RuntimeApplyAuthorization:
            raise RuntimeWriteDeniedError(
                "Runtime writes require an exact in-process authorization"
            )

        if payload is None:
            raise RuntimeWriteDeniedError(
                "Runtime authorization requires the exact apply payload"
            )

        runtime_authorization._consume(
            command=normalized_command,
            database=normalized_database,
            payload=payload,
            proposal_hash=proposal_hash,
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


def proposal_payload_hash(
    payload: Mapping[str, Any],
) -> str:
    """Return a deterministic fingerprint without exposing payload values."""

    normalized_payload = _normalized_payload(payload)
    canonical = json.dumps(
        normalized_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_confirmation_envelope(
    command: Any,
    database: Any,
    payload: Mapping[str, Any],
    *,
    supplied_proposal_hash: Any | None = None,
) -> MerchantConfirmationEnvelope:
    """Build safe confirmation metadata for one exact proposal."""

    normalized_command = normalize_command(command)

    if normalized_command not in WRITE_COMMANDS:
        raise CommandNotAllowedError(
            "Only write commands can create confirmation envelopes"
        )

    normalized_database = normalize_database_target(database)
    normalized_payload = _normalized_payload(payload)
    expected_version = _normalize_expected_version(
        normalized_payload.get("expected_version")
    )
    calculated_proposal_hash = proposal_hash(
        normalized_command,
        normalized_database,
        normalized_payload,
    )

    if supplied_proposal_hash is not None:
        normalized_supplied_hash = _normalize_sha256(
            supplied_proposal_hash,
            "proposal_hash",
        )

        if not hmac.compare_digest(
            normalized_supplied_hash,
            calculated_proposal_hash,
        ):
            raise ConfirmationEnvelopeError(
                "Confirmation does not match the exact proposal"
            )

    payload_digest = proposal_payload_hash(
        normalized_payload
    )
    confirmation_digest = _confirmation_hash(
        contract_version=CONTRACT_VERSION,
        confirmation_version=CONFIRMATION_VERSION,
        operation=CONFIRMATION_OPERATION,
        command=normalized_command,
        database_target=normalized_database,
        expected_version=expected_version,
        payload_hash=payload_digest,
        proposal_hash=calculated_proposal_hash,
    )

    return MerchantConfirmationEnvelope(
        contract_version=CONTRACT_VERSION,
        confirmation_version=CONFIRMATION_VERSION,
        operation=CONFIRMATION_OPERATION,
        command=normalized_command,
        database_target=normalized_database,
        expected_version=expected_version,
        payload_hash=payload_digest,
        proposal_hash=calculated_proposal_hash,
        confirmation_hash=confirmation_digest,
    )


def parse_confirmation_token(
    value: Any,
) -> MerchantConfirmationEnvelope:
    """Decode and validate one canonical Merchant confirmation token."""

    if not isinstance(value, str):
        raise ConfirmationEnvelopeError(
            "Merchant confirmation token must be text"
        )

    token = value.strip()

    if (
        not token
        or len(token) > MAX_CONFIRMATION_TOKEN_LENGTH
        or not CONFIRMATION_TOKEN_PATTERN.fullmatch(token)
    ):
        raise ConfirmationEnvelopeError(
            "Merchant confirmation token is malformed"
        )

    padding = "=" * (-len(token) % 4)

    try:
        decoded = base64.b64decode(
            token + padding,
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
        payload = json.loads(decoded)
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise ConfirmationEnvelopeError(
            "Merchant confirmation token is malformed"
        ) from error

    required_fields = {
        "contract_version",
        "confirmation_version",
        "operation",
        "command",
        "database_target",
        "expected_version",
        "payload_hash",
        "proposal_hash",
        "confirmation_hash",
    }

    if not isinstance(payload, dict) or set(payload) != required_fields:
        raise ConfirmationEnvelopeError(
            "Merchant confirmation fields are incomplete or unexpected"
        )

    if (
        isinstance(payload["contract_version"], bool)
        or payload["contract_version"] != CONTRACT_VERSION
    ):
        raise ConfirmationEnvelopeError(
            "Unsupported Merchant proposal contract version"
        )

    if (
        isinstance(payload["confirmation_version"], bool)
        or payload["confirmation_version"] != CONFIRMATION_VERSION
    ):
        raise ConfirmationEnvelopeError(
            "Unsupported Merchant confirmation version"
        )

    if payload["operation"] != CONFIRMATION_OPERATION:
        raise ConfirmationEnvelopeError(
            "Merchant confirmation operation must be merchant_apply"
        )

    normalized_command = normalize_command(payload["command"])

    if normalized_command not in WRITE_COMMANDS:
        raise ConfirmationEnvelopeError(
            "Merchant confirmation requires a write command"
        )

    normalized_database = normalize_database_target(
        payload["database_target"]
    )
    expected_version = _normalize_expected_version(
        payload["expected_version"]
    )
    payload_digest = _normalize_sha256(
        payload["payload_hash"],
        "payload_hash",
    )
    proposal_digest = _normalize_sha256(
        payload["proposal_hash"],
        "proposal_hash",
    )
    supplied_confirmation_digest = _normalize_sha256(
        payload["confirmation_hash"],
        "confirmation_hash",
    )
    expected_confirmation_digest = _confirmation_hash(
        contract_version=CONTRACT_VERSION,
        confirmation_version=CONFIRMATION_VERSION,
        operation=CONFIRMATION_OPERATION,
        command=normalized_command,
        database_target=normalized_database,
        expected_version=expected_version,
        payload_hash=payload_digest,
        proposal_hash=proposal_digest,
    )

    if not hmac.compare_digest(
        supplied_confirmation_digest,
        expected_confirmation_digest,
    ):
        raise ConfirmationEnvelopeError(
            "Merchant confirmation binding does not match"
        )

    envelope = MerchantConfirmationEnvelope(
        contract_version=CONTRACT_VERSION,
        confirmation_version=CONFIRMATION_VERSION,
        operation=CONFIRMATION_OPERATION,
        command=normalized_command,
        database_target=normalized_database,
        expected_version=expected_version,
        payload_hash=payload_digest,
        proposal_hash=proposal_digest,
        confirmation_hash=expected_confirmation_digest,
    )

    if not hmac.compare_digest(token, envelope.to_token()):
        raise ConfirmationEnvelopeError(
            "Merchant confirmation token is not canonical"
        )

    return envelope


def issue_runtime_apply_authorization(
    confirmation: Mapping[str, Any],
    dispatch_receipt: Mapping[str, Any],
    *,
    ttl_seconds: float = (
        DEFAULT_RUNTIME_AUTHORIZATION_TTL_SECONDS
    ),
    clock: Callable[[], float] | None = None,
) -> RuntimeApplyAuthorization:
    """Issue one in-memory capability from an accepted policy dispatch.

    This function is for the trusted orchestration handoff only. The ordinary
    CLI and Merchant Manager command-line adapter never call it and expose no
    argument or environment-variable path to its result.
    """

    envelope = _confirmation_from_mapping(confirmation)

    if envelope.database_target != "runtime":
        raise RuntimeWriteDeniedError(
            "Runtime authorization requires a runtime confirmation"
        )

    _validate_dispatch_receipt(
        dispatch_receipt,
        envelope.confirmation_hash,
    )

    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, (int, float))
        or not math.isfinite(float(ttl_seconds))
        or float(ttl_seconds) <= 0
        or float(ttl_seconds)
        > MAX_RUNTIME_AUTHORIZATION_TTL_SECONDS
    ):
        raise RuntimeWriteDeniedError(
            "Runtime authorization TTL is outside the trusted bound"
        )

    selected_clock = clock or time.monotonic

    if not callable(selected_clock):
        raise RuntimeWriteDeniedError(
            "Runtime authorization clock is invalid"
        )

    issued_at = float(selected_clock())

    if not math.isfinite(issued_at):
        raise RuntimeWriteDeniedError(
            "Runtime authorization clock is invalid"
        )

    return RuntimeApplyAuthorization._issued(
        envelope.to_dict(),
        expires_at=issued_at + float(ttl_seconds),
        clock=selected_clock,
        issuer_seal=_RUNTIME_AUTHORIZATION_ISSUER_SEAL,
    )


def _confirmation_from_mapping(
    confirmation: Mapping[str, Any],
) -> MerchantConfirmationEnvelope:
    if not isinstance(confirmation, Mapping):
        raise RuntimeWriteDeniedError(
            "Runtime authorization confirmation is missing or malformed"
        )

    try:
        canonical = json.dumps(
            dict(confirmation),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        token = base64.urlsafe_b64encode(canonical).decode(
            "ascii"
        ).rstrip("=")
        return parse_confirmation_token(token)
    except (
        MerchantCliContractError,
        TypeError,
        ValueError,
    ) as error:
        raise RuntimeWriteDeniedError(
            "Runtime authorization confirmation is missing or malformed"
        ) from error


def _validate_dispatch_receipt(
    dispatch_receipt: Mapping[str, Any],
    confirmation_hash: str,
) -> None:
    required_fields = {
        "operation",
        "subagent_type",
        "teammate_name",
        "confirmation_hash",
    }

    if (
        not isinstance(dispatch_receipt, Mapping)
        or set(dispatch_receipt) != required_fields
        or dispatch_receipt.get("operation")
        != CONFIRMATION_OPERATION
        or dispatch_receipt.get("subagent_type")
        != "merchant-manager"
        or not isinstance(
            dispatch_receipt.get("teammate_name"),
            str,
        )
        or not dispatch_receipt.get("teammate_name", "").strip()
        or not isinstance(
            dispatch_receipt.get("confirmation_hash"),
            str,
        )
        or not hmac.compare_digest(
            dispatch_receipt["confirmation_hash"],
            confirmation_hash,
        )
    ):
        raise RuntimeWriteDeniedError(
            "Runtime authorization requires the exact accepted dispatch receipt"
        )


def _normalize_expected_version(value: Any) -> int | None:
    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfirmationEnvelopeError(
            "expected_version must be a positive integer or null"
        )

    return value


def _normalize_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConfirmationEnvelopeError(
            f"{field_name} must be a SHA-256 hex string"
        )

    normalized = value.strip().lower()

    if not PROPOSAL_HASH_PATTERN.fullmatch(normalized):
        raise ConfirmationEnvelopeError(
            f"{field_name} must be a SHA-256 hex string"
        )

    return normalized


def _confirmation_hash(
    *,
    contract_version: int,
    confirmation_version: int,
    operation: str,
    command: str,
    database_target: str,
    expected_version: int | None,
    payload_hash: str,
    proposal_hash: str,
) -> str:
    canonical = json.dumps(
        {
            "contract_version": contract_version,
            "confirmation_version": confirmation_version,
            "operation": operation,
            "command": command,
            "database_target": database_target,
            "expected_version": expected_version,
            "payload_hash": payload_hash,
            "proposal_hash": proposal_hash,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


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
