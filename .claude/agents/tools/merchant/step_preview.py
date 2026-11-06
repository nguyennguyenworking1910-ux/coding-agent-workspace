"""Read-only natural-language Step Update preview (CP12H.NL4B).

``build_step_update_preview(request, reads, database_target=...)`` answers
"what would happen if this step update were run?" without running it:

- the Merchant and Project are bound exactly as NL4A binds them
  (``project_status.resolve_project``): exact id, exact title, or Merchant plus
  title; several matches, or a partial title without a Merchant, only ask;
- the step is bound by its exact sequence number or through the domain step
  resolver (exact UUID or exact name). A partial name is never bound, not
  even a single one: it is offered as a candidate;
- every check is the write path's own, applied to the read snapshot in the
  order ``transition_repository.transition_step`` applies them: the status
  transition table (``validate_step_transition``, no reopen), dependency
  readiness for READY / IN_PROGRESS / COMPLETED, and, for any APPROVAL_GATE
  step, the stored-evidence gate (``resolve_database_gate``; a gate with no
  database evaluator is never met through the CLI). When nothing blocks, the
  domain planner ``propose_step_transition`` itself must accept the plan.

Nothing is written, reserved, claimed or confirmed. ``READY_FOR_CONFIRMATION``
means only that the existing domain rules would accept the update now. The
result carries no command, argv or confirmation instruction:
``executable`` and ``confirmation_available`` are always false, because Step
Update confirmation does not exist yet (CP12H.NL4C).
"""

from __future__ import annotations

import re
from typing import Any

from .dependencies import evaluate_dependency_readiness
from .engine import WorkflowEngineError, propose_step_transition
from .gate_resolver import (
    DatabaseGateResolutionError,
    database_gate_kind,
    is_approval_gate,
    resolve_database_gate,
)
from .gates import GateValidationError
from .project_nl import STEP_UPDATE, interpret_project_request
from .project_status import (
    STEP_STATUS_ORDER,
    _step,
    _summary,
    _text,
    resolve_merchant_phrase,
    resolve_project,
)
from .state_machine import (
    STEP_REOPEN_TRANSITIONS,
    WorkflowStateError,
    validate_step_transition,
)
from .step_entity_resolver import StepMatchKind, StepResolutionStatus, resolve_step_entity

MODE = "STEP_UPDATE_PREVIEW"
READY = "READY_FOR_CONFIRMATION"
BLOCKED = "BLOCKED"
CLARIFY = "NEEDS_CLARIFICATION"

# transition_repository / engine: these targets require met dependencies.
_DEPENDENCY_TARGETS = ("READY", "IN_PROGRESS", "COMPLETED")
_ACTIONABLE = ("READY", "IN_PROGRESS")
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)


def build_step_update_preview(
    request: str, reads: Any, *, database_target: str | None
) -> dict[str, Any]:
    """One read-only Step Update preview for the user's own words."""

    interpretation = interpret_project_request(request)
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
            "target_status": interpretation.target_status,
        },
        "merchant": None,
        "project": None,
        "step": None,
        "transition": None,
        "unmet_dependencies": [],
        "gate": None,
        "blocking": [],
        "candidates": [],
        "clarifications": [],
        # CP12H.NL4B-FIX2: fields the request did not settle: "step",
        # "target_status", "merchant", "project" (one question each).
        "missing": [],
    }

    if interpretation.kind != STEP_UPDATE:
        return _ask(result, "Is this a request to update one Project step? Which step, and to which status?")
    if interpretation.negated:
        return _ask(result, "The request says not to update the step. Which step update should be previewed?")
    if interpretation.exploratory:
        return _ask(result, "The request is not a definite step update. Which step update should be previewed?")

    # CP12H.NL4B-FIX2: every missing field is named in one clarification,
    # in a fixed order; the Project is never taken from an earlier request.
    if interpretation.step_reference is None:
        _missing(result, "step", "Which step? Name its number or its exact title.")
    if interpretation.target_status is None:
        _missing(result, "target_status", "Which status should the step move to (READY, IN_PROGRESS, COMPLETED, BLOCKED, SKIPPED or SUPERSEDED)?")

    merchant = project = None
    if interpretation.merchant_phrase:
        merchant, question = resolve_merchant_phrase(reads, interpretation.merchant_phrase)
        if merchant is None:
            _missing(result, "merchant", question)
        else:
            result["merchant"] = merchant

    if "merchant" not in result["missing"]:
        project, match_kind, candidates, question = resolve_project(
            reads, merchant, result["query"]["project_id"], interpretation.project_phrase
        )
        if project is None:
            result["candidates"] = candidates
            _missing(result, "project", question)

    if project is None:
        return result

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
    if result["missing"]:
        return result

    step, step_candidates, question = _resolve_step(
        interpretation.step_reference, _text(stored["id"]), steps
    )
    if step is None:
        result["candidates"] = step_candidates
        return _missing(result, "step", question)

    return _evaluate(result, detail, stored, steps, step, interpretation.target_status)


def _resolve_step(reference, project_id, steps):
    """(step row, [], None) for exactly one step, else (None, candidates, question)."""

    if not reference:
        return None, [], "Which step? Name its number or its exact title."

    if reference.isdigit():
        hits = [s for s in steps if s.get("sequence_number") == int(reference)]
        if len(hits) == 1:
            return hits[0], [], None
        return None, [_step(s) for s in hits], (
            f"No step {reference} in this Project. Which step?"
            if not hits else f"Several steps are numbered {reference}. Which one?"
        )

    resolution = resolve_step_entity(reference, project_id, steps)
    by_id = {_text(s["id"]): s for s in steps}
    candidates = [_step(by_id[c.step_id]) for c in resolution.candidates]

    if resolution.status == StepResolutionStatus.RESOLVED and resolution.match_kind in (
        StepMatchKind.UUID, StepMatchKind.STEP_NAME,
    ):
        return by_id[resolution.step_id], [], None
    if resolution.status == StepResolutionStatus.NOT_FOUND:
        return None, [], f"No step matches {reference!r} in this Project. Which step?"
    # Several exact names, or any partial name: offer, never bind.
    return None, candidates, (
        ("Several steps match " if len(candidates) > 1 else "Did you mean ")
        + "; ".join(f"step {c['sequence']} {c['name']!r}" for c in candidates)
        + f" for {reference!r}? Name the step exactly."
    )


def _evaluate(result, detail, project, steps, step, target):
    """The write path's checks on the read snapshot; READY only if none block."""

    current = step.get("status")
    step_id = _text(step["id"])
    result["step"] = {**_step(step), "version": step.get("version"),
                      "is_optional": step.get("is_optional"),
                      "condition_key": step.get("condition_key")}
    result["transition"] = {"current_status": current, "target_status": target,
                            "supported": False, "is_reopen": False}
    blocking = result["blocking"]

    try:
        validate_step_transition(current, target)
        result["transition"]["supported"] = True
    except WorkflowStateError as error:
        reopen = (str(current), target) in STEP_REOPEN_TRANSITIONS
        result["transition"]["is_reopen"] = reopen
        blocking.append(_block(
            "ALREADY_IN_STATUS" if current == target
            else "REOPEN_NOT_PREVIEWED" if reopen
            else "TRANSITION_NOT_ALLOWED",
            str(error) + (" A reopen needs an explicit reopen, which a preview never assumes."
                          if reopen else ""),
        ))

    if target in _DEPENDENCY_TARGETS:
        readiness = evaluate_dependency_readiness(step_id, steps, detail.get("dependencies") or [])
        by_id = {_text(s["id"]): s for s in steps}

        def listed(ids):
            return sorted((_step(by_id[_text(i)]) for i in ids),
                          key=lambda s: (s["sequence"] is None, s["sequence"]))

        def named(rows):
            return ", ".join(f"{s['sequence']} {s['name']}" for s in rows)

        # unmet_dependencies: the direct predecessors still open (or, if all
        # of those are done, the open ancestors), labelled by scope. The
        # transitive list names every open ancestor the count covers.
        direct = readiness.unmet_direct_predecessor_ids
        transitive = readiness.unmet_transitive_predecessor_ids
        result["unmet_dependencies"] = listed(direct or transitive)
        result["unmet_dependency_scope"] = "DIRECT" if direct or not transitive else "TRANSITIVE"
        result["unmet_transitive_dependencies"] = listed(transitive)
        result["unmet_transitive_count"] = len(transitive)
        if not readiness.is_ready:
            message = (
                ("Direct predecessors" if direct else "Earlier steps")
                + " that must be COMPLETED first: " + named(result["unmet_dependencies"])
            )
            if len(transitive) > len(result["unmet_dependencies"]):
                message += (f". All {len(transitive)} unfinished earlier steps: "
                            + named(result["unmet_transitive_dependencies"]))
            blocking.append(_block("UNMET_DEPENDENCIES", message))

    gate = _gate(result, detail, project, step)
    if gate is not None and not gate["all_met"]:
        blocking.append(_block(
            "GATE_NOT_MET",
            f"{gate['kind'] or 'Approval gate'} is not satisfied: "
            + ", ".join(gate["blocking_codes"]),
        ))

    if target == "COMPLETED" and str(project.get("project_type")) == "INTEGRATION_NEW_MERCHANT":
        # Completing an activation step may activate the Merchant; its
        # prerequisites need the locked write snapshot, so never READY here.
        blocking.append(_block(
            "MERCHANT_ACTIVATION_NOT_PREVIEWED",
            "Completing a step of an INTEGRATION_NEW_MERCHANT Project may activate "
            "the Merchant; that check is not previewed.",
        ))

    if not blocking:
        try:
            plan = propose_step_transition(
                {"project": project, "steps": steps,
                 "dependencies": detail.get("dependencies") or []},
                step_id, target, expected_version=step["version"],
                gate_required=is_approval_gate(step),
                gate_result=gate["result"] if gate is not None else None,
            )
            result["transition"].update(event_type=plan.event_type,
                                        expected_version=plan.expected_version,
                                        new_version=plan.new_version)
        except (WorkflowEngineError, WorkflowStateError) as error:
            # A rule the checks above did not name: never report READY.
            blocking.append(_block("DOMAIN_REJECTED", str(error)))

    if gate is not None:
        del gate["result"]
    result["project_state"] = _project_state(steps)
    result["outcome"] = READY if not blocking else BLOCKED
    return result


def _gate(result, detail, project, step):
    """The stored-evidence gate the write path applies to an APPROVAL_GATE step."""

    if not is_approval_gate(step):
        return None

    kind = database_gate_kind(step)
    gate = {"required": True, "kind": kind, "database_verifiable": kind is not None,
            "all_met": False, "blocking_codes": [], "missing_roles": [],
            "approved_roles": [], "result": None}

    if kind is None:
        # transition_repository passes no gate result for these: never met.
        gate["blocking_codes"] = ["NO_DATABASE_GATE_EVALUATOR"]
        result["gate"] = gate
        return gate

    # The locked write snapshot reads only this Project's own revisions.
    revisions = [r for r in detail.get("document_revisions") or []
                 if _text(r.get("project_id")) == _text(project["id"])]
    try:
        evaluated = resolve_database_gate(
            step=step, project=project, revisions=revisions,
            approvals=detail.get("document_approvals") or [],
            procurement_records=detail.get("procurement_records") or [],
        )
    except (DatabaseGateResolutionError, GateValidationError, ValueError) as error:
        gate["blocking_codes"] = [f"GATE_EVALUATION_FAILED: {error}"]
        result["gate"] = gate
        return gate

    gate.update(
        all_met=evaluated.all_met,
        blocking_codes=list(evaluated.blocking_codes),
        missing_roles=list(evaluated.missing_roles),
        approved_roles=list(evaluated.approved_roles),
        document_revision_id=evaluated.document_revision_id,
        result=evaluated,
    )
    result["gate"] = gate
    return gate


def _project_state(steps):
    counts = {status: 0 for status in STEP_STATUS_ORDER}
    for step in steps:
        counts[step["status"]] = counts.get(step["status"], 0) + 1
    return {
        "step_counts": {"total": len(steps), **counts},
        "current_steps": [_step(s) for s in steps if s["status"] in _ACTIONABLE],
    }


def _block(code, message):
    return {"code": code, "message": message}


def _ask(result, question):
    result["clarifications"].append(question)
    return result


def _missing(result, field, question):
    result["missing"].append(field)
    return _ask(result, question)
