"""CP12H.MASTER: the confirmation-first Merchant Project lifecycle, end to end,
on the Merchant test database (owner-approved DEC-SIMPLIFY, Local Test MVP).

Every operation runs through the real hooks: intent gate, read dispatch,
verified preview capture, the user's own ``/solve Xác nhận thực hiện``,
staging, preflight, the evidence-bound write transaction (claim, ledger,
mutation and event together) and the PostgreSQL-reconciled receipt. No live
``/solve`` runs; fixtures are disposable (``PYTEST_MASTER_``) and removed.
Must run alone (never concurrently with another PostgreSQL test process).
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant import lifecycle_operation as lifecycle
from claude.agents.tools.merchant.agent_cli import prepare_agent_cli_argv
from claude.agents.tools.merchant.read_commands import MerchantReadCommands
from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.agents.tools.merchant.write_adapters import (
    MerchantRepositoryWriteAdapters,
    MerchantWriteRepositories,
)
from claude.clients.merchant import approval_repository, attempt_evidence, operator_identity
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.transition_repository import MerchantStepTransitionRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository
from claude.hooks import merchant_attempt_resolution, policy_gate, runtime_state
from claude.hooks import merchant_direct_handoff as handoff
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks.merchant_preview_delivery import EVIDENCE_PREVIEW_MARKER, STEP_PREVIEW_MARKER
from claude.hooks.merchant_runtime_handoff_gate import HANDOFF_STATE_KEY
from claude.system import merchant_runtime_handoff
from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD,
    PANE,
    TEAMMATE,
    TEST_DB_CONFIGURED,
    Operation,
    dispatch,
    idle,
    isolated,
    record,
    run_hook,
    run_state,
    submit,
)
from tests.merchant.test_nl1_project_preview_postgres import _delete_fixtures
from tests.merchant.test_nl2f_execute_delivery import deliver, execute_body
from tests.merchant.test_nl3_conversational_confirmation_postgres import reuse_teammate, user_says
from tests.merchant.test_nl4b_step_preview_postgres import ask

pytestmark = pytest.mark.skipif(not TEST_DB_CONFIGURED, reason="Merchant test database not configured")

CLI = "python .claude/agents/tools/merchant/agent_cli.py"
PREFIX = "PYTEST_MASTER_"
KEY_PREFIX = "pytest:master-scope:"
OPERATOR = "0d5a0000-0000-4000-8000-000000000a01"
OTHER_OPERATOR = "0d5a0000-0000-4000-8000-000000000a02"
SHORT = f"Mst{uuid.uuid4().hex[:6]}"
TITLE = f"{SHORT} Nguyễn Văn Cừ"
ON = f"Project {TITLE} trên database test"


@pytest.fixture(autouse=True)
def pytest_operation_keys(monkeypatch):
    monkeypatch.setattr(merchant_attempt_resolution, "SCOPE_OPERATION_KEY_PREFIX", KEY_PREFIX)
    monkeypatch.setenv(operator_identity.OPERATOR_ENV, OPERATOR)


def _cleanup(repository):
    with repository.connection() as connection, connection.transaction():
        # A Project reusing a revision references it: remove it (and its
        # Steps, edges and events) before the revisions.
        reusing = [r["id"] for r in connection.execute(
            "SELECT p.id FROM merchant_ops.projects p JOIN merchant_ops.merchants m "
            "ON m.id = p.merchant_id WHERE m.code LIKE %s AND p.reused_document_revision_id IS NOT NULL",
            (PREFIX + "%",)).fetchall()]
        for project_id in reusing:
            connection.execute(
                "DELETE FROM merchant_ops.project_step_dependencies d USING merchant_ops.project_steps s "
                "WHERE d.from_step_id = s.id AND s.project_id = %s", (project_id,))
            for table, column in (("project_steps", "project_id"), ("project_events", "project_id"),
                                  ("procurement_records", "project_id"), ("projects", "id")):
                connection.execute(f"DELETE FROM merchant_ops.{table} WHERE {column} = %s", (project_id,))
        connection.execute(
            "DELETE FROM merchant_ops.document_approvals a USING merchant_ops.document_revisions d, "
            "merchant_ops.projects p, merchant_ops.merchants m WHERE a.document_revision_id = d.id "
            "AND d.project_id = p.id AND p.merchant_id = m.id AND m.code LIKE %s", (PREFIX + "%",))
        connection.execute(
            "DELETE FROM merchant_ops.document_revisions d USING merchant_ops.projects p, "
            "merchant_ops.merchants m WHERE d.project_id = p.id AND p.merchant_id = m.id "
            "AND m.code LIKE %s", (PREFIX + "%",))
        connection.execute(
            "DELETE FROM merchant_ops.procurement_records r USING merchant_ops.projects p, "
            "merchant_ops.merchants m WHERE r.project_id = p.id AND p.merchant_id = m.id "
            "AND m.code LIKE %s", (PREFIX + "%",))
        for table in ("merchant_execution_claims", "merchant_execution_ledger"):
            connection.execute(f"DELETE FROM merchant_ops.{table} WHERE operation_key LIKE %s",
                               (KEY_PREFIX + "%",))
    _delete_fixtures(repository, (), PREFIX)


class Fixture:
    def __init__(self, repository, project_id, merchant_id):
        self.repository, self.project_id, self.merchant_id = repository, project_id, merchant_id


@pytest.fixture
def project():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    _cleanup(repository)
    merchant_id = uuid.uuid4()
    with repository.connection() as connection, connection.transaction():
        connection.execute(
            "INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
            "VALUES (%s, %s, %s, 'ACTIVE')",
            (merchant_id, f"{PREFIX}{uuid.uuid4().hex[:8].upper()}", f"{SHORT} Cinemas"))
    project_id = str(MerchantWorkflowRepository(repository).create_project(
        merchant_id=str(merchant_id),
        template=get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD"),
        requires_procurement=False, title=TITLE,
    ).project_id)
    try:
        yield Fixture(repository, project_id, str(merchant_id))
    finally:
        _cleanup(repository)
        with repository.connection(read_only=True) as connection:
            assert connection.execute(
                "SELECT (SELECT count(*) FROM merchant_ops.merchants WHERE code LIKE %s)"
                " + (SELECT count(*) FROM merchant_ops.merchant_execution_claims"
                "    WHERE operation_key LIKE %s) AS n", (PREFIX + "%", KEY_PREFIX + "%"),
            ).fetchone()["n"] == 0


# ------------------------------------------------------------------ helpers


def cli_preview(repository, request):
    argv = prepare_agent_cli_argv(["evidence", "preview", "--request", request, "--test-database"])
    args = merchant_cli.build_argument_parser().parse_args(list(argv))
    return json.loads(json.dumps(merchant_cli.dispatch_read_command(
        args, MerchantReadCommands(MerchantReadRepository(repository))), default=str))


def capture(output, request, command="evidence preview", marker=EVIDENCE_PREVIEW_MARKER):
    assert run_hook({
        "hook_event_name": "PostToolUse", "session_id": PANE, "agent_type": TEAMMATE,
        "tool_name": "Bash",
        "tool_input": {"command": f'{CLI} {command} --request "{request}" --test-database'},
        "tool_response": {"stdout": json.dumps(output, ensure_ascii=False, indent=2), "stderr": ""},
    }) == 0
    exact = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    assert deliver(f"Preview.\n{marker}\n{exact}\n", capsys_holder[0]) is None
    assert idle() == 0


capsys_holder: list = [None]


READ_ASSIGNMENT = ("operation: merchant_read\ndatabase_target: test\n"
                   "Preview the operation the user described.")


def read_run(request):
    submit(request, confirmed=False, operations=[Operation.MERCHANT_READ])
    assert run_state()["merchant_read_target"] == "test"
    if dispatch(READ_ASSIGNMENT) is None:
        return
    # An idle teammate already exists: the lead reuses it (SendMessage).
    with runtime_state.locked_state(LEAD) as state:
        assert policy_gate.apply_call(state, "SendMessage",
                                      {"to": TEAMMATE, "message": READ_ASSIGNMENT},
                                      session_id=LEAD) is None


def preview(db, request):
    """A read-only preview run; returns the verified, captured output."""

    read_run(request)
    output = cli_preview(db, request)
    capture(output, request)
    return output


def terminal(outcome, command):
    return "TEAM_RESULT_JSON:\n" + json.dumps({
        "contract_version": 1, "outcome": outcome, "operation": "merchant_execute",
        "database_target": "test", "proposal_emitted": False, "command": command,
    })


def confirm(operation):
    output = user_says(f"/solve Xác nhận thực hiện {operation['operation_id'][:8]}")
    assert "hookSpecificOutput" in output, output
    assert run_state()["merchant_scope"]["argv"] == operation["argv"]
    reuse_teammate()


def execute(operation):
    return deliver(execute_body(operation["argv"]), capsys_holder[0], "execute-request")


def release(command):
    assert deliver(terminal("EXECUTE_SUCCESS", command), capsys_holder[0]) is None
    assert idle() == 0


def run_operation(db, request):
    """Preview, confirm and execute one lifecycle operation; (operation, receipt)."""

    output = preview(db, request)
    assert output["outcome"] == "PREVIEW_VALID", (output["domain_validation"], output["clarifications"])
    assert output["confirmation_available"] is True, output["confirmation_blockers"]
    operation = output["requested_operation"]
    live = [r for r in pending.live_records(LEAD, pending.LIFECYCLE_KIND)
            if r["operation_id"] == operation["operation_id"]]
    assert len(live) == 1 and live[0]["operation"] == operation
    confirm(operation)
    assert execute(operation) is None
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED", json.dumps(
        [run_state().get(HANDOFF_STATE_KEY), record()["direct_scope_execution"]], default=str)
    receipt = run_state()[handoff.LIFECYCLE_RECEIPT_STATE_KEY]
    assert receipt["status"] == "RECONCILED", receipt
    assert receipt["operator_id"] == OPERATOR and receipt["operation"] == operation["operation"]
    release(operation["command"])
    # Recovery from PostgreSQL alone gives the same evidence.
    recovered = attempt_evidence.recover_lifecycle_receipt(db, operation)
    for name in ("event_id", "transaction_id", "operation_key", "execution_attempt_id"):
        assert recovered[name] == receipt[name], name
    return operation, receipt


def run_step(db, sequence, label, title=TITLE, verb="Hoàn thành", request=None):
    """One Step Update through the confirmed pipeline, with its receipt verified."""

    request = request or (
        f"{verb} bước {sequence} của Project {title} của Merchant {SHORT} Cinemas trên database test")
    read_run(request)
    output = json.loads(json.dumps(ask(db, request), default=str))
    assert output["outcome"] == "READY_FOR_CONFIRMATION", (label, output["blocking"])
    capture(output, request, "step preview", STEP_PREVIEW_MARKER)
    operation = output["requested_operation"]
    assert user_says("/solve Xác nhận cập nhật").get("hookSpecificOutput"), label
    reuse_teammate()
    assert execute(operation) is None
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED", run_state().get(HANDOFF_STATE_KEY)
    receipt = run_state()[handoff.STEP_RECEIPT_STATE_KEY]
    assert receipt["status"] == "RECONCILED", (label, receipt)
    assert (receipt["previous_status"], receipt["new_status"]) == (
        operation["current_status"], operation["target_status"])
    # Rebuilt from PostgreSQL alone (local run state not used).
    recovered = attempt_evidence.recover_step_update_receipts(db, operation["step_id"])
    assert receipt["transaction_id"] in {r["transaction_id"] for r in recovered}
    release("step update")
    return operation


def steps(db, project_id):
    with db.connection(read_only=True) as connection:
        return {r["sequence_number"]: dict(r) for r in connection.execute(
            "SELECT id::text, sequence_number, step_name, status, version FROM merchant_ops.project_steps "
            "WHERE project_id = %s ORDER BY sequence_number", (project_id,)).fetchall()}


def advance(db, project_id, sequence, *, to="COMPLETED"):
    """Fixture setup for an ordinary Step (the accepted NL4C path covers it)."""

    repo = MerchantStepTransitionRepository(db)
    for target in ("READY", "IN_PROGRESS", "COMPLETED"):
        step = steps(db, project_id)[sequence]
        order = ("PENDING", "READY", "IN_PROGRESS", "COMPLETED")
        if order.index(step["status"]) >= order.index(target):
            continue
        repo.transition_step(step_id=step["id"], target_status=target, expected_version=step["version"])
        if target == to:
            return


def sql(db, statement, *parameters):
    with db.connection() as connection, connection.transaction():
        connection.execute(statement, parameters)


def one(db, statement, *parameters):
    with db.connection(read_only=True) as connection:
        return connection.execute(statement, parameters).fetchone()


def claims(db):
    with db.connection(read_only=True) as connection:
        return sorted(r["claim_status"] for r in connection.execute(
            "SELECT claim_status FROM merchant_ops.merchant_execution_claims WHERE operation_key LIKE %s",
            (KEY_PREFIX + "%",)).fetchall())


def spent():
    return run_state().get("merchant_runtime_authorization_issued") is True


@pytest.fixture(autouse=True)
def _capsys(capsys):
    capsys_holder[0] = capsys


# ------------------------------------------------------- the whole lifecycle


def test_a_project_completes_through_confirmed_operations_only(project):
    db, pid = project.repository, project.project_id

    # The Project starts (PLANNED -> IN_PROGRESS) as its own confirmed operation.
    _, receipt = run_operation(db, f"Bắt đầu {ON}")
    assert receipt["event_type"] == "PROJECT_STARTED"
    assert one(db, "SELECT status FROM merchant_ops.projects WHERE id = %s", pid)["status"] == "IN_PROGRESS"

    revision, receipt = run_operation(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    assert receipt["entity"]["evidence_status"] == "METADATA_ONLY"
    row = one(db, "SELECT evidence_status, content_hash, document_file_id FROM "
                  "merchant_ops.document_revisions WHERE id = %s", revision["operation_id"])
    assert (row["evidence_status"], row["content_hash"], row["document_file_id"]) == (
        "METADATA_ONLY", f"metadata-only:{revision['operation_id']}", None)

    for role, words in (("LEGAL", "Legal"), ("ACCOUNTING", "Kế toán"), ("PARTNER", "Partner")):
        decision, receipt = run_operation(
            db, f"{words} đã phê duyệt hợp đồng của {ON}, ghi chú: đồng ý điều khoản")
        approval = one(db, "SELECT approval_status, approved_by, recorded_by::text AS r, notes, decided_at "
                           "FROM merchant_ops.document_approvals WHERE id = %s", decision["operation_id"])
        assert approval["approval_status"] == "APPROVED" and approval["approved_by"] is None
        assert approval["r"] == OPERATOR and approval["decided_at"] is not None
        assert approval["notes"] == "đồng ý điều khoản"
        assert receipt["attestation"] == "OPERATOR_RECORDED"
        assert decision["params"]["role"] == role

    # Ordinary Steps 1-4, the Partner-approval gate (5) and the signing gate
    # (8) are judged from the recorded evidence, before signing (DEC-D4e
    # keeps a signed revision; the gate requires it unsigned).
    for sequence in (1, 2, 3, 4, 5, 8):
        advance(db, pid, sequence)

    signing, receipt = run_operation(db, f"Ghi nhận hợp đồng của {ON} đã ký")
    row = one(db, "SELECT signed, signing_attestation FROM merchant_ops.document_revisions WHERE id = %s",
              signing["params"]["revision_id"])
    assert (row["signed"], row["signing_attestation"]) == (True, "OPERATOR_ATTESTED_SIGNED")
    assert receipt["attestation"] == "OPERATOR_ATTESTED_SIGNED"

    run_operation(db, f"Ghi nhận Purchase Order PO-{SHORT}-001 cho {ON}")
    run_operation(db, f"Ghi nhận Payment Request PAY-{SHORT}-001 cho {ON}")

    # The final Step cannot complete while other Steps are open.
    open_request = f"Hoàn thành bước 22 của Project {TITLE} của Merchant {SHORT} Cinemas trên database test"
    blocked = ask(db, open_request)
    assert blocked["outcome"] != "READY_FOR_CONFIRMATION"

    for sequence in sorted(steps(db, pid)):
        if sequence in (21, 22) or steps(db, pid)[sequence]["status"] in ("COMPLETED", "SKIPPED"):
            continue
        advance(db, pid, sequence)

    # Steps 21 and 22 have no database evaluator: they start without
    # attestation, but completing them is operator-attested and confirmed.
    for sequence in (21, 22):
        advance(db, pid, sequence, to="IN_PROGRESS")
        with pytest.raises(Exception):                      # never without the confirmation
            MerchantStepTransitionRepository(db).transition_step(
                step_id=steps(db, pid)[sequence]["id"], target_status="COMPLETED",
                expected_version=steps(db, pid)[sequence]["version"])
        operation = run_step(db, sequence, f"step {sequence}")
        assert operation["gate_attestation"] == "OPERATOR_ATTESTED"
        event = one(db, "SELECT new_values, triggered_by::text AS t FROM merchant_ops.project_events "
                        "WHERE entity_id = %s AND event_type = 'STEP_COMPLETED'", operation["step_id"])
        assert event["new_values"]["gate_attestation"] == "OPERATOR_ATTESTED" and event["t"] == OPERATOR

    # Completing the last Step did not complete the Project.
    assert one(db, "SELECT status FROM merchant_ops.projects WHERE id = %s", pid)["status"] != "COMPLETED"
    completion, receipt = run_operation(db, f"Hoàn tất {ON}")
    assert one(db, "SELECT status FROM merchant_ops.projects WHERE id = %s", pid)["status"] == "COMPLETED"
    assert receipt["event_type"] == "PROJECT_COMPLETED"

    # Every write has exactly one completed claim; nothing else ran.
    # start, revision, 3 decisions, signing, PO, Payment Request, Steps 21 and
    # 22, completion: one completed claim per confirmed write, nothing else.
    assert claims(db) == ["COMPLETED"] * 11
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.project_events WHERE project_id = %s "
                   "AND triggered_by IS NULL AND entity_type <> 'STEP' AND event_type <> 'PROJECT_CREATED'",
               pid)["n"] == 0


def test_a_media_top_up_project_with_procurement_completes(project):
    """A second workflow variant: MEDIA_TOP_UP_NEW_DOCUMENT, procurement
    required (the proven Purchase Request path, its own confirmation phrase),
    final Step "Close payment period" attested, then Project completion."""

    db = project.repository
    title = f"{SHORT} Media Q4"
    on = f"Project {title} trên database test"
    pid = str(MerchantWorkflowRepository(db).create_project(
        merchant_id=project.merchant_id,
        template=get_standard_workflow_template("MEDIA_TOP_UP_NEW_DOCUMENT"),
        requires_procurement=True, payment_period_number=1, title=title,
    ).project_id)

    run_operation(db, f"Bắt đầu {on}")
    run_operation(db, f"Tạo phiên bản hợp đồng mới cho {on}")
    for words in ("Legal", "Kế toán", "Partner"):
        run_operation(db, f"{words} đã phê duyệt hợp đồng của {on}")

    # Purchase Request: the NL4D4A path, unchanged (its own store and phrase).
    output = preview(db, f"Ghi nhận Purchase Request PR-{SHORT}-9 cho {on}")
    assert output["outcome"] == "PREVIEW_VALID" and output["confirmation_available"] is True
    operation = output["requested_operation"]
    assert operation["operation"] == "RECORD_PURCHASE_REQUEST"      # not a lifecycle kind
    assert operation["operation"] not in lifecycle.KINDS
    assert user_says("/solve Xác nhận ghi nhận").get("hookSpecificOutput")
    reuse_teammate()
    assert execute(operation) is None
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert run_state()[handoff.PURCHASE_REQUEST_RECEIPT_STATE_KEY]["status"] == "RECONCILED"
    release("procurement update")

    for sequence in (1, 2, 3, 4, 5, 6, 7, 8):            # 5 and 8 judged from evidence
        advance(db, pid, sequence)
    run_operation(db, f"Ghi nhận hợp đồng của {on} đã ký")
    run_operation(db, f"Ghi nhận Purchase Order PO-{SHORT}-9 cho {on}")
    run_operation(db, f"Ghi nhận Payment Request PAY-{SHORT}-9 cho {on}")
    for sequence in (9, 10, 11):
        advance(db, pid, sequence)
    advance(db, pid, 12, to="IN_PROGRESS")
    attested = run_step(db, 12, "close payment period", title)
    assert attested["gate_attestation"] == "OPERATOR_ATTESTED"

    _, receipt = run_operation(db, f"Hoàn tất {on}")
    assert receipt["event_type"] == "PROJECT_COMPLETED"
    assert one(db, "SELECT status FROM merchant_ops.projects WHERE id = %s", pid)["status"] == "COMPLETED"
    assert [r["procurement_type"] for r in _rows(db, "SELECT procurement_type FROM "
            "merchant_ops.procurement_records WHERE project_id = %s ORDER BY 1", pid)] == [
        "PAYMENT_REQUEST", "PURCHASE_ORDER", "PURCHASE_REQUEST"]


def test_a_merchant_integration_project_completes_and_activates_the_merchant(project):
    """The INTEGRATION_NEW_MERCHANT variant: four evaluator-less gates are
    attested; completing "Activate Merchant" activates the ONBOARDING
    Merchant in the same transaction; the Project then completes."""

    db = project.repository
    merchant_id = uuid.uuid4()
    with db.connection() as connection, connection.transaction():
        connection.execute(
            "INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
            "VALUES (%s, %s, %s, 'ONBOARDING')",
            (merchant_id, f"{PREFIX}{uuid.uuid4().hex[:8].upper()}", f"{SHORT} Integration Pay"))
    title = f"{SHORT} Integration"
    on = f"Project {title} trên database test"
    pid = str(MerchantWorkflowRepository(db).create_project(
        merchant_id=str(merchant_id),
        template=get_standard_workflow_template("INTEGRATION_NEW_MERCHANT_STANDARD"),
        requires_procurement=False, title=title,
    ).project_id)

    def attest(sequence, label):
        advance(db, pid, sequence, to="IN_PROGRESS")
        request = (f"Hoàn thành bước {sequence} của Project {title} của Merchant "
                   f"{SHORT} Integration Pay trên database test")
        read_run(request)
        output = json.loads(json.dumps(ask(db, request), default=str))
        assert output["outcome"] == "READY_FOR_CONFIRMATION", (label, output["blocking"])
        assert output["requested_operation"]["gate_attestation"] == "OPERATOR_ATTESTED"
        capture(output, request, "step preview", STEP_PREVIEW_MARKER)
        assert user_says("/solve Xác nhận cập nhật").get("hookSpecificOutput"), label
        reuse_teammate()
        assert execute(output["requested_operation"]) is None
        assert record()["direct_scope_execution"]["status"] == "SUCCEEDED", label
        release("step update")
        return output

    run_operation(db, f"Bắt đầu {on}")
    advance(db, pid, 1)
    advance(db, pid, 2)
    attest(3, "validate master merchant identity")
    run_operation(db, f"Tạo phiên bản hợp đồng mới cho {on}")
    for words in ("Legal", "Kế toán", "Partner"):
        run_operation(db, f"{words} đã phê duyệt hợp đồng của {on}")
    for sequence in (4, 5, 6, 7, 8, 11):                 # 8 and 11 judged from evidence
        advance(db, pid, sequence)
    run_operation(db, f"Ghi nhận hợp đồng của {on} đã ký")
    run_operation(db, f"Ghi nhận Purchase Order PO-{SHORT}-INT cho {on}")
    run_operation(db, f"Ghi nhận Payment Request PAY-{SHORT}-INT cho {on}")
    for sequence in range(12, 24):
        if steps(db, pid)[sequence]["status"] not in ("COMPLETED", "SKIPPED"):
            advance(db, pid, sequence)
    attest(24, "complete UAT acceptance")
    activation = attest(25, "activate merchant")
    assert "MERCHANT_ACTIVATION_IN_SAME_TRANSACTION" in {n["code"] for n in activation.get("preview_notes", [])}
    assert one(db, "SELECT account_status FROM merchant_ops.merchants WHERE id = %s",
               merchant_id)["account_status"] == "ACTIVE"
    attest(26, "complete project")
    _, receipt = run_operation(db, f"Hoàn tất {on}")
    assert receipt["event_type"] == "PROJECT_COMPLETED"


def _rows(db, statement, *parameters):
    with db.connection(read_only=True) as connection:
        return connection.execute(statement, parameters).fetchall()


def test_ordinary_steps_run_through_the_confirmed_step_update_pipeline(project):
    """Representative ordinary Steps driven only by previews, the user's
    confirmation, Execute, revalidation, the Step event, claim, ledger and a
    PostgreSQL-reconciled receipt (no direct database update)."""

    db, pid = project.repository, project.project_id
    request = f"Bắt đầu bước 3 của Project {TITLE} của Merchant {SHORT} Cinemas trên database test"
    blocked = ask(db, request)                          # missing predecessor Step 1
    assert blocked["outcome"] != "READY_FOR_CONFIRMATION"
    assert "UNMET_DEPENDENCIES" in {b["code"] for b in blocked["blocking"]}

    started = run_step(db, 1, "start step 1", verb="Bắt đầu")
    assert (started["current_status"], started["target_status"]) == ("READY", "IN_PROGRESS")
    completed = run_step(db, 1, "complete step 1")
    assert (completed["current_status"], completed["target_status"]) == ("IN_PROGRESS", "COMPLETED")
    assert "gate_attestation" not in completed               # an ordinary Step is not attested
    # Completing Step 1 promotes its PENDING successors (Legal and Accounting
    # review) to READY in the same transaction, each with a tagged event.
    current = steps(db, pid)
    assert current[1]["status"] == "COMPLETED"
    assert current[2]["status"] == "READY" and current[3]["status"] == "READY"
    with db.connection(read_only=True) as connection:
        events = connection.execute(
            "SELECT entity_id::text AS step_id, new_values, xmin::text AS tx "
            "FROM merchant_ops.project_events WHERE project_id = %s AND entity_type = 'STEP'",
            (pid,)).fetchall()
    confirmed = [e for e in events if "promoted_after_step_id" not in e["new_values"]]
    promoted = [e for e in events if "promoted_after_step_id" in e["new_values"]]
    assert len(confirmed) == 2                                # start and complete Step 1
    assert {e["step_id"] for e in promoted} >= {current[2]["id"], current[3]["id"]}
    assert {e["new_values"]["promoted_after_step_id"] for e in promoted} == {current[1]["id"]}
    (completion,) = [e for e in confirmed if e["new_values"]["status"] == "COMPLETED"]
    assert {e["tx"] for e in promoted} == {completion["tx"]}  # same transaction as the completion
    # A promotion is never reconstructed as a Step Update receipt of the promoted Step.
    assert attempt_evidence.recover_step_update_receipts(db, current[2]["id"]) == []
    assert claims(db) == ["COMPLETED"] * 2


# ------------------------------------------------- rejection and new cycles


def _approved(db, words):
    return run_operation(db, f"{words} đã phê duyệt hợp đồng của {ON}")


def test_a_rejection_blocks_signing_until_a_new_revision_starts_a_new_cycle(project):
    db = project.repository
    first, _ = run_operation(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    _approved(db, "Legal")
    _approved(db, "Kế toán")
    rejection, receipt = run_operation(db, f"Partner đã từ chối hợp đồng của {ON}, ghi chú: thiếu phụ lục")
    assert one(db, "SELECT approval_status FROM merchant_ops.document_approvals WHERE id = %s",
               rejection["operation_id"])["approval_status"] == "REJECTED"
    assert receipt["event_type"] == "DOCUMENT_REJECTED"

    refused = cli_preview(db, f"Ghi nhận hợp đồng của {ON} đã ký")
    assert refused["outcome"] == "BLOCKED"
    assert refused["domain_validation"]["error"]["code"] == lifecycle.DECISION_REJECTED
    assert refused["requested_operation"] is None

    # A decision is final: the same role cannot decide again on this revision.
    again = cli_preview(db, f"Partner đã phê duyệt hợp đồng của {ON}")
    assert again["outcome"] == "BLOCKED"

    second, _ = run_operation(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    assert second["plan"]["previous_revision_id"] == first["operation_id"]
    for words in ("Legal", "Kế toán", "Partner"):
        _approved(db, words)
    advance(db, project.project_id, 1)
    for sequence in (2, 3, 4, 5, 8):
        advance(db, project.project_id, sequence)
    signing, _ = run_operation(db, f"Ghi nhận hợp đồng của {ON} đã ký")
    assert signing["params"]["revision_id"] == second["operation_id"]

    # A signed revision is never superseded (DEC-D4e).
    blocked = cli_preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    assert blocked["outcome"] == "BLOCKED"
    assert blocked["domain_validation"]["error"]["code"] == lifecycle.SIGNED_REVISION


# ------------------------------------------------ authority and staleness


def test_a_replayed_confirmation_and_execute_request_never_write_twice(project):
    db = project.repository
    operation, _ = run_operation(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    assert user_says(f"/solve Xác nhận thực hiện {operation['operation_id'][:8]}")["decision"] == "block"
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.document_revisions d JOIN merchant_ops.projects p "
                   "ON p.id = d.project_id WHERE p.id = %s", project.project_id)["n"] == 1
    assert claims(db) == ["COMPLETED"]


def test_a_stale_preview_is_refused_before_any_spend(project):
    db = project.repository
    _, _ = run_operation(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    output = preview(db, f"Legal đã phê duyệt hợp đồng của {ON}")
    operation = output["requested_operation"]
    confirm(operation)
    sql(db, "UPDATE merchant_ops.projects SET version = version + 1 WHERE id = %s", project.project_id)

    assert execute(operation) is None
    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == f"PREFLIGHT:{lifecycle.BASIS_CHANGED}"
    assert not spent()
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.document_approvals")["n"] >= 0
    assert claims(db) == ["COMPLETED"]


def test_a_changed_operator_is_refused_before_any_spend(project, monkeypatch):
    db = project.repository
    output = preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    operation = output["requested_operation"]
    monkeypatch.setenv(operator_identity.OPERATOR_ENV, OTHER_OPERATOR)
    assert user_says(f"/solve Xác nhận thực hiện {operation['operation_id'][:8]}")["decision"] == "block"
    monkeypatch.setenv(operator_identity.OPERATOR_ENV, OPERATOR)
    confirm(operation)
    monkeypatch.setenv(operator_identity.OPERATOR_ENV, OTHER_OPERATOR)
    assert execute(operation) is None
    assert not spent()
    assert claims(db) == []


def test_a_model_edited_operation_cannot_run(project):
    db = project.repository
    output = preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    operation = output["requested_operation"]
    confirm(operation)
    forged = list(operation["argv"])
    forged[forged.index("--type") + 1] = "INVOICE"
    deliver(execute_body(forged), capsys_holder[0], "execute-request")
    assert not spent()
    assert claims(db) == []


def test_a_typed_lifecycle_scope_is_refused(project):
    db = project.repository
    output = cli_preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    argv = output["requested_operation"]["argv"]
    result = submit("Create it", argv=argv, target="test")
    assert result["decision"] == "block"
    assert claims(db) == []


def test_the_wrong_project_or_merchant_cannot_be_bound(project):
    db = project.repository
    output = cli_preview(db, f"Tạo phiên bản hợp đồng mới cho Project {SHORT} Không Tồn Tại trên database test")
    assert output["outcome"] == "NEEDS_CLARIFICATION"
    assert output["requested_operation"] is None


def test_a_change_between_preflight_and_write_is_refused_in_the_transaction(project, monkeypatch):
    db = project.repository
    output = preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    operation = output["requested_operation"]
    confirm(operation)
    real = handoff._verify_lifecycle

    def race(attempt, repository_, operation_):
        real(attempt, repository_, operation_)
        sql(db, "UPDATE merchant_ops.projects SET version = version + 1 WHERE id = %s", project.project_id)

    monkeypatch.setattr(handoff, "_verify_lifecycle", race)
    execute(operation)
    assert spent()
    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.document_revisions WHERE project_id = %s",
               project.project_id)["n"] == 0
    assert claims(db) == ["REVOKED"]


def test_a_crash_before_commit_rolls_back_everything(project, monkeypatch):
    db = project.repository
    run_operation(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    output = preview(db, f"Legal đã phê duyệt hợp đồng của {ON}")
    operation = output["requested_operation"]
    confirm(operation)

    def crash(*_a, **_k):
        raise RuntimeError("connection lost after the approval, before the event and commit")

    monkeypatch.setattr(approval_repository.MerchantApprovalRepository, "_insert_event", staticmethod(crash))
    execute(operation)
    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.document_approvals WHERE id = %s",
               operation["operation_id"])["n"] == 0
    assert claims(db) == ["COMPLETED", "REVOKED"]


def test_a_crash_after_commit_settles_from_evidence_and_recovers(project, monkeypatch):
    db = project.repository
    output = preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")
    operation = output["requested_operation"]
    confirm(operation)
    real = merchant_runtime_handoff.invoke_authorized_scope_apply

    def lost_after_commit(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("hook process lost after commit")

    monkeypatch.setattr(merchant_runtime_handoff, "invoke_authorized_scope_apply", lost_after_commit)
    execute(operation)
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert handoff.LIFECYCLE_RECEIPT_STATE_KEY not in run_state()
    receipt = attempt_evidence.recover_lifecycle_receipt(db, operation)
    assert receipt is not None and receipt["entity"]["evidence_status"] == "METADATA_ONLY"
    execute(operation)                                   # a retry cannot write again
    assert claims(db) == ["COMPLETED"]


def test_an_expired_confirmation_is_refused_unspent(project):
    db = project.repository
    operation = preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")["requested_operation"]
    with pending._locked(LEAD, pending.LIFECYCLE_KIND) as records:
        for record_ in records:
            record_["expires_at"] = 0
    assert user_says(f"/solve Xác nhận thực hiện {operation['operation_id'][:8]}")["decision"] == "block"
    assert claims(db) == []


def test_another_session_cannot_confirm(project):
    from claude.hooks import intent_gate

    db = project.repository
    operation = preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")["requested_operation"]

    def never_classified():
        raise AssertionError("a confirmation is never classified by the model")

    result = intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": "another-session",
         "prompt": f"/solve Xác nhận thực hiện {operation['operation_id'][:8]}"},
        parser_factory=never_classified, env={})
    assert result["decision"] == "block"
    assert len(pending.live_records(LEAD, pending.LIFECYCLE_KIND)) == 1   # still pending, unspent
    assert claims(db) == []


def test_a_ledger_failure_rolls_back_the_mutation(project, monkeypatch):
    db = project.repository
    operation = preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")["requested_operation"]
    confirm(operation)

    def ledger_lost(*_a, **_k):
        raise attempt_evidence.EvidenceBindingError("evidence could not be completed")

    monkeypatch.setattr(attempt_evidence, "complete_execution_claim", ledger_lost)
    execute(operation)
    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.document_revisions WHERE project_id = %s",
               project.project_id)["n"] == 0
    assert claims(db) == ["REVOKED"]


def test_reference_project_and_merchant_errors_never_yield_an_operation(project):
    db = project.repository
    sibling = str(MerchantWorkflowRepository(db).create_project(
        merchant_id=project.merchant_id,
        template=get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD"),
        requires_procurement=False, title=f"{TITLE} Twin",
    ).project_id)
    sql(db, "INSERT INTO merchant_ops.procurement_records (id, project_id, merchant_id, procurement_type, "
            "external_id) VALUES (%s, %s, %s, 'PURCHASE_ORDER', %s)",
        uuid.uuid4(), sibling, project.merchant_id, f"PO-{SHORT}-DUP")

    duplicate = cli_preview(db, f"Ghi nhận Purchase Order PO-{SHORT}-DUP cho {ON}")
    assert duplicate["outcome"] == "BLOCKED"
    assert duplicate["domain_validation"]["error"]["code"] == "PROCUREMENT_REFERENCE_DUPLICATE"

    ambiguous = cli_preview(db, f"Bắt đầu Project {SHORT} trên database test")
    assert ambiguous["outcome"] == "NEEDS_CLARIFICATION" and ambiguous["candidates"]

    wrong_merchant = cli_preview(
        db, f"Bắt đầu Project {TITLE} của Merchant {SHORT} Khác Cinemas trên database test")
    assert wrong_merchant["outcome"] == "NEEDS_CLARIFICATION"

    missing = cli_preview(db, f"Bắt đầu Project {SHORT} Không Tồn Tại trên database test")
    assert missing["outcome"] == "NEEDS_CLARIFICATION"

    premature = cli_preview(db, f"Hoàn tất {ON}")
    assert premature["outcome"] == "BLOCKED"
    assert premature["domain_validation"]["error"]["code"] == lifecycle.STEPS_UNFINISHED
    for result in (duplicate, ambiguous, wrong_merchant, missing, premature):
        assert result["requested_operation"] is None
    assert claims(db) == []


def test_an_existing_document_media_project_records_its_po_on_the_bound_revision(project):
    """MEDIA_TOP_UP_EXISTING_DOCUMENT reuses a signed, non-superseded CONTRACT
    revision of another Project of the same Merchant, bound at creation.
    CP12H.MASTER-FIX (owner-approved): the Purchase Order prerequisite now
    accepts that bound revision; it is shown in the preview and never copied
    (the full confirmed workflow: test_master_fix_reuse_postgres.py)."""

    db = project.repository
    source = str(uuid.uuid4())
    sql(db, "INSERT INTO merchant_ops.document_revisions (id, project_id, document_type, revision_number, "
            "content_hash, signed, signed_at) VALUES (%s, %s, 'CONTRACT', 1, %s, TRUE, now())",
        source, project.project_id, f"legacy-{SHORT}")
    title = f"{SHORT} Media Existing"
    pid = str(MerchantWorkflowRepository(db).create_project(
        merchant_id=project.merchant_id,
        template=get_standard_workflow_template("MEDIA_TOP_UP_EXISTING_DOCUMENT"),
        requires_procurement=False, payment_period_number=2, title=title,
        reused_document_revision_id=source,
    ).project_id)

    po = cli_preview(db, f"Ghi nhận Purchase Order PO-{SHORT}-EX cho Project {title} trên database test")
    assert po["outcome"] == "PREVIEW_VALID", po["domain_validation"]
    assert po["existing_evidence"]["reused_document"]["revision_id"] == source
    assert po["requested_operation"]["operation"] == "RECORD_PURCHASE_ORDER"
    # The reused revision is still the other Project's, unchanged.
    row = one(db, "SELECT project_id::text AS p, signed, superseded_by FROM merchant_ops.document_revisions "
                  "WHERE id = %s", source)
    assert (row["p"], row["signed"], row["superseded_by"]) == (project.project_id, True, None)
    # Its evaluator-less gate is still attestable through the Step confirmation.
    request = f"Hoàn thành bước 1 của Project {title} của Merchant {SHORT} Cinemas trên database test"
    advance(db, pid, 1, to="IN_PROGRESS")
    output = ask(db, request)
    assert output["outcome"] == "READY_FOR_CONFIRMATION", output["blocking"]
    assert output["requested_operation"]["gate_attestation"] == "OPERATOR_ATTESTED"


# ------------------------------------------------------------ concurrency


def test_concurrent_executions_of_one_operation_write_once(project):
    db = project.repository
    operation = cli_preview(db, f"Tạo phiên bản hợp đồng mới cho {ON}")["requested_operation"]
    args = merchant_cli.build_argument_parser().parse_args(["--database", "test", *operation["argv"]])
    payload = merchant_cli.build_write_payload(args, operation["command"])
    outcomes, barrier = [], threading.Barrier(4)

    def run():
        identity = attempt_evidence.AttemptIdentity(
            operation_key=f"{KEY_PREFIX}race-{uuid.uuid4().hex}", payload_hash="a" * 64,
            execution_attempt_id=uuid.uuid4(), command=operation["command"])
        adapters = MerchantRepositoryWriteAdapters(MerchantWriteRepositories.from_repository(
            attempt_evidence.evidence_bound_repository(db, identity)))
        barrier.wait()
        try:
            adapters.create_revision(dict(payload))
            outcomes.append("ok")
        except Exception as error:  # noqa: BLE001 - every loser must refuse
            outcomes.append(type(error).__name__)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 1, outcomes
    assert one(db, "SELECT count(*) AS n FROM merchant_ops.document_revisions WHERE project_id = %s",
               project.project_id)["n"] == 1
    assert claims(db) == ["COMPLETED"]
