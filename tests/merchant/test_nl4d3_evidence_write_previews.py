"""CP12H.NL4D3: read-only natural-language evidence, approval and procurement previews.

Every preview judges the request with the domain's own engine
(``propose_document_revision``, ``propose_document_approval``,
``propose_procurement_mutation``) on a stored snapshot and grants nothing:
``read_only`` is true, ``executable`` and ``confirmation_available`` false, no
``requested_operation``, argv, scope or pending confirmation, and an approval
that the domain accepts still stops at POLICY_UNDECIDED (NL4D1 S1).
"""

from __future__ import annotations

import copy
import json
import sys
import unicodedata
from pathlib import Path

import pytest

SYSTEM_DIR = Path(__file__).resolve().parents[2] / ".claude" / "system"
sys.path.insert(0, str(SYSTEM_DIR))

from intent_parser import Domain, IntentParser, Operation  # noqa: E402
from schemas import RiskLevel  # noqa: E402

from claude.agents.tools.merchant.agent_cli import (  # noqa: E402
    MerchantAgentCliError,
    prepare_agent_cli_argv,
)
from claude.agents.tools.merchant.cli_contract import READ_COMMANDS, WRITE_COMMANDS  # noqa: E402
from claude.agents.tools.merchant.evidence_preview import (  # noqa: E402
    BLOCKED,
    CLARIFY,
    MODE,
    POLICY_UNDECIDED,
    VALID,
    build_evidence_preview,
)
from claude.agents.tools.merchant.project_nl import (  # noqa: E402
    EVIDENCE_STATUS,
    EVIDENCE_WRITE,
    MIXED,
    PROJECT_CREATE,
    STEP_UPDATE,
    interpret_project_request,
)
from claude.hooks import merchant_direct_handoff as handoff  # noqa: E402
from claude.hooks import merchant_pending_confirmation as pending  # noqa: E402
from claude.hooks import merchant_preview_delivery  # noqa: E402
from tests.merchant.test_merchant_intent_routing import CLAUDE_DIR, FakeClient, _decision  # noqa: E402
from tests.merchant.test_nl2e_p1_p2_p4 import (  # noqa: E402,F401 (fixtures)
    CLI,
    LEAD,
    MM,
    intent_gate,
    isolated,
    post_bash,
    runtime_state,
    spawn,
)
from tests.merchant.test_nl4a_project_status import decide  # noqa: E402
from tests.merchant.test_nl4d2_evidence_discovery import (  # noqa: E402
    NAMED,
    P,
    P_PROC,
    TITLE,
    EvidenceReader,
    approval,
    pr,
    revision,
)

PROC = f"Project {TITLE} Procurement"
EXECUTE = _decision(operations=[Operation.MERCHANT_EXECUTE], domains=[Domain.MERCHANT],
                    risk_level=RiskLevel.EXTERNAL_WRITE)
DIAGNOSE = _decision(operations=[Operation.DIAGNOSE], domains=[Domain.DATA])
CODE = _decision(operations=[Operation.DIAGNOSE], domains=[Domain.CODE])


def preview(text, reader=None, target="test"):
    result = build_evidence_preview(text, reader or EvidenceReader(), database_target=target)
    return json.loads(json.dumps(result, default=str))


def assert_grants_nothing(result):
    assert result["mode"] == MODE
    assert result["read_only"] is True
    assert result["executable"] is False
    assert result["confirmation_available"] is False
    assert result["authorization"] is None
    assert result["requested_operation"] is None
    text = json.dumps(result, ensure_ascii=False)
    for forbidden in ("argv", "--merchant-scope", "confirmation_command", "Xác nhận",
                      "SECRET-HASH-VALUE", "SECRET-NOTE"):
        assert forbidden not in text, forbidden


# ------------------------------------------------------------------ parsing

WRITE_REQUESTS = [
    f"Ghi nhận Purchase Request PR-001 cho {NAMED}.",
    f"Ghi nhận Purchase Order PO-001 cho {NAMED}.",
    f"Ghi nhận Payment Request PAY-001 cho {NAMED}.",
    f"Thêm revision tài liệu cho {NAMED}.",
    f"Legal đã phê duyệt revision mới nhất của {NAMED}.",
    f"Record Accounting approval for {NAMED}.",
    "Register Partner approval for the latest revision.",
    f"Add Partner approval for {NAMED}",
    f"Kế toán đã duyệt tài liệu của {NAMED}",
    f"Upload a new CONTRACT revision for {NAMED}, content hash sha256:abc",
]


@pytest.mark.parametrize("text", WRITE_REQUESTS)
def test_record_requests_are_evidence_writes(text):
    parsed = interpret_project_request(text)

    assert parsed.kind == EVIDENCE_WRITE
    assert parsed.write_requested is True


@pytest.mark.parametrize("text", [
    f"Legal đã phê duyệt revision mới nhất của {NAMED} chưa?",
    f"Has Partner approved the latest revision of {NAMED}?",
    f"{NAMED} đã có Purchase Order chưa?",
    f"Which approvals are still missing for {NAMED}?",
])
def test_approval_questions_stay_evidence_reads(text):
    assert interpret_project_request(text).kind == EVIDENCE_STATUS


@pytest.mark.parametrize("text", [
    f"Đừng ghi nhận Purchase Request PR-001 cho {NAMED}",
    f"Don't record Accounting approval for {NAMED}",
    f"Legal chưa phê duyệt revision mới nhất của {NAMED}",
])
def test_negated_requests_request_no_write(text):
    parsed = interpret_project_request(text)

    assert parsed.kind == EVIDENCE_WRITE and parsed.negated and not parsed.write_requested
    result = preview(text)
    assert result["outcome"] == CLARIFY
    assert_grants_nothing(result)


@pytest.mark.parametrize("text", [
    f"Ghi nhận Purchase Request PR-001 cho {NAMED} rồi xóa Merchant Beta Cinemas",
    f"Record Legal approval for {NAMED} and then delete the project",
    f"Ghi nhận Purchase Request PR-001 và thêm Purchase Order PO-001 cho {NAMED}",
])
def test_mixed_requests_are_never_a_single_preview(text):
    assert interpret_project_request(text).kind == MIXED
    result = preview(text)
    assert result["outcome"] == CLARIFY
    assert_grants_nothing(result)


def test_a_step_update_named_after_an_approval_stays_a_step_update():
    text = f"Đánh dấu bước Record Partner approval của {NAMED} hoàn thành"
    assert interpret_project_request(text).kind == STEP_UPDATE


def test_adding_a_revision_is_not_a_project_creation():
    assert interpret_project_request(f"Thêm revision tài liệu cho {NAMED}").kind != PROJECT_CREATE
    assert interpret_project_request("Tạo project mở rạp Beta Nguyễn Văn Cừ").kind == PROJECT_CREATE


def test_signing_is_a_previewed_evidence_write():
    # CP12H.MASTER (DEC-SIMPLIFY P4): signing is recorded as operator-attested.
    text = f"Ký revision mới nhất của {NAMED}"
    assert interpret_project_request(text).kind == EVIDENCE_WRITE
    result = preview(text, EvidenceReader(revisions=[revision(P, 1)]))
    assert result["operation_kind"] == "RECORD_SIGNING"
    # The signing gate (three APPROVED decisions) is not met: blocked, no operation.
    assert result["outcome"] == BLOCKED and result["requested_operation"] is None
    assert {n["code"] for n in result["policy_notes"]} == {"OPERATOR_ATTESTED_SIGNED"}


def test_unicode_forms_parse_the_same():
    text = f"Ghi nhận Purchase Request PR-001 cho {NAMED}"
    for form in ("NFC", "NFD"):
        result = preview(unicodedata.normalize(form, text), EvidenceReader(project_id=P))
        assert result["project_id"] == P
        assert result["requested_fields"]["external_reference"] == "PR-001"


# ------------------------------------------------------------- procurement


def test_purchase_request_preview_is_valid_and_grants_nothing():
    result = preview(f"Ghi nhận Purchase Request PR-001 cho {NAMED}.")

    assert result["outcome"] == VALID
    assert result["operation_kind"] == "RECORD_PROCUREMENT_REFERENCE"
    assert result["evidence_type"] == "PURCHASE_REQUEST"
    assert result["database_target"] == "test"
    assert result["project_id"] == P and result["merchant_id"]
    assert result["missing_required_fields"] == []
    assert result["domain_validation"]["status"] == "VALID"
    assert result["domain_validation"]["engine"].endswith("propose_procurement_mutation")
    assert result["domain_validation"]["plan"]["operation"] == "INSERT"
    assert result["existing_evidence"]["record"] is None
    # Not required for this Project, but the domain accepts it: a note only.
    assert result["existing_evidence"]["requires_procurement"] is False
    assert result["policy_blockers"] == []
    assert_grants_nothing(result)


def test_purchase_order_needs_a_signed_revision():
    result = preview(f"Ghi nhận Purchase Order PO-001 cho {NAMED}.",
                     EvidenceReader(revisions=[revision(P, 1)]))

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == "ProcurementDependencyError"
    assert_grants_nothing(result)


def test_payment_request_needs_a_purchase_order():
    result = preview(f"Ghi nhận Payment Request PAY-001 cho {NAMED}.",
                     EvidenceReader(revisions=[revision(P, 1, signed=True)]))

    assert result["outcome"] == BLOCKED
    assert "Purchase Order" in result["domain_validation"]["error"]["message"]


def test_procurement_project_purchase_order_needs_the_purchase_request_number():
    reader = EvidenceReader(revisions=[revision(P_PROC, 1, signed=True)], project_id=P_PROC)
    result = preview(f"Ghi nhận Purchase Order PO-001 cho {PROC}.", reader)

    assert result["existing_evidence"]["requires_procurement"] is True
    assert result["outcome"] == BLOCKED
    assert "Purchase Request" in result["domain_validation"]["error"]["message"]


def test_a_duplicate_reference_is_blocked_and_a_new_one_updates():
    reader = EvidenceReader(procurement=[pr("PR-001")], project_id=P_PROC)
    same = preview(f"Ghi nhận Purchase Request PR-001 cho {PROC}.", reader)
    other = preview(f"Ghi nhận Purchase Request PR-002 cho {PROC}.", reader)

    assert same["outcome"] == BLOCKED
    assert same["domain_validation"]["error"]["code"] == "ProcurementConflictError"
    # CP12H.NL4D4A (approved DEC-P1c): a recorded Purchase Request reference
    # is never replaced. NL4D3 previewed this as a valid UPDATE.
    assert other["outcome"] == BLOCKED
    assert other["domain_validation"]["error"]["code"] == (
        "PROCUREMENT_REFERENCE_REPLACEMENT_UNSUPPORTED")
    assert other["existing_evidence"]["record"]["version"] == 1


def test_an_over_long_reference_is_blocked_and_a_missing_one_asks():
    long_ref = "PR-" + "9" * 120
    too_long = preview(f"Ghi nhận Purchase Request {long_ref} cho {NAMED}.")
    missing = preview(f"Ghi nhận Purchase Request cho {NAMED}.")

    assert too_long["outcome"] == BLOCKED
    assert "100" in too_long["domain_validation"]["error"]["message"]
    assert missing["outcome"] == CLARIFY
    assert missing["missing_required_fields"] == ["external_reference"]


def test_a_project_name_is_never_read_as_a_reference():
    reader = EvidenceReader()
    reader.projects[0]["title"] = "Beta NL4C2B Step Acceptance"
    result = preview("Ghi nhận Purchase Request cho Project Beta NL4C2B Step Acceptance", reader)

    assert result["outcome"] == CLARIFY
    assert result["missing_required_fields"] == ["external_reference"]


# ---------------------------------------------------------------- revisions


def test_a_revision_needs_its_type_but_no_content_hash():
    # CP12H.MASTER (DEC-SIMPLIFY P5): a revision is metadata-only; no file or hash.
    result = preview(f"Thêm revision tài liệu cho {NAMED}.",
                     EvidenceReader(revisions=[revision(P, 1)]))

    assert result["outcome"] == CLARIFY
    assert result["operation_kind"] == "REGISTER_DOCUMENT_REVISION"
    assert set(result["missing_required_fields"]) == {"document_type"}
    assert result["existing_evidence"]["active_revisions"][0]["revision_number"] == 1


def test_a_complete_revision_preview_supersedes_the_active_one():
    result = preview(f"Upload a new CONTRACT revision for {NAMED}",
                     EvidenceReader(revisions=[revision(P, 1)]))

    assert result["outcome"] == VALID
    plan = result["domain_validation"]["plan"]
    assert plan["revision_number"] == 2 and plan["previous_revision_number"] == 1
    assert {n["code"] for n in result["policy_notes"]} == {"METADATA_ONLY_REVISION"}
    assert_grants_nothing(result)


def test_a_typed_content_hash_is_never_accepted_or_echoed():
    # CP12H.MASTER: a typed hash cannot be verified, so it is never recorded.
    result = preview(f"Upload a new CONTRACT revision for {NAMED}, content hash sha256:abc",
                     EvidenceReader(revisions=[revision(P, 1)]))

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == "CONTENT_HASH_NOT_ACCEPTED"
    assert result["requested_fields"]["content_hash_provided"] is True
    assert "sha256:abc" not in json.dumps(result)
    assert result["requested_operation"] is None


def test_an_invalid_date_range_is_blocked():
    result = preview(f"Upload a new CONTRACT revision for {NAMED}, "
                     "effective 2026-12-01, expiry 2026-11-01")

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == "DocumentEngineError"


# ---------------------------------------------------------------- approvals


def test_a_valid_approval_is_an_operator_recorded_decision():
    # CP12H.MASTER (DEC-SIMPLIFY P1-P3): no POLICY_UNDECIDED; the operator
    # records the decision and the approver is never identified.
    result = preview(f"Legal đã phê duyệt revision mới nhất của {NAMED}.",
                     EvidenceReader(revisions=[revision(P, 1)]))

    assert result["outcome"] == VALID
    assert result["evidence_type"] == "LEGAL_APPROVAL"
    assert result["domain_validation"]["status"] == "VALID"
    assert result["domain_validation"]["plan"]["target_status"] == "APPROVED"
    assert result["policy_blockers"] == []
    assert {n["code"] for n in result["policy_notes"]} == {"OPERATOR_RECORDED_DECISION"}
    assert "final" in result["domain_validation"]["finality"].lower()
    assert_grants_nothing(result)


@pytest.mark.parametrize("text,role", [
    (f"Record Accounting approval for {NAMED}.", "ACCOUNTING"),
    (f"Add Partner approval for {NAMED}", "PARTNER"),
    (f"Kế toán đã duyệt tài liệu của {NAMED}", "ACCOUNTING"),
])
def test_each_role_previews(text, role):
    result = preview(text, EvidenceReader(revisions=[revision(P, 1)]))

    assert result["evidence_type"] == f"{role}_APPROVAL"
    assert result["outcome"] == VALID


def test_an_approval_without_a_revision_is_blocked():
    result = preview(f"Record Accounting approval for {NAMED}.")

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == "MISSING_DOCUMENT_REVISION"


def test_an_outdated_revision_cannot_be_approved():
    reader = EvidenceReader(revisions=[revision(P, 1, superseded_by=revision(P, 2)["id"]),
                                       revision(P, 2)])
    result = preview(f"Legal đã phê duyệt revision 1 của {NAMED}.", reader)

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == "ApprovalRevisionNotActiveError"


def test_a_final_approval_cannot_change():
    reader = EvidenceReader(revisions=[revision(P, 1)], approvals=[approval(1, "LEGAL")])
    result = preview(f"Legal đã phê duyệt revision mới nhất của {NAMED}.", reader)

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == "ApprovalFinalizedError"
    assert result["existing_evidence"]["approval"]["status"] == "APPROVED"


def test_a_pending_approval_can_be_decided():
    reader = EvidenceReader(revisions=[revision(P, 1)],
                            approvals=[approval(1, "PARTNER", status="PENDING")])
    result = preview(f"Add Partner approval for {NAMED}", reader)

    assert result["outcome"] == VALID
    assert result["domain_validation"]["plan"]["operation"] == "UPDATE"


def test_multiple_active_document_types_ask_which_one():
    reader = EvidenceReader(revisions=[revision(P, 1),
                                       dict(revision(P, 2, document_type="ADDENDUM"),
                                            revision_number=1)])
    asked = preview(f"Record Accounting approval for {NAMED}.", reader)
    chosen = preview(f"Record Accounting approval for the ADDENDUM of {NAMED}.", reader)

    assert asked["outcome"] == CLARIFY
    assert {c["document_type"] for c in asked["candidates"]} == {"CONTRACT", "ADDENDUM"}
    assert chosen["outcome"] == VALID
    assert chosen["existing_evidence"]["revision"]["document_type"] == "ADDENDUM"


@pytest.mark.parametrize("text", [
    f"Record CEO approval for {NAMED}.",
    f"Ghi nhận phê duyệt của Giám đốc cho {NAMED}.",
])
def test_an_unsupported_role_is_blocked(text):
    result = preview(text, EvidenceReader(revisions=[revision(P, 1)]))

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == "UNSUPPORTED_APPROVAL_ROLE"


def test_a_missing_role_asks():
    result = preview(f"Approve the latest document of {NAMED}",
                     EvidenceReader(revisions=[revision(P, 1)]))

    assert result["outcome"] == CLARIFY
    assert result["missing_required_fields"] == ["approver_role"]


def test_two_roles_ask_for_one_preview_each():
    result = preview(f"Legal và Accounting đã phê duyệt tài liệu của {NAMED}",
                     EvidenceReader(revisions=[revision(P, 1)]))

    assert result["outcome"] == CLARIFY


# ------------------------------------------------- identity and lifecycle


def test_a_missing_or_ambiguous_project_asks_and_infers_nothing():
    missing = preview("Register Partner approval for the latest revision.")
    ambiguous = preview("Ghi nhận Purchase Request PR-001 cho Project Beta Nguyễn Văn Cừ")

    assert missing["outcome"] == CLARIFY and missing["project_id"] is None
    assert ambiguous["outcome"] == CLARIFY and ambiguous["project_id"] is None
    assert len(ambiguous["candidates"]) >= 2


def test_a_project_of_another_merchant_is_not_bound():
    result = preview(f"Ghi nhận Purchase Request PR-001 cho {NAMED} của Lotte Cinema")

    assert result["outcome"] == CLARIFY and result["project_id"] is None


def test_a_closed_project_is_blocked_by_the_domain():
    reader = EvidenceReader()
    reader.projects[0]["status"] = "COMPLETED"
    result = preview(f"Ghi nhận Purchase Request PR-001 cho {NAMED}.", reader)

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == "ProcurementLifecycleClosedError"


def test_the_basis_changes_when_the_project_version_changes():
    reader = EvidenceReader()
    first = preview(f"Ghi nhận Purchase Request PR-001 cho {NAMED}.", reader)
    reader.projects[0]["version"] += 1
    second = preview(f"Ghi nhận Purchase Request PR-001 cho {NAMED}.", reader)

    assert first["basis"]["project_version"] + 1 == second["basis"]["project_version"]
    assert first["basis_sha256"] != second["basis_sha256"]


def test_a_preview_reads_only():
    # EvidenceReader fails the test on any non-read attribute.
    for text in WRITE_REQUESTS:
        assert_grants_nothing(preview(text, EvidenceReader(revisions=[revision(P, 1)])))


# ------------------------------------------------------- routing (entry point)


def parse(text, decision=EXECUTE):
    return IntentParser(CLAUDE_DIR / "agents.json", client=FakeClient(decision)).parse(text)


@pytest.mark.parametrize("text", WRITE_REQUESTS)
@pytest.mark.parametrize("decision", [EXECUTE, DIAGNOSE], ids=["execute", "diagnose"])
def test_evidence_writes_route_to_merchant_manager(text, decision):
    envelope = parse(text, decision)

    assert envelope.selected_agents == ["merchant-manager"]
    assert set(envelope.operations) <= {"merchant_execute", "merchant_read"}


@pytest.mark.parametrize("text", [
    "Approve the PR for the parser fix",
    "Record the approval flow in the implementation docs",
    "Add a revision field to the document model in evidence_preview.py",
])
def test_code_requests_are_not_evidence_writes(text):
    envelope = parse(text, CODE)

    assert "merchant-manager" not in envelope.selected_agents


def submit(text, decision=EXECUTE):
    class Model:
        def parse(self, request):
            return IntentParser(CLAUDE_DIR / "agents.json", client=FakeClient(decision)).parse(request)

    return intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD, "prompt": f"/solve {text}"},
        parser_factory=Model, env={},
    )


@pytest.mark.parametrize("text", [
    f"Ghi nhận Purchase Request PR-001 cho {NAMED} trên database test",
    f"Legal đã phê duyệt revision mới nhất của {NAMED} trên database test.",
])
def test_an_unscoped_evidence_write_runs_as_a_read(isolated, text):
    output = submit(text)

    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["selected_agents"] == ["merchant-manager"]
    assert run["operations"] == ["merchant_read"] and run["risk_level"] == "read_only"
    assert run["merchant_read_target"] == "test"
    assert run["confirmed"] is False and run.get("merchant_scope") is None
    envelope = intent_gate.load_intent_envelope(LEAD)
    assert envelope["requires_confirmation"] is False
    assert pending.load_records(LEAD) == [] and pending.load_records(LEAD, pending.STEP_KIND) == []


def test_a_mixed_destructive_request_is_not_downgraded(isolated):
    text = f"Ghi nhận Purchase Request PR-001 cho {NAMED}, rồi xóa Merchant Beta Cinemas"
    submit(text, _decision(operations=[Operation.MERCHANT_EXECUTE], domains=[Domain.MERCHANT],
                           risk_level=RiskLevel.DESTRUCTIVE))
    run = runtime_state.load_state(LEAD)

    assert run is None or run["operations"] != ["merchant_read"]


@pytest.mark.parametrize("argv", [
    ["document", "approve", P, "--role", "LEGAL", "--status", "APPROVED"],
    ["procurement", "update", P, "--type", "PURCHASE_REQUEST", "--external-id", "PR-1"],
    ["document", "revision-create", P, "--type", "CONTRACT", "--content-hash", "h"],
])
def test_a_typed_evidence_scope_is_still_refused(argv):
    # Runtime never executes these. CP12H.NL4D4A / CP12H.MASTER: on the test
    # database each runs only as the user's confirmation of a verified
    # preview; a typed scope is refused at the intent gate, and the preflight
    # requires the confirmed pending operation with the identical argv
    # (test_nl4d4a_purchase_request.py, test_master_lifecycle_postgres.py).
    command = " ".join(argv[:2])
    assert handoff.direct_execute_enabled(command, "runtime") is False
    if command != "procurement update":
        assert command in handoff.LIFECYCLE_ONLY_COMMANDS
        assert handoff.is_lifecycle_attempt(command, argv[2:], "test")


# --------------------------------------------------------- CLI and security


def test_the_cli_exposes_a_read_that_cannot_write():
    assert "evidence preview" in READ_COMMANDS and "evidence preview" not in WRITE_COMMANDS
    argv = prepare_agent_cli_argv(["evidence", "preview", "--request", "x", "--test-database"])
    assert argv[:2] == ("--database", "test")
    for flag in ("--execute", "--apply", "--propose"):
        with pytest.raises(MerchantAgentCliError):
            prepare_agent_cli_argv(["evidence", "preview", "--request", "x", flag])


def test_write_authority_is_unchanged():
    assert handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False
    # CP12H.NL4D4A: the confirmed Purchase Request joined test mode.
    # CP12H.MASTER: the confirmed lifecycle operations joined test mode.
    assert handoff.TEST_MODE_COMMANDS == {"merchant create", "project create", "step update",
                                          "procurement update", "document revision-create",
                                          "document approve", "document sign", "project update"}


@pytest.fixture
def preview_run(isolated, monkeypatch):
    from claude.hooks import harness_team_identity

    assert spawn(isolated) is None
    monkeypatch.setattr(harness_team_identity, "verified_teammate_pane",
                        lambda owner, name: "7000:%7" if (owner, name) == (LEAD, MM) else None)
    text = f"Ghi nhận Purchase Request PR-001 cho {NAMED}."
    result = preview(text)
    command = f'{CLI} evidence preview --request "{text}" --test-database'
    return result, command, json.dumps(result, ensure_ascii=False, indent=2)


def block(result):
    marker = merchant_preview_delivery.EVIDENCE_PREVIEW_MARKER
    return f"{marker}\n{json.dumps(result, ensure_ascii=False, separators=(',', ':'))}"


def capture(command, stdout):
    return merchant_preview_delivery.record_preview_evidence(post_bash(command, stdout))


def test_the_verified_preview_is_delivered_exactly_and_creates_nothing(preview_run):
    result, command, stdout = preview_run
    assert capture(command, stdout)

    assert decide(f"PR-001 can be recorded; nothing was changed.\n{block(result)}\n") is None
    assert decide("PR-001 can be recorded.") is not None                       # missing block
    assert decide(block(dict(result, outcome=BLOCKED))) is not None              # altered
    assert decide(f"{block(result)}\nType /solve --confirm --merchant-scope [...]") is not None
    assert decide(f"{block(result)}\nconfirmation_command: x") is not None
    assert pending.load_records(LEAD) == [] and pending.load_records(LEAD, pending.STEP_KIND) == []


@pytest.mark.parametrize("forge", [
    lambda r: r.update(read_only=False),
    lambda r: r.update(executable=True),
    lambda r: r.update(confirmation_available=True),
    lambda r: r.update(authorization={"granted": True}),
    lambda r: r.update(requested_operation={"argv": ["procurement", "update"]}),
    lambda r: r.update(mode="EVIDENCE_STATUS"),
    lambda r: r.update(database_target="runtime"),
])
def test_a_forged_preview_is_unverified(preview_run, forge):
    result, command, _ = preview_run
    forged = copy.deepcopy(result)
    forge(forged)

    assert not capture(command, json.dumps(forged, ensure_ascii=False))
    assert decide(block(forged)) is not None
    assert decide("EVIDENCE_WRITE_PREVIEW_FAILED: the CLI output could not be verified.") is None


def test_only_merchant_manager_can_be_dispatched_for_a_preview(isolated):
    from tests.merchant.test_nl2e_p1_p2_p4 import policy_gate

    assert submit(f"Ghi nhận Purchase Request PR-001 cho {NAMED} trên database test",
                  DIAGNOSE).get("decision") != "block"
    assignment = ("operation: merchant_read\ndatabase_target: test\n"
                  "Preview recording the Purchase Request reference; nothing is written.")
    for agent, allowed in (("diagnostician", False), ("coder", False), ("merchant-manager", True)):
        with runtime_state.locked_state(LEAD) as state:
            decision = policy_gate.apply_call(
                state, "Agent", {"subagent_type": agent, "name": agent, "prompt": assignment}, LEAD)
        assert (decision is None) is allowed, agent
