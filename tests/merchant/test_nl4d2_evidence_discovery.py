"""CP12H.NL4D2: read-only natural-language evidence and approval discovery.

The fake reader serves a real OPENING_NEW_CINEMA_STANDARD workflow (22 steps,
the template's own edges, the no-procurement variant's dropped edges) and
refuses every non-read API. Every gate result is cross-checked against
``resolve_database_gate`` itself: the discovery reuses the domain, it never
re-implements a rule.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant.agent_cli import MerchantAgentCliError, prepare_agent_cli_argv
from claude.agents.tools.merchant.evidence_status import (
    CLARIFY,
    INVALID,
    MISSING,
    NOT_REQUIRED,
    PRESENT,
    REQUIRED,
    STATUS,
    UNKNOWN,
    build_evidence_status,
)
from claude.agents.tools.merchant.gate_resolver import resolve_database_gate
from claude.agents.tools.merchant.project_nl import (
    EVIDENCE_STATUS,
    PROJECT_STATUS,
    STEP_UPDATE,
    interpret_project_request,
)
from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.clients.merchant.read_repository import ProjectNotFoundError
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks import merchant_preview_delivery
from claude.hooks.merchant_preview_delivery import EVIDENCE_RESULT_MARKER
from tests.merchant.test_nl1_project_preview import BETA, LOTTE, merchant
from tests.merchant.test_nl2e_p1_p2_p4 import (  # noqa: F401 (fixtures)
    CLI,
    LEAD,
    MM,
    deny,
    intent_gate,
    isolated,
    post_bash,
    runtime_state,
    spawn,
)
from tests.merchant.test_nl4a_project_status import ExecuteParser, decide

T0 = datetime(2026, 11, 4, 7, 0, tzinfo=timezone.utc)
P = "eeeeeeee-0000-4000-8000-000000000001"          # no procurement
P_PROC = "eeeeeeee-0000-4000-8000-000000000002"     # requires procurement
P_TWIN = "eeeeeeee-0000-4000-8000-000000000003"     # similar title
P_LOTTE = "eeeeeeee-0000-4000-8000-000000000004"
TITLE = "Beta Nguyễn Văn Cừ Evidence"
NAMED = f"Project {TITLE}"
TEMPLATE = get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD")
SEQ = {s.key: s.sequence_number for s in TEMPLATE.steps}


def sid(project_id, sequence):
    return str(uuid.uuid5(uuid.UUID(project_id), f"step-{sequence}"))


def rid(n):
    return f"cccccccc-0000-4000-8000-{n:012d}"


def project(project_id, title, merchant_id=BETA, requires_procurement=False):
    code, name = {BETA: ("NL2_LIVE_BETA", "Beta Cinemas"), LOTTE: ("LOTTE", "Lotte Cinema")}[merchant_id]
    return {
        "id": project_id, "merchant_id": merchant_id, "merchant_code": code,
        "merchant_name": name, "project_type": "OPENING_NEW_CINEMA",
        "workflow_variant": "OPENING_NEW_CINEMA_STANDARD", "title": title,
        "status": "IN_PROGRESS", "requires_procurement": requires_procurement,
        "created_at": T0, "updated_at": T0, "version": 4,
    }


def steps_for(project_id, statuses, requires_procurement=False):
    """The template's 22 steps; 6-7 SKIPPED without procurement."""

    rows = []
    for s in TEMPLATE.steps:
        n = s.sequence_number
        default = "SKIPPED" if s.condition_key and not requires_procurement else "PENDING"
        status = statuses.get(n, "READY" if n == 1 else default)
        rows.append({
            "id": sid(project_id, n), "project_id": project_id, "sequence_number": n,
            "template_step_id": str(uuid.UUID(int=n)), "step_name": s.name,
            "step_type": s.step_type, "branch_key": s.branch_key, "is_optional": s.is_optional,
            "condition_key": s.condition_key, "status": status,
            "version": 1 if status == "PENDING" else 2,
            "actual_start": None, "actual_completion": None,
        })
    return rows


def edges_for(project_id, requires_procurement=False):
    edges = []
    for d in TEMPLATE.dependencies:
        a, b = SEQ[d.from_step_key], SEQ[d.to_step_key]
        if not requires_procurement and (a in (6, 7) or b in (6, 7)):
            continue                                  # the factory drops them
        edges.append({"id": str(uuid.uuid4()), "from_step_id": sid(project_id, a),
                      "to_step_id": sid(project_id, b), "dependency_type": d.dependency_type})
    return edges


def revision(project_id, n, *, superseded_by=None, signed=False, document_type="CONTRACT"):
    return {"id": rid(n), "project_id": project_id, "document_type": document_type,
            "revision_number": n, "superseded_by": superseded_by, "signed": signed,
            "signed_at": T0 if signed else None, "effective_date": None,
            "expiry_date": None, "created_at": T0, "content_hash": "SECRET-HASH-VALUE"}


def approval(n, role, status="APPROVED"):
    return {"id": str(uuid.uuid4()), "document_revision_id": rid(n), "approver_role": role,
            "approval_status": status, "approved_at": T0 if status == "APPROVED" else None,
            "notes": "SECRET-NOTE"}


def pr(external_id="PR-001"):
    return {"id": str(uuid.uuid4()), "project_id": P_PROC, "procurement_type": "PURCHASE_REQUEST",
            "external_id": external_id, "status": "SUBMITTED", "version": 1,
            "created_at": T0, "updated_at": T0}


# Steps 1-4 done: step 5 (Partner gate) is next; 8 waits on 5.
REVIEWED = {1: "COMPLETED", 2: "COMPLETED", 3: "COMPLETED", 4: "COMPLETED"}


class EvidenceReader:
    """Read-only fake. Any other attribute access fails the test."""

    def __init__(self, *, statuses=REVIEWED, revisions=(), approvals=(), procurement=(),
                 project_id=P):
        self.merchants = [merchant(BETA, "NL2_LIVE_BETA", "Beta Cinemas"),
                          merchant(LOTTE, "LOTTE", "Lotte Cinema")]
        self.projects = [
            project(P, TITLE),
            project(P_PROC, f"{TITLE} Procurement", requires_procurement=True),
            project(P_TWIN, f"{TITLE} Twin"),
            project(P_LOTTE, "Lotte Evidence", LOTTE),
        ]
        self.statuses = dict(statuses)
        self.revisions = [dict(r, project_id=project_id) for r in revisions]
        self.approvals = list(approvals)
        self.procurement = list(procurement)

    def list_merchants(self, *, status=None):
        return copy.deepcopy(self.merchants)

    def list_projects(self, *, merchant_id=None, status=None):
        return [copy.deepcopy(p) for p in self.projects
                if (merchant_id is None or p["merchant_id"] == merchant_id)
                and (status is None or p["status"] == status)]

    def get_project_detail(self, project_id):
        found = [p for p in self.projects if p["id"] == project_id]
        if not found:
            raise ProjectNotFoundError(project_id)
        proc = found[0]["requires_procurement"]
        return copy.deepcopy({
            "project": found[0],
            "steps": steps_for(project_id, self.statuses, proc),
            "dependencies": edges_for(project_id, proc),
            "merchant_contacts": [],
            "document_revisions": [r for r in self.revisions if r["project_id"] == project_id],
            "document_approvals": self.approvals,
            "procurement_records": [r for r in self.procurement if r["project_id"] == project_id],
            "integration_identifiers": [],
        })

    def __getattr__(self, name):
        raise AssertionError(f"evidence discovery used a non-read API: {name}")


def ask(text, reader=None, target="test"):
    result = build_evidence_status(text, reader or EvidenceReader(), database_target=target)
    return json.loads(json.dumps(result, default=str))


def role(result, name):
    return next(a for a in result["approvals"] if a["role"] == name)


def gate(result, sequence):
    return next(g for g in result["gates"] if g["sequence"] == sequence)


def proc(result, kind):
    return next(p for p in result["procurement"] if p["procurement_type"] == kind)


def codes(result):
    return sorted((m["code"], m.get("role"), m["gate"]["sequence"]) for m in result["missing"])


# ----------------------------------------------------------------- parsing


@pytest.mark.parametrize("text,step", [
    (f"{NAMED} còn thiếu giấy tờ gì?", None),
    (f"Bước Partner Approval của {NAMED} còn thiếu gì?", "Partner Approval"),
    (f"Legal đã duyệt tài liệu mới nhất của {NAMED} chưa?", None),
    (f"Accounting Review của {NAMED} đang chờ điều kiện nào?", None),
    (f"{NAMED} đã có Purchase Order chưa?", None),
    (f"Show missing approvals for {NAMED}.", None),
    (f"Which evidence blocks Step 8 of {NAMED}?", "8"),
    (f"List document revisions for {NAMED}.", None),
])
def test_evidence_questions_are_read_only_evidence_requests(text, step):
    result = interpret_project_request(text)

    assert result.kind == EVIDENCE_STATUS and result.write_requested is False
    assert result.step_reference == step
    assert result.project_phrase == TITLE


@pytest.mark.parametrize("text,kind", [
    (f"{NAMED} hiện tại đến bước nào?", PROJECT_STATUS),
    (f"Bước Legal review của {NAMED} đã hoàn thành chưa?", PROJECT_STATUS),
    (f"Đánh dấu bước 5 của {NAMED} là hoàn thành", STEP_UPDATE),
])
def test_status_and_update_wording_keeps_its_kind(text, kind):
    assert interpret_project_request(text).kind == kind


@pytest.mark.parametrize("text", [
    f"Ghi nhận Partner đã duyệt tài liệu của {NAMED}",
    f"Upload tài liệu mới cho {NAMED}",
    f"Approve the latest document of {NAMED}",
])
def test_evidence_writes_are_never_read_as_discovery(text):
    assert interpret_project_request(text).kind != EVIDENCE_STATUS


# ------------------------------------------------------------- result shape


def test_result_is_data_and_never_authorizes():
    reader = EvidenceReader(revisions=[revision(P, 1)], approvals=[approval(1, "PARTNER")])
    result = ask(f"{NAMED} còn thiếu giấy tờ gì?", reader)

    assert result["outcome"] == STATUS and result["mode"] == "EVIDENCE_STATUS"
    assert result["read_only"] is True and result["executable"] is False
    assert result["confirmation_available"] is False and result["authorization"] is None
    assert result["project"]["project_id"] == P and result["project"]["version"] == 4
    assert result["merchant"]["code"] == "NL2_LIVE_BETA"
    text = json.dumps(result)
    for forbidden in ("SECRET-HASH-VALUE", "SECRET-NOTE", "content_hash", "requested_operation",
                      "confirmation_command", "--merchant-scope", "argv"):
        assert forbidden not in text


def test_gate_results_are_the_domains_own():
    reader = EvidenceReader(revisions=[revision(P, 1)], approvals=[approval(1, "PARTNER")])
    detail = reader.get_project_detail(P)
    result = ask(f"{NAMED} còn thiếu giấy tờ gì?", reader)

    for step in detail["steps"]:
        if step["sequence_number"] in (5, 8):
            expected = resolve_database_gate(
                step=step, project=detail["project"], revisions=detail["document_revisions"],
                approvals=detail["document_approvals"],
                procurement_records=detail["procurement_records"],
            ).to_dict()
            assert gate(result, step["sequence_number"])["evaluation"] == json.loads(
                json.dumps(expected, default=str))


# ------------------------------------------------------- domain correctness


def test_no_document_revision():
    result = ask(f"{NAMED} còn thiếu giấy tờ gì?")

    (document,) = result["documents"]
    assert (document["status"], document["requirement"]) == (MISSING, REQUIRED)
    assert all((a["status"], a["reason"]) == (MISSING, "MISSING_DOCUMENT_REVISION")
               for a in result["approvals"])
    assert gate(result, 5)["gate_status"] == "NOT_MET"
    assert ("MISSING_DOCUMENT_REVISION", None, 5) in codes(result)


def test_one_unsigned_revision_without_approvals():
    result = ask(f"Show missing approvals for {NAMED}.",
                 EvidenceReader(revisions=[revision(P, 1)]))

    (document,) = result["documents"]
    assert [r["status"] for r in document["revisions"]] == [PRESENT]
    assert document["revisions"][0]["signed"] is False
    partner, legal = role(result, "PARTNER"), role(result, "LEGAL")
    assert (partner["status"], partner["requirement"]) == (MISSING, REQUIRED)
    assert [g["sequence"] for g in partner["required_by"]] == [5, 8]
    assert [g["sequence"] for g in legal["required_by"]] == [8]
    assert ("MISSING_REQUIRED_APPROVALS", "PARTNER", 5) in codes(result)


def test_multiple_revisions_mark_the_superseded_one_invalid():
    reader = EvidenceReader(revisions=[revision(P, 1, superseded_by=rid(2)), revision(P, 2)])
    (document,) = ask(f"List document revisions for {NAMED}.", reader)["documents"]

    assert [(r["revision_number"], r["status"], r["reason"]) for r in document["revisions"]] == [
        (1, INVALID, "SUPERSEDED"), (2, PRESENT, "ACTIVE")]


def test_an_approval_on_an_outdated_revision_never_approves_the_latest():
    reader = EvidenceReader(
        revisions=[revision(P, 1, superseded_by=rid(2)), revision(P, 2)],
        approvals=[approval(1, "PARTNER")],                     # historical, valid then
    )
    result = ask(f"Legal đã duyệt tài liệu mới nhất của {NAMED} chưa?", reader)

    partner = role(result, "PARTNER")
    assert (partner["status"], partner["document_revision_id"]) == (MISSING, rid(2))
    (outdated,) = result["outdated_approvals"]
    assert (outdated["role"], outdated["status"], outdated["reason"]) == (
        "PARTNER", INVALID, "SUPERSEDED_REVISION")
    assert gate(result, 5)["gate_status"] == "NOT_MET"


@pytest.mark.parametrize("absent", ["LEGAL", "ACCOUNTING", "PARTNER"])
def test_signing_gate_names_the_missing_role(absent):
    statuses = {**REVIEWED, 5: "COMPLETED"}                     # step 8 is next
    approvals = [approval(1, r) for r in ("LEGAL", "ACCOUNTING", "PARTNER") if r != absent]
    result = ask(f"Which evidence blocks Step 8 of {NAMED}?",
                 EvidenceReader(statuses=statuses, revisions=[revision(P, 1)], approvals=approvals))

    signing = result["focus_step"]["gate"]
    assert result["focus_step"]["sequence"] == 8
    assert signing["gate_status"] == "NOT_MET"
    assert signing["evaluation"]["missing_roles"] == [absent]
    assert role(result, absent)["status"] == MISSING
    assert gate(result, 5)["gate_status"] == "CLOSED"
    assert ("MISSING_REQUIRED_APPROVALS", absent, 8) in codes(result)


def test_rejected_and_pending_decisions_are_classified():
    reader = EvidenceReader(revisions=[revision(P, 1)],
                            approvals=[approval(1, "PARTNER", "REJECTED"),
                                       approval(1, "LEGAL", "PENDING")])
    result = ask(f"Show missing approvals for {NAMED}.", reader)

    assert (role(result, "PARTNER")["status"], role(result, "PARTNER")["reason"]) == (
        INVALID, "REJECTED_FINAL")
    assert (role(result, "LEGAL")["status"], role(result, "LEGAL")["reason"]) == (
        MISSING, "PENDING_DECISION")


def test_procurement_required_and_purchase_request_missing():
    statuses = {**REVIEWED, 5: "COMPLETED", 6: "COMPLETED", 7: "COMPLETED"}
    approvals = [approval(1, r) for r in ("LEGAL", "ACCOUNTING", "PARTNER")]
    reader = EvidenceReader(statuses=statuses, revisions=[revision(P_PROC, 1)],
                            approvals=approvals, project_id=P_PROC)
    result = ask(f"Project {TITLE} Procurement đã có Purchase Request chưa?", reader)

    request = proc(result, "PURCHASE_REQUEST")
    assert (request["status"], request["requirement"]) == (MISSING, REQUIRED)
    assert gate(result, 8)["blocking_codes"] == ["MISSING_PURCHASE_REQUEST"]
    assert ("MISSING_PURCHASE_REQUEST", None, 8) in codes(result)

    reader.procurement = [pr()]
    met = ask(f"Project {TITLE} Procurement đã có Purchase Request chưa?", reader)
    assert proc(met, "PURCHASE_REQUEST")["status"] == PRESENT
    assert gate(met, 8)["gate_status"] == "MET"

    reader.procurement = [pr(external_id=None)]
    blank = ask(f"Project {TITLE} Procurement đã có Purchase Request chưa?", reader)
    assert (proc(blank, "PURCHASE_REQUEST")["status"],
            proc(blank, "PURCHASE_REQUEST")["reason"]) == (INVALID, "NO_EXTERNAL_ID")


def test_procurement_not_required():
    result = ask(f"{NAMED} đã có Purchase Order chưa?")

    assert proc(result, "PURCHASE_REQUEST")["requirement"] == NOT_REQUIRED
    order = proc(result, "PURCHASE_ORDER")
    assert (order["status"], order["requirement"]) == (MISSING, NOT_REQUIRED)
    assert "PURCHASE_ORDER" in result["query"]["procurement_types"]
    assert not any(m["code"] == "MISSING_PURCHASE_REQUEST" for m in result["missing"])


def test_step_5_blocked_by_a_partial_unique_step_name():
    result = ask(f"Bước Partner Approval của {NAMED} còn thiếu gì?",
                 EvidenceReader(revisions=[revision(P, 1)]))

    focus = result["focus_step"]
    assert (focus["sequence"], focus["match_kind"]) == (5, "PARTIAL_UNIQUE")
    assert focus["gate"]["gate_status"] == "NOT_MET"
    assert focus["gate"]["evaluation"]["missing_roles"] == ["PARTNER"]


def test_a_step_without_a_gate_reports_dependencies_only():
    result = ask(f"Accounting Review của {NAMED} đang chờ điều kiện nào?",
                 EvidenceReader(statuses={1: "IN_PROGRESS"}))

    focus = result["focus_step"]
    assert (focus["sequence"], focus["gate"], focus["evidence_requirement"]) == (3, None, NOT_REQUIRED)
    assert [d["sequence"] for d in focus["unmet_direct_dependencies"]] == [1]


def test_incomplete_dependencies_are_listed_for_the_gate():
    result = ask(f"Which evidence blocks Step 8 of {NAMED}?",
                 EvidenceReader(statuses={1: "COMPLETED"}))

    focus = result["focus_step"]
    assert [d["sequence"] for d in focus["unmet_direct_dependencies"]] == [5]
    assert focus["unmet_transitive_count"] == 4                  # 2, 3, 4, 5


def test_gates_without_an_evaluator_are_never_satisfiable():
    result = ask(f"{NAMED} còn thiếu giấy tờ gì?")

    for sequence in (21, 22):
        assert gate(result, sequence)["gate_status"] == "NO_DATABASE_EVALUATOR"
        assert ("NO_DATABASE_GATE_EVALUATOR", None, sequence) in codes(result)


def test_an_already_signed_latest_revision_blocks_the_signing_gate():
    statuses = {**REVIEWED, 5: "COMPLETED"}
    approvals = [approval(1, r) for r in ("LEGAL", "ACCOUNTING", "PARTNER")]
    result = ask(f"Which evidence blocks Step 8 of {NAMED}?",
                 EvidenceReader(statuses=statuses, revisions=[revision(P, 1, signed=True)],
                                approvals=approvals))

    assert gate(result, 8)["blocking_codes"] == ["DOCUMENT_ALREADY_SIGNED"]


def test_several_active_document_types_are_unknown_not_guessed():
    reader = EvidenceReader(revisions=[revision(P, 1), dict(revision(P, 2), id=rid(9),
                                                            document_type="ANNEX")])
    result = ask(f"Show missing approvals for {NAMED}.", reader)

    assert gate(result, 5)["gate_status"] == UNKNOWN
    assert all(a["status"] == UNKNOWN for a in result["approvals"])


# ------------------------------------------------------- identity binding


@pytest.mark.parametrize("text", [
    "Project Beta Nguyễn Văn Cừ còn thiếu giấy tờ gì?",          # three partial matches
    "Project này còn thiếu giấy tờ gì?",                         # no trusted binding
    "Project Unknown Site còn thiếu giấy tờ gì?",
])
def test_ambiguous_or_missing_projects_ask(text):
    result = ask(text)

    assert result["outcome"] == CLARIFY and result["clarifications"]
    assert result["project"] is None and result["gates"] == []


def test_a_unicode_title_resolves_exactly_and_similar_titles_stay_apart():
    assert ask(f"{NAMED} còn thiếu giấy tờ gì?")["project"]["project_id"] == P
    assert ask(f"{NAMED} Twin còn thiếu giấy tờ gì?")["project"]["project_id"] == P_TWIN


def test_an_ambiguous_step_asks():
    result = ask(f"Bước review của {NAMED} còn thiếu phê duyệt gì?")

    assert result["outcome"] == CLARIFY
    assert {c["sequence"] for c in result["candidates"]} >= {2, 3}


# ------------------------------------------ CLI, routing and delivery (hooks)


def test_cli_exposes_a_read_that_cannot_write():
    argv = prepare_agent_cli_argv(["project", "evidence", "--request", "x", "--test-database"])
    assert argv[:2] == ("--database", "test")
    with pytest.raises(MerchantAgentCliError):
        prepare_agent_cli_argv(["project", "evidence", "--request", "x", "--execute"])
    with pytest.raises(MerchantAgentCliError):
        prepare_agent_cli_argv(["project", "show", P, "--test-database"])


def test_the_intent_gate_runs_evidence_questions_as_reads(isolated):
    text = f"{NAMED} còn thiếu giấy tờ gì trên database test?"
    output = intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD, "prompt": f"/solve {text}"},
        parser_factory=ExecuteParser, env={},
    )

    assert output.get("decision") != "block", output
    state = runtime_state.load_state(LEAD)
    assert state["operations"] == ["merchant_read"] and state["risk_level"] == "read_only"
    assert state["merchant_read_target"] == "test" and state.get("merchant_scope") is None


@pytest.fixture
def evidence_run(isolated, monkeypatch):
    from claude.hooks import harness_team_identity

    assert spawn(isolated) is None                        # an unscoped merchant_read run on test
    monkeypatch.setattr(harness_team_identity, "verified_teammate_pane",
                        lambda owner, name: "7000:%7" if (owner, name) == (LEAD, MM) else None)
    text = f"{NAMED} còn thiếu giấy tờ gì?"
    result = ask(text, EvidenceReader(revisions=[revision(P, 1)]))
    command = f'{CLI} project evidence --request "{text}" --test-database'
    return result, command, json.dumps(result, ensure_ascii=False, indent=2)


def block(result):
    return f"{EVIDENCE_RESULT_MARKER}\n{json.dumps(result, ensure_ascii=False, separators=(',', ':'))}"


def capture(command, stdout):
    return merchant_preview_delivery.record_preview_evidence(post_bash(command, stdout))


def test_the_verified_capture_is_delivered_exactly_and_creates_nothing(evidence_run):
    result, command, stdout = evidence_run
    assert capture(command, stdout)

    note = "Partner approval of revision 1 is missing; nothing was changed."
    assert decide(f"{note}\n{block(result)}\n") is None
    assert decide(note) is not None                                     # missing block
    assert decide(block(dict(result, outcome="NEEDS_CLARIFICATION"))) is not None  # altered
    assert decide(f"{block(result)}\n{block(result)}") is not None      # twice
    assert decide(f"{block(result)}\nType /solve --confirm --merchant-scope [...]") is not None
    assert decide(f"{block(result)}\nconfirmation_command: x") is not None
    assert pending.load_records(LEAD, pending.STEP_KIND) == []
    assert pending.load_records(LEAD) == []


@pytest.mark.parametrize("forge", [
    lambda r: r.update(read_only=False),
    lambda r: r.update(authorization={"granted": True}),
    lambda r: r.update(executable=True),
    lambda r: r.update(confirmation_available=True),
    lambda r: r.update(mode="PROJECT_STATUS"),
    lambda r: r.update(database_target="runtime"),
])
def test_a_forged_capture_is_unverified(evidence_run, forge):
    result, command, _ = evidence_run
    forged = copy.deepcopy(result)
    forge(forged)

    assert not capture(command, json.dumps(forged, ensure_ascii=False))
    assert decide(block(forged)) is not None
    assert decide("EVIDENCE_DELIVERY_FAILED: the CLI output could not be verified.") is None


def test_a_runtime_read_cannot_answer_a_test_run(evidence_run):
    result, command, stdout = evidence_run

    assert not capture(command.replace(" --test-database", ""), stdout)
