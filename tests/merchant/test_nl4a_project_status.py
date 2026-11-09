"""CP12H.NL4A: natural-language, read-only Project discovery and status.

``project status --request "<user words>" [--test-database]`` resolves a
Project (exact id, exact title, Merchant + title, Merchant + status filter)
over the existing read repository and reports database-backed workflow state.
It never authorizes anything. No database: a read-only fake.
"""

from __future__ import annotations

import copy
import json
import uuid

import pytest

from claude.agents.tools.merchant.agent_cli import (
    MerchantAgentCliError,
    prepare_agent_cli_argv,
)
from claude.agents.tools.merchant.project_nl import (
    PROJECT_LIST,
    PROJECT_STATUS,
    STEP_UPDATE,
    interpret_project_request,
)
from claude.agents.tools.merchant.project_status import (
    CLARIFY,
    LIST,
    STATUS,
    build_project_status,
)
from claude.clients.merchant.repository import ProjectNotFoundError
from claude.hooks import merchant_preview_delivery
from claude.hooks.merchant_preview_delivery import STATUS_RESULT_MARKER
from tests.merchant.test_nl1_project_preview import BETA, LOTTE, merchant
from tests.merchant.test_nl2e_p1_p2_p4 import (  # noqa: F401  (fixtures)
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

P_NVC = "aaaaaaaa-0000-4000-8000-000000000001"
P_NL3 = "aaaaaaaa-0000-4000-8000-000000000002"
P_LOTTE = "aaaaaaaa-0000-4000-8000-000000000003"
P_TD1 = "aaaaaaaa-0000-4000-8000-000000000004"
P_TD2 = "aaaaaaaa-0000-4000-8000-000000000005"
P_DONE = "aaaaaaaa-0000-4000-8000-000000000006"


def summary(project_id, title, merchant_id=BETA, status="IN_PROGRESS"):
    code, name = {BETA: ("NL2_LIVE_BETA", "Beta Cinemas"),
                  LOTTE: ("LOTTE", "Lotte Cinema")}[merchant_id]
    return {
        "id": project_id, "merchant_id": merchant_id, "merchant_code": code,
        "merchant_name": name, "project_type": "OPENING_NEW_CINEMA",
        "workflow_variant": "OPENING_NEW_CINEMA_STANDARD", "title": title,
        "status": status, "requires_procurement": False,
        "created_at": "2026-11-04T06:44:38+00:00",
        "updated_at": "2026-11-04T06:44:38+00:00", "version": 1,
    }


def step(n, name, status, step_type="SEQUENTIAL"):
    return {
        "id": str(uuid.UUID(int=n)), "sequence_number": n, "step_name": name,
        "status": status, "branch_key": "b", "step_type": step_type,
        "is_optional": status == "SKIPPED", "condition_key": None, "version": 1,
        "actual_completion": "2026-11-04T07:00:00+00:00" if status == "COMPLETED" else None,
    }


def edge(a, b):
    return {"id": str(uuid.uuid4()), "from_step_id": str(uuid.UUID(int=a)),
            "to_step_id": str(uuid.UUID(int=b)), "dependency_type": "MUST_COMPLETE_BEFORE"}


# 1 done; 2 ready after 1; 3 in progress; 4 waits on 2; 5 skipped (no edges);
# 6 pending but its only predecessor (1) is complete; 7 an approval gate on 4.
STEPS = [
    step(1, "Draft or renew document", "COMPLETED"),
    step(2, "Legal review", "READY"),
    step(3, "Accounting review", "IN_PROGRESS"),
    step(4, "Send reviewed revision to Partner", "PENDING"),
    step(5, "Create Purchase Request", "SKIPPED"),
    step(6, "Create Production agent", "PENDING"),
    step(7, "Record Partner approval", "PENDING", "APPROVAL_GATE"),
]
EDGES = [edge(1, 2), edge(1, 3), edge(2, 4), edge(1, 6), edge(4, 7)]


class StatusReader:
    """Read-only fake. Any other attribute access fails the test."""

    def __init__(self, projects=None):
        self.merchants = [merchant(BETA, "NL2_LIVE_BETA", "Beta Cinemas"),
                          merchant(LOTTE, "LOTTE", "Lotte Cinema")]
        self.projects = projects if projects is not None else [
            summary(P_NVC, "Beta Nguyễn Văn Cừ"),
            summary(P_NL3, "Beta NL3 Confirmation Test", status="PLANNED"),
            summary(P_LOTTE, "Lotte Nguyễn Văn Cừ", LOTTE),
            summary(P_DONE, "Beta Quận 9", status="COMPLETED"),
        ]

    def list_merchants(self, *, status=None):
        return copy.deepcopy(self.merchants)

    def list_projects(self, *, merchant_id=None, status=None):
        return [copy.deepcopy(p) for p in self.projects
                if (merchant_id is None or p["merchant_id"] == merchant_id)
                and (status is None or p["status"] == status)]

    def get_project_detail(self, project_id):
        found = [p for p in self.projects if p["id"] == project_id]
        if not found:
            raise ProjectNotFoundError(f"Merchant project not found: {project_id}")
        return {
            "project": copy.deepcopy(found[0]), "steps": copy.deepcopy(STEPS),
            "dependencies": copy.deepcopy(EDGES), "merchant_contacts": [],
            "document_revisions": [{"id": "d1"}], "document_approvals": [],
            "procurement_records": [], "integration_identifiers": [],
        }

    def __getattr__(self, name):
        raise AssertionError(f"status used a non-read API: {name}")


def status(text, reader=None, target="test"):
    return build_project_status(text, reader or StatusReader(), database_target=target)


def seqs(items):
    return [item["sequence"] for item in items]


# --------------------------------------------------------------- discovery


@pytest.mark.parametrize(
    "text,project_id",
    [
        ("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?", P_NVC),
        ("Các bước đang chờ của Project Beta NL3 Confirmation Test là gì?", P_NL3),
        ("What is the status of project Beta NL3 Confirmation Test?", P_NL3),
        ("Which step is the project Beta Nguyễn Văn Cừ at?", P_NVC),
        (f"Which step is project {P_NL3} at?", P_NL3),
        (f"Project {P_NL3.upper()} đang ở bước nào?", P_NL3),
        ("Project Nguyễn Văn Cừ của Lotte Cinema đang ở bước nào?", P_LOTTE),
    ],
)
def test_status_question_resolves_exactly_one_project(text, project_id):
    result = status(text)

    assert result["outcome"] == STATUS, result["clarifications"]
    assert result["project"]["project_id"] == project_id
    assert result["read_only"] is True and result["authorization"] is None
    assert result["database_target"] == "test"


def test_unicode_title_and_identity_are_preserved():
    result = status("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?")

    project = result["project"]
    assert project["title"] == "Beta Nguyễn Văn Cừ"
    assert project["merchant_code"] == "NL2_LIVE_BETA"
    assert project["merchant_id"] == BETA
    assert project["project_type"] == "OPENING_NEW_CINEMA"
    assert project["workflow_variant"] == "OPENING_NEW_CINEMA_STANDARD"
    assert project["status"] == "IN_PROGRESS"
    assert project["last_updated_at"] == "2026-11-04T07:00:00+00:00"
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result


@pytest.mark.parametrize(
    "text,expected",
    [
        # Same words, two Merchants: never silently pick one.
        ("Project Nguyễn Văn Cừ đang ở bước nào?", {P_NVC, P_LOTTE}),
    ],
)
def test_ambiguous_project_returns_candidates_only(text, expected):
    result = status(text)

    assert result["outcome"] == CLARIFY
    assert result["project"] is None
    assert {c["project_id"] for c in result["candidates"]} == expected
    assert all(c["merchant_code"] for c in result["candidates"])


def test_duplicate_exact_titles_are_ambiguous():
    reader = StatusReader([summary(P_TD1, "Beta Thảo Điền"), summary(P_TD2, "Beta Thảo Điền")])

    result = status("Project Beta Thảo Điền đang ở bước nào?", reader)

    assert result["outcome"] == CLARIFY
    assert {c["project_id"] for c in result["candidates"]} == {P_TD1, P_TD2}


@pytest.mark.parametrize(
    "text",
    [
        "Những bước nào đã hoàn thành và còn vướng ở đâu?",   # no Project named
        "Project Galaxy Quận 9 đang ở bước nào?",              # no such Project
        f"Which step is project {uuid.UUID(int=99)} at?",      # unknown id
        # A real Project, but not under the Merchant the user named.
        "Project Beta NL3 Confirmation Test của Lotte Cinema đang ở bước nào?",
        "Project Beta NL3 Confirmation Test của Merchant Galaxy đang ở bước nào?",
    ],
)
def test_missing_or_incorrect_project_asks_instead_of_guessing(text):
    result = status(text)

    assert result["outcome"] == CLARIFY
    assert result["project"] is None
    assert result["clarifications"]
    assert "steps" not in result


# ------------------------------------------------------------- workflow state


def test_counts_current_steps_and_dependencies_come_from_the_database():
    result = status("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?")

    assert result["step_counts"] == {
        "total": 7, "PENDING": 3, "READY": 1, "IN_PROGRESS": 1, "BLOCKED": 0,
        "COMPLETED": 1, "SKIPPED": 1, "SUPERSEDED": 0,
    }
    # Actionable now: persisted READY / IN_PROGRESS.
    assert seqs(result["current_steps"]) == [2, 3]
    # PENDING whose predecessors are all COMPLETED: unlocked, but still PENDING.
    assert seqs(result["dependency_ready_steps"]) == [6]
    assert all(s["status"] == "PENDING" for s in result["dependency_ready_steps"])
    waiting = {s["sequence"]: s for s in result["waiting_steps"]}
    assert set(waiting) == {4, 7}
    assert seqs(waiting[4]["unmet_predecessors"]) == [2]
    assert waiting[4]["unmet_predecessors"][0]["status"] == "READY"
    assert seqs(waiting[7]["unmet_predecessors"]) == [4]


def test_skipped_is_never_reported_as_completed():
    result = status("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?")

    assert seqs(result["completed_steps"]) == [1]
    assert seqs(result["skipped_steps"]) == [5]
    assert 5 not in seqs(result["current_steps"]) + seqs(result["waiting_steps"])


def test_approvals_and_evidence_are_reported_from_stored_rows():
    result = status("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?")

    assert seqs(result["approval_gates"]) == [7]
    assert result["evidence"] == {
        "document_revisions": 1, "document_approvals": 0, "procurement_records": 0,
    }


def test_conversational_claims_do_not_change_step_state():
    claimed = status(
        "Legal review đã xong rồi, vậy Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?"
    )

    assert claimed["step_counts"]["COMPLETED"] == 1
    assert seqs(claimed["current_steps"]) == [2, 3]


# ------------------------------------------------------------------- lists


def test_merchant_project_list_is_scoped_to_that_merchant():
    result = status("Liệt kê các Project của Merchant Beta Cinemas trên database test.")

    assert result["outcome"] == LIST
    assert result["merchant"]["code"] == "NL2_LIVE_BETA"
    assert {p["project_id"] for p in result["projects"]} == {P_NVC, P_NL3, P_DONE}
    assert P_LOTTE not in {p["project_id"] for p in result["projects"]}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Liệt kê các Project đang chạy của Beta Cinemas", {P_NVC}),
        ("List the completed projects of Beta Cinemas", {P_DONE}),
        ("Liệt kê các Project đã hoàn thành của Beta Cinemas", {P_DONE}),
    ],
)
def test_merchant_project_list_honours_status_filters(text, expected):
    result = status(text)

    assert result["outcome"] == LIST
    assert {p["project_id"] for p in result["projects"]} == expected


def test_list_without_a_resolvable_merchant_asks():
    result = status("Liệt kê các Project của Merchant Galaxy")

    assert result["outcome"] == CLARIFY
    assert "projects" not in result


# ------------------------------------------------------- parser: reads stay reads


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Những bước nào đã hoàn thành và còn vướng ở đâu?", PROJECT_STATUS),
        ("Các bước đang chờ của Project Beta NL3 Confirmation Test là gì?", PROJECT_STATUS),
        ("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?", PROJECT_STATUS),
        ("Liệt kê các Project của Merchant Beta Cinemas trên database test.", PROJECT_LIST),
    ],
)
def test_status_questions_never_request_a_write(text, kind):
    result = interpret_project_request(text)

    assert result.kind == kind
    assert result.write_requested is False


@pytest.mark.parametrize(
    "text",
    [
        "Cập nhật bước Legal review của project Beta là xong",
        "Hoàn thành bước Legal review của project Beta Nguyễn Văn Cừ",
        "Mark the Legal review step of project Beta as complete",
    ],
)
def test_explicit_step_updates_are_still_step_updates(text):
    result = interpret_project_request(text)

    assert result.kind == STEP_UPDATE
    assert result.write_requested is True


class ExecuteParser:
    """The model's misreading of a status question as a write."""

    def parse(self, request):
        return {
            "request_id": "nl4a", "raw_request": request,
            "task_class": "small_task", "risk_level": "external_write",
            "operations": ["merchant_execute"], "candidate_agents": [MM],
            "selected_agents": [MM],
            "limits": {"max_members": 1, "max_tool_rounds": 1,
                       "max_total_tool_calls": 10, "max_run_budget_usd": 1.0},
            "requires_clarification": False, "requires_confirmation": True,
            "reasons": [],
        }


@pytest.mark.parametrize(
    "text,target",
    [
        ("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?", "runtime"),
        ("Những bước nào đã hoàn thành và còn vướng ở đâu?", "runtime"),
        ("Liệt kê các Project của Merchant Beta Cinemas trên database test.", "test"),
    ],
)
def test_status_requests_run_read_only_without_confirm(isolated, text, target):
    output = intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD,
         "prompt": f"/solve {text}"},
        parser_factory=ExecuteParser, env={},
    )

    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["operations"] == ["merchant_read"]
    assert run["risk_level"] == "read_only"
    assert run["merchant_read_target"] == target
    assert run.get("merchant_scope") is None


def test_explicit_step_update_runs_only_as_a_read_only_preview(isolated):
    # CP12H.NL4B changed this on purpose: an unscoped Step update was blocked
    # for --confirm; it now runs only as the read-only `step preview`, with no
    # write scope (a Step Update needs the user's separate confirmation).
    output = intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD,
         "prompt": "/solve Cập nhật bước Legal review của project Beta là xong"},
        parser_factory=ExecuteParser, env={},
    )

    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["operations"] == ["merchant_read"]
    assert run["risk_level"] == "read_only"
    assert run.get("merchant_scope") is None


# ------------------------------------------------- database target isolation


def test_agent_cli_status_reads_test_only_when_asked():
    test = prepare_agent_cli_argv(["project", "status", "--request", "x", "--test-database"])
    runtime = prepare_agent_cli_argv(["project", "status", "--request", "x"])

    assert test[:2] == ("--database", "test") and "--test-database" not in test
    assert runtime[:2] == ("--database", "runtime")


def test_other_reads_still_cannot_reach_the_test_database():
    with pytest.raises(MerchantAgentCliError):
        prepare_agent_cli_argv(["project", "list", "--test-database"])


@pytest.mark.parametrize(
    "arguments,target",
    [
        (("project", "status", "--request", "x", "--test-database"), "test"),
        (("project", "status", "--request", "x"), "runtime"),
    ],
)
def test_policy_target_check_knows_the_status_command(arguments, target):
    assert merchant_preview_delivery.command_target(arguments) == target


# ------------------------------------------------------------ result delivery


STATUS_TEST = f'{CLI} project status --request "Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?" --test-database'


@pytest.fixture
def status_run(isolated, monkeypatch):
    from claude.hooks import harness_team_identity

    assert spawn(isolated) is None  # an unscoped merchant_read run on test
    monkeypatch.setattr(
        harness_team_identity, "verified_teammate_pane",
        lambda owner, name: "7000:%7" if (owner, name) == (LEAD, MM) else None,
    )
    result = status("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?")
    return result, json.dumps(result, ensure_ascii=False, indent=2)


def report(body):
    return {
        "hook_event_name": "PreToolUse", "session_id": "nl2e-pane",
        "agent_type": MM, "tool_name": "SendMessage",
        "tool_input": {"to": "team-lead", "message": body},
    }


def decide(body):
    return merchant_preview_delivery.preview_delivery_decision(report(body), deny)


def exact(result):
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def test_verified_status_is_delivered_only_as_the_exact_cli_object(status_run):
    result, stdout = status_run
    assert merchant_preview_delivery.record_preview_evidence(post_bash(STATUS_TEST, stdout))

    summary_text = "Beta Nguyễn Văn Cừ is IN_PROGRESS; Legal review is READY."
    assert decide(f"{summary_text}\n{STATUS_RESULT_MARKER}\n{exact(result)}\n") is None
    # Missing, altered or duplicated object: refused.
    assert decide(summary_text) is not None
    altered = dict(result, step_counts=dict(result["step_counts"], COMPLETED=5))
    assert decide(f"{STATUS_RESULT_MARKER}\n{exact(altered)}") is not None
    twice = f"{STATUS_RESULT_MARKER}\n{exact(result)}\n{STATUS_RESULT_MARKER}\n{exact(result)}"
    assert decide(twice) is not None


def test_status_block_without_verified_capture_is_refused(status_run):
    result, stdout = status_run
    merchant_preview_delivery.record_preview_evidence(post_bash(STATUS_TEST, "garbled " + stdout[:50]))

    assert decide(f"{STATUS_RESULT_MARKER}\n{exact(result)}") is not None
    assert decide("STATUS_DELIVERY_FAILED: the status output could not be verified.") is None


def test_status_block_with_no_status_run_is_refused(status_run):
    result, _ = status_run

    assert decide(f"{STATUS_RESULT_MARKER}\n{exact(result)}") is not None


def test_status_read_never_grants_write_authority(status_run):
    result, stdout = status_run
    merchant_preview_delivery.record_preview_evidence(post_bash(STATUS_TEST, stdout))

    assert runtime_state.load_state(LEAD).get("merchant_scope") is None
    assert result["authorization"] is None
