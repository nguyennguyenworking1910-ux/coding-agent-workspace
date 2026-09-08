"""Private, local-only Merchant runtime catalog validation."""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .merchant_engine import (
    MERCHANT_CODE_PATTERN,
    REGION_CODE_PATTERN,
)


EXPECTED_CATALOG_RECORDS = 22
MAX_CATALOG_BYTES = 1_000_000
CATALOG_ACCOUNT_STATUSES = frozenset(
    {
        "ONBOARDING",
        "ACTIVE",
    }
)
CATALOG_FIELDS = frozenset(
    {
        "code",
        "name",
        "region_code",
        "account_status",
    }
)
REQUIRED_CATALOG_FIELDS = frozenset(
    {
        "code",
        "name",
        "account_status",
    }
)
CATALOG_ID_NAMESPACE = uuid.UUID(
    "17f4ad99-14ad-5e58-a7a5-f9530d8f79c9"
)


class PrivateCatalogError(ValueError):
    """Base error whose public text never contains catalog values."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        record_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.record_number = record_number


class PrivateCatalogReadError(PrivateCatalogError):
    """Raised when a private source cannot be read safely."""


class PrivateCatalogValidationError(PrivateCatalogError):
    """Raised when private source content violates the contract."""


@dataclass(frozen=True, slots=True, repr=False)
class PrivateMerchantRecord:
    """One normalized private record; representations stay redacted."""

    merchant_id: str
    code: str
    name: str
    region_code: str | None
    account_status: str

    def __repr__(self) -> str:
        return "PrivateMerchantRecord(<redacted>)"

    def _canonical_dict(self) -> dict[str, str | None]:
        return {
            "account_status": self.account_status,
            "code": self.code,
            "merchant_id": self.merchant_id,
            "name": self.name,
            "region_code": self.region_code,
        }


@dataclass(frozen=True, slots=True, repr=False)
class PrivateMerchantCatalog:
    """Validated records plus non-secret source and plan bindings."""

    records: tuple[PrivateMerchantRecord, ...]
    source_sha256: str
    catalog_sha256: str

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def status_counts(self) -> dict[str, int]:
        counts = Counter(
            record.account_status for record in self.records
        )
        return {
            status: counts.get(status, 0)
            for status in sorted(CATALOG_ACCOUNT_STATUSES)
        }

    def safe_summary(self) -> dict[str, Any]:
        """Return only counts and hashes suitable for ordinary output."""

        return {
            "success": True,
            "record_count": self.record_count,
            "status_counts": self.status_counts,
            "source_sha256": self.source_sha256,
            "catalog_sha256": self.catalog_sha256,
        }

    def __repr__(self) -> str:
        return (
            "PrivateMerchantCatalog("
            f"record_count={self.record_count}, "
            f"source_sha256={self.source_sha256!r}, "
            f"catalog_sha256={self.catalog_sha256!r})"
        )


def load_private_catalog(
    source_path: str | os.PathLike[str],
) -> PrivateMerchantCatalog:
    """Load one explicit local file without exposing its path in errors."""

    try:
        path = Path(source_path)
    except (TypeError, ValueError):
        raise PrivateCatalogReadError(
            "Private Merchant catalog path is invalid",
            reason_code="INVALID_SOURCE_PATH",
        ) from None

    try:
        if not path.is_file():
            raise PrivateCatalogReadError(
                "Private Merchant catalog source is not a file",
                reason_code="SOURCE_NOT_FILE",
            )

        size = path.stat().st_size
    except PrivateCatalogReadError:
        raise
    except OSError:
        raise PrivateCatalogReadError(
            "Private Merchant catalog source could not be inspected",
            reason_code="SOURCE_INSPECTION_FAILED",
        ) from None

    if size > MAX_CATALOG_BYTES:
        raise PrivateCatalogReadError(
            "Private Merchant catalog exceeds the size limit",
            reason_code="SOURCE_TOO_LARGE",
        )

    try:
        source = path.read_bytes()
    except OSError:
        raise PrivateCatalogReadError(
            "Private Merchant catalog source could not be read",
            reason_code="SOURCE_READ_FAILED",
        ) from None

    return validate_private_catalog_bytes(source)


def validate_private_catalog_bytes(
    source: bytes | bytearray,
) -> PrivateMerchantCatalog:
    """Validate exact UTF-8 JSON bytes without database access."""

    if not isinstance(source, (bytes, bytearray)):
        raise PrivateCatalogValidationError(
            "Private Merchant catalog source must be bytes",
            reason_code="SOURCE_NOT_BYTES",
        )

    encoded = bytes(source)

    if len(encoded) > MAX_CATALOG_BYTES:
        raise PrivateCatalogValidationError(
            "Private Merchant catalog exceeds the size limit",
            reason_code="SOURCE_TOO_LARGE",
        )

    if encoded.startswith(b"\xef\xbb\xbf"):
        raise PrivateCatalogValidationError(
            "Private Merchant catalog must be UTF-8 without BOM",
            reason_code="UTF8_BOM_NOT_ALLOWED",
        )

    try:
        text = encoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise PrivateCatalogValidationError(
            "Private Merchant catalog must be valid UTF-8",
            reason_code="INVALID_UTF8",
        ) from None

    try:
        payload = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_fields,
        )
    except PrivateCatalogValidationError:
        raise
    except (json.JSONDecodeError, RecursionError):
        raise PrivateCatalogValidationError(
            "Private Merchant catalog must be valid JSON",
            reason_code="INVALID_JSON",
        ) from None

    records = _catalog_records(payload)
    catalog_sha256 = _catalog_hash(records)

    return PrivateMerchantCatalog(
        records=records,
        source_sha256=hashlib.sha256(encoded).hexdigest(),
        catalog_sha256=catalog_sha256,
    )


def _object_without_duplicate_fields(
    pairs: Sequence[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for key, value in pairs:
        if key in result:
            raise PrivateCatalogValidationError(
                "Private Merchant catalog contains duplicate fields",
                reason_code="DUPLICATE_FIELD",
            )

        result[key] = value

    return result


def _catalog_records(
    payload: Any,
) -> tuple[PrivateMerchantRecord, ...]:
    if (
        not isinstance(payload, Sequence)
        or isinstance(payload, (str, bytes, bytearray))
    ):
        raise PrivateCatalogValidationError(
            "Private Merchant catalog root must be a JSON array",
            reason_code="ROOT_NOT_ARRAY",
        )

    if len(payload) != EXPECTED_CATALOG_RECORDS:
        raise PrivateCatalogValidationError(
            "Private Merchant catalog must contain exactly 22 records",
            reason_code="INVALID_RECORD_COUNT",
        )

    records = tuple(
        _catalog_record(record, record_number)
        for record_number, record in enumerate(payload, start=1)
    )
    codes = [record.code for record in records]

    if len(set(codes)) != len(codes):
        raise PrivateCatalogValidationError(
            "Private Merchant catalog contains duplicate normalized codes",
            reason_code="DUPLICATE_CODE",
        )

    return tuple(sorted(records, key=lambda record: record.code))


def _catalog_record(
    record: Any,
    record_number: int,
) -> PrivateMerchantRecord:
    if not isinstance(record, Mapping):
        raise _record_error(
            record_number,
            "RECORD_NOT_OBJECT",
            "must be an object",
        )

    fields = set(record)

    if fields - CATALOG_FIELDS:
        raise _record_error(
            record_number,
            "UNKNOWN_FIELDS",
            "contains unknown fields",
        )

    if REQUIRED_CATALOG_FIELDS - fields:
        raise _record_error(
            record_number,
            "MISSING_FIELDS",
            "is missing required fields",
        )

    code = _normalized_code(
        record.get("code"),
        record_number,
    )
    name = _normalized_name(
        record.get("name"),
        record_number,
    )
    region_code = _normalized_region(
        record.get("region_code"),
        record_number,
    )
    account_status = _account_status(
        record.get("account_status"),
        record_number,
    )

    return PrivateMerchantRecord(
        merchant_id=str(
            uuid.uuid5(CATALOG_ID_NAMESPACE, code)
        ),
        code=code,
        name=name,
        region_code=region_code,
        account_status=account_status,
    )


def _normalized_code(
    value: Any,
    record_number: int,
) -> str:
    if not isinstance(value, str):
        raise _record_error(
            record_number,
            "INVALID_CODE_TYPE",
            "has an invalid code type",
        )

    normalized = value.strip().upper()

    if not MERCHANT_CODE_PATTERN.fullmatch(normalized):
        raise _record_error(
            record_number,
            "INVALID_CODE",
            "has an invalid code",
        )

    return normalized


def _normalized_name(
    value: Any,
    record_number: int,
) -> str:
    if not isinstance(value, str):
        raise _record_error(
            record_number,
            "INVALID_NAME_TYPE",
            "has an invalid name type",
        )

    normalized = unicodedata.normalize("NFC", value.strip())

    if not normalized:
        raise _record_error(
            record_number,
            "BLANK_NAME",
            "has a blank name",
        )

    if len(normalized) > 500:
        raise _record_error(
            record_number,
            "NAME_TOO_LONG",
            "has a name longer than 500 characters",
        )

    if any(
        unicodedata.category(character) in {"Cc", "Cs"}
        for character in normalized
    ):
        raise _record_error(
            record_number,
            "INVALID_NAME_CHARACTER",
            "has an invalid name character",
        )

    return normalized


def _normalized_region(
    value: Any,
    record_number: int,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise _record_error(
            record_number,
            "INVALID_REGION_TYPE",
            "has an invalid region code type",
        )

    normalized = value.strip().upper()

    if not REGION_CODE_PATTERN.fullmatch(normalized):
        raise _record_error(
            record_number,
            "INVALID_REGION",
            "has an invalid region code",
        )

    return normalized


def _account_status(
    value: Any,
    record_number: int,
) -> str:
    if (
        not isinstance(value, str)
        or value not in CATALOG_ACCOUNT_STATUSES
    ):
        raise _record_error(
            record_number,
            "INVALID_ACCOUNT_STATUS",
            "has an invalid account status",
        )

    return value


def _record_error(
    record_number: int,
    reason_code: str,
    reason: str,
) -> PrivateCatalogValidationError:
    return PrivateCatalogValidationError(
        f"Private Merchant catalog record {record_number} {reason}",
        reason_code=reason_code,
        record_number=record_number,
    )


def _catalog_hash(
    records: Sequence[PrivateMerchantRecord],
) -> str:
    encoded = json.dumps(
        [
            record._canonical_dict()
            for record in records
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()
