"""Pure contracts for the production Merchant alert worker.

This module is intentionally dependency-free. It validates worker limits,
constructs an allowlisted delivery payload, calculates bounded retry delays,
and converts failures to stable reason codes before database or network I/O.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping


ALERT_TYPES = frozenset(
    {
        "OVERDUE",
        "DUE_TODAY",
        "DUE_SOON",
        "BLOCKED",
        "MISSING_GATE",
    }
)
DELIVERY_CHANNELS = frozenset({"INTERNAL", "EMAIL", "SLACK"})
DEADLINE_ALERT_TYPES = frozenset({"OVERDUE", "DUE_TODAY", "DUE_SOON"})
CONDITION_ALERT_TYPES = frozenset({"BLOCKED", "MISSING_GATE"})

DEDUPLICATION_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT_PATTERN = re.compile(r"^[A-Za-z0-9:_.|\-]+$")
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INTEGER_PATTERN = re.compile(r"^[0-9]+$")

DEFAULT_PROJECT_LIMIT = 100
MAX_PROJECT_LIMIT = 500
DEFAULT_CLAIM_LIMIT = 25
MAX_CLAIM_LIMIT = 100
DEFAULT_MAX_ATTEMPTS = 5
MAX_MAX_ATTEMPTS = 10
DEFAULT_LEASE_SECONDS = 120
MIN_LEASE_SECONDS = 30
MAX_LEASE_SECONDS = 900
DEFAULT_RETRY_BASE_SECONDS = 300
MIN_RETRY_SECONDS = 1
MAX_RETRY_BASE_SECONDS = 3_600
DEFAULT_RETRY_MAX_SECONDS = 21_600
MAX_RETRY_MAX_SECONDS = 86_400
DEFAULT_NETWORK_TIMEOUT_SECONDS = 10
MIN_NETWORK_TIMEOUT_SECONDS = 1
MAX_NETWORK_TIMEOUT_SECONDS = 60
MIN_LEASE_TIMEOUT_MARGIN_SECONDS = 5
MAX_CONDITION_FINGERPRINT_LENGTH = 255


class AlertContractError(ValueError):
    """Fail-closed validation error that never contains the rejected value."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(reason_code="
            f"{self.reason_code!r})"
        )


class DeliveryFailureCode(str, Enum):
    """Allowlisted failure reasons safe for logs and PostgreSQL."""

    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    CLAIM_LOST = "CLAIM_LOST"
    TRANSPORT_TIMEOUT = "TRANSPORT_TIMEOUT"
    TRANSPORT_UNAVAILABLE = "TRANSPORT_UNAVAILABLE"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_RESPONSE_INVALID = "PROVIDER_RESPONSE_INVALID"
    UNEXPECTED_FAILURE = "UNEXPECTED_FAILURE"


class SafeDeliveryError(RuntimeError):
    """Delivery failure carrying only an allowlisted code and retry policy."""

    def __init__(
        self,
        code: DeliveryFailureCode,
        *,
        retryable: bool,
    ) -> None:
        if not isinstance(code, DeliveryFailureCode):
            raise TypeError("code must be a DeliveryFailureCode")
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be a boolean")

        self.code = code
        self.retryable = retryable
        super().__init__(code.value)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(code={self.code.value!r}, "
            f"retryable={self.retryable!r})"
        )


@dataclass(frozen=True)
class WorkerLimits:
    """Reviewed numeric limits for one alert-worker execution."""

    project_limit: int = DEFAULT_PROJECT_LIMIT
    claim_limit: int = DEFAULT_CLAIM_LIMIT
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    retry_base_seconds: int = DEFAULT_RETRY_BASE_SECONDS
    retry_max_seconds: int = DEFAULT_RETRY_MAX_SECONDS
    network_timeout_seconds: int = DEFAULT_NETWORK_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _validate_bounded_int(
            "PROJECT_LIMIT",
            self.project_limit,
            minimum=1,
            maximum=MAX_PROJECT_LIMIT,
        )
        _validate_bounded_int(
            "CLAIM_LIMIT",
            self.claim_limit,
            minimum=1,
            maximum=MAX_CLAIM_LIMIT,
        )
        _validate_bounded_int(
            "MAX_ATTEMPTS",
            self.max_attempts,
            minimum=1,
            maximum=MAX_MAX_ATTEMPTS,
        )
        _validate_bounded_int(
            "LEASE_SECONDS",
            self.lease_seconds,
            minimum=MIN_LEASE_SECONDS,
            maximum=MAX_LEASE_SECONDS,
        )
        _validate_bounded_int(
            "RETRY_BASE_SECONDS",
            self.retry_base_seconds,
            minimum=MIN_RETRY_SECONDS,
            maximum=MAX_RETRY_BASE_SECONDS,
        )
        _validate_bounded_int(
            "RETRY_MAX_SECONDS",
            self.retry_max_seconds,
            minimum=MIN_RETRY_SECONDS,
            maximum=MAX_RETRY_MAX_SECONDS,
        )
        _validate_bounded_int(
            "NETWORK_TIMEOUT_SECONDS",
            self.network_timeout_seconds,
            minimum=MIN_NETWORK_TIMEOUT_SECONDS,
            maximum=MAX_NETWORK_TIMEOUT_SECONDS,
        )

        if self.retry_max_seconds < self.retry_base_seconds:
            raise AlertContractError(
                "CONFIG_RETRY_MAX_BELOW_BASE"
            )

        minimum_lease = (
            self.network_timeout_seconds
            + MIN_LEASE_TIMEOUT_MARGIN_SECONDS
        )

        if self.lease_seconds < minimum_lease:
            raise AlertContractError(
                "CONFIG_LEASE_TOO_SHORT_FOR_NETWORK_TIMEOUT"
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "WorkerLimits":
        source = os.environ if environ is None else environ

        return cls(
            project_limit=_environment_int(
                source,
                "MERCHANT_ALERT_PROJECT_LIMIT",
                DEFAULT_PROJECT_LIMIT,
            ),
            claim_limit=_environment_int(
                source,
                "MERCHANT_ALERT_CLAIM_LIMIT",
                DEFAULT_CLAIM_LIMIT,
            ),
            max_attempts=_environment_int(
                source,
                "MERCHANT_ALERT_MAX_ATTEMPTS",
                DEFAULT_MAX_ATTEMPTS,
            ),
            lease_seconds=_environment_int(
                source,
                "MERCHANT_ALERT_LEASE_SECONDS",
                DEFAULT_LEASE_SECONDS,
            ),
            retry_base_seconds=_environment_int(
                source,
                "MERCHANT_ALERT_RETRY_BASE_SECONDS",
                DEFAULT_RETRY_BASE_SECONDS,
            ),
            retry_max_seconds=_environment_int(
                source,
                "MERCHANT_ALERT_RETRY_MAX_SECONDS",
                DEFAULT_RETRY_MAX_SECONDS,
            ),
            network_timeout_seconds=_environment_int(
                source,
                "MERCHANT_ALERT_NETWORK_TIMEOUT_SECONDS",
                DEFAULT_NETWORK_TIMEOUT_SECONDS,
            ),
        )

    def retry_delay_seconds(self, attempt_number: int) -> int | None:
        """Return the next bounded delay, or ``None`` when exhausted."""
        _validate_bounded_int(
            "ATTEMPT_NUMBER",
            attempt_number,
            minimum=1,
            maximum=self.max_attempts,
        )

        if attempt_number >= self.max_attempts:
            return None

        delay = self.retry_base_seconds * (2 ** (attempt_number - 1))
        return min(delay, self.retry_max_seconds)

    def to_safe_dict(self) -> dict[str, int]:
        return {
            "project_limit": self.project_limit,
            "claim_limit": self.claim_limit,
            "max_attempts": self.max_attempts,
            "lease_seconds": self.lease_seconds,
            "retry_base_seconds": self.retry_base_seconds,
            "retry_max_seconds": self.retry_max_seconds,
            "network_timeout_seconds": self.network_timeout_seconds,
        }


@dataclass(frozen=True)
class DeliveryPayload:
    """Allowlisted channel-neutral representation of a claimed alert."""

    delivery_id: str
    project_id: str
    project_step_id: str | None
    alert_type: str
    business_due_date: date | None
    condition_fingerprint: str | None
    deduplication_key: str
    delivery_channel: str
    attempt_number: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "delivery_id",
            _normalized_uuid(self.delivery_id, "DELIVERY_ID"),
        )
        object.__setattr__(
            self,
            "project_id",
            _normalized_uuid(self.project_id, "PROJECT_ID"),
        )

        if self.project_step_id in (None, ""):
            object.__setattr__(self, "project_step_id", None)
        else:
            object.__setattr__(
                self,
                "project_step_id",
                _normalized_uuid(
                    self.project_step_id,
                    "PROJECT_STEP_ID",
                ),
            )

        alert_type = _normalized_choice(
            self.alert_type,
            ALERT_TYPES,
            "ALERT_TYPE",
        )
        delivery_channel = _normalized_choice(
            self.delivery_channel,
            DELIVERY_CHANNELS,
            "DELIVERY_CHANNEL",
        )
        object.__setattr__(self, "alert_type", alert_type)
        object.__setattr__(
            self,
            "delivery_channel",
            delivery_channel,
        )

        due_date = _normalized_date(self.business_due_date)
        fingerprint = _normalized_fingerprint(
            self.condition_fingerprint
        )
        object.__setattr__(self, "business_due_date", due_date)
        object.__setattr__(
            self,
            "condition_fingerprint",
            fingerprint,
        )

        if due_date is None and fingerprint is None:
            raise AlertContractError(
                "PAYLOAD_CONDITION_EVIDENCE_REQUIRED"
            )
        if alert_type in DEADLINE_ALERT_TYPES and due_date is None:
            raise AlertContractError(
                "PAYLOAD_DEADLINE_DATE_REQUIRED"
            )
        if alert_type in CONDITION_ALERT_TYPES and fingerprint is None:
            raise AlertContractError(
                "PAYLOAD_FINGERPRINT_REQUIRED"
            )

        deduplication_key = str(self.deduplication_key).strip()

        if not DEDUPLICATION_KEY_PATTERN.fullmatch(
            deduplication_key
        ):
            raise AlertContractError(
                "PAYLOAD_DEDUPLICATION_KEY_INVALID"
            )

        object.__setattr__(
            self,
            "deduplication_key",
            deduplication_key,
        )
        _validate_bounded_int(
            "ATTEMPT_NUMBER",
            self.attempt_number,
            minimum=1,
            maximum=MAX_MAX_ATTEMPTS,
        )

    @classmethod
    def from_delivery_record(
        cls,
        record: Mapping[str, Any],
    ) -> "DeliveryPayload":
        """Project a repository record onto the explicit safe field list."""
        try:
            return cls(
                delivery_id=record["id"],
                project_id=record["project_id"],
                project_step_id=record.get("project_step_id"),
                alert_type=record["alert_type"],
                business_due_date=record.get("business_due_date"),
                condition_fingerprint=record.get(
                    "condition_fingerprint"
                ),
                deduplication_key=record["deduplication_key"],
                delivery_channel=record["delivery_channel"],
                attempt_number=record["delivery_attempt_count"],
            )
        except KeyError as exc:
            raise AlertContractError(
                "PAYLOAD_REQUIRED_FIELD_MISSING"
            ) from exc

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "project_id": self.project_id,
            "project_step_id": self.project_step_id,
            "alert_type": self.alert_type,
            "business_due_date": (
                self.business_due_date.isoformat()
                if self.business_due_date
                else None
            ),
            "condition_fingerprint": self.condition_fingerprint,
            "deduplication_key": self.deduplication_key,
            "delivery_channel": self.delivery_channel,
            "attempt_number": self.attempt_number,
        }


def safe_failure_summary(error: BaseException) -> str:
    """Return a stable summary without copying exception text."""
    if isinstance(error, SafeDeliveryError):
        return error.code.value
    if isinstance(error, AlertContractError):
        return DeliveryFailureCode.CONFIGURATION_INVALID.value
    return DeliveryFailureCode.UNEXPECTED_FAILURE.value


def _environment_int(
    environ: Mapping[str, str],
    variable: str,
    default: int,
) -> int:
    if variable not in environ:
        return default

    raw_value = environ[variable]

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise AlertContractError(f"CONFIG_{variable}_INVALID")

    normalized = raw_value.strip()

    if not INTEGER_PATTERN.fullmatch(normalized):
        raise AlertContractError(
            f"CONFIG_{variable}_INVALID"
        )

    return int(normalized, 10)


def _validate_bounded_int(
    field: str,
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise AlertContractError(f"CONFIG_{field}_OUT_OF_RANGE")


def _normalized_uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise AlertContractError(
            f"PAYLOAD_{field}_INVALID"
        ) from exc


def _normalized_choice(
    value: Any,
    allowed: frozenset[str],
    field: str,
) -> str:
    normalized = str(value).strip().upper()

    if normalized not in allowed:
        raise AlertContractError(f"PAYLOAD_{field}_INVALID")

    return normalized


def _normalized_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        raise AlertContractError("PAYLOAD_BUSINESS_DUE_DATE_INVALID")
    if isinstance(value, date):
        return value

    text = str(value).strip()

    if not ISO_DATE_PATTERN.fullmatch(text):
        raise AlertContractError("PAYLOAD_BUSINESS_DUE_DATE_INVALID")

    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise AlertContractError(
            "PAYLOAD_BUSINESS_DUE_DATE_INVALID"
        ) from exc


def _normalized_fingerprint(value: Any) -> str | None:
    if value in (None, ""):
        return None

    text = str(value).strip()

    if (
        not text
        or len(text) > MAX_CONDITION_FINGERPRINT_LENGTH
        or not FINGERPRINT_PATTERN.fullmatch(text)
    ):
        raise AlertContractError(
            "PAYLOAD_CONDITION_FINGERPRINT_INVALID"
        )

    return text
