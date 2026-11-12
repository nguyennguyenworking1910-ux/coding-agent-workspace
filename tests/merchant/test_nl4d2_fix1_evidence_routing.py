"""CP12H.NL4D2-FIX1: Merchant evidence questions are routed to merchant-manager.

Live failure: "/solve Bước Partner Approval của Project Beta NL4C2B Step
Acceptance còn thiếu gì trên database test?" reached the gate as
``selected_agents = ["diagnostician"]``. The model classified it as a data
diagnosis, and the local Merchant guardrail claimed only Project types and
Step updates, so nothing corrected the roster.

These tests drive the real ``IntentParser`` with that model decision (and
others), then the real intent gate, so they cover the entry point and not
only the text parser.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SYSTEM_DIR = Path(__file__).resolve().parents[2] / ".claude" / "system"
sys.path.insert(0, str(SYSTEM_DIR))

from intent_parser import Domain, IntentParser, Operation  # noqa: E402
from schemas import RiskLevel  # noqa: E402

from claude.agents.tools.merchant.evidence_status import build_evidence_status  # noqa: E402
from claude.agents.tools.merchant.project_nl import (  # noqa: E402
    EVIDENCE_STATUS,
    interpret_project_request,
)
from claude.hooks import merchant_direct_handoff as handoff  # noqa: E402
from claude.hooks import merchant_pending_confirmation as pending  # noqa: E402
from tests.merchant.test_merchant_intent_routing import (  # noqa: E402
    CLAUDE_DIR,
    FakeClient,
    _decision,
)
from tests.merchant.test_nl2e_p1_p2_p4 import (  # noqa: E402,F401  (fixtures)
    LEAD,
    intent_gate,
    isolated,
    runtime_state,
)
from tests.merchant.test_nl4d2_evidence_discovery import EvidenceReader, NAMED  # noqa: E402

LIVE = ("Bước Partner Approval của Project Beta NL4C2B Step Acceptance còn thiếu gì "
        "trên database test?")
# The live model decision: a read-only data diagnosis for the diagnostician.
DIAGNOSE = _decision(operations=[Operation.DIAGNOSE], domains=[Domain.DATA])
CODE_DIAGNOSE = _decision(operations=[Operation.DIAGNOSE], domains=[Domain.CODE])
CODE_REVIEW = _decision(operations=[Operation.REVIEW], domains=[Domain.CODE])

EVIDENCE_QUESTIONS = [
    LIVE,
    "Bước Partner Approval của Project Beta NL4C2B Step Acceptance còn thiếu gì?",
    "Project Beta NL4C2B Step Acceptance còn thiếu giấy tờ gì trên database test?",
    "Project Beta NL4C2B Step Acceptance còn thiếu giấy tờ và phê duyệt gì trên database test?",
    "Legal Review của Project Beta NL4C2B Step Acceptance đang chờ điều kiện nào?",
    "Legal Review đang chờ điều kiện nào?",
    "Step 8 của Project Beta NL4C2B Step Acceptance bị chặn vì sao?",
    "Bước 8 bị chặn vì sao?",
    "What is missing for Partner Approval?",
    "What is missing for Partner Approval of project Beta NL4C2B Step Acceptance?",
    "Which approvals are still required for project Beta NL4C2B Step Acceptance?",
    "What blocks Step 8?",
    "What blocks Step 8 of project Beta NL4C2B Step Acceptance on the test database?",
]


def parse(text, decision=DIAGNOSE):
    return IntentParser(CLAUDE_DIR / "agents.json", client=FakeClient(decision)).parse(text)


def submit(text, decision=DIAGNOSE):
    class Model:
        def parse(self, request):
            return parse(request, decision)

    return intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD, "prompt": f"/solve {text}"},
        parser_factory=Model, env={},
    )


# ----------------------------------------------------------- entry point


def test_the_live_request_reaches_merchant_manager_as_a_test_read(isolated):
    output = submit(LIVE)

    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["selected_agents"] == ["merchant-manager"]
    assert run["operations"] == ["merchant_read"] and run["risk_level"] == "read_only"
    assert run["merchant_read_target"] == "test"
    assert run["confirmed"] is False and run.get("merchant_scope") is None
    envelope = intent_gate.load_intent_envelope(LEAD)
    assert envelope["requires_confirmation"] is False
    assert envelope["merchant_database_target"] == "test"
    assert any("local guardrail" in r for r in envelope["reasons"])
    assert pending.load_records(LEAD) == [] and pending.load_records(LEAD, pending.STEP_KIND) == []


@pytest.mark.parametrize("text", EVIDENCE_QUESTIONS)
def test_evidence_questions_are_merchant_reads_whatever_the_model_says(text):
    envelope = parse(text)

    assert envelope.operations == ["merchant_read"]
    assert envelope.selected_agents == ["merchant-manager"]
    assert envelope.risk_level == RiskLevel.READ_ONLY
    assert interpret_project_request(text).kind == EVIDENCE_STATUS


@pytest.mark.parametrize("text", [
    "Step 8 của Project Beta NL4C2B Step Acceptance bị chặn vì sao?",
    "What blocks Step 8 of project Beta NL4C2B Step Acceptance on the test database?",
])
def test_the_routed_read_answers_with_the_domain_gate(text):
    result = build_evidence_status(text.replace("Beta NL4C2B Step Acceptance", NAMED[8:]),
                                   EvidenceReader(), database_target="test")

    assert result["outcome"] == "EVIDENCE_STATUS"
    assert result["focus_step"]["sequence"] == 8
    assert result["focus_step"]["gate"]["gate_status"] == "NOT_MET"


def test_no_project_is_inferred_for_a_step_only_question():
    result = build_evidence_status("What blocks Step 8?", EvidenceReader(), database_target="test")

    assert result["outcome"] == "NEEDS_CLARIFICATION" and result["project"] is None


# ------------------------------------------------------------- negatives


@pytest.mark.parametrize("text,decision", [
    ("Diagnose the Step Preview parser.", CODE_DIAGNOSE),
    ("Find the bug in intent_gate.py.", CODE_DIAGNOSE),
    ("Why do merchant tests fail?", CODE_DIAGNOSE),
    ("Review the Project evidence implementation.", CODE_REVIEW),
    ("What blocks the CI pipeline step for the evidence module?", CODE_DIAGNOSE),
    ("Which approvals are still required?", CODE_REVIEW),        # no Merchant context
    ("Why is step 3 of the pytest fixture setup blocked?", CODE_DIAGNOSE),
])
def test_code_questions_stay_code_work(text, decision):
    envelope = parse(text, decision)

    assert "merchant-manager" not in envelope.selected_agents
    assert not set(envelope.operations) & {"merchant_read", "merchant_execute"}


@pytest.mark.parametrize("text", [
    "Ghi nhận Partner đã duyệt tài liệu của Project Beta NL4C2B Step Acceptance",
    "Approve the latest document of project Beta NL4C2B Step Acceptance",
    "Upload tài liệu mới cho Project Beta NL4C2B Step Acceptance",
])
def test_evidence_writes_are_never_downgraded_to_the_read(isolated, text):
    assert interpret_project_request(text).kind != EVIDENCE_STATUS
    submit(text, _decision(operations=[Operation.MERCHANT_EXECUTE], domains=[Domain.MERCHANT],
                           risk_level=RiskLevel.EXTERNAL_WRITE))
    run = runtime_state.load_state(LEAD)
    # Never the evidence-status read. CP12H.NL4D3 supersedes the original
    # "never merchant_read" check: an unscoped evidence write now runs only as
    # the read-only `evidence preview`, so the run is refused, or read-only,
    # unconfirmed and unscoped, and creates no pending confirmation.
    assert run is None or (run["risk_level"] == "read_only"
                           and run["confirmed"] is False
                           and run.get("merchant_scope") is None)
    assert pending.load_records(LEAD) == [] and pending.load_records(LEAD, pending.STEP_KIND) == []


def test_a_mixed_request_is_not_a_read():
    text = ("Project Beta NL4C2B Step Acceptance còn thiếu giấy tờ gì, rồi xóa Merchant "
            "Beta Cinemas")
    envelope = parse(text, _decision(operations=[Operation.MERCHANT_EXECUTE],
                                     domains=[Domain.MERCHANT],
                                     risk_level=RiskLevel.DESTRUCTIVE))

    assert envelope.operations != ["merchant_read"]
    assert envelope.risk_level != RiskLevel.READ_ONLY


def test_runtime_direct_execute_stays_disabled():
    assert handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False
    # CP12H.NL4D4A: the confirmed Purchase Request joined test mode.
    assert handoff.TEST_MODE_COMMANDS == {"merchant create", "project create", "step update",
                                          "procurement update",
                                          # CP12H.MASTER: confirmed lifecycle operations.
                                          "document revision-create", "document approve",
                                          "document sign", "project update"}


# ------------------------------------------------------- dispatch (policy gate)


def test_only_merchant_manager_can_be_dispatched_for_the_live_request(isolated):
    from tests.merchant.test_nl2e_p1_p2_p4 import policy_gate

    assert submit(LIVE).get("decision") != "block"
    assignment = ("operation: merchant_read\ndatabase_target: test\n"
                  "Answer what evidence the named step still lacks.")

    with runtime_state.locked_state(LEAD) as state:
        refused = policy_gate.apply_call(
            state, "Agent",
            {"subagent_type": "diagnostician", "name": "diagnostician", "prompt": assignment},
            LEAD)
    assert refused is not None
    assert refused["hookSpecificOutput"]["permissionDecision"] == "deny"

    with runtime_state.locked_state(LEAD) as state:
        allowed = policy_gate.apply_call(
            state, "Agent",
            {"subagent_type": "merchant-manager", "name": "merchant-manager", "prompt": assignment},
            LEAD)
    assert allowed is None
