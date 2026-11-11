"""Trusted Purchase Request recording contract (CP12H.NL4D4A).

A verified ``evidence preview`` of one new Purchase Request on the test
database carries ``requested_operation``: the exact ``procurement update``
that would record it, bound to the trusted local operator (DEC-A0) and to a
basis hash of what was judged. It is data, never authority (NOT_AUTHORIZED).
Trusted code turns a verified capture of it into a pending confirmation; the
user's own ``/solve Xác nhận ghi nhận`` spends it; ``verify_purchase_request``
re-judges it before any spend and again inside the write transaction, after
the Project and its procurement records are locked.

Approved policy applied here (NL4D-DEC):

- DEC-P1a: a reference is unique within (merchant, procurement type,
  reference), exactly as typed. Migration 007 enforces it in the database.
- DEC-P1c: creation only. An existing Purchase Request reference is never
  replaced; any existing Purchase Request record refuses the operation.
- DEC-P2: ``requires_procurement=false`` does not forbid it (the preview
  notes PROCUREMENT_NOT_REQUIRED); no Step or workflow state changes.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from .procurement_engine import ProcurementEngineError, propose_procurement_mutation

OPERATION_COMMAND = "procurement update"
OPERATION_NAME = "RECORD_PURCHASE_REQUEST"
PROCUREMENT_TYPE = "PURCHASE_REQUEST"
NOT_AUTHORIZED = "NOT_AUTHORIZED"
# Mirrors merchant_direct_handoff (test-mode only; runtime Direct EXECUTE is
# off). Reporting only: the gate and preflight decide independently.
CONFIRMABLE_TARGETS = frozenset({"test"})
OPERATION_NOTE = (
    "Data, not authority. Nothing was recorded. Only the user's own "
    "confirmation of this exact operation, re-checked against current state "
    "and the trusted operator, can run it."
)

BASIS_REQUIRED = "PURCHASE_REQUEST_BASIS_REQUIRED"
MERCHANT_MISMATCH = "MERCHANT_MISMATCH"
RECORD_EXISTS = "PURCHASE_REQUEST_ALREADY_RECORDED"
REPLACEMENT_UNSUPPORTED = "PROCUREMENT_REFERENCE_REPLACEMENT_UNSUPPORTED"
DUPLICATE_REFERENCE = "PROCUREMENT_REFERENCE_DUPLICATE"
NOT_VALID = "PURCHASE_REQUEST_NOT_VALID"
BASIS_CHANGED = "PURCHASE_REQUEST_BASIS_CHANGED"

# The engine's "new id" argument while judging. Never written.
_PLACEHOLDER_ID = "00000000-0000-4000-8000-00000000d4a0"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
# Every field the confirmed argv may carry; anything else is not this operation.
_PAYLOAD_FIELDS = frozenset({"project_id", "procurement_type", "external_id",
                             "merchant_code", "operator_id", "expected_basis_hash"})


class PurchaseRequestMismatch(PermissionError):
    """The confirmed Purchase Request no longer matches its preview."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _canonical(row: Any) -> str:
    return json.dumps(dict(row), sort_keys=True, ensure_ascii=False, default=str)


def _purchase_request(records: Any) -> dict[str, Any] | None:
    return next((dict(r) for r in records or []
                 if str(r.get("procurement_type")).upper() == PROCUREMENT_TYPE), None)


def reference_blocker(
    project_id: str, record: dict[str, Any] | None, reference: str, holders: Any,
) -> tuple[str, str] | None:
    """(code, message) when DEC-P1a or DEC-P1c forbids recording ``reference``."""

    if record is not None and record.get("external_id") not in (None, reference):
        return REPLACEMENT_UNSUPPORTED, (
            "This Project already has a Purchase Request with another reference; "
            "replacing a recorded reference is not supported (DEC-P1c).")
    elsewhere = [h for h in holders or [] if _text(h.get("project_id")) != project_id]
    if elsewhere:
        return DUPLICATE_REFERENCE, (
            "This Merchant already has a record of this type with exactly this "
            "reference on another Project (DEC-P1a).")
    return None


def purchase_request_basis(detail: dict[str, Any], reference: str, holders: Any,
                           operator_id: str) -> str:
    """sha256 of what the operation was judged on.

    The Project row (version, status, requires_procurement, Merchant fields),
    every procurement record of the Project, every record of the Merchant
    holding the reference, the reference itself and the operator.
    """

    basis = {
        "operation": [PROCUREMENT_TYPE, reference, operator_id],
        "project": _canonical(detail["project"]),
        "procurement_records": sorted(_canonical(r) for r in detail.get("procurement_records") or []),
        "reference_holders": sorted(_canonical(h) for h in holders or []),
    }
    return hashlib.sha256(
        json.dumps(basis, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def canonical_purchase_request_argv(operation: dict[str, Any]) -> list[str]:
    """The one argv form of a previewed Purchase Request (fixed order)."""

    return [
        "procurement", "update", operation["project_id"],
        "--type", PROCUREMENT_TYPE,
        "--external-id", operation["reference"],
        "--merchant-code", operation["merchant_code"],
        "--operator-id", operation["operator_id"],
        "--expected-basis", operation["expected_basis"],
    ]


def build_operation(detail: dict[str, Any], reference: str, holders: Any,
                    operator_id: str, database_target: str) -> dict[str, Any]:
    project = dict(detail["project"])
    operation = {
        "command": OPERATION_COMMAND,
        "operation": OPERATION_NAME,
        "status": NOT_AUTHORIZED,
        "database_target": database_target,
        "procurement_type": PROCUREMENT_TYPE,
        "merchant_id": _text(project["merchant_id"]),
        "merchant_code": project.get("merchant_code"),
        "project_id": _text(project["id"]),
        "project_title": project.get("title"),
        "project_version": project.get("version"),
        "requires_procurement": bool(project.get("requires_procurement")),
        "reference": reference,
        "operator_id": operator_id,
        "expected_basis": purchase_request_basis(detail, reference, holders, operator_id),
    }
    operation["argv"] = canonical_purchase_request_argv(operation)
    operation["note"] = OPERATION_NOTE
    validate_operation(operation)
    return operation


def _safe_reference(value: Any) -> bool:
    """One argv-safe token the domain accepts (non-blank, at most 100 characters)."""

    return (
        isinstance(value, str) and 0 < len(value) <= 100
        and not value.startswith("-")
        and unicodedata.normalize("NFC", value) == value
        and not any(c.isspace() or unicodedata.category(c).startswith("C") for c in value)
    )


def validate_operation(operation: Any) -> None:
    """Raise ValueError unless ``operation`` is one complete, canonical Purchase Request.

    Rejects truncated, edited, retargeted or reconstructed operations. It never
    grants authority.
    """

    if not isinstance(operation, dict):
        raise ValueError("requested_operation must be an object")
    expected = {"command": OPERATION_COMMAND, "operation": OPERATION_NAME,
                "status": NOT_AUTHORIZED, "procurement_type": PROCUREMENT_TYPE}
    for name, value in expected.items():
        if operation.get(name) != value:
            raise ValueError(f"requested_operation {name} must be {value}")
    if operation.get("database_target") not in CONFIRMABLE_TARGETS:
        raise ValueError("requested_operation must target the test database")
    for name in ("merchant_id", "merchant_code", "project_id", "project_title", "operator_id"):
        value = operation.get(name)
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"requested_operation field {name} is missing")
    for name in ("merchant_id", "project_id", "operator_id"):
        if not _UUID.fullmatch(operation[name]):
            raise ValueError("requested_operation identifiers must be canonical UUIDs")
    if operation["operator_id"] == "00000000-0000-0000-0000-000000000000":
        raise ValueError("requested_operation has no operator")
    version = operation.get("project_version")
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
        raise ValueError("requested_operation project_version must be a positive integer")
    if not isinstance(operation.get("requires_procurement"), bool):
        raise ValueError("requested_operation requires_procurement must be a boolean")
    if not _safe_reference(operation.get("reference")) or not _safe_reference(
            operation["merchant_code"]):
        raise ValueError("requested_operation reference is not one exact token")
    if not isinstance(operation.get("expected_basis"), str) or not _HEX64.fullmatch(
            operation["expected_basis"]):
        raise ValueError("requested_operation has no valid expected_basis")
    if operation.get("argv") != canonical_purchase_request_argv(operation):
        raise ValueError("requested_operation argv is not the canonical operation")


def is_confirmed_payload(payload: dict[str, Any]) -> bool:
    """A ``procurement update`` payload that claims a previewed Purchase Request."""

    return any(payload.get(name) is not None
               for name in ("expected_basis_hash", "merchant_code", "operator_id"))


def verify_purchase_request(reads: Any, payload: dict[str, Any], operator_id: str) -> dict[str, Any]:
    """Refuse unless the confirmed Purchase Request still matches its preview.

    ``payload`` is the exact confirmed CLI payload and ``operator_id`` the
    trusted operator resolved now. Re-reads the Project, its procurement
    records and the Merchant's holders of the reference, re-applies DEC-P1a,
    DEC-P1c and the domain engine, and recomputes the basis. Raises
    PurchaseRequestMismatch; returns the engine's plan.
    """

    # procurement_id is generated by the CLI at execution (GENERATED_ID_FIELDS),
    # never by the scope: the canonical argv cannot carry it.
    present = {k for k, v in payload.items() if v is not None} - {"procurement_id"}
    if (
        present - _PAYLOAD_FIELDS
        or not all(payload.get(name) for name in _PAYLOAD_FIELDS)
        or payload.get("procurement_type") != PROCUREMENT_TYPE
    ):
        raise PurchaseRequestMismatch(
            BASIS_REQUIRED,
            "a Purchase Request is recorded only as the preview's exact operation",
        )
    if payload["operator_id"] != operator_id:
        raise PurchaseRequestMismatch("OPERATOR_IDENTITY_CHANGED")

    reference = payload["external_id"]
    detail = reads.get_project_detail(payload["project_id"])
    project = dict(detail["project"])
    if project.get("merchant_code") != payload["merchant_code"]:
        raise PurchaseRequestMismatch(MERCHANT_MISMATCH, "the Project belongs to another Merchant")

    records = [dict(r) for r in detail.get("procurement_records") or []]
    existing = _purchase_request(records)
    holders = reads.procurement_reference_holders(
        _text(project["merchant_id"]), PROCUREMENT_TYPE, reference)
    blocker = reference_blocker(_text(project["id"]), existing, reference, holders)
    if blocker is not None:
        raise PurchaseRequestMismatch(*blocker)
    if existing is not None or holders:
        raise PurchaseRequestMismatch(RECORD_EXISTS, "only a new Purchase Request can be recorded")

    try:
        plan = propose_procurement_mutation(
            {"project": project, "procurement_records": records,
             "document_revisions": detail.get("document_revisions") or []},
            procurement_id=_PLACEHOLDER_ID, procurement_type=PROCUREMENT_TYPE,
            external_id=reference, triggered_by=operator_id,
        )
    except ProcurementEngineError as error:
        raise PurchaseRequestMismatch(NOT_VALID, type(error).__name__) from error
    if plan.operation != "INSERT" or plan.external_id != reference:
        raise PurchaseRequestMismatch(NOT_VALID, "the domain would not create this record")

    if purchase_request_basis(detail, reference, holders, operator_id) != payload["expected_basis_hash"]:
        raise PurchaseRequestMismatch(
            BASIS_CHANGED, "the Project or its procurement evidence changed since the preview")
    return plan.to_dict()
