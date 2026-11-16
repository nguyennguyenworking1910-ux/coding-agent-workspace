"""CP12H.MASTER-FIX: signed contract revision reuse across Projects of the
same Merchant (Existing-Document Media), end to end on the test database.

Writes under test run through the real hooks and the user's confirmations
(preview, pending record, ``/solve Xác nhận ...``, preflight, transaction,
receipt). Candidate states are prepared with disposable SQL fixtures. Must
run alone (never concurrently with another PostgreSQL test process).
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant.read_commands import MerchantReadCommands
from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.agents.tools.merchant.write_adapters import (
    MerchantRepositoryWriteAdapters,
    MerchantWriteRepositories,
)
from claude.clients.merchant import attempt_evidence
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks.merchant_preview_delivery import PREVIEW_OPERATION_MARKER
from claude.hooks.merchant_runtime_handoff_gate import HANDOFF_STATE_KEY
from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD, PANE, TEAMMATE, TEST_DB_CONFIGURED, idle, isolated, record, run_hook, run_state,
)
from tests.merchant.test_master_lifecycle_postgres import (  # noqa: F401
    CLI, KEY_PREFIX, ON, SHORT, TITLE, _capsys, advance, capsys_holder, claims, cli_preview,
    deliver, execute, one, project, pytest_operation_keys, read_run, release, reuse_teammate,
    run_operation, run_step, sql, steps, user_says,
)

pytestmark = pytest.mark.skipif(not TEST_DB_CONFIGURED, reason="Merchant test database not configured")

MERCHANT = f"{SHORT} Cinemas"


def create_text(source_title=None, period=3, title="Q4"):
    reuse = (f"sử dụng hợp đồng đã ký của Project {source_title}" if source_title
             else "sử dụng hợp đồng đã ký hiện có")
    return (f"Tạo Project media {title} cho {MERCHANT} kỳ thanh toán {period}, {reuse} "
            "trên database test")


def project_preview(db, text):
    return json.loads(json.dumps(MerchantReadCommands(MerchantReadRepository(db)).project_preview(
        request=text, database_target="test"), default=str))


def confirmed_create(db, text):
    """Preview, capture, confirm and execute one Project create; the operation."""

    read_run(text)
    output = project_preview(db, text)
    assert output["outcome"] == "READY_FOR_CONFIRMATION", output["clarifications"]
    assert run_hook({
        "hook_event_name": "PostToolUse", "session_id": PANE, "agent_type": TEAMMATE,
        "tool_name": "Bash",
        "tool_input": {"command": f'{CLI} project preview --request "{text}" --test-database'},
        "tool_response": {"stdout": json.dumps(output, ensure_ascii=False, indent=2), "stderr": ""},
    }) == 0
    operation = output["requested_operation"]
    exact = json.dumps(operation, ensure_ascii=False, separators=(",", ":"))
    assert deliver(f"Preview ready.\n{PREVIEW_OPERATION_MARKER}\n{exact}\n", capsys_holder[0]) is None
    assert idle() == 0
    assert user_says("/solve Xác nhận tạo").get("hookSpecificOutput")
    reuse_teammate()
    assert execute(operation) is None
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED", run_state().get(HANDOFF_STATE_KEY)
    release("project create")
    return output


def signed_contract(db, project_id, number=1, document_type="CONTRACT"):
    revision = str(uuid.uuid4())
    sql(db, "INSERT INTO merchant_ops.document_revisions (id, project_id, document_type, revision_number, "
            "content_hash, signed, signed_at) VALUES (%s, %s, %s, %s, 'legacy', TRUE, now())",
        revision, project_id, document_type, number)
    return revision


def sibling(db, merchant_id, title):
    return str(MerchantWorkflowRepository(db).create_project(
        merchant_id=merchant_id, template=get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD"),
        requires_procurement=False, title=title).project_id)


def source_state(db, revision_id):
    with db.connection(read_only=True) as connection:
        return (dict(connection.execute(
            "SELECT * FROM merchant_ops.document_revisions WHERE id = %s", (revision_id,)).fetchone()),
            [dict(r) for r in connection.execute(
                "SELECT * FROM merchant_ops.document_approvals WHERE document_revision_id = %s "
                "ORDER BY approver_role", (revision_id,)).fetchall()])


# ------------------------------------------------------- full workflow


def test_existing_document_media_project_completes_on_a_reused_signed_contract(project):
    db = project.repository

    # Source: metadata-only contract, three decisions, operator-attested signing.
    revision, _ = run_operation(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    for words in ("Legal", "Kế toán", "Partner"):
        run_operation(db, f"{words} đã phê duyệt hợp đồng của {ON}")
    for sequence in (1, 2, 3, 4, 5, 8):     # F1: the signing-gate Step precedes signing
        advance(db, project.project_id, sequence)
    run_operation(db, f"Ghi nhận hợp đồng của {ON} đã ký")
    source_id = revision["operation_id"]
    before = source_state(db, source_id)
    assert before[0]["signing_attestation"] == "OPERATOR_ATTESTED_SIGNED"

    # Destination: the confirmed Project create binds that exact revision.
    output = confirmed_create(db, create_text(TITLE))
    reused = output["reused_document"]
    assert reused["revision_id"] == source_id and reused["source_project_id"] == project.project_id
    assert reused["signing_attestation"] == "OPERATOR_ATTESTED_SIGNED"     # never upgraded
    assert [c["revision_id"] for c in output["reuse_candidates"]] == [source_id]
    operation = output["requested_operation"]
    assert operation["reused_document_revision_id"] == source_id
    assert operation["argv"][operation["argv"].index("--reused-document-revision-id") + 1] == source_id
    destination = operation["project_id"]
    title = one(db, "SELECT title FROM merchant_ops.projects WHERE id = %s", destination)["title"]
    assert one(db, "SELECT reused_document_revision_id::text AS r, payment_period_number AS n FROM "
                   "merchant_ops.projects WHERE id = %s", destination) == {"r": source_id, "n": 3}
    on = f"Project {title} trên database test"

    run_operation(db, f"Bắt đầu {on}")
    advance(db, destination, 1, to="IN_PROGRESS")
    attested = run_step(db, 1, "validate existing signed document", title=title)
    assert attested["gate_attestation"] == "OPERATOR_ATTESTED"
    po, po_receipt = run_operation(db, f"Ghi nhận Purchase Order PO-{SHORT}-RU cho {on}")
    pay, _ = run_operation(db, f"Ghi nhận Payment Request PAY-{SHORT}-RU cho {on}")
    for sequence in (2, 3):
        advance(db, destination, sequence)
    advance(db, destination, 4, to="IN_PROGRESS")
    run_step(db, 4, "close payment period (final)", title=title)
    _, receipt = run_operation(db, f"Hoàn tất {on}")
    assert receipt["event_type"] == "PROJECT_COMPLETED"

    # Receipts rebuild from PostgreSQL alone; nothing was copied or changed.
    assert attempt_evidence.recover_lifecycle_receipt(db, po)["entity"]["external_id"] == f"PO-{SHORT}-RU"
    assert attempt_evidence.recover_lifecycle_receipt(db, pay)["event_type"] == "PROCUREMENT_CREATED"
    assert source_state(db, source_id) == before
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.document_revisions WHERE project_id = %s",
               destination)["n"] == 0
    assert one(db, "SELECT status FROM merchant_ops.projects WHERE id = %s",
               project.project_id)["status"] == "PLANNED"                      # source untouched


# ------------------------------------------------- candidate selection


def test_no_eligible_revision_asks_and_names_the_missing_prerequisite(project):
    db = project.repository
    signed_contract(db, project.project_id, document_type="ADDENDUM")       # not a contract
    output = project_preview(db, create_text())
    assert output["outcome"] == "NEEDS_CLARIFICATION" and output["requested_operation"] is None
    assert any("No eligible signed CONTRACT" in q for q in output["clarifications"])


def test_several_eligible_revisions_require_an_explicit_choice(project):
    db = project.repository
    first = signed_contract(db, project.project_id)
    other_title = f"{SHORT} Second Site"
    second = signed_contract(db, sibling(db, project.merchant_id, other_title))

    asked = project_preview(db, create_text())
    assert asked["outcome"] == "NEEDS_CLARIFICATION" and asked["requested_operation"] is None
    assert {c["revision_id"] for c in asked["reuse_candidates"]} == {first, second}

    by_project = project_preview(db, create_text(other_title))
    assert by_project["outcome"] == "READY_FOR_CONFIRMATION", by_project["clarifications"]
    assert by_project["requested_operation"]["reused_document_revision_id"] == second

    by_id = project_preview(db, create_text() + f" (revision {first})")
    assert by_id["requested_operation"]["reused_document_revision_id"] == first


@pytest.mark.parametrize("make_ineligible", [
    lambda db, f, r: sql(db, "INSERT INTO merchant_ops.document_approvals (id, document_revision_id, "
                             "approver_role, approval_status) VALUES (%s, %s, 'PARTNER', 'REJECTED')",
                         uuid.uuid4(), r),
    lambda db, f, r: sql(db, "UPDATE merchant_ops.document_revisions SET superseded_by = %s WHERE id = %s",
                         signed_contract(db, f.project_id, 2), r),
], ids=["rejected", "superseded"])
def test_an_ineligible_source_is_never_proposed_or_bound(project, make_ineligible):
    db = project.repository
    revision = signed_contract(db, project.project_id)
    make_ineligible(db, project, revision)
    output = project_preview(db, create_text() + f" (revision {revision})")
    assert output["outcome"] == "BLOCKED" and output["requested_operation"] is None
    assert {c["kind"] for c in output["conflicts"]} & {"REUSED_REVISION_REJECTED", "REUSED_REVISION_SUPERSEDED"}


def test_an_unsigned_or_foreign_revision_is_never_a_candidate(project):
    db = project.repository
    sql(db, "INSERT INTO merchant_ops.document_revisions (id, project_id, document_type, revision_number, "
            "content_hash) VALUES (%s, %s, 'CONTRACT', 1, 'legacy')", uuid.uuid4(), project.project_id)
    # A signed contract of another Merchant's Project.
    other = uuid.uuid4()
    sql(db, "INSERT INTO merchant_ops.merchants (id, code, name, account_status) VALUES "
            "(%s, %s, %s, 'ACTIVE')", other, f"PYTEST_MASTER_{uuid.uuid4().hex[:8].upper()}",
        f"{SHORT} Foreign Cinemas")
    foreign = signed_contract(db, sibling(db, str(other), f"{SHORT} Foreign Site"))
    output = project_preview(db, create_text())
    assert output["outcome"] == "NEEDS_CLARIFICATION" and output["reuse_candidates"] == []
    forced = project_preview(db, create_text() + f" (revision {foreign})")
    assert forced["requested_operation"] is None


@pytest.mark.parametrize("text", [
    f"Create an Existing-Document Media project Q4 for {MERCHANT}, payment period 3, "
    f"using the signed contract from Project {TITLE} on the test database",
    f"Tạo Project Existing-Document Media Q4 cho Merchant {MERCHANT} kỳ 3 và sử dụng hợp đồng đã ký "
    "hiện có trên database test",
    f"Tạo Project media Q4 cho {MERCHANT} kỳ thanh toán 3, sử dụng hợp đồng đã ký của Project {TITLE} "
    "trên database test",
])
def test_vietnamese_and_english_requests_bind_the_one_eligible_revision(project, text):
    db = project.repository
    revision = signed_contract(db, project.project_id)
    output = project_preview(db, text)
    assert output["outcome"] == "READY_FOR_CONFIRMATION", output["clarifications"]
    fields = output["requested_operation"]
    assert fields["workflow_variant"] == "MEDIA_TOP_UP_EXISTING_DOCUMENT"
    assert fields["reused_document_revision_id"] == revision
    assert fields["payment_period_number"] == 3
    assert output["merchant"]["code"].startswith("PYTEST_MASTER_")
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.projects WHERE reused_document_revision_id "
                   "IS NOT NULL AND merchant_id = %s", project.merchant_id)["n"] == 0                                   # a preview binds nothing


# --------------------------------------------- authority and staleness


def test_a_handwritten_binding_cannot_run(project):
    db = project.repository
    first = signed_contract(db, project.project_id)
    second = signed_contract(db, sibling(db, project.merchant_id, f"{SHORT} Second Site"))
    text = create_text() + f" (revision {first})"
    read_run(text)
    output = project_preview(db, text)
    operation = output["requested_operation"]
    assert run_hook({
        "hook_event_name": "PostToolUse", "session_id": PANE, "agent_type": TEAMMATE, "tool_name": "Bash",
        "tool_input": {"command": f'{CLI} project preview --request "{text}" --test-database'},
        "tool_response": {"stdout": json.dumps(output, ensure_ascii=False, indent=2), "stderr": ""},
    }) == 0
    deliver(f"Preview ready.\n{PREVIEW_OPERATION_MARKER}\n"
            f"{json.dumps(operation, ensure_ascii=False, separators=(',', ':'))}\n", capsys_holder[0])
    idle()
    assert user_says("/solve Xác nhận tạo").get("hookSpecificOutput")
    reuse_teammate()
    forged = list(operation["argv"])
    forged[forged.index("--reused-document-revision-id") + 1] = second
    execute({"argv": forged})
    assert run_state().get("merchant_runtime_authorization_issued") is not True
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.projects WHERE reused_document_revision_id "
                   "IS NOT NULL AND merchant_id = %s", project.merchant_id)["n"] == 0


def test_a_source_change_after_the_preview_refuses_the_create_before_any_spend(project):
    db = project.repository
    revision = signed_contract(db, project.project_id)
    text = create_text()
    read_run(text)
    output = project_preview(db, text)
    operation = output["requested_operation"]
    assert run_hook({
        "hook_event_name": "PostToolUse", "session_id": PANE, "agent_type": TEAMMATE, "tool_name": "Bash",
        "tool_input": {"command": f'{CLI} project preview --request "{text}" --test-database'},
        "tool_response": {"stdout": json.dumps(output, ensure_ascii=False, indent=2), "stderr": ""},
    }) == 0
    deliver(f"Preview ready.\n{PREVIEW_OPERATION_MARKER}\n"
            f"{json.dumps(operation, ensure_ascii=False, separators=(',', ':'))}\n", capsys_holder[0])
    idle()
    sql(db, "INSERT INTO merchant_ops.document_approvals (id, document_revision_id, approver_role, "
            "approval_status) VALUES (%s, %s, 'LEGAL', 'REJECTED')", uuid.uuid4(), revision)
    assert user_says("/solve Xác nhận tạo").get("hookSpecificOutput")
    reuse_teammate()
    execute(operation)
    assert run_state()[HANDOFF_STATE_KEY]["failure_type"].startswith("PREFLIGHT:")
    assert run_state().get("merchant_runtime_authorization_issued") is not True
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.projects WHERE id = %s",
               operation["project_id"])["n"] == 0
    # Replay of the spent confirmation finds nothing.
    assert user_says("/solve Xác nhận tạo")["decision"] == "block"


def test_concurrent_creates_of_one_operation_bind_once(project):
    db = project.repository
    revision = signed_contract(db, project.project_id)
    operation = project_preview(db, create_text())["requested_operation"]
    args = merchant_cli.build_argument_parser().parse_args(["--database", "test", *operation["argv"]])
    payload = merchant_cli.build_write_payload(args, "project create")
    outcomes, barrier = [], threading.Barrier(3)

    def run():
        identity = attempt_evidence.AttemptIdentity(
            operation_key=f"{KEY_PREFIX}create-{uuid.uuid4().hex}", payload_hash="a" * 64,
            execution_attempt_id=uuid.uuid4(), command="project create")
        adapters = MerchantRepositoryWriteAdapters(MerchantWriteRepositories.from_repository(
            attempt_evidence.evidence_bound_repository(db, identity)))
        barrier.wait()
        try:
            adapters.create_project(dict(payload))
            outcomes.append("ok")
        except Exception as error:  # noqa: BLE001 - every loser must refuse
            outcomes.append(type(error).__name__)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 1, outcomes
    rows = [dict(r) for r in _rows(db, "SELECT id::text AS id, reused_document_revision_id::text AS r "
                                       "FROM merchant_ops.projects WHERE reused_document_revision_id IS NOT NULL "
                                       "AND merchant_id = %s", project.merchant_id)]
    assert rows == [{"id": operation["project_id"], "r": revision}]
    assert claims(db) == ["COMPLETED"]


def test_a_po_ledger_failure_on_a_reused_contract_rolls_back(project, monkeypatch):
    from tests.merchant.test_master_lifecycle_postgres import confirm, preview

    db = project.repository
    signed_contract(db, project.project_id)
    output = confirmed_create(db, create_text())
    title = one(db, "SELECT title FROM merchant_ops.projects WHERE id = %s",
                output["requested_operation"]["project_id"])["title"]
    operation = preview(db, f"Ghi nhận Purchase Order PO-{SHORT}-LF cho Project {title} trên database test"
                        )["requested_operation"]
    assert operation is not None
    confirm(operation)

    def ledger_lost(*_a, **_k):
        raise attempt_evidence.EvidenceBindingError("evidence could not be completed")

    monkeypatch.setattr(attempt_evidence, "complete_execution_claim", ledger_lost)
    execute(operation)
    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.procurement_records WHERE external_id = %s",
               f"PO-{SHORT}-LF")["n"] == 0
    assert sorted(claims(db)) == ["COMPLETED", "REVOKED"]


def test_a_project_with_its_own_signed_revision_keeps_the_existing_rules(project):
    db = project.repository
    signed_contract(db, project.project_id)        # the Project's own signed contract
    output = cli_preview(db, f"Ghi nhận Purchase Order PO-{SHORT}-OWN cho {ON}")
    assert output["outcome"] == "PREVIEW_VALID", output["domain_validation"]
    assert "reused_document" not in output["existing_evidence"]


def _rows(db, statement, *parameters):
    with db.connection(read_only=True) as connection:
        return connection.execute(statement, parameters).fetchall()
