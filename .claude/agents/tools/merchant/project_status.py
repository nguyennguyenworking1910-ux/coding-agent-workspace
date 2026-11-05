"""Read-only natural-language Project discovery and workflow status (CP12H.NL4A).

``build_project_status(request, reads, database_target=...)`` binds a Project
from the user's words only through the authoritative read repository:

- an exact Project UUID in the request;
- an exact Project title (across Merchants, or within a named Merchant);
- a Merchant plus a unique partial title within that Merchant;
- a Merchant plus an optional status filter, for a list.

A partial title with no Merchant named is only ever a candidate. Several
matches are returned as candidates and nothing is selected; no match,
or no Project named, asks a question. Step state comes from stored rows and the
domain dependency evaluator only: a step is actionable when it is READY or
IN_PROGRESS; a PENDING step whose predecessors are all COMPLETED is reported as
dependency-ready but still PENDING; SKIPPED is never COMPLETED. The result is
data: ``read_only`` is always true and ``authorization`` always null.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .dependencies import dependency_ready_step_ids, evaluate_dependency_readiness
from .project_entity_resolver import resolve_project_entity
from .project_nl import PROJECT_LIST, PROJECT_STATUS, fold, interpret_project_request
from .project_preview import resolve_merchant

MODE = "PROJECT_STATUS"
STATUS = "PROJECT_STATUS"
LIST = "PROJECT_LIST"
CLARIFY = "NEEDS_CLARIFICATION"

STEP_STATUS_ORDER = (
    "PENDING", "READY", "IN_PROGRESS", "BLOCKED", "COMPLETED", "SKIPPED", "SUPERSEDED",
)
_ACTIONABLE = ("READY", "IN_PROGRESS")
_WAITING = ("PENDING", "BLOCKED")
_TERMINAL = ("COMPLETED", "SKIPPED", "SUPERSEDED")

_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
# Folded status words for a Project list; one filter at most.
_LIST_FILTERS = (
    ("IN_PROGRESS", r"\b(?:dang chay|dang thuc hien|dang trien khai|in progress|active|running)\b"),
    ("COMPLETED", r"\b(?:da hoan thanh|completed|finished)\b"),
    ("PLANNED", r"\b(?:chua bat dau|planned|not started)\b"),
    ("BLOCKED", r"\b(?:bi chan|blocked)\b"),
    ("ON_HOLD", r"\b(?:tam dung|on hold)\b"),
    ("CANCELLED", r"\b(?:da huy|cancelled|canceled)\b"),
)


def build_project_status(request: str, reads: Any, *, database_target: str | None) -> dict[str, Any]:
    """One read-only status or list result for the user's own words."""

    interpretation = interpret_project_request(request)
    project_uuid = _UUID.search(request)
    result: dict[str, Any] = {
        "success": True,
        "mode": MODE,
        "database_target": database_target or "runtime",
        "outcome": CLARIFY,
        "read_only": True,
        "authorization": None,
        "query": {
            "kind": interpretation.kind,
            "merchant_phrase": interpretation.merchant_phrase,
            "project_phrase": interpretation.project_phrase,
            "project_id": project_uuid.group().lower() if project_uuid else None,
        },
        "merchant": None,
        "project": None,
        "candidates": [],
        "clarifications": [],
    }

    merchant = None
    if interpretation.merchant_phrase:
        merchant, _, question = resolve_merchant(
            reads.list_merchants(), interpretation.merchant_phrase, None, None
        )
        if merchant is None:
            return _ask(result, question)
        result["merchant"] = {
            "merchant_id": _text(merchant["merchant_id"]),
            "code": merchant["code"],
            "name": merchant["name"],
            "match_kind": merchant["match_kind"],
        }

    if interpretation.kind == PROJECT_LIST and project_uuid is None:
        return _project_list(result, reads, merchant, fold(request))

    if interpretation.kind != PROJECT_STATUS and project_uuid is None:
        return _ask(result, "Is this a question about one Project's status? Which Project?")

    projects = reads.list_projects(
        merchant_id=_text(merchant["merchant_id"]) if merchant else None, status=None
    )
    found, match_kind = _find_project(
        projects, merchant, result["query"]["project_id"], interpretation.project_phrase
    )

    if found is None:
        return _ask(
            result,
            "Which Project do you mean? Name its title (and Merchant) or its Project ID."
            if not (result["query"]["project_id"] or interpretation.project_phrase)
            else "No Project matches "
            + repr(result["query"]["project_id"] or interpretation.project_phrase)
            + (f" for Merchant {merchant['code']}" if merchant else "")
            + ". Which Project do you mean?",
        )

    if len(found) > 1 or (merchant is None and match_kind == "CANDIDATE"):
        # Several matches, or a partial title with no Merchant named: offer
        # candidates and never bind one.
        result["candidates"] = [_summary(p) for p in found]
        return _ask(
            result,
            ("Several Projects match: " if len(found) > 1 else "Did you mean: ")
            + "; ".join(f"{p['title']} ({p['merchant_code']}, {_text(p['id'])})" for p in found)
            + "?" + (" Which one?" if len(found) > 1 else ""),
        )

    return _project_status(result, reads, found[0], match_kind)


def _find_project(projects, merchant, project_id, phrase):
    """(matches or None, match kind). Never picks one of several."""

    if project_id:
        hits = [p for p in projects if _text(p["id"]).lower() == project_id]
        return (hits or None), "UUID"

    if not phrase:
        return None, None

    if merchant is not None:
        resolution = resolve_project_entity(phrase, _text(merchant["merchant_id"]), projects)
        ids = {c.project_id for c in resolution.candidates}
        hits = [p for p in projects if _text(p["id"]) in ids]
        return (hits or None), resolution.match_kind.value

    wanted = fold(phrase)
    exact = [p for p in projects if p.get("title") and fold(p["title"]) == wanted]
    if exact:
        return exact, "TITLE"
    partial = [
        p for p in projects
        if p.get("title") and re.search(rf"(?:^| ){re.escape(wanted)}(?: |$)", fold(p["title"]))
    ]
    return (partial or None), "CANDIDATE"


def _project_list(result, reads, merchant, folded):
    if merchant is None:
        return _ask(result, "Which Merchant's Projects should be listed?")

    filters = [status for status, pattern in _LIST_FILTERS if re.search(pattern, folded)]
    if len(filters) > 1:
        return _ask(result, "Which Project status should be listed: " + ", ".join(filters) + "?")

    status = filters[0] if filters else None
    projects = reads.list_projects(merchant_id=_text(merchant["merchant_id"]), status=status)
    result.update(
        outcome=LIST,
        status_filter=status,
        projects=[_summary(p) for p in projects],
    )
    return result


def _project_status(result, reads, project, match_kind):
    detail = reads.get_project_detail(_text(project["id"]))
    steps = detail.get("steps") or []
    dependencies = detail.get("dependencies") or []
    by_id = {_text(s["id"]): s for s in steps}

    counts = {status: 0 for status in STEP_STATUS_ORDER}
    for step in steps:
        counts[step["status"]] = counts.get(step["status"], 0) + 1

    ready_ids = set(dependency_ready_step_ids(steps, dependencies))
    waiting = []
    for step in steps:
        if step["status"] in _WAITING and _text(step["id"]) not in ready_ids:
            readiness = evaluate_dependency_readiness(_text(step["id"]), steps, dependencies)
            unmet = readiness.unmet_direct_predecessor_ids or readiness.unmet_transitive_predecessor_ids
            waiting.append(dict(
                _step(step),
                unmet_predecessors=_by_sequence([_step(by_id[_text(i)]) for i in unmet]),
            ))

    timestamps = [project.get("updated_at")] + [
        s.get(field) for s in steps for field in ("actual_start", "actual_completion")
    ]

    result.update(
        outcome=STATUS,
        project={
            **_summary(project),
            "requires_procurement": project.get("requires_procurement"),
            "version": project.get("version"),
            "created_at": _text(project.get("created_at")),
            "last_updated_at": _latest(timestamps),
            "match_kind": match_kind,
        },
        step_counts={"total": len(steps), **counts},
        current_steps=[_step(s) for s in steps if s["status"] in _ACTIONABLE],
        dependency_ready_steps=[_step(s) for s in steps if _text(s["id"]) in ready_ids],
        waiting_steps=_by_sequence(waiting),
        completed_steps=[_step(s) for s in steps if s["status"] == "COMPLETED"],
        skipped_steps=[_step(s) for s in steps if s["status"] == "SKIPPED"],
        approval_gates=[
            _step(s) for s in steps
            if s.get("step_type") == "APPROVAL_GATE" and s["status"] not in _TERMINAL
        ],
        evidence={
            "document_revisions": len(detail.get("document_revisions") or []),
            "document_approvals": len(detail.get("document_approvals") or []),
            "procurement_records": len(detail.get("procurement_records") or []),
        },
    )
    if result["merchant"] is None:
        result["merchant"] = {
            "merchant_id": _text(project["merchant_id"]),
            "code": project.get("merchant_code"),
            "name": project.get("merchant_name"),
            "match_kind": "FROM_PROJECT",
        }
    return result


def _ask(result, question):
    result["clarifications"].append(question)
    return result


def _summary(project):
    return {
        "project_id": _text(project["id"]),
        "title": project.get("title"),
        "status": project.get("status"),
        "merchant_id": _text(project.get("merchant_id")),
        "merchant_code": project.get("merchant_code"),
        "merchant_name": project.get("merchant_name"),
        "project_type": project.get("project_type"),
        "workflow_variant": project.get("workflow_variant"),
        "updated_at": _text(project.get("updated_at")),
    }


def _step(step):
    return {
        "step_id": _text(step["id"]),
        "sequence": step.get("sequence_number"),
        "name": step.get("step_name"),
        "status": step.get("status"),
        "step_type": step.get("step_type"),
        "branch_key": step.get("branch_key"),
    }


def _by_sequence(steps):
    return sorted(steps, key=lambda s: (s["sequence"] is None, s["sequence"]))


def _latest(values):
    stamps = []
    for value in values:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if isinstance(value, datetime):
            stamps.append(value)
    return max(stamps).isoformat() if stamps else None


def _text(value):
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)
