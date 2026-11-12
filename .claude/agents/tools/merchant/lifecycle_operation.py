"""Trusted confirmation-first lifecycle operations (CP12H.MASTER).

Owner-approved policy DEC-SIMPLIFY (P1-P8), DEC-SIMPLIFY-a and -b, Local
Test MVP: a user's explicit confirmation of one exact, verified preview is
the authority for an ordinary business operation. No document upload,
approver verification, role mapping or second operator is required.

One module judges, binds and re-verifies six operations:

- CREATE_METADATA_ONLY_REVISION  (``document revision-create``): a revision
  with no file; evidence_status METADATA_ONLY and content_hash fixed to
  ``metadata-only:<revision id>`` (migration 009). A signed active revision
  of the type is never superseded (DEC-D4e).
- RECORD_APPROVAL_DECISION       (``document approve``): one role, one final
  APPROVED or REJECTED decision on the latest active unsigned revision, with
  optional notes and decision date. The trusted operator is the *recorder*
  (``recorded_by``); the approver is never fabricated (``approved_by`` NULL).
- RECORD_OPERATOR_ATTESTED_SIGNING (``document sign``): the existing signing
  gate (LEGAL, ACCOUNTING and PARTNER APPROVED, Purchase Request when
  procurement is required) must hold; stored as OPERATOR_ATTESTED_SIGNED.
- RECORD_PURCHASE_ORDER / RECORD_PAYMENT_REQUEST (``procurement update``):
  create-only, exact reference, unique per (Merchant, type, reference)
  (DEC-P1a), existing domain prerequisites (signed revision; PO number).
- COMPLETE_PROJECT               (``project update --status COMPLETED``): every
  Step terminal (COMPLETED, SKIPPED or SUPERSEDED) and every non-skipped
  final Step COMPLETED; a separate operation, never implied by a Step.

Each operation is data, never authority (NOT_AUTHORIZED). It carries the
trusted local operator (DEC-A0) and a basis hash of the whole Project
snapshot it was judged on. ``verify`` re-reads current state, re-judges with
the domain engines and recomputes the basis; the preflight runs it before any
spend and the write adapter runs it again inside the write transaction, after
the locks. Any change refuses the operation.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .approval_engine import propose_document_approval
from .document_engine import propose_document_revision
from .procurement_engine import propose_procurement_mutation
from .project_engine import PROJECT_TERMINAL_STEP_STATUSES, propose_project_transition
from .signing_engine import propose_document_signing

NOT_AUTHORIZED = "NOT_AUTHORIZED"
CONFIRMABLE_TARGETS = frozenset({"test"})
OPERATION_NOTE = (
    "Data, not authority. Nothing was written. Only the user's own "
    "confirmation of this exact operation, re-checked against current state "
    "and the trusted operator, can run it."
)

CREATE_REVISION = "CREATE_METADATA_ONLY_REVISION"
RECORD_DECISION = "RECORD_APPROVAL_DECISION"
SIGN = "RECORD_OPERATOR_ATTESTED_SIGNING"
PURCHASE_ORDER = "RECORD_PURCHASE_ORDER"
PAYMENT_REQUEST = "RECORD_PAYMENT_REQUEST"
COMPLETE_PROJECT = "COMPLETE_PROJECT"
START_PROJECT = "START_PROJECT"
KINDS = (CREATE_REVISION, RECORD_DECISION, SIGN, PURCHASE_ORDER, PAYMENT_REQUEST, COMPLETE_PROJECT,
         START_PROJECT)
# project update: the status each Project operation sets.
PROJECT_TARGETS = {START_PROJECT: "IN_PROGRESS", COMPLETE_PROJECT: "COMPLETED"}

COMMANDS = {
    CREATE_REVISION: "document revision-create",
    RECORD_DECISION: "document approve",
    SIGN: "document sign",
    PURCHASE_ORDER: "procurement update",
    PAYMENT_REQUEST: "procurement update",
    COMPLETE_PROJECT: "project update",
    START_PROJECT: "project update",
}
PROCUREMENT_TYPES = {PURCHASE_ORDER: "PURCHASE_ORDER", PAYMENT_REQUEST: "PAYMENT_REQUEST"}
# Commands whose confirmed form is a lifecycle operation. ``procurement
# update`` is one only for a Purchase Order or Payment Request; a Purchase
# Request stays on its proven NL4D4A path.
LIFECYCLE_COMMANDS = frozenset(COMMANDS.values())

METADATA_ONLY = "METADATA_ONLY"
METADATA_ONLY_PREFIX = "metadata-only:"
OPERATOR_RECORDED = "OPERATOR_RECORDED"
OPERATOR_ATTESTED_SIGNED = "OPERATOR_ATTESTED_SIGNED"
DECISIONS = ("APPROVED", "REJECTED")
ROLES = ("LEGAL", "ACCOUNTING", "PARTNER")

# Refusal reasons.
BASIS_REQUIRED = "LIFECYCLE_BASIS_REQUIRED"
BASIS_CHANGED = "LIFECYCLE_BASIS_CHANGED"
MERCHANT_MISMATCH = "MERCHANT_MISMATCH"
OPERATOR_CHANGED = "OPERATOR_IDENTITY_CHANGED"
NOT_VALID = "LIFECYCLE_OPERATION_NOT_VALID"
SIGNED_REVISION = "SIGNED_REVISION_NOT_SUPERSEDED"
DECISION_RECORDED = "APPROVAL_DECISION_ALREADY_RECORDED"
DECISION_REJECTED = "APPROVAL_REJECTED_BLOCKS_SIGNING"
RECORD_EXISTS = "PROCUREMENT_RECORD_ALREADY_RECORDED"
DUPLICATE_REFERENCE = "PROCUREMENT_REFERENCE_DUPLICATE"
STEPS_UNFINISHED = "PROJECT_STEPS_UNFINISHED"
FINAL_STEP_UNFINISHED = "FINAL_STEP_NOT_COMPLETED"
REVISION_NOT_FOUND = "DOCUMENT_REVISION_NOT_FOUND"
DATE_INVALID = "DECISION_DATE_INVALID"
NOTES_INVALID = "NOTES_INVALID"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TYPE = re.compile(r"[A-Z][A-Z0-9_]{0,99}")
_BASIS_SECTIONS = ("steps", "dependencies", "document_revisions", "document_approvals",
                   "procurement_records")
# Project timezone: a stated decision or signing date is that day, 00:00 here.
_LOCAL = timezone(timedelta(hours=7))
_PLACEHOLDER_ID = "00000000-0000-4000-8000-0000000000aa"
_NIL = "00000000-0000-0000-0000-000000000000"

# The CLI payload fields each confirmed command may carry (None ignored).
_PAYLOAD_FIELDS = {
    CREATE_REVISION: {"revision_id", "project_id", "document_type", "content_hash", "effective_date",
                      "expiry_date", "merchant_code", "operator_id", "expected_basis_hash"},
    RECORD_DECISION: {"approval_id", "document_revision_id", "approver_role", "approval_status",
                      "expected_status", "occurred_at", "notes", "project_id", "merchant_code",
                      "operator_id", "expected_basis_hash"},
    SIGN: {"document_revision_id", "signed_at", "project_id", "merchant_code", "operator_id",
           "expected_basis_hash"},
    # procurement_id is generated by the CLI at execution (GENERATED_ID_FIELDS),
    # never by the scope: the canonical argv cannot carry it.
    PURCHASE_ORDER: {"project_id", "procurement_type", "external_id", "merchant_code", "operator_id",
                     "expected_basis_hash", "procurement_id"},
    PAYMENT_REQUEST: {"project_id", "procurement_type", "external_id", "merchant_code", "operator_id",
                      "expected_basis_hash", "procurement_id"},
    COMPLETE_PROJECT: {"project_id", "status", "expected_version", "merchant_code", "operator_id",
                       "expected_basis_hash"},
    START_PROJECT: {"project_id", "status", "expected_version", "merchant_code", "operator_id",
                    "expected_basis_hash"},
}
_REQUIRED = {
    CREATE_REVISION: ("revision_id", "project_id", "document_type", "content_hash"),
    RECORD_DECISION: ("approval_id", "document_revision_id", "approver_role", "approval_status",
                      "project_id"),
    SIGN: ("document_revision_id", "project_id"),
    PURCHASE_ORDER: ("project_id", "procurement_type", "external_id"),
    PAYMENT_REQUEST: ("project_id", "procurement_type", "external_id"),
    COMPLETE_PROJECT: ("project_id", "status", "expected_version"),
    START_PROJECT: ("project_id", "status", "expected_version"),
}


class LifecycleMismatch(PermissionError):
    """The operation is not valid now, or no longer matches its preview."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


# ----------------------------------------------------------------- helpers


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _canonical(row: Any) -> str:
    return json.dumps(dict(row), sort_keys=True, ensure_ascii=False, default=str)


def metadata_only_hash(revision_id: str) -> str:
    return f"{METADATA_ONLY_PREFIX}{revision_id}"


def safe_token(value: Any, limit: int = 100) -> bool:
    """One argv-safe token (no spaces or control characters, not an option)."""

    return (
        isinstance(value, str) and 0 < len(value) <= limit and not value.startswith("-")
        and unicodedata.normalize("NFC", value) == value
        and not any(c.isspace() or unicodedata.category(c).startswith("C") for c in value)
    )


def valid_notes(value: Any) -> bool:
    """Optional free text: 1-500 characters, NFC, no control characters."""

    return (
        isinstance(value, str) and 0 < len(value) <= 500 and value == value.strip()
        and not value.startswith("-") and unicodedata.normalize("NFC", value) == value
        and not any(unicodedata.category(c).startswith("C") for c in value)
    )


def _date_text(value: Any) -> str | None:
    """A stated date (YYYY-MM-DD) from a payload value (date, datetime or text)."""

    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=_LOCAL)
        return moment.astimezone(_LOCAL).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    if _DATE.fullmatch(text):
        return text
    return _date_text(datetime.fromisoformat(text))


def _moment(day: str | None) -> datetime | None:
    return None if day is None else datetime.fromisoformat(day).replace(tzinfo=_LOCAL)


def moment_argument(day: str) -> str:
    """The canonical ``--occurred-at``/``--signed-at`` text of a stated day."""

    return f"{day}T00:00:00+07:00"


def _check_day(day: str | None, field: str) -> None:
    if day is None:
        return
    try:
        parsed = date.fromisoformat(day)
    except (TypeError, ValueError) as error:
        raise LifecycleMismatch(DATE_INVALID, f"{field} is not a date") from error
    if parsed > datetime.now(_LOCAL).date():
        raise LifecycleMismatch(DATE_INVALID, f"{field} is in the future")


def _own_revisions(detail: dict[str, Any]) -> list[dict[str, Any]]:
    project_id = _text(detail["project"]["id"])
    return [dict(r) for r in detail.get("document_revisions") or []
            if _text(r.get("project_id")) == project_id]


def _revision(detail: dict[str, Any], revision_id: str) -> dict[str, Any]:
    found = next((r for r in _own_revisions(detail) if _text(r["id"]) == revision_id), None)
    if found is None:
        raise LifecycleMismatch(REVISION_NOT_FOUND, "the revision is not part of this Project")
    return found


def _approvals(detail: dict[str, Any]) -> list[dict[str, Any]]:
    ids = {_text(r["id"]) for r in _own_revisions(detail)}
    return [dict(a) for a in detail.get("document_approvals") or []
            if _text(a.get("document_revision_id")) in ids]


def _engine(call: Any) -> Any:
    try:
        return call()
    except LifecycleMismatch:
        raise
    except ValueError as error:  # every domain engine error is a ValueError
        raise LifecycleMismatch(NOT_VALID, f"{type(error).__name__}: {error}") from error


def final_step_ids(detail: dict[str, Any]) -> set[str]:
    """The workflow's final Step: the Project's highest-numbered Step.

    Every registered template has exactly one sink and it is its last Step
    ("Complete project", "Close payment period"). "No successor" is not used:
    a conditionally SKIPPED Step loses its edges at instantiation and would
    look final.
    """

    steps = [s for s in detail.get("steps") or [] if isinstance(s.get("sequence_number"), int)]
    if not steps:
        return set()
    last = max(s["sequence_number"] for s in steps)
    return {_text(s["id"]) for s in steps if s["sequence_number"] == last}


# ------------------------------------------------------------------ judges


def judge(kind: str, detail: dict[str, Any], params: dict[str, Any],
          holders: Any = (), operator_id: str | None = None) -> dict[str, Any]:
    """Judge one operation on a Project snapshot; a plan summary or LifecycleMismatch."""

    project = dict(detail["project"])
    revisions = _own_revisions(detail)

    if kind == CREATE_REVISION:
        document_type = params["document_type"]
        if not isinstance(document_type, str) or not _TYPE.fullmatch(document_type):
            raise LifecycleMismatch(NOT_VALID, "document type must match ^[A-Z][A-Z0-9_]{0,99}$")
        active = [r for r in revisions if r.get("superseded_by") is None
                  and str(r.get("document_type")).upper() == document_type]
        if any(r.get("signed") for r in active):
            raise LifecycleMismatch(SIGNED_REVISION, (
                "the active revision of this type is signed and is not superseded (DEC-D4e)"))
        for name in ("effective_date", "expiry_date"):
            if params.get(name) is not None and not _DATE.fullmatch(str(params[name])):
                raise LifecycleMismatch(NOT_VALID, f"{name} is not a date")
        plan = _engine(lambda: propose_document_revision(
            {"project": project, "revisions": revisions},
            revision_id=params["revision_id"], document_type=document_type,
            content_hash=metadata_only_hash(params["revision_id"]),
            effective_date=date.fromisoformat(params["effective_date"]) if params.get("effective_date") else None,
            expiry_date=date.fromisoformat(params["expiry_date"]) if params.get("expiry_date") else None,
            created_by=operator_id,
        ))
        return {"revision_number": plan.revision_number,
                "previous_revision_id": plan.previous_revision_id,
                "previous_revision_number": plan.previous_revision_number,
                "event_type": plan.event_type}

    if kind == RECORD_DECISION:
        target = _revision(detail, params["revision_id"])
        if params["role"] not in ROLES or params["decision"] not in DECISIONS:
            raise LifecycleMismatch(NOT_VALID, "role must be LEGAL, ACCOUNTING or PARTNER and the "
                                               "decision APPROVED or REJECTED")
        if params.get("decision_note") is not None and not valid_notes(params["decision_note"]):
            raise LifecycleMismatch(NOTES_INVALID, "notes must be 1-500 characters of plain text")
        _check_day(params.get("decided_on"), "decision date")
        approvals = _approvals(detail)
        current = next((a for a in approvals
                        if _text(a.get("document_revision_id")) == params["revision_id"]
                        and str(a.get("approver_role")).upper() == params["role"]), None)
        current_status = None if current is None else str(current.get("approval_status")).upper()
        if current_status in DECISIONS:
            raise LifecycleMismatch(DECISION_RECORDED, (
                f"{params['role']} already recorded {current_status} for this revision; a decision "
                "is final (register a new revision to start a new approval cycle)"))
        plan = _engine(lambda: propose_document_approval(
            {"project": project, "revisions": revisions, "approvals": approvals},
            document_revision_id=params["revision_id"], approval_id=params["approval_id"],
            approver_role=params["role"], approval_status=params["decision"],
            expected_status=current_status, occurred_at=_moment(params.get("decided_on")),
            notes=params.get("decision_note"),
        ))
        return {"operation": plan.operation, "current_status": current_status,
                "document_type": target.get("document_type"),
                "revision_number": target.get("revision_number"),
                "event_type": plan.event_type}

    if kind == SIGN:
        target = _revision(detail, params["revision_id"])
        _check_day(params.get("signed_on"), "signing date")
        rejected = sorted(str(a.get("approver_role")).upper() for a in _approvals(detail)
                          if _text(a.get("document_revision_id")) == params["revision_id"]
                          and str(a.get("approval_status")).upper() == "REJECTED")
        if rejected:
            raise LifecycleMismatch(DECISION_REJECTED, (
                f"{', '.join(rejected)} rejected this revision, so it cannot be signed; register a "
                "new revision to start a new approval cycle"))
        plan = _engine(lambda: propose_document_signing(
            {"project": project, "document_revisions": revisions,
             "document_approvals": _approvals(detail),
             "procurement_records": [dict(r) for r in detail.get("procurement_records") or []]},
            document_revision_id=params["revision_id"], occurred_at=_moment(params.get("signed_on")),
        ))
        return {"document_type": target.get("document_type"),
                "revision_number": target.get("revision_number"), "event_type": plan.event_type}

    if kind in PROCUREMENT_TYPES:
        procurement_type = PROCUREMENT_TYPES[kind]
        reference = params["reference"]
        if not safe_token(reference):
            raise LifecycleMismatch(NOT_VALID, "the reference must be one exact token")
        records = [dict(r) for r in detail.get("procurement_records") or []]
        if any(str(r.get("procurement_type")).upper() == procurement_type for r in records):
            raise LifecycleMismatch(RECORD_EXISTS, (
                "this Project already has this record; replacing a recorded reference is not "
                "supported"))
        if holders:  # any holder: this Project's own record is RECORD_EXISTS above
            raise LifecycleMismatch(DUPLICATE_REFERENCE, (
                "this Merchant already has a record of this type with exactly this reference "
                "(DEC-P1a)"))
        plan = _engine(lambda: propose_procurement_mutation(
            {"project": project, "procurement_records": records, "document_revisions": revisions},
            procurement_id=_PLACEHOLDER_ID, procurement_type=procurement_type,
            external_id=reference, triggered_by=operator_id,
        ))
        if plan.operation != "INSERT":
            raise LifecycleMismatch(RECORD_EXISTS, "only a new record can be created")
        return {"procurement_type": procurement_type, "event_type": plan.event_type}

    if kind == COMPLETE_PROJECT:
        steps = [dict(s) for s in detail.get("steps") or []]
        unfinished = sorted(_text(s["id"]) for s in steps
                            if str(s.get("status")).upper() not in PROJECT_TERMINAL_STEP_STATUSES)
        if unfinished:
            raise LifecycleMismatch(STEPS_UNFINISHED, (
                f"{len(unfinished)} Step(s) are not COMPLETED or legitimately SKIPPED"))
        finals = final_step_ids(detail)
        open_finals = sorted(_text(s["id"]) for s in steps if _text(s["id"]) in finals
                             and str(s.get("status")).upper() not in ("COMPLETED", "SKIPPED"))
        if open_finals or not any(_text(s["id"]) in finals and str(s.get("status")).upper()
                                  == "COMPLETED" for s in steps):
            raise LifecycleMismatch(FINAL_STEP_UNFINISHED, "the workflow's final Step is not COMPLETED")
        if params["expected_version"] != project.get("version"):
            raise LifecycleMismatch(BASIS_CHANGED, "the Project version changed")
        plan = _engine(lambda: propose_project_transition(
            {"project": project, "steps": steps}, "COMPLETED",
            expected_version=params["expected_version"],
        ))
        return {"current_status": plan.current_status, "new_version": plan.new_version,
                "event_type": plan.event_type}

    if kind == START_PROJECT:
        if params["expected_version"] != project.get("version"):
            raise LifecycleMismatch(BASIS_CHANGED, "the Project version changed")
        plan = _engine(lambda: propose_project_transition(
            {"project": project, "steps": [dict(s) for s in detail.get("steps") or []]},
            "IN_PROGRESS", expected_version=params["expected_version"],
        ))
        return {"current_status": plan.current_status, "new_version": plan.new_version,
                "event_type": plan.event_type}

    raise LifecycleMismatch(NOT_VALID, f"unknown operation {kind!r}")


# ------------------------------------------------------- basis and argv


def basis(kind: str, detail: dict[str, Any], params: dict[str, Any], operator_id: str,
          holders: Any = ()) -> str:
    """sha256 of the operation and the whole Project snapshot it was judged on."""

    value = {
        "operation": [kind, sorted((k, _text(v)) for k, v in params.items()), operator_id],
        "project": _canonical(detail["project"]),
        **{name: sorted(_canonical(row) for row in detail.get(name) or []) for name in _BASIS_SECTIONS},
        "reference_holders": sorted(_canonical(h) for h in holders or []),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def canonical_argv(operation: dict[str, Any]) -> list[str]:
    """The one argv form of an operation (fixed order)."""

    kind, p = operation["operation"], operation["params"]
    binding = ["--merchant-code", operation["merchant_code"], "--operator-id", operation["operator_id"],
               "--expected-basis", operation["expected_basis"]]
    if kind == CREATE_REVISION:
        argv = ["document", "revision-create", operation["project_id"], "--type", p["document_type"],
                "--content-hash", metadata_only_hash(p["revision_id"]), "--revision-id", p["revision_id"]]
        for name, flag in (("effective_date", "--effective-date"), ("expiry_date", "--expiry-date")):
            if p.get(name):
                argv += [flag, p[name]]
        return argv + binding
    if kind == RECORD_DECISION:
        argv = ["document", "approve", p["revision_id"], "--role", p["role"], "--status", p["decision"],
                "--approval-id", p["approval_id"]]
        if p.get("expected_status"):
            argv += ["--expected-status", p["expected_status"]]
        if p.get("decided_on"):
            argv += ["--occurred-at", moment_argument(p["decided_on"])]
        if p.get("decision_note"):
            argv += ["--notes", p["decision_note"]]
        return argv + ["--project-id", operation["project_id"]] + binding
    if kind == SIGN:
        argv = ["document", "sign", p["revision_id"]]
        if p.get("signed_on"):
            argv += ["--signed-at", moment_argument(p["signed_on"])]
        return argv + ["--project-id", operation["project_id"]] + binding
    if kind in PROCUREMENT_TYPES:
        return ["procurement", "update", operation["project_id"], "--type", PROCUREMENT_TYPES[kind],
                "--external-id", p["reference"]] + binding
    if kind in PROJECT_TARGETS:
        return ["project", "update", operation["project_id"], "--status", PROJECT_TARGETS[kind],
                "--expected-version", str(p["expected_version"])] + binding
    raise ValueError(f"unknown operation {kind!r}")


# -------------------------------------------------------------- operation


def build_operation(kind: str, detail: dict[str, Any], params: dict[str, Any], operator_id: str,
                    database_target: str, holders: Any = (), summary: str = "") -> dict[str, Any]:
    """The confirmable operation of a judged request (raises LifecycleMismatch)."""

    plan = judge(kind, detail, params, holders, operator_id)
    project = dict(detail["project"])
    operation_id = params.get("revision_id") if kind == CREATE_REVISION else (
        params.get("approval_id") if kind == RECORD_DECISION else str(uuid.uuid4()))
    operation = {
        "command": COMMANDS[kind],
        "operation": kind,
        "status": NOT_AUTHORIZED,
        "database_target": database_target,
        "operation_id": operation_id,
        "merchant_id": _text(project["merchant_id"]),
        "merchant_code": project.get("merchant_code"),
        "project_id": _text(project["id"]),
        "project_title": project.get("title"),
        "project_version": project.get("version"),
        "operator_id": operator_id,
        "params": dict(params),
        "plan": plan,
        "summary": summary,
        "expected_basis": basis(kind, detail, params, operator_id, holders),
    }
    operation["argv"] = canonical_argv(operation)
    operation["note"] = OPERATION_NOTE
    validate_operation(operation)
    return operation


def validate_operation(operation: Any) -> None:
    """Raise ValueError unless ``operation`` is one complete canonical operation.

    Rejects truncated, edited, retargeted or reconstructed operations. Never
    grants authority.
    """

    if not isinstance(operation, dict):
        raise ValueError("requested_operation must be an object")
    kind = operation.get("operation")
    if kind not in KINDS or operation.get("command") != COMMANDS[kind]:
        raise ValueError("requested_operation is not a lifecycle operation")
    if operation.get("status") != NOT_AUTHORIZED:
        raise ValueError("requested_operation status must be NOT_AUTHORIZED")
    if operation.get("database_target") not in CONFIRMABLE_TARGETS:
        raise ValueError("requested_operation must target the test database")
    for name in ("operation_id", "merchant_id", "project_id", "operator_id"):
        if not isinstance(operation.get(name), str) or not _UUID.fullmatch(operation[name]):
            raise ValueError(f"requested_operation {name} must be a canonical UUID")
    if operation["operator_id"] == _NIL:
        raise ValueError("requested_operation has no operator")
    if not safe_token(operation.get("merchant_code")):
        raise ValueError("requested_operation merchant_code is not one exact token")
    if not isinstance(operation.get("project_title"), str) or not operation["project_title"]:
        raise ValueError("requested_operation project_title is missing")
    version = operation.get("project_version")
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
        raise ValueError("requested_operation project_version must be a positive integer")
    if not isinstance(operation.get("expected_basis"), str) or not _HEX64.fullmatch(
            operation["expected_basis"]):
        raise ValueError("requested_operation has no valid expected_basis")
    params = operation.get("params")
    if not isinstance(params, dict):
        raise ValueError("requested_operation params are missing")
    _validate_params(kind, params)
    if operation.get("argv") != canonical_argv(operation):
        raise ValueError("requested_operation argv is not the canonical operation")


def _validate_params(kind: str, p: dict[str, Any]) -> None:
    expected = {
        CREATE_REVISION: {"revision_id", "document_type", "effective_date", "expiry_date"},
        # decision_note: the user's own note for this decision, shown back for
        # confirmation (stored approval notes stay redacted in reads).
        RECORD_DECISION: {"revision_id", "approval_id", "role", "decision", "expected_status",
                          "decided_on", "decision_note"},
        SIGN: {"revision_id", "signed_on"},
        PURCHASE_ORDER: {"reference"},
        PAYMENT_REQUEST: {"reference"},
        COMPLETE_PROJECT: {"expected_version"},
        START_PROJECT: {"expected_version"},
    }[kind]
    if set(p) != expected:
        raise ValueError("requested_operation params do not match the operation")
    for name in ("revision_id", "approval_id"):
        if name in p and (not isinstance(p[name], str) or not _UUID.fullmatch(p[name])):
            raise ValueError(f"requested_operation {name} must be a canonical UUID")
    for name in ("effective_date", "expiry_date", "decided_on", "signed_on"):
        if p.get(name) is not None and (not isinstance(p[name], str) or not _DATE.fullmatch(p[name])):
            raise ValueError(f"requested_operation {name} must be YYYY-MM-DD")
    if "document_type" in p and (not isinstance(p["document_type"], str)
                                 or not _TYPE.fullmatch(p["document_type"])):
        raise ValueError("requested_operation document_type is not canonical")
    if "role" in p and (p["role"] not in ROLES or p["decision"] not in DECISIONS
                        or p["expected_status"] not in (None, "PENDING")):
        raise ValueError("requested_operation decision is not canonical")
    if p.get("decision_note") is not None and not valid_notes(p["decision_note"]):
        raise ValueError("requested_operation notes are not plain text")
    if "reference" in p and not safe_token(p["reference"]):
        raise ValueError("requested_operation reference is not one exact token")
    if "expected_version" in p and (not isinstance(p["expected_version"], int)
                                    or isinstance(p["expected_version"], bool)
                                    or p["expected_version"] <= 0):
        raise ValueError("requested_operation expected_version must be a positive integer")


# ------------------------------------------------------- confirmed payloads


def kind_of(command: str, payload: dict[str, Any]) -> str | None:
    """The lifecycle operation a confirmed CLI payload claims, else None."""

    if command == "procurement update":
        procurement_type = str(payload.get("procurement_type") or "").upper()
        return {v: k for k, v in PROCUREMENT_TYPES.items()}.get(procurement_type)
    if command == "project update":
        status = str(payload.get("status") or "").upper()
        return {v: k for k, v in PROJECT_TARGETS.items()}.get(status, COMPLETE_PROJECT)
    return {v: k for k, v in COMMANDS.items() if v != "procurement update"}.get(command)


def is_confirmed_payload(payload: dict[str, Any]) -> bool:
    """A payload that claims a previewed operation (it carries a binding field)."""

    return any(payload.get(name) is not None
               for name in ("expected_basis_hash", "merchant_code", "operator_id"))


def params_from_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The operation params a confirmed CLI payload names (exact, never inferred)."""

    present = {k for k, v in payload.items() if v is not None and v is not False}
    if present - _PAYLOAD_FIELDS[kind] or not all(payload.get(n) is not None for n in _REQUIRED[kind]) \
            or not all(payload.get(n) for n in ("merchant_code", "operator_id", "expected_basis_hash")):
        raise LifecycleMismatch(BASIS_REQUIRED, "only the preview's exact operation can run")
    if kind == CREATE_REVISION:
        params = {"revision_id": str(payload["revision_id"]),
                  "document_type": str(payload["document_type"]),
                  "effective_date": _date_text(payload.get("effective_date")),
                  "expiry_date": _date_text(payload.get("expiry_date"))}
        if payload["content_hash"] != metadata_only_hash(params["revision_id"]):
            raise LifecycleMismatch(BASIS_REQUIRED, "a metadata-only revision carries no content hash")
        return params
    if kind == RECORD_DECISION:
        return {"revision_id": str(payload["document_revision_id"]),
                "approval_id": str(payload["approval_id"]),
                "role": str(payload["approver_role"]).upper(),
                "decision": str(payload["approval_status"]).upper(),
                "expected_status": payload.get("expected_status"),
                "decided_on": _date_text(payload.get("occurred_at")),
                "decision_note": payload.get("notes")}
    if kind == SIGN:
        return {"revision_id": str(payload["document_revision_id"]),
                "signed_on": _date_text(payload.get("signed_at"))}
    if kind in PROCUREMENT_TYPES:
        return {"reference": payload["external_id"]}
    if str(payload.get("status")).upper() != PROJECT_TARGETS[kind]:
        raise LifecycleMismatch(BASIS_REQUIRED, "a confirmed Project update only starts or completes it")
    return {"expected_version": int(payload["expected_version"])}


def argv_from_payload(command: str, payload: dict[str, Any]) -> list[str]:
    """The canonical argv a confirmed payload must have been parsed from."""

    kind = kind_of(command, payload)
    if kind is None:
        raise LifecycleMismatch(BASIS_REQUIRED, "not a lifecycle operation")
    return canonical_argv({
        "operation": kind, "params": params_from_payload(kind, payload),
        "project_id": str(payload["project_id"]), "merchant_code": payload["merchant_code"],
        "operator_id": payload["operator_id"], "expected_basis": payload["expected_basis_hash"],
    })


def verify(reads: Any, command: str, payload: dict[str, Any], operator_id: str) -> dict[str, Any]:
    """Refuse unless the confirmed operation is still valid and matches its preview.

    ``payload`` is the exact confirmed CLI payload and ``operator_id`` the
    trusted operator resolved now. Re-reads the Project (and reference holders),
    re-judges with the domain engines and recomputes the basis. Returns
    ``{"kind", "params", "plan", "project"}``; raises LifecycleMismatch.
    """

    kind = kind_of(command, payload)
    if kind is None:
        raise LifecycleMismatch(BASIS_REQUIRED, "not a lifecycle operation")
    params = params_from_payload(kind, payload)
    if payload["operator_id"] != operator_id:
        raise LifecycleMismatch(OPERATOR_CHANGED)
    detail = reads.get_project_detail(str(payload["project_id"]))
    project = dict(detail["project"])
    if project.get("merchant_code") != payload["merchant_code"]:
        raise LifecycleMismatch(MERCHANT_MISMATCH, "the Project belongs to another Merchant")
    holders = (reads.procurement_reference_holders(
        _text(project["merchant_id"]), PROCUREMENT_TYPES[kind], params["reference"])
        if kind in PROCUREMENT_TYPES else ())
    plan = judge(kind, detail, params, holders, operator_id)
    if basis(kind, detail, params, operator_id, holders) != payload["expected_basis_hash"]:
        raise LifecycleMismatch(BASIS_CHANGED, "the Project changed since the preview")
    return {"kind": kind, "params": params, "plan": plan, "project": project}
