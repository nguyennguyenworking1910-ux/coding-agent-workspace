"""Pure planning for private Merchant runtime initialization."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .catalog_contract import (
    CATALOG_ACCOUNT_STATUSES,
    EXPECTED_CATALOG_RECORDS,
    PrivateMerchantCatalog,
    PrivateMerchantRecord,
)


CATALOG_PLAN_VERSION = 1
CATALOG_INSERT = "INSERT"
CATALOG_NO_OP = "NO_OP"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TARGET_FIELDS = frozenset(
    {
        "merchant_id",
        "code",
        "name",
        "region_code",
        "account_status",
        "version",
    }
)


class CatalogPlanError(ValueError):
    """Base planning error with value-safe public text."""

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


class CatalogBindingError(CatalogPlanError):
    """Raised when the catalog differs from its reviewed binding."""


class CatalogTargetConflictError(CatalogPlanError):
    """Raised when runtime state is not empty or exactly identical."""


@dataclass(frozen=True, slots=True, repr=False)
class CatalogInitializationPlan:
    """An immutable plan consumed later by an authorized executor."""

    action: str
    records: tuple[PrivateMerchantRecord, ...]
    source_sha256: str
    catalog_sha256: str
    plan_sha256: str
    target_count_before: int

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def target_count_after(self) -> int:
        return EXPECTED_CATALOG_RECORDS

    @property
    def requires_authorization(self) -> bool:
        return self.action == CATALOG_INSERT

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
        """Return the complete non-secret review surface."""

        return {
            "success": True,
            "plan_version": CATALOG_PLAN_VERSION,
            "action": self.action,
            "record_count": self.record_count,
            "status_counts": self.status_counts,
            "target_count_before": self.target_count_before,
            "target_count_after": self.target_count_after,
            "source_sha256": self.source_sha256,
            "catalog_sha256": self.catalog_sha256,
            "plan_sha256": self.plan_sha256,
            "requires_authorization": self.requires_authorization,
            "transaction_mode": "SINGLE_ATOMIC_TRANSACTION",
        }

    def __repr__(self) -> str:
        return (
            "CatalogInitializationPlan("
            f"action={self.action!r}, "
            f"record_count={self.record_count}, "
            f"target_count_before={self.target_count_before}, "
            f"source_sha256={self.source_sha256!r}, "
            f"catalog_sha256={self.catalog_sha256!r}, "
            f"plan_sha256={self.plan_sha256!r})"
        )


def build_catalog_initialization_plan(
    catalog: PrivateMerchantCatalog,
    *,
    existing_records: Sequence[Mapping[str, Any]],
    expected_source_sha256: str,
    expected_catalog_sha256: str,
) -> CatalogInitializationPlan:
    """Bind one validated catalog to empty or identical target state."""

    if not isinstance(catalog, PrivateMerchantCatalog):
        raise CatalogPlanError(
            "Catalog planning requires a validated private catalog",
            reason_code="INVALID_CATALOG",
        )

    reviewed_source_hash = _reviewed_hash(
        expected_source_sha256,
        "source",
    )
    reviewed_catalog_hash = _reviewed_hash(
        expected_catalog_sha256,
        "catalog",
    )

    if catalog.source_sha256 != reviewed_source_hash:
        raise CatalogBindingError(
            "Private Merchant catalog source hash does not match "
            "the reviewed binding",
            reason_code="SOURCE_HASH_MISMATCH",
        )

    if catalog.catalog_sha256 != reviewed_catalog_hash:
        raise CatalogBindingError(
            "Private Merchant catalog plan hash does not match "
            "the reviewed binding",
            reason_code="CATALOG_HASH_MISMATCH",
        )

    target_records = _target_records(existing_records)

    if not target_records:
        action = CATALOG_INSERT
    elif _target_is_identical(catalog.records, target_records):
        action = CATALOG_NO_OP
    else:
        raise CatalogTargetConflictError(
            "Merchant target catalog is neither empty nor "
            "identical to the reviewed catalog",
            reason_code="TARGET_STATE_CONFLICT",
        )

    plan_hash = _plan_hash(
        action=action,
        catalog=catalog,
        target_count_before=len(target_records),
    )

    return CatalogInitializationPlan(
        action=action,
        records=catalog.records,
        source_sha256=reviewed_source_hash,
        catalog_sha256=reviewed_catalog_hash,
        plan_sha256=plan_hash,
        target_count_before=len(target_records),
    )


def _reviewed_hash(
    value: Any,
    label: str,
) -> str:
    if not isinstance(value, str):
        raise CatalogBindingError(
            f"Reviewed {label} hash must be a lowercase SHA-256",
            reason_code=f"INVALID_{label.upper()}_HASH",
        )

    if not SHA256_PATTERN.fullmatch(value):
        raise CatalogBindingError(
            f"Reviewed {label} hash must be a lowercase SHA-256",
            reason_code=f"INVALID_{label.upper()}_HASH",
        )

    return value


def _target_records(
    existing_records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if (
        not isinstance(existing_records, Sequence)
        or isinstance(
            existing_records,
            (str, bytes, bytearray),
        )
    ):
        raise CatalogTargetConflictError(
            "Merchant target state must be a sequence",
            reason_code="INVALID_TARGET_STATE",
        )

    normalized = tuple(
        _target_record(record, record_number)
        for record_number, record in enumerate(
            existing_records,
            start=1,
        )
    )
    merchant_ids = [
        record["merchant_id"] for record in normalized
    ]
    codes = [record["code"] for record in normalized]

    if len(set(merchant_ids)) != len(merchant_ids):
        raise CatalogTargetConflictError(
            "Merchant target state contains duplicate identities",
            reason_code="DUPLICATE_TARGET_ID",
        )

    if len(set(codes)) != len(codes):
        raise CatalogTargetConflictError(
            "Merchant target state contains duplicate codes",
            reason_code="DUPLICATE_TARGET_CODE",
        )

    return tuple(
        sorted(
            normalized,
            key=lambda record: record["code"],
        )
    )


def _target_record(
    record: Any,
    record_number: int,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise _target_error(
            record_number,
            "TARGET_RECORD_NOT_OBJECT",
            "must be an object",
        )

    fields = set(record)

    if fields != TARGET_FIELDS:
        raise _target_error(
            record_number,
            "INVALID_TARGET_FIELDS",
            "has invalid fields",
        )

    merchant_id = record.get("merchant_id")
    code = record.get("code")
    name = record.get("name")
    region_code = record.get("region_code")
    account_status = record.get("account_status")
    version = record.get("version")

    if not isinstance(merchant_id, str):
        raise _target_error(
            record_number,
            "INVALID_TARGET_ID",
            "has an invalid identity",
        )

    if not isinstance(code, str):
        raise _target_error(
            record_number,
            "INVALID_TARGET_CODE",
            "has an invalid code",
        )

    if not isinstance(name, str):
        raise _target_error(
            record_number,
            "INVALID_TARGET_NAME",
            "has an invalid name",
        )

    if region_code is not None and not isinstance(
        region_code,
        str,
    ):
        raise _target_error(
            record_number,
            "INVALID_TARGET_REGION",
            "has an invalid region",
        )

    if account_status not in CATALOG_ACCOUNT_STATUSES:
        raise _target_error(
            record_number,
            "INVALID_TARGET_STATUS",
            "has an invalid status",
        )

    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != 1
    ):
        raise _target_error(
            record_number,
            "INVALID_TARGET_VERSION",
            "has an invalid version",
        )

    return {
        "merchant_id": merchant_id,
        "code": code,
        "name": name,
        "region_code": region_code,
        "account_status": account_status,
        "version": version,
    }


def _target_error(
    record_number: int,
    reason_code: str,
    reason: str,
) -> CatalogTargetConflictError:
    return CatalogTargetConflictError(
        f"Merchant target record {record_number} {reason}",
        reason_code=reason_code,
        record_number=record_number,
    )


def _target_is_identical(
    catalog_records: Sequence[PrivateMerchantRecord],
    target_records: Sequence[Mapping[str, Any]],
) -> bool:
    if len(catalog_records) != len(target_records):
        return False

    for catalog_record, target_record in zip(
        catalog_records,
        target_records,
        strict=True,
    ):
        if (
            catalog_record.merchant_id
            != target_record["merchant_id"]
            or catalog_record.code != target_record["code"]
            or catalog_record.name != target_record["name"]
            or catalog_record.region_code
            != target_record["region_code"]
            or catalog_record.account_status
            != target_record["account_status"]
            or target_record["version"] != 1
        ):
            return False

    return True


def _plan_hash(
    *,
    action: str,
    catalog: PrivateMerchantCatalog,
    target_count_before: int,
) -> str:
    payload = {
        "action": action,
        "catalog_sha256": catalog.catalog_sha256,
        "plan_version": CATALOG_PLAN_VERSION,
        "record_count": catalog.record_count,
        "source_sha256": catalog.source_sha256,
        "status_counts": catalog.status_counts,
        "target_count_after": EXPECTED_CATALOG_RECORDS,
        "target_count_before": target_count_before,
        "transaction_mode": "SINGLE_ATOMIC_TRANSACTION",
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()
