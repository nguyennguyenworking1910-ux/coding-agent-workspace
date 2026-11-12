"""Read-only natural-language evidence write previews (CP12H.NL4D3).

``build_evidence_preview(request, reads, database_target=...)`` answers "what
would happen if this evidence were recorded?" for exactly one of:

- registering a document revision (``document revision-create``);
- recording a LEGAL, ACCOUNTING or PARTNER approval (``document approve``);
- recording a Purchase Request, Purchase Order or Payment Request reference
  (``procurement update``).

The Merchant and Project are bound exactly as NL4A and NL4D2 bind them
(``project_status.resolve_project``); anything ambiguous only asks. The
request is then judged by the domain's own pure engine on the stored
snapshot (``propose_document_revision``, ``propose_document_approval``,
``propose_procurement_mutation``), and an engine refusal is reported with the
engine's own error class. Nothing is re-implemented and no policy is invented:

- an approval the domain accepts still ends POLICY_UNDECIDED, because who may
  attest a LEGAL, ACCOUNTING or PARTNER decision, and how ``acted_by`` is bound
  to that person, is undecided (NL4D1 S1);
- signing has no command (NL4D1 D1) and is never previewed.

CP12H.MASTER (owner-approved DEC-SIMPLIFY, Local Test MVP) supersedes the
POLICY_UNDECIDED and no-signing limits above: on the test database, with a
trusted local operator, a valid request for a metadata-only revision, one
APPROVED or REJECTED decision, operator-attested signing, a Purchase Order, a
Payment Request or Project completion carries a ``lifecycle_operation``
``requested_operation`` (NOT_AUTHORIZED) and ``confirmation_available: true``:
the user may type ``/solve Xác nhận thực hiện <code>``. A recorded decision
names the operator as recorder only; the approver is never inferred.

Nothing is written, reserved, claimed or confirmed: ``read_only`` is always
true, ``executable`` false and ``authorization`` null. A PREVIEW_VALID outcome
is never authority to write. Content hashes and approval notes are never
echoed.

CP12H.NL4D4A: approved policy DEC-P1a (a reference is unique per Merchant and
type) and DEC-P1c (a recorded Purchase Request reference is never replaced)
block such requests on every target. A PREVIEW_VALID *new* Purchase Request
on the test database, judged with a trusted local operator (DEC-A0), also
carries ``requested_operation`` (``purchase_request.build_operation``,
NOT_AUTHORIZED) and ``confirmation_available: true``: the user may type
``/solve Xác nhận ghi nhận``. Everything else carries no operation, and
``confirmation_blockers`` says why. No other evidence write is confirmable.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import date
from typing import Any

from .approval_engine import ApprovalEngineError, propose_document_approval
from .document_engine import DocumentEngineError, propose_document_revision
from .evidence_status import _UUID
from .gates import APPROVER_ROLES
from .procurement_engine import ProcurementEngineError, propose_procurement_mutation
from . import lifecycle_operation as lifecycle
from . import purchase_request
from .project_nl import EVIDENCE_WRITE, fold, interpret_project_request
from .project_status import _summary, _text, resolve_merchant_phrase, resolve_project

MODE = "EVIDENCE_WRITE_PREVIEW"
VALID = "PREVIEW_VALID"
BLOCKED = "BLOCKED"
CLARIFY = "NEEDS_CLARIFICATION"
POLICY_UNDECIDED = "POLICY_UNDECIDED"

REVISION = "REGISTER_DOCUMENT_REVISION"
APPROVAL = "RECORD_APPROVAL"
PROCUREMENT = "RECORD_PROCUREMENT_REFERENCE"
SIGNING = "RECORD_SIGNING"
COMPLETION = "COMPLETE_PROJECT"
STARTING = "START_PROJECT"

# A placeholder id for the engines' "new id" argument. Never output.
_PLACEHOLDER_ID = "00000000-0000-4000-8000-00000000d3d3"

_ROLE_WORDS = (
    ("LEGAL", r"\b(?:legal|phap ly|phap che)\b"),
    ("ACCOUNTING", r"\b(?:accounting|ke toan)\b"),
    ("PARTNER", r"\b(?:partner|doi tac)\b"),
)
# Full names only: a bare "PR" or "PO" is usually code review or a pull request.
_PROCUREMENT_NAMES = (
    ("PURCHASE_REQUEST", r"\b(?:purchase (?:request|requisition)|yeu cau mua hang)\b"),
    ("PURCHASE_ORDER", r"\b(?:purchase order|don dat hang)\b"),
    ("PAYMENT_REQUEST", r"\b(?:payment request|de nghi thanh toan)\b"),
)
_APPROVAL_WORD = (
    r"\b(?:phe duyet|duyet|approvals?|approve|approved|reject(?:ed|ion)?|tu choi)\b"
)
_REJECT_WORD = r"\b(?:reject(?:ed|ion)?|tu choi)\b"
_PENDING_WORD = r"\b(?:yeu cau phe duyet|gui duyet|cho duyet|request(?:ed)? approval|pending)\b"
# A word written as the approver that is not a domain role ("CEO approval",
# "phê duyệt của Giám đốc", "Giám đốc đã phê duyệt").
_ROLE_PHRASES = (
    r"\b(\w+) (?:approvals?|approved|rejection|rejected)\b",
    r"\b(?:approvals?|rejection) (?:from|by) (\w+(?: \w+)?)\b",
    r"\b(?:phe duyet|duyet|tu choi) (?:cua|tu|boi) (\w+(?: \w+)?)\b",
    r"^(\w+(?: \w+)?) (?:da |vua )?(?:phe duyet|duyet|tu choi)\b",
)
_NOT_A_ROLE = frozenset(
    "record register add upload log the a an latest new this that ghi nhan them hay "
    "vui long please document revision tai lieu ho so ban moi nhat cho for to of da "
    "has have not dont don t do khong dung chua s".split()
)
_REVISION_NUMBER = r"\b(?:revision|rev|phien ban|ban)(?: so)? (\d+)\b"
_TYPE_EXPLICIT = r"\b(?:document type|type|loai tai lieu|loai)\s+([a-z][a-z0-9_]*)\b"
_HASH = re.compile(
    r"(?i)\b(?:content[ _-]?hash|hash|checksum|m[aã] b[aă]m)\s*[:=]?\s*([^\s,;]+)"
)
_DATES = (
    ("effective_date", re.compile(r"(?i)(?:effective|hi[eệ]u l[uự]c)\D{0,20}(\d{4}-\d{2}-\d{2})")),
    ("expiry_date", re.compile(r"(?i)(?:expir\w*|h[eế]t h[aạ]n)\D{0,20}(\d{4}-\d{2}-\d{2})")),
)
# CP12H.NL4D3-FIX1: a procurement reference is one whole whitespace-delimited
# token, kept exactly as typed. Safe, documented normalization only: matching
# surrounding quotes or brackets, one leading "#", and trailing sentence
# punctuation (. , ! ? :) are removed, and the token is NFC normalized. A
# token is a reference when it contains a digit and is letters or digits
# joined by - _ / . (Unicode letters allowed). This is an extraction limit,
# not a domain rule: the domain itself only requires non-blank text of at most
# 100 characters. Any other digit-bearing token (shell or SQL metacharacters,
# a dangling separator, an unbalanced quote) or a control character makes the
# reference unsafe; two different references are ambiguous. Both only ask.
_REFERENCE_TOKEN = re.compile(r"^[^\W_](?:[\w./-]*[^\W_])?$")
_ENCLOSURES = {'"': '"', "'": "'", "`": "`", "“": "”", "‘": "’", "«": "»", "(": ")",
               "[": "]", "「": "」"}
_SENTENCE_PUNCTUATION = ".,!?:"
# A bare number counts only after one of these words (folded).
_REFERENCE_ANCHORS = frozenset(
    "so number no ref reference ma id request requisition order hang toan".split()
)
REFERENCE_MISSING = "MISSING"
REFERENCE_AMBIGUOUS = "AMBIGUOUS"
REFERENCE_UNSAFE = "UNSAFE"

_POLICY_ATTESTATION = {
    "code": "APPROVAL_ATTESTATION_POLICY_UNDECIDED",
    "decision": "NL4D-DEC S1",
    "explanation": (
        "No policy defines who may record a LEGAL, ACCOUNTING or PARTNER decision on the "
        "approver's behalf. The domain accepts any writer and stores acted_by unverified."
    ),
}
_POLICY_ACTOR = {
    "code": "APPROVAL_ACTOR_UNBOUND",
    "decision": "NL4D-DEC S1",
    "explanation": (
        "acted_by must be a person's UUID, and no trusted mapping from a request to the "
        "approving person exists, so the approval would carry no verified actor."
    ),
}
_FINALITY = (
    "APPROVED and REJECTED are final (ApprovalFinalizedError): a mistaken decision can only "
    "be replaced by registering a new revision, which supersedes the old approvals."
)
_SOURCES = {
    REVISION: "document_engine.propose_document_revision",
    APPROVAL: "approval_engine.propose_document_approval",
    PROCUREMENT: "procurement_engine.propose_procurement_mutation",
    SIGNING: "signing_engine.propose_document_signing",
    COMPLETION: "project_engine.propose_project_transition",
    STARTING: "project_engine.propose_project_transition",
}
_START_PROJECT = (
    r"\b(?:bat dau|khoi dong|start|begin|kick off)(?: (?:the|toan bo))? (?:project|du an)\b"
)
# CP12H.MASTER: what a signing or Project-completion request says (folded).
_SIGN_WORD = r"\b(?:da ky|ky ket|ky xong|signed|sign|ky)\b"
_COMPLETE_PROJECT = (
    # "đóng" (close), never the "động" of "khởi động" (start): both fold to "dong".
    r"\b(?:hoan tat|hoan thanh|complete|close|(?<!khoi )dong|ket thuc|finish)(?: (?:the|toan bo|ca))? "
    r"(?:project|du an)\b"
)
# Documented alias: the contract is the CONTRACT document type.
_TYPE_ALIASES = ((r"\b(?:hop dong|contract)\b", "CONTRACT"),)
# A stated date (ISO only) and optional notes ("ghi chú: ...", "notes: ...").
_ANY_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_NOTES = re.compile(
    r"(?i)(?:ghi ch[uú]|notes?|l[yý] do|reason)\s*[:：]\s*(?:\"([^\"]+)\"|“([^”]+)”|(.+))$")
_TRAILING_TARGET = re.compile(
    r"(?i)\s*[,.;]?\s*(?:tr[eê]n|on|in|to)\s+(?:the\s+)?(?:database|db|c[ơo] s[ởo] d[ữu] li[ệe]u)"
    r"\s+(?:test|th[ửu] nghi[ệe]m)\s*[.!]?\s*$")


def build_evidence_preview(
    request: str, reads: Any, *, database_target: str | None,
    operator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One read-only evidence write preview for the user's own words.

    ``operator`` is the trusted local operator status
    (``operator_identity.operator_status()``), resolved by the CLI from local
    configuration; absent, no operation is ever produced.
    """

    interpretation = interpret_project_request(request)
    folded = fold(request)
    result: dict[str, Any] = {
        "success": True,
        "mode": MODE,
        "database_target": database_target or "runtime",
        "outcome": CLARIFY,
        "read_only": True,
        "executable": False,
        "confirmation_available": False,
        "authorization": None,
        "requested_operation": None,
        "operation_kind": None,
        "evidence_type": None,
        "merchant_id": None,
        "project_id": None,
        "resolved": {"merchant": None, "project": None},
        "requested_fields": {},
        "missing_required_fields": [],
        "existing_evidence": {},
        "domain_validation": {"status": "NOT_EVALUATED", "engine": None, "error": None,
                              "plan": None},
        "policy_blockers": [],
        "policy_notes": [],
        "recording_operator": None,
        "confirmation_blockers": [],
        "basis": None,
        "basis_sha256": None,
        "candidates": [],
        "clarifications": [],
        "query": {"kind": interpretation.kind, "negated": interpretation.negated,
                  "project_phrase": interpretation.project_phrase,
                  "merchant_phrase": interpretation.merchant_phrase},
    }

    if interpretation.kind != EVIDENCE_WRITE:
        return _ask(result, "This preview covers one document revision, one LEGAL, ACCOUNTING or "
                            "PARTNER decision, signing, one Purchase Request, Purchase Order or "
                            "Payment Request reference, or completing one Project. Which one "
                            "should be previewed?")
    if interpretation.negated or not interpretation.write_requested:
        return _ask(result, "The request says not to record this (or that it has not happened), "
                            "so there is nothing to preview. What should be previewed?")

    # Names are masked so a Project title never supplies a role or a type.
    masked = _masked(folded, interpretation)
    operation, evidence_type, question = _operation(masked)
    result["operation_kind"] = operation
    result["evidence_type"] = evidence_type
    if question:
        return _ask(result, question)

    fields, missing, merchant_phrase = _requested_fields(
        request, folded, masked, operation, evidence_type, interpretation)
    # The hash itself is sensitive (SENSITIVE_FIELD_NAMES): never in the result.
    content_hash = fields.pop("_content_hash", None)
    result["requested_fields"] = fields
    if fields.get("unsupported_role"):
        return _block(result, "UNSUPPORTED_APPROVAL_ROLE",
                      f"{fields['unsupported_role']!r} is not an approver role; the domain "
                      f"supports {', '.join(sorted(APPROVER_ROLES))} (gates.APPROVER_ROLES).")
    if fields.get("roles_named", 0) > 1:
        return _ask(result, "One approval is previewed at a time: which role, LEGAL, ACCOUNTING "
                            "or PARTNER?")

    # ------------------------------------------------------------ identity
    merchant = None
    if merchant_phrase:
        merchant, question = resolve_merchant_phrase(reads, merchant_phrase, exact=True)
        if merchant is None:
            return _ask(result, question)
        result["resolved"]["merchant"] = merchant
    project_uuid = _UUID.search(request)
    project, match_kind, candidates, question = resolve_project(
        reads, merchant, project_uuid.group().lower() if project_uuid else None,
        interpretation.project_phrase)
    if project is None:
        result["candidates"] = candidates
        return _ask(result, question)

    detail = reads.get_project_detail(_text(project["id"]))
    stored = dict(detail["project"])
    result["project_id"] = _text(stored["id"])
    result["merchant_id"] = _text(stored.get("merchant_id"))
    result["resolved"]["project"] = {
        **_summary(project),
        "version": stored.get("version"),
        "requires_procurement": stored.get("requires_procurement"),
        "match_kind": match_kind,
    }
    if result["resolved"]["merchant"] is None:
        result["resolved"]["merchant"] = {
            "merchant_id": result["merchant_id"],
            "code": project.get("merchant_code"),
            "name": project.get("merchant_name"),
            "match_kind": "FROM_PROJECT",
        }

    revisions = [dict(r) for r in detail.get("document_revisions") or []]
    approvals = [dict(a) for a in detail.get("document_approvals") or []]
    records = [dict(r) for r in detail.get("procurement_records") or []]
    revision_ids = {_text(r["id"]) for r in revisions}
    approvals = [a for a in approvals if _text(a.get("document_revision_id")) in revision_ids]

    if operation in (REVISION, APPROVAL, SIGNING) and fields.get("document_type") is None:
        # A stored document type written whole in the request binds; nothing is inferred.
        written = sorted({str(r["document_type"]).upper() for r in revisions
                          if re.search(rf"\b{re.escape(str(r['document_type']).lower())}\b", masked)})
        if len(written) == 1:
            fields["document_type"] = written[0]
            if "document_type" in missing:
                missing.remove("document_type")

    # The recording operator is shown for every confirmable write.
    result["recording_operator"] = dict(operator) if operator else {
        "status": "OPERATOR_IDENTITY_NOT_RESOLVED", "operator_id": None}

    # CP12H.MASTER-FIX: the signed revision bound at Project creation, if any.
    reused = (lifecycle.reused_revision(reads, detail)
              if stored.get("reused_document_revision_id") is not None
              and hasattr(reads, "list_reusable_revisions") else None)
    if operation == PROCUREMENT:
        _procurement(result, reads, stored, revisions, records, fields, missing, reused)
        if fields.get("procurement_type") == "PURCHASE_REQUEST":
            _purchase_request_operation(result, reads, detail, fields, operator)
        elif not missing and result["outcome"] == VALID:
            kind = (lifecycle.PURCHASE_ORDER if fields["procurement_type"] == "PURCHASE_ORDER"
                    else lifecycle.PAYMENT_REQUEST)
            reference = fields["external_reference"]
            holders = reads.procurement_reference_holders(
                _text(stored["merchant_id"]), fields["procurement_type"], reference)
            _lifecycle_operation(result, kind, detail, {"reference": reference}, holders,
                                 f"record {fields['procurement_type'].replace('_', ' ').title()} "
                                 f"{reference}", reused=reused)
    elif operation == REVISION:
        _revision(result, stored, revisions, fields, missing, content_hash)
        if result["outcome"] == VALID:
            _lifecycle_operation(result, lifecycle.CREATE_REVISION, detail, {
                "revision_id": result["domain_validation"].pop("_revision_id"),
                "document_type": fields["document_type"],
                "effective_date": fields.get("effective_date"),
                "expiry_date": fields.get("expiry_date"),
            }, (), f"create metadata-only {fields['document_type']} revision "
                  f"{result['domain_validation']['plan'].get('revision_number')} (no file)")
    elif operation == SIGNING:
        _signing(result, detail, revisions, fields)
    elif operation == COMPLETION:
        _completion(result, detail)
    elif operation == STARTING:
        _starting(result, detail)
    else:
        _approval(result, stored, revisions, approvals, fields, missing)
        if result["outcome"] == VALID:
            target = result["existing_evidence"]["revision"]
            current = result["existing_evidence"]["approval"]
            _lifecycle_operation(result, lifecycle.RECORD_DECISION, detail, {
                "revision_id": target["revision_id"],
                "approval_id": result["domain_validation"].pop("_approval_id"),
                "role": fields["approver_role"],
                "decision": fields["approval_status"],
                "expected_status": "PENDING" if current else None,
                "decided_on": fields.get("decided_on"),
                "decision_note": fields.get("decision_note"),
            }, (), f"record {fields['approver_role']} {fields['approval_status']} on "
                  f"{target['document_type']} revision {target['revision_number']}")
    return result


# ------------------------------------------------------------- the request


def _masked(folded, interpretation):
    text = f" {folded} "
    for phrase in (interpretation.project_phrase, interpretation.merchant_phrase):
        if phrase:
            text = text.replace(f" {fold(phrase)} ", " ")
    return " ".join(text.split())


def _operation(masked):
    """(operation, evidence type, question or None)."""

    # CP12H.MASTER: completing the Project itself (never a Step: a step noun
    # makes it a Step Update upstream), then operator-attested signing.
    if re.search(_COMPLETE_PROJECT, masked) and not re.search(r"\b(?:buoc|step)\b", masked):
        return COMPLETION, "PROJECT_COMPLETION", None
    if re.search(_START_PROJECT, masked) and not re.search(r"\b(?:buoc|step)\b", masked):
        return STARTING, "PROJECT_START", None
    types = [kind for kind, pattern in _PROCUREMENT_NAMES if re.search(pattern, masked)]
    if len(types) > 1:
        return PROCUREMENT, None, ("One procurement reference is previewed at a time: Purchase "
                                   "Request, Purchase Order or Payment Request?")
    if types:
        return PROCUREMENT, types[0], None
    if re.search(_SIGN_WORD, masked) and not re.search(_APPROVAL_WORD, masked):
        return SIGNING, "OPERATOR_ATTESTED_SIGNING", None
    if re.search(_APPROVAL_WORD, masked):
        roles = [role for role, pattern in _ROLE_WORDS if re.search(pattern, masked)]
        return APPROVAL, f"{roles[0]}_APPROVAL" if len(roles) == 1 else None, None
    return REVISION, "DOCUMENT_REVISION", None


def _requested_fields(request, folded, masked, operation, evidence_type, interpretation):
    """(fields as written, missing required fields, Merchant phrase to resolve)."""

    fields: dict[str, Any] = {}
    missing: list[str] = []
    merchant_phrase = interpretation.merchant_phrase

    if operation == PROCUREMENT:
        reference, problem = _reference(request, interpretation)
        fields["procurement_type"] = evidence_type
        fields["external_reference"] = reference
        if problem is not None:
            fields["reference_problem"] = problem
            missing.append("external_reference")
    elif operation == APPROVAL:
        roles = [role for role, pattern in _ROLE_WORDS if re.search(pattern, masked)]
        fields["approver_role"] = roles[0] if len(roles) == 1 else None
        fields["roles_named"] = len(roles)
        fields["approval_status"] = (
            "REJECTED" if re.search(_REJECT_WORD, masked)
            else "PENDING" if re.search(_PENDING_WORD, masked) else "APPROVED"
        )
        number = re.search(_REVISION_NUMBER, masked)
        fields["revision_reference"] = int(number.group(1)) if number else "LATEST"
        fields["document_type"] = _explicit_type(masked, request)
        fields["actor"] = None
        # CP12H.MASTER: optional decision date and notes, as written.
        fields["decided_on"], fields["date_problem"] = _stated_date(request)
        fields["decision_note"] = _notes(request)
        if not roles:
            unsupported = _unsupported_role(folded)
            if unsupported:
                fields["unsupported_role"] = unsupported
            else:
                missing.append("approver_role")
        # "phê duyệt của Giám đốc": the owner phrase names the approver, not a Merchant.
        if merchant_phrase and (
            fields.get("unsupported_role") == fold(merchant_phrase)
            or any(re.search(p, fold(merchant_phrase)) for _, p in _ROLE_WORDS)
        ):
            merchant_phrase = None
    elif operation == SIGNING:
        fields["document_type"] = _explicit_type(masked, request)
        number = re.search(_REVISION_NUMBER, masked)
        fields["revision_reference"] = int(number.group(1)) if number else "LATEST"
        fields["signed_on"], fields["date_problem"] = _stated_date(request)
    elif operation in (COMPLETION, STARTING):
        pass
    else:
        fields["document_type"] = _explicit_type(masked, request)
        hashed = _HASH.search(request)
        fields["content_hash_provided"] = hashed is not None
        for name, pattern in _DATES:
            found = pattern.search(request)
            fields[name] = found.group(1) if found else None
        if fields["document_type"] is None:
            missing.append("document_type")
        # CP12H.MASTER: a revision is metadata-only (no file); a typed hash
        # cannot be verified and is never stored.
        fields["_content_hash"] = hashed.group(1) if hashed else None
    return fields, missing, merchant_phrase


def _reference(request, interpretation):
    """(the one reference written outside every Project or Merchant name, None),
    or (None, MISSING | AMBIGUOUS | UNSAFE). Never shortened or rebuilt."""

    if any(unicodedata.category(c) == "Cc" and c not in "\t\n\r" for c in request):
        return None, REFERENCE_UNSAFE
    text = request
    for phrase in (interpretation.project_phrase, interpretation.merchant_phrase):
        if phrase:
            text = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
    text = _UUID.sub(" ", text)

    found: list[str] = []
    previous = ""
    for raw in text.split():
        token = _unwrapped(raw)
        if any(c.isdigit() for c in token):
            if not _REFERENCE_TOKEN.fullmatch(token):
                return None, REFERENCE_UNSAFE
            # A bare number ("năm 2026") is a reference only after a keyword
            # or the record's own name ("số 2026001", "Purchase Request 2026001").
            if not token.isdigit() or previous in _REFERENCE_ANCHORS or raw.startswith("#"):
                found.append(token)
        previous = fold(raw)
    distinct = set(found)
    if not distinct:
        return None, REFERENCE_MISSING
    if len(distinct) > 1:
        return None, REFERENCE_AMBIGUOUS
    return distinct.pop(), None


def _unwrapped(raw):
    """The token without its documented enclosures and sentence punctuation, NFC."""

    token = raw
    while True:
        before = token
        token = token.rstrip(_SENTENCE_PUNCTUATION)
        if len(token) >= 2 and _ENCLOSURES.get(token[0]) == token[-1]:
            token = token[1:-1]
        if token.startswith("#"):
            token = token[1:]
        if token == before:
            return unicodedata.normalize("NFC", token)


def _explicit_type(masked, request=""):
    found = re.search(_TYPE_EXPLICIT, masked)
    if found:
        return found.group(1).upper()
    # "a new CONTRACT revision": an uppercase type written beside the noun.
    found = re.search(r"\b([A-Z][A-Z0-9_]{2,})\s+(?:revision|document)\b", request)
    if found:
        return found.group(1)
    # CP12H.MASTER: documented aliases ("hợp đồng", "contract" -> CONTRACT).
    aliases = {name for pattern, name in _TYPE_ALIASES if re.search(pattern, masked)}
    return aliases.pop() if len(aliases) == 1 else None


def _stated_date(request):
    """(the one ISO date written, None) or (None, AMBIGUOUS); never inferred."""

    dates = set(_ANY_DATE.findall(request))
    if len(dates) > 1:
        return None, REFERENCE_AMBIGUOUS
    return (dates.pop() if dates else None), None


def _notes(request):
    """Optional notes after "ghi chú:" / "notes:", exactly as written."""

    found = _NOTES.search(request.strip())
    if not found:
        return None
    text = next(group for group in found.groups() if group is not None)
    text = _TRAILING_TARGET.sub("", text).strip().strip("\"“”'")
    return text or None


def _unsupported_role(folded):
    for pattern in _ROLE_PHRASES:
        for found in re.finditer(pattern, folded):
            words = [w for w in found.group(1).split() if w not in _NOT_A_ROLE]
            if words:
                return " ".join(words)
    return None


# ------------------------------------------------------------- operations


def _procurement(result, reads, project, revisions, records, fields, missing, reused=None):
    kind = fields["procurement_type"]
    record = next((r for r in records if str(r.get("procurement_type")).upper() == kind), None)
    signed = [r for r in revisions if r.get("superseded_by") is None and r.get("signed")]
    result["existing_evidence"] = {
        "record": None if record is None else {
            "procurement_id": _text(record["id"]),
            "external_id": record.get("external_id"),
            "status": record.get("status"),
            "version": record.get("version"),
        },
        "requires_procurement": bool(project.get("requires_procurement")),
        "purchase_request_number_recorded": any(
            str(r.get("procurement_type")).upper() == "PURCHASE_REQUEST" and r.get("external_id")
            for r in records),
        "purchase_order_number_recorded": any(
            str(r.get("procurement_type")).upper() == "PURCHASE_ORDER" and r.get("external_id")
            for r in records),
        "signed_active_revision": bool(signed),
    }
    if kind == "PURCHASE_REQUEST" and not project.get("requires_procurement"):
        result["policy_notes"].append({
            "code": "PROCUREMENT_NOT_REQUIRED",
            "explanation": "This Project does not require procurement; the domain still "
                           "accepts a Purchase Request record, and no gate checks it.",
        })
    _basis(result, project, record=record)
    if not missing:
        # CP12H.NL4D4A: approved DEC-P1a / DEC-P1c, before the engine.
        holders = reads.procurement_reference_holders(
            _text(project["merchant_id"]), kind, fields["external_reference"])
        blocker = purchase_request.reference_blocker(
            _text(project["id"]), record, fields["external_reference"], holders)
        if blocker is not None:
            return _block(result, *blocker)
        if record is not None and kind != "PURCHASE_REQUEST":
            # CP12H.MASTER: create-only, never a replacement.
            return _block(result, lifecycle.RECORD_EXISTS,
                          "This Project already has this record; replacing a recorded "
                          "reference is not supported.")
    if missing:
        result["missing_required_fields"] = missing
        name = kind.replace("_", " ").title()
        return _ask(result, {
            REFERENCE_AMBIGUOUS: f"The request names more than one possible {name} reference. "
                                 "Which single reference should be recorded?",
            REFERENCE_UNSAFE: f"The {name} reference could not be read exactly (it contains "
                              "spaces, symbols or control characters). Write it once, as one "
                              "word, for example PR-2026-001.",
        }.get(fields.get("reference_problem"),
              f"Which {name} number or reference should be recorded?"))
    if reused is not None:
        from .document_reuse import summary

        result["existing_evidence"]["reused_document"] = summary(reused)
    _judge(result, PROCUREMENT, lambda: propose_procurement_mutation(
        {"project": project, "procurement_records": records, "document_revisions": revisions,
         "reused_document_revision": reused},
        procurement_id=_PLACEHOLDER_ID, procurement_type=kind,
        external_id=fields["external_reference"],
        # Recording a reference keeps the stored status: an update writes
        # plan.status as given, so None would clear it.
        status=record.get("status") if record else None,
        expected_version=record.get("version") if record else None,
    ), plan_fields=("operation", "procurement_type", "external_id", "status", "current_status",
                    "current_version", "new_version", "event_type"))


def _purchase_request_operation(result, reads, detail, fields, operator):
    """CP12H.NL4D4A: the confirmable operation of a valid new Purchase Request."""

    if fields.get("procurement_type") != "PURCHASE_REQUEST":
        return
    result["recording_operator"] = dict(operator) if operator else {
        "status": "OPERATOR_IDENTITY_NOT_RESOLVED", "operator_id": None}
    if result["outcome"] != VALID:
        return
    blockers = result["confirmation_blockers"]
    if result["database_target"] not in purchase_request.CONFIRMABLE_TARGETS:
        blockers.append("RUNTIME_EXECUTION_DISABLED")
    if result["domain_validation"]["plan"].get("operation") != "INSERT":
        blockers.append(purchase_request.RECORD_EXISTS)
    if result["recording_operator"]["status"] != "TRUSTED":
        blockers.append(result["recording_operator"]["status"])
    if blockers:
        return
    reference = fields["external_reference"]
    project = detail["project"]
    holders = reads.procurement_reference_holders(
        _text(project["merchant_id"]), "PURCHASE_REQUEST", reference)
    result["requested_operation"] = purchase_request.build_operation(
        detail, reference, holders, result["recording_operator"]["operator_id"],
        result["database_target"])
    result["confirmation_available"] = True


def _revision(result, project, revisions, fields, missing, content_hash):
    stored_types = sorted({str(r["document_type"]).upper() for r in revisions})
    active = [r for r in revisions if r.get("superseded_by") is None]
    result["existing_evidence"] = {
        "active_revisions": [_revision_summary(r) for r in active],
        "document_types": stored_types,
    }
    result["policy_notes"].append({
        "code": "METADATA_ONLY_REVISION",
        "explanation": "The revision is recorded without a file (METADATA_ONLY): it carries no "
                       "file or integrity evidence. Uploading a file is optional and separate.",
    })
    _basis(result, project, revisions=active)
    if content_hash is not None:
        return _block(result, "CONTENT_HASH_NOT_ACCEPTED",
                      "A typed content hash cannot be verified, so it is never recorded. Remove "
                      "it: the revision is recorded as metadata only (no file).")
    if missing:
        result["missing_required_fields"] = missing
        result["candidates"] = [{"document_type": t} for t in stored_types]
        return _ask(result, "Which document type (for example CONTRACT) should the new "
                            "revision have?")
    dates = {}
    for name in ("effective_date", "expiry_date"):
        try:
            dates[name] = date.fromisoformat(fields[name]) if fields[name] else None
        except ValueError:
            return _block(result, "DocumentEngineError", f"{name} is not a valid date.")
    signed_active = [r for r in active if r.get("signed")
                     and str(r.get("document_type")).upper() == fields["document_type"]]
    if signed_active:
        return _block(result, lifecycle.SIGNED_REVISION,
                      "The active revision of this type is signed and is not superseded "
                      "(DEC-D4e).")
    revision_id = str(uuid.uuid4())
    if _judge(result, REVISION, lambda: propose_document_revision(
        {"project": project, "revisions": revisions},
        revision_id=revision_id, document_type=fields["document_type"],
        content_hash=lifecycle.metadata_only_hash(revision_id), **dates,
    ), plan_fields=("document_type", "revision_number", "previous_revision_id",
                    "previous_revision_number", "event_type")):
        result["domain_validation"]["_revision_id"] = revision_id


def _lifecycle_operation(result, kind, detail, params, holders, summary, reused=None):
    """CP12H.MASTER: the confirmable operation of a valid request, or why not."""

    blockers = result["confirmation_blockers"]
    if result["database_target"] not in lifecycle.CONFIRMABLE_TARGETS:
        blockers.append("RUNTIME_EXECUTION_DISABLED")
    if result["recording_operator"]["status"] != "TRUSTED":
        blockers.append(result["recording_operator"]["status"])
    if blockers:
        return
    try:
        operation = lifecycle.build_operation(
            kind, detail, params, result["recording_operator"]["operator_id"],
            result["database_target"], holders, summary, reused)
    except lifecycle.LifecycleMismatch as error:
        _block(result, error.reason, error.detail or error.reason)
        return
    result["requested_operation"] = operation
    result["confirmation_available"] = True


def _target_revision(result, revisions, fields):
    """The one revision a signing request names (latest active by default)."""

    kind, reference = fields.get("document_type"), fields.get("revision_reference", "LATEST")
    candidates = [r for r in revisions if kind is None or str(r["document_type"]).upper() == kind]
    if reference == "LATEST":
        candidates = [r for r in candidates if r.get("superseded_by") is None]
    else:
        candidates = [r for r in candidates if r.get("revision_number") == reference]
    if len(candidates) != 1:
        result["candidates"] = [_revision_summary(r) for r in candidates
                                or [r for r in revisions if r.get("superseded_by") is None]]
        _ask(result, "Which document revision was signed? Name its document type (for example "
                     "CONTRACT) or revision number.")
        return None
    return candidates[0]


def _signing(result, detail, revisions, fields):
    project = detail["project"]
    active = [r for r in revisions if r.get("superseded_by") is None]
    result["existing_evidence"] = {"active_revisions": [_revision_summary(r) for r in active]}
    result["policy_notes"].append({
        "code": "OPERATOR_ATTESTED_SIGNED",
        "explanation": "Signing is recorded as attested by the trusted local operator "
                       "(OPERATOR_ATTESTED_SIGNED). No signed file, signatory or cryptographic "
                       "signature is verified.",
    })
    if not revisions:
        return _block(result, "MISSING_DOCUMENT_REVISION",
                      "No document revision exists, so there is nothing to sign.")
    if fields.get("date_problem"):
        return _ask(result, "The request names more than one date: which one is the signing "
                            "date (YYYY-MM-DD)?")
    target = _target_revision(result, revisions, fields)
    if target is None:
        return result
    result["existing_evidence"]["revision"] = _revision_summary(target)
    _basis(result, project, revisions=[target])
    params = {"revision_id": _text(target["id"]), "signed_on": fields.get("signed_on")}
    try:
        plan = lifecycle.judge(lifecycle.SIGN, detail, params)
    except lifecycle.LifecycleMismatch as error:
        result["domain_validation"]["engine"] = _SOURCES[SIGNING]
        return _block(result, error.reason, error.detail or error.reason)
    result["domain_validation"].update(status="VALID", engine=_SOURCES[SIGNING], plan=plan)
    result["outcome"] = VALID
    _lifecycle_operation(result, lifecycle.SIGN, detail, params, (),
                         f"record {target['document_type']} revision {target['revision_number']} "
                         "as signed (operator-attested)")
    return result


def _completion(result, detail):
    project = detail["project"]
    steps = [dict(s) for s in detail.get("steps") or []]
    finals = lifecycle.final_step_ids(detail)
    result["existing_evidence"] = {
        "project_status": project.get("status"),
        "step_counts": {status: sum(1 for s in steps if s.get("status") == status)
                        for status in sorted({str(s.get("status")) for s in steps})},
        "unfinished_steps": [
            {"step_id": _text(s["id"]), "sequence": s.get("sequence_number"),
             "name": s.get("step_name"), "status": s.get("status")}
            for s in sorted(steps, key=lambda s: s.get("sequence_number") or 0)
            if str(s.get("status")) not in ("COMPLETED", "SKIPPED", "SUPERSEDED")],
        "final_steps": [{"step_id": _text(s["id"]), "name": s.get("step_name"),
                         "status": s.get("status")} for s in steps if _text(s["id"]) in finals],
    }
    _basis(result, project)
    params = {"expected_version": project.get("version")}
    try:
        plan = lifecycle.judge(lifecycle.COMPLETE_PROJECT, detail, params)
    except lifecycle.LifecycleMismatch as error:
        result["domain_validation"]["engine"] = _SOURCES[COMPLETION]
        return _block(result, error.reason, error.detail or error.reason)
    result["domain_validation"].update(status="VALID", engine=_SOURCES[COMPLETION], plan=plan)
    result["outcome"] = VALID
    _lifecycle_operation(result, lifecycle.COMPLETE_PROJECT, detail, params, (),
                         "complete the Project")
    return result


def _starting(result, detail):
    project = detail["project"]
    result["existing_evidence"] = {"project_status": project.get("status")}
    _basis(result, project)
    params = {"expected_version": project.get("version")}
    try:
        plan = lifecycle.judge(lifecycle.START_PROJECT, detail, params)
    except lifecycle.LifecycleMismatch as error:
        result["domain_validation"]["engine"] = _SOURCES[STARTING]
        return _block(result, error.reason, error.detail or error.reason)
    result["domain_validation"].update(status="VALID", engine=_SOURCES[STARTING], plan=plan)
    result["outcome"] = VALID
    _lifecycle_operation(result, lifecycle.START_PROJECT, detail, params, (), "start the Project")
    return result


def _approval(result, project, revisions, approvals, fields, missing):
    role = fields["approver_role"]
    active = [r for r in revisions if r.get("superseded_by") is None]
    reference, kind = fields["revision_reference"], fields["document_type"]
    candidates = [r for r in revisions if kind is None or str(r["document_type"]).upper() == kind]
    if reference == "LATEST":
        candidates = [r for r in candidates if r.get("superseded_by") is None]
    else:
        candidates = [r for r in candidates if r.get("revision_number") == reference]

    result["existing_evidence"] = {"active_revisions": [_revision_summary(r) for r in active]}
    if missing:
        result["missing_required_fields"] = missing
        return _ask(result, "Whose approval should be previewed: LEGAL, ACCOUNTING or PARTNER?")
    if fields["approval_status"] not in lifecycle.DECISIONS:
        return _block(result, "DECISION_REQUIRED",
                      "Only a final APPROVED or REJECTED decision is recorded; a pending "
                      "request for approval is not.")
    if fields.get("date_problem"):
        return _ask(result, "The request names more than one date: which one is the decision "
                            "date (YYYY-MM-DD)?")
    if not revisions:
        return _block(result, "MISSING_DOCUMENT_REVISION",
                      "No document revision exists, so there is nothing to approve.")
    if len(candidates) != 1:
        result["candidates"] = [_revision_summary(r) for r in candidates or active]
        return _ask(result, "Which revision should be approved? Name its document type "
                            "(for example CONTRACT) or revision number.")

    target = candidates[0]
    current = next((a for a in approvals
                    if _text(a.get("document_revision_id")) == _text(target["id"])
                    and str(a.get("approver_role")).upper() == role), None)
    result["existing_evidence"].update({
        "revision": _revision_summary(target),
        "approval": None if current is None else {
            "status": current.get("approval_status"),
            "approved_at": _text(current.get("approved_at")),
        },
        "outdated_approvals": [
            {"revision_number": r.get("revision_number"), "status": a.get("approval_status")}
            for r in revisions if r.get("superseded_by") is not None
            for a in approvals
            if _text(a.get("document_revision_id")) == _text(r["id"])
            and str(a.get("approver_role")).upper() == role
        ],
    })
    _basis(result, project, revisions=[target], approval=current)
    approval_id = str(uuid.uuid4())
    if _judge(result, APPROVAL, lambda: propose_document_approval(
        {"project": project, "revisions": revisions, "approvals": approvals},
        document_revision_id=_text(target["id"]), approval_id=approval_id,
        approver_role=role, approval_status=fields["approval_status"],
        expected_status=current.get("approval_status") if current else None,
    ), plan_fields=("operation", "approver_role", "document_type", "revision_number",
                    "current_status", "target_status", "event_type")):
        # CP12H.MASTER (DEC-SIMPLIFY): the operator records the decision; the
        # approver is not identified and never inferred.
        result["domain_validation"]["finality"] = _FINALITY
        result["domain_validation"]["_approval_id"] = approval_id
        result["policy_notes"].append({
            "code": "OPERATOR_RECORDED_DECISION",
            "explanation": "The trusted local operator records this decision on the "
                           "approver's behalf; the approver is not identified or verified.",
        })


# ---------------------------------------------------------------- helpers


def _judge(result, operation, propose, *, plan_fields):
    """Run the domain engine; True when it accepts the request."""

    validation = result["domain_validation"]
    validation["engine"] = _SOURCES[operation]
    try:
        plan = propose().to_dict()
    except (DocumentEngineError, ApprovalEngineError, ProcurementEngineError) as error:
        if "document_type is required" in str(error):
            result["missing_required_fields"] = ["document_type"]
            _ask(result, "The Project has several active document types: which one?")
        else:
            _block(result, type(error).__name__, str(error))
        return False
    validation["status"] = "VALID"
    validation["plan"] = {name: plan.get(name) for name in plan_fields}
    result["outcome"] = VALID
    return True


def _revision_summary(revision):
    return {
        "revision_id": _text(revision.get("id")),
        "document_type": revision.get("document_type"),
        "revision_number": revision.get("revision_number"),
        "signed": bool(revision.get("signed")),
        "superseded": revision.get("superseded_by") is not None,
    }


def _basis(result, project, *, revisions=(), approval=None, record=None):
    """What the preview judged. Descriptive only: never authority."""

    basis = {
        "project_id": _text(project.get("id")),
        "project_status": project.get("status"),
        "project_version": project.get("version"),
        "revisions": [_revision_summary(r) for r in revisions],
        "approval_status": approval.get("approval_status") if approval else None,
        "procurement_version": record.get("version") if record else None,
    }
    result["basis"] = basis
    result["basis_sha256"] = hashlib.sha256(
        json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()


def _block(result, code, message):
    result["outcome"] = BLOCKED
    result["domain_validation"]["status"] = "INVALID"
    result["domain_validation"]["error"] = {"code": code, "message": message}
    return result


def _ask(result, question):
    result["outcome"] = CLARIFY
    result["clarifications"] = [question] if question else []
    return result
