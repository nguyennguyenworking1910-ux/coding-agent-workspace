"""Read-only natural-language evidence and approval discovery (CP12H.NL4D2).

``build_evidence_status(request, reads, database_target=...)`` answers "what
evidence does this Project (or this step) have, and what does it still lack?"
from stored rows and the domain's own evaluators only:

- the Merchant and Project are bound exactly as NL4A binds them
  (``project_status.resolve_project``); anything ambiguous only asks;
- a step, when named, is bound by number, exact title, or a unique partial
  title; several matches only ask;
- every gate is evaluated by ``gate_resolver.resolve_database_gate``, exactly
  as ``transition_repository.transition_step`` evaluates it; a gate with no
  database evaluator is reported as such and never as satisfiable;
- an approval counts only on the revision the gate judges (the latest active
  one); approvals on superseded revisions are reported as outdated, never as
  approval of the latest revision.

Nothing is written, reserved, claimed or confirmed: ``read_only`` is always
true, ``executable`` and ``confirmation_available`` false, ``authorization``
null, and no operation, argv or command is produced. Document content hashes
and approval notes are never included.

Classification. ``status`` says what is stored: PRESENT, MISSING, INVALID
(stored but cannot count: rejected, superseded, or a record without its
number) or UNKNOWN (the domain refused to judge the snapshot).
``requirement`` says whether an open gate needs it: REQUIRED, NOT_REQUIRED or
UNKNOWN. Requirements come only from gate evaluations; nothing else is
inferred.
"""

from __future__ import annotations

import re
from typing import Any

from .dependencies import evaluate_dependency_readiness
from .gate_resolver import (
    DatabaseGateResolutionError,
    database_gate_kind,
    is_approval_gate,
    resolve_database_gate,
)
from .gates import (
    APPROVER_ROLES,
    GateValidationError,
    evaluate_approval_gate,
    latest_document_revision,
)
from .procurement_engine import PROCUREMENT_TYPES
from .project_nl import EVIDENCE_STATUS, fold, interpret_project_request
from .project_status import _step, _summary, _text, resolve_merchant_phrase, resolve_project
from .step_entity_resolver import StepMatchKind, StepResolutionStatus, resolve_step_entity
from .step_preview import _written_title

MODE = "EVIDENCE_STATUS"
STATUS = "EVIDENCE_STATUS"
CLARIFY = "NEEDS_CLARIFICATION"

PRESENT = "PRESENT"
MISSING = "MISSING"
INVALID = "INVALID"
UNKNOWN = "UNKNOWN"
REQUIRED = "REQUIRED"
NOT_REQUIRED = "NOT_REQUIRED"

GATE_MET = "MET"
GATE_NOT_MET = "NOT_MET"
GATE_CLOSED = "CLOSED"
GATE_NO_EVALUATOR = "NO_DATABASE_EVALUATOR"

_TERMINAL = ("COMPLETED", "SKIPPED", "SUPERSEDED")
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
# What the question names (folded); used only to narrow the answer.
_ROLE_WORDS = (
    ("LEGAL", r"\b(?:legal|phap ly|phap che)\b"),
    ("ACCOUNTING", r"\b(?:accounting|ke toan)\b"),
    ("PARTNER", r"\bpartner\b"),
)
_PROCUREMENT_WORDS = (
    ("PURCHASE_REQUEST", r"\b(?:purchase (?:request|requisition)s?|yeu cau mua hang|pr)\b"),
    ("PURCHASE_ORDER", r"\b(?:purchase orders?|don dat hang|po)\b"),
    ("PAYMENT_REQUEST", r"\b(?:payment requests?|de nghi thanh toan)\b"),
)
_SOURCES = {
    "gate": "gate_resolver.resolve_database_gate (as transition_repository.transition_step)",
    "approval": "gates.evaluate_approval_gate / gates.latest_document_revision",
    "dependencies": "dependencies.evaluate_dependency_readiness",
    "procurement": "gates.evaluate_signing_gate (Purchase Request); stored procurement_records",
}


def build_evidence_status(request: str, reads: Any, *, database_target: str | None) -> dict[str, Any]:
    """One read-only evidence and approval answer for the user's own words."""

    interpretation = interpret_project_request(request)
    folded = fold(request)
    project_uuid = _UUID.search(request)
    result: dict[str, Any] = {
        "success": True,
        "mode": MODE,
        "database_target": database_target or "runtime",
        "outcome": CLARIFY,
        "read_only": True,
        "executable": False,
        "confirmation_available": False,
        "authorization": None,
        "query": {
            "kind": interpretation.kind,
            "merchant_phrase": interpretation.merchant_phrase,
            "project_phrase": interpretation.project_phrase,
            "project_id": project_uuid.group().lower() if project_uuid else None,
            "step_reference": interpretation.step_reference,
            "roles": [role for role, pattern in _ROLE_WORDS if re.search(pattern, folded)],
            "procurement_types": [
                kind for kind, pattern in _PROCUREMENT_WORDS if re.search(pattern, folded)
            ],
        },
        "merchant": None,
        "project": None,
        "focus_step": None,
        "documents": [],
        "approvals": [],
        "outdated_approvals": [],
        "procurement": [],
        "gates": [],
        "missing": [],
        "sources": _SOURCES,
        "candidates": [],
        "clarifications": [],
    }

    if interpretation.kind != EVIDENCE_STATUS:
        return _ask(result, "Is this a question about one Project's documents, approvals or "
                            "procurement records? Which Project?")

    merchant = None
    if interpretation.merchant_phrase:
        merchant, question = resolve_merchant_phrase(reads, interpretation.merchant_phrase)
        if merchant is None:
            return _ask(result, question)
        result["merchant"] = merchant

    project, match_kind, candidates, question = resolve_project(
        reads, merchant, result["query"]["project_id"], interpretation.project_phrase
    )
    if project is None:
        result["candidates"] = candidates
        return _ask(result, question)

    detail = reads.get_project_detail(_text(project["id"]))
    stored = dict(detail["project"])
    steps = detail.get("steps") or []
    result["project"] = {
        **_summary(project),
        "version": stored.get("version"),
        "requires_procurement": stored.get("requires_procurement"),
        "match_kind": match_kind,
    }
    if result["merchant"] is None:
        result["merchant"] = {
            "merchant_id": _text(project["merchant_id"]),
            "code": project.get("merchant_code"),
            "name": project.get("merchant_name"),
            "match_kind": "FROM_PROJECT",
        }

    focus = None
    reference = interpretation.step_reference or _whole_title(request, steps)
    if reference:
        focus, step_candidates, question = _resolve_step(reference, request, _text(stored["id"]), steps)
        if focus is None:
            result["candidates"] = step_candidates
            return _ask(result, question)

    _evaluate(result, detail, stored, steps, focus)
    result["outcome"] = STATUS
    return result


# ------------------------------------------------------------------ steps


def _whole_title(request, steps):
    """A stored step title written whole in the request, if exactly one is."""

    words = f" {fold(request)} "
    hits = {str(s["step_name"]) for s in steps
            if s.get("step_name") and f" {fold(str(s['step_name']))} " in words}
    return hits.pop() if len(hits) == 1 else None


def _resolve_step(reference, request, project_id, steps):
    """(step, [], None) for exactly one step, else (None, candidates, question)."""

    if reference.isdigit():
        hits = [s for s in steps if s.get("sequence_number") == int(reference)]
        if len(hits) == 1:
            return hits[0], [], None
        return None, [_step(s) for s in hits], f"No step {reference} in this Project. Which step?"

    resolution = resolve_step_entity(_written_title(reference, request, steps), project_id, steps)
    by_id = {_text(s["id"]): s for s in steps}
    candidates = [by_id[c.step_id] for c in resolution.candidates]

    if resolution.status == StepResolutionStatus.RESOLVED and resolution.match_kind in (
        StepMatchKind.UUID, StepMatchKind.STEP_NAME,
    ):
        return by_id[resolution.step_id], [], None
    if len(candidates) == 1:
        # Read-only: a single partial match ("Partner Approval" ->
        # "Record Partner approval") is reported, marked as such.
        return dict(candidates[0], _partial_match=True), [], None
    if not candidates:
        return None, [], f"No step matches {reference!r} in this Project. Which step?"
    return None, [_step(s) for s in candidates], (
        "Several steps match "
        + "; ".join(f"step {s['sequence_number']} {s['step_name']!r}" for s in candidates)
        + f" for {reference!r}. Which one?"
    )


# --------------------------------------------------------------- evidence


def _evaluate(result, detail, project, steps, focus):
    revisions = list(detail.get("document_revisions") or [])
    approvals = list(detail.get("document_approvals") or [])
    procurement = list(detail.get("procurement_records") or [])
    dependencies = detail.get("dependencies") or []
    project_id = _text(project["id"])

    gates = [_gate(s, project, steps, dependencies, revisions, approvals, procurement)
             for s in sorted(steps, key=lambda s: s.get("sequence_number") or 0)
             if is_approval_gate(s)]
    open_gates = [g for g in gates if g["gate_status"] in (GATE_MET, GATE_NOT_MET)]
    unknown_gate = any(g["gate_status"] == UNKNOWN for g in gates)

    result["gates"] = gates
    result["documents"] = _documents(revisions, open_gates, unknown_gate)
    result["approvals"], result["outdated_approvals"] = _approvals(
        project_id, revisions, approvals, open_gates, unknown_gate)
    result["procurement"] = _procurement(project, procurement, open_gates, unknown_gate)
    result["missing"] = _missing(gates)

    if focus is not None:
        result["focus_step"] = _focus(focus, gates, steps, dependencies)


def _gate(step, project, steps, dependencies, revisions, approvals, procurement):
    entry = {
        **_step(step),
        "version": step.get("version"),
        "gate_kind": database_gate_kind(step),
        "database_verifiable": database_gate_kind(step) is not None,
        "gate_status": None,
        "evaluation": None,
        "blocking_codes": [],
        "explanation": None,
        "unmet_direct_dependencies": _unmet(step, steps, dependencies),
    }
    if step.get("status") in _TERMINAL:
        entry.update(gate_status=GATE_CLOSED,
                     explanation=f"Step is {step.get('status')}; its gate no longer applies.")
        return entry
    if entry["gate_kind"] is None:
        entry.update(gate_status=GATE_NO_EVALUATOR, blocking_codes=["NO_DATABASE_GATE_EVALUATOR"],
                     explanation="This approval gate has no database evaluator, so no stored "
                                 "evidence can satisfy it and the step cannot move through the CLI.")
        return entry
    try:
        evaluation = resolve_database_gate(
            step=step, project=project, revisions=revisions,
            approvals=approvals, procurement_records=procurement,
        )
    except (GateValidationError, DatabaseGateResolutionError) as error:
        entry.update(gate_status=UNKNOWN, explanation=f"The domain could not judge this gate: {error}")
        return entry
    entry.update(
        gate_status=GATE_MET if evaluation.all_met else GATE_NOT_MET,
        evaluation=evaluation.to_dict(),
        blocking_codes=list(evaluation.blocking_codes),
        explanation=("Every stored requirement of this gate is met."
                     if evaluation.all_met else "Blocked by: " + ", ".join(evaluation.blocking_codes)),
    )
    return entry


def _unmet(step, steps, dependencies):
    readiness = evaluate_dependency_readiness(_text(step["id"]), steps, dependencies)
    by_id = {_text(s["id"]): s for s in steps}
    return sorted((_step(by_id[_text(i)]) for i in readiness.unmet_direct_predecessor_ids),
                  key=lambda s: s["sequence"] or 0)


def _required_by(open_gates, predicate):
    return [{"sequence": g["sequence"], "name": g["name"]} for g in open_gates
            if g["evaluation"] is not None and predicate(g["evaluation"])]


def _requirement(required_by, unknown_gate):
    return REQUIRED if required_by else UNKNOWN if unknown_gate else NOT_REQUIRED


def _documents(revisions, open_gates, unknown_gate):
    """Every revision per document type; the active one PRESENT, superseded INVALID."""

    required_by = _required_by(open_gates, lambda e: True)
    by_type: dict[str, list] = {}
    for revision in revisions:
        by_type.setdefault(str(revision.get("document_type")), []).append(revision)
    documents = []
    for document_type, items in sorted(by_type.items()):
        items.sort(key=lambda r: int(r.get("revision_number") or 0))
        documents.append({
            "document_type": document_type,
            "requirement": _requirement(required_by, unknown_gate),
            "required_by": required_by,
            "revisions": [{
                "revision_id": _text(r["id"]),
                "revision_number": r.get("revision_number"),
                "status": INVALID if r.get("superseded_by") is not None else PRESENT,
                "reason": "SUPERSEDED" if r.get("superseded_by") is not None else "ACTIVE",
                "superseded_by": _text(r.get("superseded_by")),
                "signed": bool(r.get("signed")),
                "signed_at": _text(r.get("signed_at")),
                "effective_date": _text(r.get("effective_date")),
                "expiry_date": _text(r.get("expiry_date")),
                "created_at": _text(r.get("created_at")),
            } for r in items],
        })
    if not documents:
        documents.append({
            "document_type": None,
            "requirement": _requirement(required_by, unknown_gate),
            "required_by": required_by,
            "status": MISSING,
            "reason": "MISSING_DOCUMENT_REVISION",
            "revisions": [],
        })
    return documents


def _approvals(project_id, revisions, approvals, open_gates, unknown_gate):
    """Per role, on the revision the gates judge; older approvals are outdated."""

    roles = tuple(sorted(APPROVER_ROLES))
    try:
        latest = latest_document_revision(project_id, revisions)
        judged = evaluate_approval_gate(project_id, revisions, approvals, required_roles=roles)
    except GateValidationError as error:
        latest, judged, refusal = None, None, str(error)
    else:
        refusal = None

    latest_id = _text(latest["id"]) if latest is not None else None
    rows = {}
    outdated = []
    for approval in approvals:
        on = _text(approval.get("document_revision_id"))
        entry = {
            "role": approval.get("approver_role"),
            "approval_status": approval.get("approval_status"),
            "approved_at": _text(approval.get("approved_at")),
            "document_revision_id": on,
        }
        if latest_id is not None and on == latest_id:
            rows[approval.get("approver_role")] = entry
        else:
            outdated.append(dict(entry, status=INVALID, reason=(
                "SUPERSEDED_REVISION" if latest_id is not None else "REVISION_NOT_JUDGED"),
                explanation="This approval is on a revision the gates do not judge; it never "
                            "counts as approval of the latest revision."))

    result = []
    for role in roles:
        required_by = _required_by(
            open_gates, lambda e, r=role: r in tuple(e["approved_roles"]) + tuple(e["missing_roles"]))
        row = rows.get(role)
        if judged is None:
            status, reason = UNKNOWN, refusal
        elif latest is None:
            status, reason = MISSING, "MISSING_DOCUMENT_REVISION"
        elif role in judged.approved_roles:
            status, reason = PRESENT, "APPROVED"
        elif row is None:
            status, reason = MISSING, "NO_APPROVAL_ON_LATEST_REVISION"
        elif str(row["approval_status"]).upper() == "PENDING":
            status, reason = MISSING, "PENDING_DECISION"
        elif str(row["approval_status"]).upper() == "REJECTED":
            status, reason = INVALID, "REJECTED_FINAL"
        else:
            status, reason = INVALID, "APPROVED_WITHOUT_TIMESTAMP"
        result.append({
            "role": role,
            "status": status,
            "reason": reason,
            "requirement": _requirement(required_by, unknown_gate),
            "required_by": required_by,
            "document_revision_id": latest_id,
            "approval": row,
        })
    return result, outdated


def _procurement(project, records, open_gates, unknown_gate):
    by_type = {str(r.get("procurement_type")).upper(): r for r in records}
    entries = []
    for kind in sorted(PROCUREMENT_TYPES):
        record = by_type.get(kind)
        number = (record or {}).get("external_id")
        if record is None:
            status, reason = MISSING, "NO_RECORD"
        elif isinstance(number, str) and number.strip():
            status, reason = PRESENT, "RECORDED"
        else:
            status, reason = INVALID, "NO_EXTERNAL_ID"
        if kind == "PURCHASE_REQUEST":
            required_by = _required_by(open_gates, lambda e: bool(e.get("requires_procurement")))
            requirement = _requirement(required_by, unknown_gate)
            note = ("Required by the signing gate because the Project requires procurement."
                    if required_by else
                    "Not required: the Project does not require procurement."
                    if not project.get("requires_procurement") else
                    "No open gate checks it now.")
        else:
            required_by, requirement = [], NOT_REQUIRED
            note = ("No workflow gate checks this record; the related steps are not linked "
                    "to procurement evidence.")
        entries.append({
            "procurement_type": kind,
            "status": status,
            "reason": reason,
            "requirement": requirement,
            "required_by": required_by,
            "external_id": number if status == PRESENT else None,
            "record_status": (record or {}).get("status"),
            "version": (record or {}).get("version"),
            "note": note,
        })
    return entries


def _missing(gates):
    """What open gates still lack, with the gate and the domain code it came from."""

    missing = []
    for gate in gates:
        where = {"sequence": gate["sequence"], "name": gate["name"]}
        if gate["gate_status"] == GATE_NO_EVALUATOR:
            missing.append({"code": "NO_DATABASE_GATE_EVALUATOR", "gate": where,
                            "explanation": gate["explanation"]})
            continue
        evaluation = gate["evaluation"]
        if gate["gate_status"] != GATE_NOT_MET or evaluation is None:
            continue
        for code in evaluation["blocking_codes"]:
            if code == "MISSING_REQUIRED_APPROVALS":
                for role in evaluation["missing_roles"]:
                    missing.append({"code": code, "role": role, "gate": where,
                                    "explanation": f"{role} approval of the latest revision is missing."})
            else:
                missing.append({"code": code, "gate": where, "explanation": {
                    "MISSING_DOCUMENT_REVISION": "No active document revision exists.",
                    "MISSING_PURCHASE_REQUEST": "No Purchase Request number is recorded.",
                    "DOCUMENT_ALREADY_SIGNED": "The latest revision is already signed.",
                }.get(code, code)})
    return missing


def _focus(step, gates, steps, dependencies):
    gate = next((g for g in gates if g["step_id"] == _text(step["id"])), None)
    readiness = evaluate_dependency_readiness(_text(step["id"]), steps, dependencies)
    return {
        **_step(step),
        "version": step.get("version"),
        "match_kind": "PARTIAL_UNIQUE" if step.get("_partial_match") else "EXACT",
        "gate": gate,
        "evidence_requirement": (
            "GATE" if gate is not None else NOT_REQUIRED
        ),
        "explanation": (
            None if gate is not None else
            "This step has no approval gate: moving it checks dependencies only, no stored evidence."
        ),
        "unmet_direct_dependencies": _unmet(step, steps, dependencies),
        "unmet_transitive_count": len(readiness.unmet_transitive_predecessor_ids),
    }


def _ask(result, question):
    result["clarifications"].append(question)
    return result
