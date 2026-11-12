"""CP12H.NL4B: natural-language, read-only Step Update preview.

``step preview --request "<user words>" [--test-database]`` resolves one
Project and one Step from the user's words and applies the write path's own
checks (transition table, dependencies, stored-evidence gates, the domain
planner) to the read snapshot. It never writes, reserves, claims or confirms.
No database: a read-only fake with timezone-aware datetimes.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone

import pytest

from claude.agents.tools.merchant.agent_cli import (
    MerchantAgentCliError,
    prepare_agent_cli_argv,
)
from claude.agents.tools.merchant.project_nl import (
    PROJECT_STATUS,
    STEP_UPDATE,
    interpret_project_request,
)
from claude.agents.tools.merchant.step_preview import (
    BLOCKED,
    CLARIFY,
    READY,
    build_step_update_preview,
)
from claude.clients.merchant.repository import ProjectNotFoundError
from claude.hooks import merchant_preview_delivery
from claude.hooks.merchant_preview_delivery import (
    STEP_PREVIEW_DELIVERY_FAILED,
    STEP_PREVIEW_MARKER,
)
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
from tests.merchant.test_nl4a_project_status import ExecuteParser, report

P_NVC = "bbbbbbbb-0000-4000-8000-000000000001"
P_LOTTE = "bbbbbbbb-0000-4000-8000-000000000002"
P_INT = "bbbbbbbb-0000-4000-8000-000000000003"
REV = "cccccccc-0000-4000-8000-000000000001"
T0 = datetime(2026, 11, 4, 7, 0, tzinfo=timezone.utc)
NVC = "Project Beta Nguyễn Văn Cừ"


def project(project_id, title, merchant_id=BETA, project_type="OPENING_NEW_CINEMA"):
    code, name = {BETA: ("NL2_LIVE_BETA", "Beta Cinemas"),
                  LOTTE: ("LOTTE", "Lotte Cinema")}[merchant_id]
    return {
        "id": project_id, "merchant_id": merchant_id, "merchant_code": code,
        "merchant_name": name, "project_type": project_type,
        "workflow_variant": project_type + "_STANDARD", "title": title,
        "status": "IN_PROGRESS", "requires_procurement": False,
        "created_at": T0, "updated_at": T0, "version": 3,
    }


def step(n, name, status, step_type="SEQUENTIAL", optional=False):
    return {
        "id": str(uuid.UUID(int=n)), "project_id": None, "sequence_number": n,
        "template_step_id": str(uuid.UUID(int=1000 + n)),
        "step_name": name, "status": status, "branch_key": "b",
        "step_type": step_type, "is_optional": optional, "condition_key": None,
        "version": 2 if status != "PENDING" else 1,
        "actual_start": T0 if status in ("IN_PROGRESS", "COMPLETED") else None,
        "actual_completion": T0 if status == "COMPLETED" else None,
    }


def edge(a, b):
    return {"id": str(uuid.uuid4()), "from_step_id": str(uuid.UUID(int=a)),
            "to_step_id": str(uuid.UUID(int=b)), "dependency_type": "MUST_COMPLETE_BEFORE"}


# 1 done; 2 ready; 3 in progress; 4 waits on 2 and 3; 5 optional, pending;
# 6 partner-approval gate in progress (DB gate); 7 UAT gate in progress (no
# DB evaluator); 8 "Legal sign-off" (partial-name sibling of 2); 9 skipped.
STEPS = [
    step(1, "Draft or renew document", "COMPLETED"),
    step(2, "Legal Review", "READY"),
    step(3, "Accounting Review", "IN_PROGRESS"),
    step(4, "Send reviewed revision to Partner", "PENDING"),
    step(5, "Create Purchase Request", "PENDING", optional=True),
    step(6, "Record Partner approval", "IN_PROGRESS", "APPROVAL_GATE"),
    step(7, "Complete UAT acceptance", "IN_PROGRESS", "APPROVAL_GATE"),
    step(8, "Legal sign-off", "PENDING"),
    step(9, "Kick-off meeting", "SKIPPED", optional=True),
]
EDGES = [edge(1, 2), edge(1, 3), edge(2, 4), edge(3, 4), edge(1, 5), edge(1, 6),
         edge(1, 7), edge(1, 8)]


def revision(project_id):
    return {"id": REV, "project_id": project_id, "document_type": "CONTRACT",
            "revision_number": 1, "superseded_by": None, "signed": False}


PARTNER_OK = {"id": "a1", "document_revision_id": REV, "approver_role": "PARTNER",
              "approval_status": "APPROVED", "approved_at": T0}


class StepReader:
    """Read-only fake. Any other attribute access fails the test."""

    def __init__(self, steps=None, revisions=(), approvals=()):
        self.merchants = [merchant(BETA, "NL2_LIVE_BETA", "Beta Cinemas"),
                          merchant(LOTTE, "LOTTE", "Lotte Cinema")]
        self.projects = [
            project(P_NVC, "Beta Nguyễn Văn Cừ"),
            project(P_LOTTE, "Lotte Nguyễn Văn Cừ", LOTTE),
            project(P_INT, "Beta Integration", project_type="INTEGRATION_NEW_MERCHANT"),
        ]
        self.steps = steps if steps is not None else STEPS
        self.revisions = list(revisions)
        self.approvals = list(approvals)

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
        return copy.deepcopy({
            "project": found[0],
            "steps": [dict(s, project_id=project_id) for s in self.steps],
            "dependencies": EDGES, "merchant_contacts": [],
            "document_revisions": self.revisions, "document_approvals": self.approvals,
            "procurement_records": [], "integration_identifiers": [],
        })

    def __getattr__(self, name):
        raise AssertionError(f"step preview used a non-read API: {name}")


def preview(text, reader=None, target="test"):
    return build_step_update_preview(text, reader or StepReader(), database_target=target)


def codes(result):
    return [b["code"] for b in result["blocking"]]


# ----------------------------------------------------------- interpretation


@pytest.mark.parametrize(
    "text,reference,target",
    [
        (f"Đánh dấu bước Legal Review của {NVC} là hoàn thành", "Legal Review", "COMPLETED"),
        (f"Cập nhật bước 2 của {NVC} thành đang thực hiện", "2", "IN_PROGRESS"),
        (f"Mark step 3 of project Beta Nguyễn Văn Cừ as completed", "3", "COMPLETED"),
        (f"Bỏ qua bước 5 của {NVC}", "5", "SKIPPED"),
        (f"Start step 2 of project Beta Nguyễn Văn Cừ", "2", "IN_PROGRESS"),
    ],
)
def test_vn_and_en_step_updates_are_parsed(text, reference, target):
    result = interpret_project_request(text)

    assert result.kind == STEP_UPDATE
    assert (result.step_reference, result.target_status) == (reference, target)


@pytest.mark.parametrize(
    "text",
    [
        f"Bước Legal Review của {NVC} đã hoàn thành chưa?",
        "Is the Legal Review step of project Beta Nguyễn Văn Cừ completed?",
    ],
)
def test_read_questions_are_not_step_updates(text):
    assert interpret_project_request(text).kind == PROJECT_STATUS
    result = preview(text)
    assert result["outcome"] == CLARIFY and result["step"] is None


# ------------------------------------------------------------ eligibility


def test_eligible_update_is_ready_and_carries_identity_and_versions():
    result = preview(f"Bắt đầu bước 2 của {NVC}")

    assert result["outcome"] == READY, result["blocking"]
    assert result["project"]["project_id"] == P_NVC
    assert result["project"]["title"] == "Beta Nguyễn Văn Cừ"  # Unicode kept
    assert result["project"]["version"] == 3
    assert (result["step"]["sequence"], result["step"]["name"], result["step"]["version"]) == (2, "Legal Review", 2)
    assert result["transition"] == {
        "current_status": "READY", "target_status": "IN_PROGRESS", "supported": True,
        "is_reopen": False, "event_type": result["transition"]["event_type"],
        "expected_version": 2, "new_version": 3,
    }
    assert result["unmet_dependencies"] == [] and result["gate"] is None
    assert result["project_state"]["step_counts"]["total"] == len(STEPS)


def test_in_progress_step_can_complete_in_english():
    result = preview("Mark step 3 of project Beta Nguyễn Văn Cừ as completed")
    assert result["outcome"] == READY and result["transition"]["target_status"] == "COMPLETED"


def test_unsupported_transition_is_blocked():
    result = preview(f"Đánh dấu bước Legal Review của {NVC} là hoàn thành")  # READY -> COMPLETED

    assert result["outcome"] == BLOCKED
    assert result["transition"]["supported"] is False
    assert codes(result) == ["TRANSITION_NOT_ALLOWED"]


def test_already_in_status_is_blocked():
    assert codes(preview(f"Đánh dấu bước 1 của {NVC} là hoàn thành")) == ["ALREADY_IN_STATUS"]


def test_unmet_dependencies_are_listed_in_sequence_order():
    result = preview(f"Cập nhật bước 4 của {NVC} thành sẵn sàng")

    assert result["outcome"] == BLOCKED and codes(result) == ["UNMET_DEPENDENCIES"]
    assert [s["sequence"] for s in result["unmet_dependencies"]] == [2, 3]


def test_skipping_an_optional_pending_step_is_previewed():
    result = preview(f"Bỏ qua bước 5 của {NVC}")
    assert result["outcome"] == READY and result["transition"]["target_status"] == "SKIPPED"


@pytest.mark.parametrize(
    "text,code",
    [
        (f"Đánh dấu bước 9 của {NVC} là hoàn thành", "TRANSITION_NOT_ALLOWED"),
        (f"Cập nhật bước 9 của {NVC} thành sẵn sàng", "REOPEN_NOT_PREVIEWED"),
    ],
)
def test_skipped_step_is_never_completed_or_silently_reopened(text, code):
    result = preview(text)
    assert result["outcome"] == BLOCKED and codes(result) == [code]


def test_database_gate_without_evidence_is_blocked():
    result = preview(f"Đánh dấu bước 6 của {NVC} là hoàn thành")

    assert result["outcome"] == BLOCKED and codes(result) == ["GATE_NOT_MET"]
    assert result["gate"]["database_verifiable"] is True
    assert "MISSING_DOCUMENT_REVISION" in result["gate"]["blocking_codes"]
    assert "result" not in result["gate"]


def test_database_gate_with_stored_approval_is_ready():
    reader = StepReader(revisions=[revision(P_NVC)], approvals=[PARTNER_OK])
    result = preview(f"Đánh dấu bước 6 của {NVC} là hoàn thành", reader)

    assert result["outcome"] == READY, result["blocking"]
    assert result["gate"]["all_met"] is True and result["gate"]["approved_roles"] == ["PARTNER"]


def test_another_projects_revision_never_satisfies_the_gate():
    reader = StepReader(revisions=[revision(P_LOTTE)], approvals=[PARTNER_OK])
    assert codes(preview(f"Đánh dấu bước 6 của {NVC} là hoàn thành", reader)) == ["GATE_NOT_MET"]


def test_gate_with_no_database_evaluator_is_completed_only_by_attestation():
    # CP12H.MASTER (owner-approved DEC-SIMPLIFY P7): an evaluator-less gate no
    # longer blocks forever. Completing it is READY only as the user's
    # confirmed, operator-attested operation; nothing is verified by data.
    result = preview(f"Đánh dấu bước 7 của {NVC} là hoàn thành")

    assert result["outcome"] == READY, result["blocking"]
    assert result["gate"]["kind"] == "OPERATOR_ATTESTATION"
    assert result["gate"]["database_verifiable"] is False
    assert result["requested_operation"]["gate_attestation"] == "OPERATOR_ATTESTED"
    assert result["requested_operation"]["argv"][-2:] == ["--gate-attestation", "OPERATOR_ATTESTED"]


def test_an_integration_step_completion_is_previewed_with_its_attestation():
    # CP12H.MASTER: only the activation Step activates the Merchant (and that
    # is re-checked in the same transaction), so other INTEGRATION_NEW_MERCHANT
    # Steps are no longer blanket-blocked.
    result = preview("Mark step 3 of project Beta Integration as completed")
    assert "MERCHANT_ACTIVATION_NOT_PREVIEWED" not in codes(result)
    assert result["outcome"] == READY, result["blocking"]


# --------------------------------------------------------- clarification


@pytest.mark.parametrize(
    "text",
    [
        f"Cập nhật bước 2 của {NVC}",                       # no target status
        f"Đừng đánh dấu bước 2 của {NVC} là hoàn thành",     # negated
        "Đánh dấu bước 2 là hoàn thành",                    # no Project
        f"Đánh dấu bước 42 của {NVC} là hoàn thành",          # no such step
        "Đánh dấu bước 2 của Project Nguyễn Văn Cừ là hoàn thành",  # 2 Projects
        f"Đánh dấu bước 2 và bước 3 của {NVC} là hoàn thành",  # 2 steps
    ],
)
def test_incomplete_or_ambiguous_requests_ask(text):
    result = preview(text)

    assert result["outcome"] == CLARIFY and result["clarifications"]
    assert result["step"] is None and result["transition"] is None


def test_partial_step_name_is_offered_never_bound():
    result = preview(f"Đánh dấu bước Legal của {NVC} là hoàn thành")

    assert result["outcome"] == CLARIFY and result["step"] is None
    assert sorted(c["name"] for c in result["candidates"]) == ["Legal Review", "Legal sign-off"]


def test_duplicate_exact_step_names_are_ambiguous():
    steps = STEPS + [dict(step(10, "Legal Review", "READY"))]
    result = preview(f"Bắt đầu bước Legal Review của {NVC}", StepReader(steps=steps))

    assert result["outcome"] == CLARIFY
    assert sorted(c["sequence"] for c in result["candidates"]) == [2, 10]


# ---------------------------------------------------------- read-only proof


def test_preview_is_data_and_never_authorizes_or_mutates():
    reader = StepReader()
    before = copy.deepcopy((reader.projects, reader.steps, reader.revisions))
    result = preview(f"Bắt đầu bước 2 của {NVC}", reader)

    assert result["outcome"] == READY
    assert result["read_only"] is True and result["executable"] is False
    # CP12H.NL4C (intentional change): a READY test-database preview may be
    # confirmed by the user; that is not authorization.
    assert result["confirmation_available"] is True and result["authorization"] is None
    text = json.dumps(result, default=str)
    for forbidden in ("confirmation_command", "--merchant-scope"):
        assert forbidden not in text
    # CP12H.NL4C1 (intentional change): a READY preview names its exact
    # operation as data, never as authority.
    assert result["requested_operation"]["status"] == "NOT_AUTHORIZED"
    assert (reader.projects, reader.steps, reader.revisions) == before


# ------------------------------------------------- intent gate and adapter


@pytest.mark.parametrize(
    "text,target",
    [
        (f"Đánh dấu bước Legal Review của {NVC} là hoàn thành trên database test", "test"),
        ("Mark step 3 of project Beta Nguyễn Văn Cừ as completed", "runtime"),
    ],
)
def test_unscoped_step_update_runs_only_as_a_read(isolated, text, target):
    output = intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD, "prompt": f"/solve {text}"},
        parser_factory=ExecuteParser, env={},
    )

    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["operations"] == ["merchant_read"] and run["risk_level"] == "read_only"
    assert run["merchant_read_target"] == target
    assert run.get("merchant_scope") is None


def test_agent_cli_step_preview_reads_test_only_when_asked():
    test = prepare_agent_cli_argv(["step", "preview", "--request", "x", "--test-database"])
    runtime = prepare_agent_cli_argv(["step", "preview", "--request", "x"])

    assert test[:2] == ("--database", "test") and "--test-database" not in test
    assert runtime[:2] == ("--database", "runtime")
    assert merchant_preview_delivery.command_target(("step", "preview", "--request", "x", "--test-database")) == "test"


@pytest.mark.parametrize(
    "argv",
    [
        ["step", "update", "--test-database"],
        ["step", "resolve", "--project-id", P_NVC, "--query", "x", "--test-database"],
    ],
)
def test_step_writes_and_other_reads_cannot_reach_the_test_database(argv):
    with pytest.raises(MerchantAgentCliError):
        prepare_agent_cli_argv(argv)


# ------------------------------------------------------------ result delivery


STEP_TEXT = f"Bắt đầu bước 2 của {NVC}"
STEP_TEST = f'{CLI} step preview --request "{STEP_TEXT}" --test-database'


@pytest.fixture
def step_run(isolated, monkeypatch):
    from claude.hooks import harness_team_identity, merchant_pending_confirmation

    assert spawn(isolated) is None  # an unscoped merchant_read run on test
    monkeypatch.setattr(
        harness_team_identity, "verified_teammate_pane",
        lambda owner, name: "7000:%7" if (owner, name) == (LEAD, MM) else None,
    )

    def no_pending(*args, **kwargs):
        raise AssertionError("a Step preview created a pending confirmation")

    monkeypatch.setattr(merchant_pending_confirmation, "record_pending", no_pending)
    return lambda text=STEP_TEXT, reader=None: (
        lambda result: (result, json.dumps(result, ensure_ascii=False, indent=2, default=str))
    )(json.loads(json.dumps(preview(text, reader), default=str)))


def decide(body):
    return merchant_preview_delivery.preview_delivery_decision(report(body), deny)


def block(result):
    return f"{STEP_PREVIEW_MARKER}\n{json.dumps(result, ensure_ascii=False, separators=(',', ':'))}"


def capture(command, stdout):
    return merchant_preview_delivery.record_preview_evidence(post_bash(command, stdout))


def test_ready_step_preview_is_delivered_as_the_exact_cli_object(step_run):
    result, stdout = step_run()
    assert result["outcome"] == READY
    assert capture(STEP_TEST, stdout)

    note = "Step 2 Legal Review is READY_FOR_CONFIRMATION under the domain rules; nothing was updated."
    assert decide(f"{note}\n{block(result)}\n") is None
    assert decide(note) is not None                                    # missing
    assert decide(block(dict(result, outcome=BLOCKED))) is not None     # altered
    assert decide(f"{block(result)}\n{block(result)}") is not None      # twice


@pytest.mark.parametrize(
    "extra",
    [
        "Confirm with /solve --confirm --merchant-scope [step update ...]",
        'confirmation_command: "/solve Xác nhận"',
        "MERCHANT_PREVIEW_OPERATION_JSON: {}",
        "PREVIEW_DELIVERY_FAILED: none",
    ],
)
def test_step_preview_report_never_carries_confirmation_or_operation(step_run, extra):
    result, stdout = step_run()
    capture(STEP_TEST, stdout)

    assert decide(f"{block(result)}\n{extra}") is not None


def test_blocked_step_preview_cannot_be_presented_as_ready(step_run):
    text = f"Đánh dấu bước Legal Review của {NVC} là hoàn thành"
    result, stdout = step_run(text)
    command = f'{CLI} step preview --request "{text}" --test-database'
    assert result["outcome"] == BLOCKED and capture(command, stdout)

    assert decide(f"Blocked: TRANSITION_NOT_ALLOWED.\n{block(result)}") is None
    assert decide(f"This step is ready for confirmation.\n{block(result)}") is not None
    assert decide(f"It is not READY_FOR_CONFIRMATION.\n{block(result)}") is None


def test_unverified_capture_is_only_a_delivery_failure(step_run):
    result, stdout = step_run()
    assert not capture(STEP_TEST, "garbled " + stdout[:40])

    assert decide(block(result)) is not None
    assert decide("The preview could not be verified.") is not None
    assert decide(f"{STEP_PREVIEW_DELIVERY_FAILED}: output could not be verified.") is None


def test_forged_flags_are_never_verified(step_run):
    result, _ = step_run()
    forged = dict(result, executable=True)
    assert not capture(STEP_TEST, json.dumps(forged, ensure_ascii=False))


def test_step_block_with_no_capture_is_refused(step_run):
    result, _ = step_run()
    assert decide(block(result)) is not None


def test_step_preview_never_grants_write_authority(step_run):
    result, stdout = step_run()
    capture(STEP_TEST, stdout)  # record_pending would raise

    run = runtime_state.load_state(LEAD)
    assert run.get("merchant_scope") is None and run["operations"] == ["merchant_read"]
