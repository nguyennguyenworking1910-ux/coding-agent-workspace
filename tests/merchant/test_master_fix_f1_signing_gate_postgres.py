"""CP12H.MASTER-FIX-F1: signing waits for the workflow's signing-gate Step.

The template makes "Sign document" depend on "Validate signing gate", and the
gate evaluator ("every prerequisite for document signing") refuses a signed
revision (DOCUMENT_ALREADY_SIGNED). Signing before the gate Step was COMPLETED
therefore left the Step, and so the Project, permanently unfinishable (F1).
Signing now requires every signing-gate Step of the Project to be COMPLETED,
in the preview, the preflight and under the write transaction's locks.
Must run alone (never concurrently with another PostgreSQL test process).
"""

from __future__ import annotations

import pytest

from claude.agents.tools.merchant import lifecycle_operation as lifecycle
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks.merchant_runtime_handoff_gate import HANDOFF_STATE_KEY
from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD, TEST_DB_CONFIGURED, isolated, run_state,
)
from tests.merchant.test_master_lifecycle_postgres import (  # noqa: F401
    ON, _capsys, advance, capsys_holder, cli_preview, confirm, execute, one, preview, project,
    pytest_operation_keys, run_operation, run_step, spent, steps,
)

pytestmark = pytest.mark.skipif(not TEST_DB_CONFIGURED, reason="Merchant test database not configured")

SIGN = f"Ghi nhận hợp đồng của {ON} đã ký"


def _approved_revision(db):
    run_operation(db, f"Bắt đầu {ON}")
    revision, _ = run_operation(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    for words in ("Legal", "Kế toán", "Partner"):
        run_operation(db, f"{words} đã phê duyệt hợp đồng của {ON}")
    return revision["operation_id"]


def test_signing_before_the_signing_gate_step_is_blocked_and_creates_no_pending(project):
    db, pid = project.repository, project.project_id
    revision = _approved_revision(db)

    early = preview(db, SIGN)                       # verified capture, as a live teammate would
    assert early["outcome"] == "BLOCKED"
    assert early["domain_validation"]["error"]["code"] == lifecycle.SIGNING_GATE_OPEN
    assert "8" in early["domain_validation"]["error"]["message"]
    assert "Validate signing gate" in early["domain_validation"]["error"]["message"]
    assert early["requested_operation"] is None and early["confirmation_available"] is False
    assert pending.live_records(LEAD, pending.LIFECYCLE_KIND) == []
    assert one(db, "SELECT signed FROM merchant_ops.document_revisions WHERE id = %s", revision)["signed"] is False

    # A gate Step that is only IN_PROGRESS is not enough.
    for sequence in (1, 2, 3, 4, 5):
        advance(db, pid, sequence)
    advance(db, pid, 8, to="IN_PROGRESS")
    assert cli_preview(db, SIGN)["domain_validation"]["error"]["code"] == lifecycle.SIGNING_GATE_OPEN


def test_signing_after_the_gate_step_keeps_the_project_completable(project):
    db, pid = project.repository, project.project_id
    _approved_revision(db)
    for sequence in (1, 2, 3, 4, 5, 8):             # 5 and 8 judged from the recorded evidence
        advance(db, pid, sequence)

    signing, receipt = run_operation(db, SIGN)
    assert receipt["attestation"] == lifecycle.OPERATOR_ATTESTED_SIGNED
    assert steps(db, pid)[8]["status"] == "COMPLETED"

    for sequence in sorted(steps(db, pid)):
        if sequence in (21, 22) or steps(db, pid)[sequence]["status"] in ("COMPLETED", "SKIPPED"):
            continue
        advance(db, pid, sequence)
    for sequence in (21, 22):
        advance(db, pid, sequence, to="IN_PROGRESS")
        run_step(db, sequence, f"step {sequence}")
    _, receipt = run_operation(db, f"Hoàn tất {ON}")
    assert receipt["event_type"] == "PROJECT_COMPLETED"


def test_a_step_change_after_the_signing_preview_refuses_it_before_spend(project):
    db, pid = project.repository, project.project_id
    revision = _approved_revision(db)
    for sequence in (1, 2, 3, 4, 5, 8):
        advance(db, pid, sequence)
    output = preview(db, SIGN)
    operation = output["requested_operation"]
    assert output["outcome"] == "PREVIEW_VALID" and operation is not None

    confirm(operation)
    advance(db, pid, 9, to="READY")                 # a concurrent Step Update changes the basis
    assert execute(operation) is None
    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == f"PREFLIGHT:{lifecycle.BASIS_CHANGED}"
    assert not spent()
    assert one(db, "SELECT signed FROM merchant_ops.document_revisions WHERE id = %s", revision)["signed"] is False


def test_the_judge_finds_signing_gates_by_template_metadata_not_by_number():
    project = {"id": "11111111-1111-4111-8111-111111111111", "status": "IN_PROGRESS",
               "requires_procurement": False}
    revision = {"id": "22222222-2222-4222-8222-222222222222", "project_id": project["id"],
                "document_type": "CONTRACT", "revision_number": 1, "signed": False,
                "superseded_by": None, "created_at": "2026-11-13T00:00:00+07:00"}
    approvals = [{"id": f"3333333{i}-3333-4333-8333-333333333333", "document_revision_id": revision["id"],
                  "approver_role": role, "approval_status": "APPROVED"}
                 for i, role in enumerate(("LEGAL", "ACCOUNTING", "PARTNER"))]

    def detail(gate_status, sequence):
        return {"project": project, "document_revisions": [revision], "document_approvals": approvals,
                "procurement_records": [], "steps": [
                    {"id": "44444444-4444-4444-8444-444444444444", "sequence_number": sequence,
                     "step_name": "Validate signing gate", "step_type": "APPROVAL_GATE",
                     "status": gate_status},
                    {"id": "55555555-5555-4555-8555-555555555555", "sequence_number": 3,
                     "step_name": "Validate Master Merchant identity", "step_type": "APPROVAL_GATE",
                     "status": "PENDING"}]}

    params = {"revision_id": revision["id"], "signed_on": None}
    with pytest.raises(lifecycle.LifecycleMismatch) as refused:
        lifecycle.judge(lifecycle.SIGN, detail("READY", 11), params)   # integration: Step 11
    assert refused.value.reason == lifecycle.SIGNING_GATE_OPEN and "11" in refused.value.detail
    try:                                            # the full engine path is covered on PostgreSQL above
        lifecycle.judge(lifecycle.SIGN, detail("COMPLETED", 11), params)
    except lifecycle.LifecycleMismatch as error:
        assert error.reason != lifecycle.SIGNING_GATE_OPEN
