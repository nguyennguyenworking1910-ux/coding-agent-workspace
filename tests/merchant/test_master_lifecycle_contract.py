"""CP12H.MASTER: the confirmation-first lifecycle contract without a database.

Operation shape and tampering, preview -> payload -> argv round trips, the
natural-language edge cases (Vietnamese and English, ambiguity, negation,
several operations, wrong target, missing or duplicate references, notes and
dates), the workflow template audit and the trusted confirmation phrases.
"""

from __future__ import annotations

import copy
import json
import uuid

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant import lifecycle_operation as lifecycle
from claude.agents.tools.merchant.evidence_preview import BLOCKED, CLARIFY, VALID, build_evidence_preview
from claude.agents.tools.merchant.project_nl import EVIDENCE_WRITE, MIXED, interpret_project_request
from claude.agents.tools.merchant.workflow_templates import STANDARD_WORKFLOW_TEMPLATES
from claude.hooks import merchant_pending_confirmation as pending
from tests.merchant.test_nl4d2_evidence_discovery import (
    NAMED, P, REVIEWED, EvidenceReader, approval, revision,
)

OPERATOR = "0d5a0000-0000-4000-8000-0000000000c1"
TRUSTED = {"status": "TRUSTED", "operator_id": OPERATOR}


def preview(text, reader=None, target="test", operator=TRUSTED):
    result = build_evidence_preview(text, reader or EvidenceReader(), database_target=target,
                                    operator=operator)
    return json.loads(json.dumps(result, default=str))


def approved(*roles, status="APPROVED"):
    return [approval(1, role, status=status) for role in roles]


def payload_of(operation):
    args = merchant_cli.build_argument_parser().parse_args(["--database", "test", *operation["argv"]])
    return {k: v for k, v in merchant_cli.build_write_payload(args, operation["command"]).items()
            if v is not None}


# ------------------------------------------------------------ operations


def test_a_metadata_only_revision_operation_round_trips():
    result = preview(f"Tạo phiên bản hợp đồng mới cho {NAMED}")
    assert result["outcome"] == VALID and result["confirmation_available"] is True
    operation = result["requested_operation"]
    assert operation["operation"] == lifecycle.CREATE_REVISION
    assert operation["params"]["document_type"] == "CONTRACT"
    argv = operation["argv"]
    assert argv[argv.index("--content-hash") + 1] == f"metadata-only:{operation['operation_id']}"
    assert lifecycle.argv_from_payload(operation["command"], payload_of(operation)) == argv
    assert result["read_only"] is True and result["executable"] is False
    assert result["authorization"] is None and operation["status"] == "NOT_AUTHORIZED"


@pytest.mark.parametrize("text,role,decision", [
    (f"Legal đã phê duyệt hợp đồng của {NAMED}", "LEGAL", "APPROVED"),
    (f"Accounting approved the CONTRACT of {NAMED}", "ACCOUNTING", "APPROVED"),
    (f"Partner đã từ chối hợp đồng của {NAMED}", "PARTNER", "REJECTED"),
    (f"Record Partner rejection for {NAMED}", "PARTNER", "REJECTED"),
])
def test_one_decision_per_operation_in_both_languages(text, role, decision):
    result = preview(text, EvidenceReader(revisions=[revision(P, 1)]))
    assert result["outcome"] == VALID, result["domain_validation"]
    params = result["requested_operation"]["params"]
    assert (params["role"], params["decision"]) == (role, decision)
    assert lifecycle.argv_from_payload("document approve",
                                       payload_of(result["requested_operation"])) \
        == result["requested_operation"]["argv"]


def test_notes_and_a_decision_date_are_kept_exactly_and_the_approver_is_never_named():
    result = preview(f"Legal đã phê duyệt hợp đồng của {NAMED} ngày 2026-11-10, "
                     "ghi chú: \"đồng ý, kèm phụ lục 2\"",
                     EvidenceReader(revisions=[revision(P, 1)]))
    operation = result["requested_operation"]
    assert operation["params"]["decided_on"] == "2026-11-10"
    assert operation["params"]["decision_note"] == "đồng ý, kèm phụ lục 2"
    assert operation["argv"][operation["argv"].index("--occurred-at") + 1] == "2026-11-10T00:00:00+07:00"
    assert "--acted-by" not in operation["argv"]
    assert {n["code"] for n in result["policy_notes"]} == {"OPERATOR_RECORDED_DECISION"}


def test_two_dates_ask_and_a_future_date_is_refused():
    two = preview(f"Legal đã phê duyệt hợp đồng của {NAMED} 2026-11-01 2026-11-02",
                  EvidenceReader(revisions=[revision(P, 1)]))
    assert two["outcome"] == CLARIFY
    future = preview(f"Legal đã phê duyệt hợp đồng của {NAMED} 2999-01-01",
                     EvidenceReader(revisions=[revision(P, 1)]))
    assert future["outcome"] == BLOCKED
    assert future["domain_validation"]["error"]["code"] == lifecycle.DATE_INVALID


def test_a_pending_request_for_approval_is_not_a_decision():
    result = preview(f"Gửi duyệt hợp đồng của {NAMED} cho Legal",
                     EvidenceReader(revisions=[revision(P, 1)]))
    assert result["requested_operation"] is None


def test_signing_needs_three_approvals_and_any_rejection_blocks_it():
    blocked = preview(f"Ghi nhận hợp đồng của {NAMED} đã ký",
                      EvidenceReader(revisions=[revision(P, 1)], approvals=approved("LEGAL", "ACCOUNTING")))
    assert blocked["outcome"] == BLOCKED and blocked["requested_operation"] is None

    rejected = preview(f"Ghi nhận hợp đồng của {NAMED} đã ký", EvidenceReader(
        revisions=[revision(P, 1)],
        approvals=approved("LEGAL", "ACCOUNTING") + approved("PARTNER", status="REJECTED")))
    assert rejected["domain_validation"]["error"]["code"] == lifecycle.DECISION_REJECTED

    # F1: with all three approvals, signing still waits for the signing-gate Step (8).
    gate_open = preview(f"Ghi nhận hợp đồng của {NAMED} đã ký", EvidenceReader(
        revisions=[revision(P, 1)], approvals=approved("LEGAL", "ACCOUNTING", "PARTNER")))
    assert gate_open["domain_validation"]["error"]["code"] == lifecycle.SIGNING_GATE_OPEN
    assert gate_open["requested_operation"] is None

    ready = preview(f"Ghi nhận hợp đồng của {NAMED} đã ký", EvidenceReader(
        statuses={**REVIEWED, 5: "COMPLETED", 8: "COMPLETED"},
        revisions=[revision(P, 1)], approvals=approved("LEGAL", "ACCOUNTING", "PARTNER")))
    assert ready["outcome"] == VALID, ready["domain_validation"]
    assert ready["requested_operation"]["operation"] == lifecycle.SIGN
    assert {n["code"] for n in ready["policy_notes"]} == {"OPERATOR_ATTESTED_SIGNED"}


def test_a_purchase_order_needs_a_signed_revision_and_its_own_reference():
    unsigned = preview(f"Ghi nhận Purchase Order PO-001 cho {NAMED}",
                       EvidenceReader(revisions=[revision(P, 1)]))
    assert unsigned["outcome"] == BLOCKED and unsigned["requested_operation"] is None
    missing = preview(f"Ghi nhận Purchase Order cho {NAMED}",
                      EvidenceReader(revisions=[revision(P, 1, signed=True)]))
    assert missing["outcome"] == CLARIFY
    signed = preview(f"Ghi nhận Purchase Order PO-001 cho {NAMED}",
                     EvidenceReader(revisions=[revision(P, 1, signed=True)]))
    assert signed["outcome"] == VALID, signed["domain_validation"]
    assert signed["requested_operation"]["operation"] == lifecycle.PURCHASE_ORDER
    assert signed["requested_operation"]["params"] == {"reference": "PO-001"}


def test_a_runtime_target_or_missing_operator_never_yields_an_operation():
    runtime = preview(f"Tạo phiên bản hợp đồng mới cho {NAMED}", target="runtime")
    assert runtime["requested_operation"] is None
    assert "RUNTIME_EXECUTION_DISABLED" in runtime["confirmation_blockers"]
    unconfigured = preview(f"Tạo phiên bản hợp đồng mới cho {NAMED}", operator=None)
    assert unconfigured["requested_operation"] is None
    assert "OPERATOR_IDENTITY_NOT_RESOLVED" in unconfigured["confirmation_blockers"]


# ---------------------------------------------------------- tampering


def _operation():
    return preview(f"Tạo phiên bản hợp đồng mới cho {NAMED}")["requested_operation"]


@pytest.mark.parametrize("edit", [
    lambda o: o.update(status="AUTHORIZED"),
    lambda o: o.update(database_target="runtime"),
    lambda o: o.update(operator_id="00000000-0000-0000-0000-000000000000"),
    lambda o: o["params"].update(document_type="contract"),
    lambda o: o["argv"].append("--created-by"),
    lambda o: o.update(expected_basis="0" * 63),
    lambda o: o["params"].update(extra=1),
    lambda o: o.update(operation="DELETE_PROJECT"),
])
def test_an_edited_operation_is_rejected(edit):
    operation = copy.deepcopy(_operation())
    edit(operation)
    with pytest.raises(ValueError):
        lifecycle.validate_operation(operation)


def test_a_payload_with_extra_fields_or_a_typed_hash_is_not_the_operation():
    operation = _operation()
    payload = payload_of(operation)
    with pytest.raises(lifecycle.LifecycleMismatch):
        lifecycle.params_from_payload(lifecycle.CREATE_REVISION, {**payload, "created_by": OPERATOR})
    with pytest.raises(lifecycle.LifecycleMismatch):
        lifecycle.params_from_payload(lifecycle.CREATE_REVISION, {**payload, "content_hash": "sha256:" + "a" * 64})


# ------------------------------------------------------- natural language


@pytest.mark.parametrize("text", [
    f"Tạo phiên bản hợp đồng mới cho {NAMED}",
    f"Ký hợp đồng cho {NAMED}",
    f"Record the CONTRACT of {NAMED} as signed",
    f"Hoàn tất {NAMED}",
    f"Complete project {NAMED.split(' ', 1)[1]}",
    f"Bắt đầu {NAMED}",
    f"Kick off project {NAMED.split(' ', 1)[1]}",
])
def test_lifecycle_requests_are_evidence_writes(text):
    interpretation = interpret_project_request(text)
    assert interpretation.kind == EVIDENCE_WRITE and interpretation.write_requested


@pytest.mark.parametrize("text", [
    f"Hợp đồng của {NAMED} chưa ký",
    f"Không hoàn tất {NAMED}",
    f"Đừng ghi nhận Legal đã phê duyệt hợp đồng của {NAMED}",
])
def test_negated_requests_never_yield_an_operation(text):
    assert preview(text, EvidenceReader(revisions=[revision(P, 1)]))["requested_operation"] is None


def test_several_operations_in_one_request_are_mixed():
    text = f"Legal đã phê duyệt hợp đồng của {NAMED} và ghi nhận Purchase Order PO-1"
    assert interpret_project_request(text).kind == MIXED


def test_a_step_named_complete_project_is_a_step_update_not_project_completion():
    assert interpret_project_request(
        f"Hoàn thành bước Complete project của {NAMED}").kind == "STEP_UPDATE"


def test_ambiguous_document_types_and_roles_ask():
    reader = EvidenceReader(revisions=[revision(P, 1), dict(revision(P, 2, document_type="ADDENDUM"),
                                                            revision_number=1)])
    assert preview(f"Ký tài liệu của {NAMED}", reader)["outcome"] == CLARIFY
    assert preview(f"Legal và Partner đã phê duyệt hợp đồng của {NAMED}",
                   EvidenceReader(revisions=[revision(P, 1)]))["outcome"] == CLARIFY


def test_a_project_that_cannot_be_completed_says_why():
    result = preview(f"Hoàn tất {NAMED}")
    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == lifecycle.STEPS_UNFINISHED
    assert result["existing_evidence"]["unfinished_steps"]


# ---------------------------------------------------- confirmation phrases


@pytest.mark.parametrize("text,parsed", [
    ("Xác nhận thực hiện 1a2b3c4d", ("confirm", "1a2b3c4d")),
    ("xac nhan thuc hien thao tac 1a2b3c4d", ("confirm", "1a2b3c4d")),
    ("Confirm operation", ("confirm", None)),
    ("Hủy thực hiện 1a2b3c4d", ("cancel", "1a2b3c4d")),
    ("Xác nhận thực hiện 1a2b3c4d ngay", None),           # anything extra: not a confirmation
    ("Xác nhận thực hiện xyz", None),
])
def test_only_the_exact_operation_phrase_confirms(text, parsed):
    assert pending.parse_lifecycle_confirmation(text) == parsed
    # A lifecycle phrase never confirms another kind, nor the reverse.
    assert pending.parse_confirmation(text) is None
    assert pending.parse_step_confirmation(text) is None
    assert pending.parse_purchase_request_confirmation(text) is None
    assert pending.parse_lifecycle_confirmation("Xác nhận ghi nhận 1a2b3c4d") is None


def test_a_scheduled_prompt_cannot_carry_an_operation_confirmation():
    assert pending.scheduled_prompt_denial("CronCreate", {"prompt": "/solve Xác nhận thực hiện 1a2b3c4d"})


# ------------------------------------------------------ template audit


def test_every_template_has_one_final_step_and_its_evaluator_less_gates_are_known():
    from claude.agents.tools.merchant.gate_resolver import DATABASE_VERIFIABLE_GATE_NAMES, normalize_gate_step_name

    audit = {}
    for template in STANDARD_WORKFLOW_TEMPLATES:
        successors = {d.from_step_key for d in template.dependencies}
        sinks = [s for s in template.steps if s.key not in successors]
        last = max(template.steps, key=lambda s: s.sequence_number)
        assert sinks == [last], template.name                  # the final Step is the last Step
        audit[template.name] = sorted(
            s.name for s in template.steps if s.step_type == "APPROVAL_GATE"
            and normalize_gate_step_name(s.name) not in DATABASE_VERIFIABLE_GATE_NAMES)
    assert audit == {
        "MEDIA_TOP_UP_NEW_DOCUMENT": ["Close payment period"],
        "MEDIA_TOP_UP_EXISTING_DOCUMENT": ["Close payment period", "Validate existing signed document"],
        "OPENING_NEW_CINEMA_STANDARD": ["Complete UAT acceptance", "Complete project"],
        "INTEGRATION_NEW_MERCHANT_STANDARD": ["Activate Merchant", "Complete UAT acceptance",
                                              "Complete project", "Validate Master Merchant identity"],
    }


def test_final_step_is_the_projects_highest_numbered_step():
    detail = {"steps": [{"id": uuid.UUID(int=i), "sequence_number": i} for i in (1, 2, 9)],
              "dependencies": []}
    assert lifecycle.final_step_ids(detail) == {str(uuid.UUID(int=9))}
