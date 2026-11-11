"""CP12H.NL4D4A on the Merchant test database: confirmed Purchase Request recording.

Run A is the unscoped read-only ``evidence preview``: the real PostToolUse(Bash)
hook captures the CLI output and records the trusted pending Purchase Request.
The user's own ``/solve Xác nhận ghi nhận`` then starts Run B, which executes
through the unchanged Direct EXECUTE pipeline: intent gate, policy gate, pane
identity, staging, completeness, team-state reservation, one-use spend,
evidence-bound transaction (claim + ledger + procurement row + PROCUREMENT
event) and TeammateIdle settlement.

Each test seeds throwaway ``PYTEST_NL4D4A_`` Merchants and Projects and removes
exactly what it created; evidence uses ``pytest:`` operation keys. Never
touches the NL2/NL3/NL4C acceptance Projects. Must run alone: never
concurrently with another PostgreSQL test process on the same database.
"""

from __future__ import annotations

import json
import threading
import uuid

import psycopg
import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant import purchase_request as pr_contract
from claude.agents.tools.merchant.agent_cli import prepare_agent_cli_argv
from claude.agents.tools.merchant.read_commands import MerchantReadCommands
from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.agents.tools.merchant.write_adapters import (
    MerchantRepositoryWriteAdapters,
    MerchantWriteRepositories,
)
from claude.clients.merchant import attempt_evidence, operator_identity, procurement_repository
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository
from claude.hooks import merchant_attempt_resolution
from claude.hooks import merchant_direct_handoff as handoff
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks.merchant_preview_delivery import EVIDENCE_PREVIEW_MARKER
from claude.hooks.merchant_runtime_handoff_gate import HANDOFF_STATE_KEY, HANDOFF_SUCCESS
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
from tests.merchant.test_nl3_conversational_confirmation_postgres import (
    reuse_teammate,
    user_says,
)

pytestmark = pytest.mark.skipif(
    not TEST_DB_CONFIGURED, reason="Merchant test database not configured"
)

CLI = "python .claude/agents/tools/merchant/agent_cli.py"
PREFIX = "PYTEST_NL4D4A_"
KEY_PREFIX = "pytest:nl4d4a-scope:"
OPERATOR = "0d4a0000-0000-4000-8000-00000000e2e0"
OTHER_OPERATOR = "0d4a0000-0000-4000-8000-00000000e2e1"
SHORT = f"Nlpr{uuid.uuid4().hex[:6]}"
TITLE = f"{SHORT} Nguyễn Văn Cừ"
REFERENCE = "PR-NL4D4A-001"
REQUEST = f"Ghi nhận Purchase Request {REFERENCE} cho Project {TITLE} trên database test"


@pytest.fixture(autouse=True)
def pytest_operation_keys(monkeypatch):
    monkeypatch.setattr(merchant_attempt_resolution, "SCOPE_OPERATION_KEY_PREFIX", KEY_PREFIX)
    monkeypatch.setenv(operator_identity.OPERATOR_ENV, OPERATOR)


def _cleanup(repository):
    with repository.connection() as connection, connection.transaction():
        connection.execute(
            "DELETE FROM merchant_ops.procurement_records r USING merchant_ops.projects p, "
            "merchant_ops.merchants m WHERE r.project_id = p.id AND p.merchant_id = m.id "
            "AND m.code LIKE %s", (PREFIX + "%",))
        for table in ("merchant_execution_claims", "merchant_execution_ledger"):
            connection.execute(
                f"DELETE FROM merchant_ops.{table} WHERE operation_key LIKE %s",
                (KEY_PREFIX + "%",))
    _delete_fixtures(repository, (), PREFIX)


def _merchant(repository, name):
    merchant_id = uuid.uuid4()
    with repository.connection() as connection, connection.transaction():
        connection.execute(
            "INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
            "VALUES (%s, %s, %s, 'ACTIVE')",
            (merchant_id, f"{PREFIX}{uuid.uuid4().hex[:8].upper()}", name),
        )
    return str(merchant_id)


def _project(repository, merchant_id, title):
    return str(MerchantWorkflowRepository(repository).create_project(
        merchant_id=merchant_id,
        template=get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD"),
        requires_procurement=False, title=title,
    ).project_id)


@pytest.fixture
def project():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    _cleanup(repository)
    merchant_id = _merchant(repository, f"{SHORT} Cinemas")
    project_id = _project(repository, merchant_id, TITLE)
    sibling_id = _project(repository, merchant_id, f"{TITLE} Twin")
    other_merchant = _merchant(repository, f"{SHORT} Other Cinemas")
    foreign_id = _project(repository, other_merchant, f"{SHORT} Lotte Nguyễn")
    try:
        yield SimpleFixture(repository, project_id, merchant_id, sibling_id, foreign_id)
    finally:
        _cleanup(repository)
        with repository.connection(read_only=True) as connection:
            left = connection.execute(
                "SELECT (SELECT count(*) FROM merchant_ops.merchants WHERE code LIKE %s)"
                " + (SELECT count(*) FROM merchant_ops.merchant_execution_claims"
                "    WHERE operation_key LIKE %s) AS n",
                (PREFIX + "%", KEY_PREFIX + "%"),
            ).fetchone()["n"]
        assert left == 0


class SimpleFixture:
    def __init__(self, repository, project_id, merchant_id, sibling_id, foreign_id):
        self.repository, self.project_id, self.merchant_id = repository, project_id, merchant_id
        self.sibling_id, self.foreign_id = sibling_id, foreign_id


# ------------------------------------------------------------------ helpers


def cli_preview(repository, request=REQUEST):
    argv = prepare_agent_cli_argv(["evidence", "preview", "--request", request, "--test-database"])
    args = merchant_cli.build_argument_parser().parse_args(list(argv))
    assert args.database == "test"
    result = merchant_cli.dispatch_read_command(
        args, MerchantReadCommands(MerchantReadRepository(repository)))
    return json.loads(json.dumps(result, default=str))


def preview_run(repository, capsys):
    """Run A: the read-only preview; returns the captured requested_operation."""

    submit(REQUEST, confirmed=False, operations=[Operation.MERCHANT_READ])
    assert run_state()["merchant_read_target"] == "test"
    assert dispatch(
        "operation: merchant_read\ndatabase_target: test\n"
        "Preview the Purchase Request the user described."
    ) is None

    output = cli_preview(repository)
    assert output["outcome"] == "PREVIEW_VALID", output
    assert [n["code"] for n in output["policy_notes"]] == ["PROCUREMENT_NOT_REQUIRED"]
    assert output["confirmation_available"] is True
    assert run_hook({
        "hook_event_name": "PostToolUse", "session_id": PANE,
        "agent_type": TEAMMATE, "tool_name": "Bash",
        "tool_input": {"command": f'{CLI} evidence preview --request "{REQUEST}" --test-database'},
        "tool_response": {"stdout": json.dumps(output, ensure_ascii=False, indent=2),
                          "stderr": ""},
    }) == 0

    exact = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    assert deliver(f"{REFERENCE} can be recorded.\n{EVIDENCE_PREVIEW_MARKER}\n{exact}\n",
                   capsys) is None
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"

    operation = output["requested_operation"]
    (live,) = pending.live_records(LEAD, pending.PURCHASE_REQUEST_KIND)
    assert live["operation"] == operation and live["operator_id"] == OPERATOR
    return operation


def confirm():
    output = user_says("/solve Xác nhận ghi nhận")
    assert "hookSpecificOutput" in output, output
    assert run_state()["merchant_scope"]["command"] == "procurement update"
    reuse_teammate()


def execute(operation, capsys):
    return deliver(execute_body(operation["argv"]), capsys, "execute-request")


def records(repository, project_id=None):
    with repository.connection(read_only=True) as connection:
        rows = connection.execute(
            "SELECT r.project_id::text, r.merchant_id::text, r.procurement_type, r.external_id, "
            "r.status, r.version FROM merchant_ops.procurement_records r "
            "JOIN merchant_ops.projects p ON p.id = r.project_id "
            "JOIN merchant_ops.merchants m ON m.id = p.merchant_id WHERE m.code LIKE %s "
            "AND (%s::uuid IS NULL OR r.project_id = %s::uuid) ORDER BY 1",
            (PREFIX + "%", project_id, project_id),
        ).fetchall()
    return [tuple(row.values()) for row in rows]


def events(repository, project_id):
    with repository.connection(read_only=True) as connection:
        return connection.execute(
            "SELECT entity_type, event_type, triggered_by::text AS operator "
            "FROM merchant_ops.project_events WHERE project_id = %s ORDER BY created_at",
            (project_id,),
        ).fetchall()


def steps(repository, project_id):
    with repository.connection(read_only=True) as connection:
        return [tuple(r.values()) for r in connection.execute(
            "SELECT sequence_number, status, version FROM merchant_ops.project_steps "
            "WHERE project_id = %s ORDER BY sequence_number", (project_id,)).fetchall()]


def claims(repository):
    with repository.connection(read_only=True) as connection:
        return [row["claim_status"] for row in connection.execute(
            "SELECT claim_status FROM merchant_ops.merchant_execution_claims "
            "WHERE operation_key LIKE %s", (KEY_PREFIX + "%",),
        ).fetchall()]


def sql(repository, statement, *parameters):
    with repository.connection() as connection, connection.transaction():
        connection.execute(statement, parameters)


def insert_record(repository, project_id, merchant_id, reference, kind="PURCHASE_REQUEST"):
    sql(repository,
        "INSERT INTO merchant_ops.procurement_records (id, project_id, merchant_id, "
        "procurement_type, external_id) VALUES (%s, %s, %s, %s, %s)",
        uuid.uuid4(), project_id, merchant_id, kind, reference)


def spent():
    return run_state().get("merchant_runtime_authorization_issued") is True


def terminal(outcome):
    return "TEAM_RESULT_JSON:\n" + json.dumps({
        "contract_version": 1, "outcome": outcome, "operation": "merchant_execute",
        "database_target": "test", "proposal_emitted": False, "command": "procurement update",
    })


def identity_of_current_task():
    execution = record()["direct_scope_execution"]
    return merchant_attempt_resolution.scope_attempt_identity(LEAD, TEAMMATE, execution)


def confirmed_payload(operation):
    args = merchant_cli.build_argument_parser().parse_args(
        ["--database", "test", *operation["argv"]])
    return merchant_cli.build_write_payload(args, "procurement update")


# ----------------------------------------------------------------- success


def test_confirmed_purchase_request_is_recorded_once_with_a_reconciled_receipt(project, capsys):
    db, project_id = project.repository, project.project_id
    steps_before = steps(db, project_id)
    operation = preview_run(db, capsys)
    assert records(db) == []

    confirm()
    assert execute(operation, capsys) is None

    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert run_state()[HANDOFF_STATE_KEY]["status"] == HANDOFF_SUCCESS
    assert records(db) == [(project_id, project.merchant_id, "PURCHASE_REQUEST", REFERENCE,
                            None, 1)]
    assert [tuple(e.values()) for e in events(db, project_id)
            if e["entity_type"] == "PROCUREMENT"] == [
        ("PROCUREMENT", "PROCUREMENT_CREATED", OPERATOR)]
    assert claims(db) == ["COMPLETED"]
    # DEC-P2: no Step or workflow state changed.
    assert steps(db, project_id) == steps_before

    receipt = run_state()[handoff.PURCHASE_REQUEST_RECEIPT_STATE_KEY]
    identity = identity_of_current_task()
    assert receipt["status"] == "RECONCILED", receipt
    assert {k: receipt[k] for k in (
        "operator_id", "merchant_id", "project_id", "procurement_type", "reference",
        "record_version", "execution_attempt_id", "operation_key", "payload_hash",
        "database_target", "claim_status",
    )} == {
        "operator_id": OPERATOR, "merchant_id": project.merchant_id, "project_id": project_id,
        "procurement_type": "PURCHASE_REQUEST", "reference": REFERENCE, "record_version": 1,
        "execution_attempt_id": str(identity.execution_attempt_id),
        "operation_key": identity.operation_key, "payload_hash": identity.payload_hash,
        "database_target": "test", "claim_status": "COMPLETED",
    }
    # Recovery from PostgreSQL alone: local run and team state are not used.
    (recovered,) = attempt_evidence.recover_purchase_request_receipts(db, project_id)
    for name in ("event_id", "procurement_id", "transaction_id", "operation_key",
                 "execution_attempt_id", "operator_id", "reference"):
        assert recovered[name] == receipt[name], name

    # A contradictory terminal report is denied; the consistent one releases.
    assert deliver(terminal("EXECUTE_FAILED"), capsys) is not None
    assert deliver(terminal("EXECUTE_SUCCESS"), capsys) is None
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"

    # Replayed confirmation: the pending record was spent.
    run_id = run_state()["run_id"]
    assert user_says("/solve Xác nhận ghi nhận")["decision"] == "block"
    assert run_state()["run_id"] == run_id
    assert len(records(db)) == 1


def test_replayed_execute_request_in_the_same_task_never_writes_twice(project, capsys):
    db = project.repository
    operation = preview_run(db, capsys)
    confirm()
    assert execute(operation, capsys) is None

    execute(operation, capsys)                           # replayed teammate message

    assert len(records(db)) == 1
    assert claims(db) == ["COMPLETED"]
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"


# ------------------------------------------------------- refused before spend


@pytest.mark.parametrize("change,reason", [
    (lambda f: sql(f.repository, "UPDATE merchant_ops.projects SET version = version + 1 "
                   "WHERE id = %s", f.project_id), "PURCHASE_REQUEST_BASIS_CHANGED"),
    (lambda f: insert_record(f.repository, f.sibling_id, f.merchant_id, REFERENCE),
     "PROCUREMENT_REFERENCE_DUPLICATE"),
    (lambda f: insert_record(f.repository, f.project_id, f.merchant_id, "PR-OTHER-1"),
     "PROCUREMENT_REFERENCE_REPLACEMENT_UNSUPPORTED"),
    (lambda f: insert_record(f.repository, f.project_id, f.merchant_id, None),
     "PURCHASE_REQUEST_ALREADY_RECORDED"),
    (lambda f: f.monkeypatch.setenv(operator_identity.OPERATOR_ENV, OTHER_OPERATOR),
     "OPERATOR_IDENTITY_CHANGED"),
    (lambda f: f.monkeypatch.setattr(handoff, "REFERENCE_UNIQUE_INDEX", "missing_idx"),
     "PROCUREMENT_REFERENCE_CONSTRAINT_MISSING"),
], ids=["project-version", "duplicate-in-merchant", "replacement", "record-exists",
        "operator-substituted", "constraint-missing"])
def test_state_changed_after_confirmation_is_refused_before_any_spend(
    project, capsys, monkeypatch, change, reason
):
    db = project.repository
    operation = preview_run(db, capsys)
    confirm()
    project.monkeypatch = monkeypatch
    change(project)
    before = records(db)

    assert execute(operation, capsys) is None

    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == f"PREFLIGHT:{reason}"
    assert not spent()
    assert records(db) == before
    assert claims(db) == []
    assert "direct_scope_execution" not in record()
    # A forged success report cannot claim what did not happen.
    assert deliver(terminal("EXECUTE_SUCCESS"), capsys) is not None


def test_missing_confirmation_record_is_refused_before_any_spend(project, capsys):
    db = project.repository
    operation = preview_run(db, capsys)
    confirm()
    pending.store_path(LEAD, pending.PURCHASE_REQUEST_KIND).unlink()

    assert execute(operation, capsys) is None

    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == (
        "PREFLIGHT:PURCHASE_REQUEST_CONFIRMATION_REQUIRED")
    assert not spent()
    assert records(db) == []


def test_a_model_generated_actor_cannot_be_executed(project, capsys):
    db = project.repository
    operation = preview_run(db, capsys)
    confirm()
    forged = list(operation["argv"])
    forged[forged.index("--operator-id") + 1] = OTHER_OPERATOR

    execute({"argv": forged}, capsys)

    assert not spent()
    assert records(db) == []
    assert claims(db) == []


# ------------------------------------------------- failure and recovery


@pytest.mark.parametrize("change", [
    lambda f: insert_record(f.repository, f.sibling_id, f.merchant_id, REFERENCE),
    lambda f: sql(f.repository, "UPDATE merchant_ops.projects SET version = version + 1 "
                  "WHERE id = %s", f.project_id),
], ids=["duplicate-reference", "project-version"])
def test_change_between_preflight_and_write_is_refused_in_the_transaction(
    project, capsys, monkeypatch, change
):
    db = project.repository
    operation = preview_run(db, capsys)
    confirm()
    real = handoff._verify_purchase_request

    def race(attempt, repository_, operation_):
        real(attempt, repository_, operation_)          # preflight accepts
        change(project)                                 # then the basis changes

    monkeypatch.setattr(handoff, "_verify_purchase_request", race)

    execute(operation, capsys)

    assert spent()                                      # the single attempt is consumed
    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert records(db, project.project_id) == []        # in-transaction re-judgement refused
    assert claims(db) == ["REVOKED"]                    # fenced: can never commit later


def test_operator_substitution_inside_the_transaction_is_refused(project, capsys, monkeypatch):
    db = project.repository
    operation = preview_run(db, capsys)
    confirm()
    real = handoff._verify_purchase_request

    def swap(attempt, repository_, operation_):
        real(attempt, repository_, operation_)
        monkeypatch.setenv(operator_identity.OPERATOR_ENV, OTHER_OPERATOR)

    monkeypatch.setattr(handoff, "_verify_purchase_request", swap)

    execute(operation, capsys)

    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert records(db) == []
    assert claims(db) == ["REVOKED"]


def test_crash_before_commit_rolls_back_everything(project, capsys, monkeypatch):
    db = project.repository
    operation = preview_run(db, capsys)
    confirm()

    def crash(*_a, **_k):
        raise RuntimeError("connection lost after INSERT, before the event and commit")

    monkeypatch.setattr(procurement_repository.MerchantProcurementRepository,
                        "_insert_event", staticmethod(crash))

    execute(operation, capsys)

    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert records(db) == []
    assert claims(db) == ["REVOKED"]


def test_failed_ledger_persistence_rolls_back_the_record(project, capsys, monkeypatch):
    db = project.repository
    operation = preview_run(db, capsys)
    confirm()

    def ledger_lost(*_a, **_k):
        raise attempt_evidence.EvidenceBindingError("evidence could not be completed")

    monkeypatch.setattr(attempt_evidence, "complete_execution_claim", ledger_lost)

    execute(operation, capsys)

    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert records(db) == []                            # the INSERT ran, then rolled back
    assert claims(db) == ["REVOKED"]


def test_crash_after_commit_settles_from_evidence_and_recovers_from_postgres(
    project, capsys, monkeypatch
):
    db = project.repository
    operation = preview_run(db, capsys)
    confirm()
    real = merchant_runtime_handoff.invoke_authorized_scope_apply

    def lost_after_commit(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("hook process lost after commit")

    monkeypatch.setattr(merchant_runtime_handoff, "invoke_authorized_scope_apply",
                        lost_after_commit)

    execute(operation, capsys)

    assert run_state()[HANDOFF_STATE_KEY]["status"] != HANDOFF_SUCCESS
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert handoff.PURCHASE_REQUEST_RECEIPT_STATE_KEY not in run_state()
    (receipt,) = attempt_evidence.recover_purchase_request_receipts(db, project.project_id)
    assert (receipt["reference"], receipt["operator_id"]) == (REFERENCE, OPERATOR)
    assert receipt["execution_attempt_id"] == str(identity_of_current_task().execution_attempt_id)

    execute(operation, capsys)                          # a retry cannot write again
    assert len(records(db)) == 1
    assert claims(db) == ["COMPLETED"]


# ------------------------------------------------------------ concurrency


def _bound_adapters(repository, key, command="procurement update"):
    identity = attempt_evidence.AttemptIdentity(
        operation_key=key, payload_hash="a" * 64,
        execution_attempt_id=uuid.uuid4(), command=command,
    )
    bound = attempt_evidence.evidence_bound_repository(repository, identity)
    return MerchantRepositoryWriteAdapters(MerchantWriteRepositories.from_repository(bound))


def _race(callables):
    outcomes, barrier = [], threading.Barrier(len(callables))

    def run(call):
        barrier.wait()
        try:
            call()
            outcomes.append("ok")
        except Exception as error:  # noqa: BLE001 - every loser must refuse
            outcomes.append(type(error).__name__)

    threads = [threading.Thread(target=run, args=(c,)) for c in callables]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def test_two_claims_for_one_operation_write_once(project):
    db = project.repository
    operation = cli_preview(db)["requested_operation"]
    payload = confirmed_payload(operation)
    key = f"{KEY_PREFIX}race-{uuid.uuid4().hex}"

    outcomes = _race([
        lambda: _bound_adapters(db, key).update_procurement(dict(payload)) for _ in range(4)])

    assert outcomes.count("ok") == 1, outcomes
    assert len(records(db)) == 1
    assert claims(db) == ["COMPLETED"]


def test_concurrent_duplicate_references_on_two_projects_commit_at_most_once(
    project, monkeypatch
):
    """Both application checks pass before either inserts; the database decides."""

    db = project.repository
    first = cli_preview(db)["requested_operation"]
    second = cli_preview(db, REQUEST.replace(TITLE, f"{TITLE} Twin"))["requested_operation"]
    assert (first["project_id"], second["project_id"]) == (project.project_id, project.sibling_id)
    gate = threading.Barrier(2, timeout=30)
    real = pr_contract.verify_purchase_request

    def checked_then_wait(*args):
        plan = real(*args)
        gate.wait()                                     # both passed the application check
        return plan

    monkeypatch.setattr(pr_contract, "verify_purchase_request", checked_then_wait)

    outcomes = _race([
        lambda op=op: _bound_adapters(db, f"{KEY_PREFIX}dup-{uuid.uuid4().hex}")
        .update_procurement(confirmed_payload(op)) for op in (first, second)])

    assert outcomes.count("ok") == 1, outcomes
    assert "ProcurementConflictError" in outcomes      # the unique index refused the other
    assert [r[3] for r in records(db)] == [REFERENCE]
    assert sorted(claims(db)) == ["COMPLETED"]          # the loser's evidence rolled back


def test_the_same_reference_at_another_merchant_is_recorded(project):
    db = project.repository
    foreign = cli_preview(db, REQUEST.replace(TITLE, f"{SHORT} Lotte Nguyễn"))
    own = cli_preview(db)["requested_operation"]
    other = foreign["requested_operation"]

    _bound_adapters(db, f"{KEY_PREFIX}m1-{uuid.uuid4().hex}").update_procurement(
        confirmed_payload(own))
    _bound_adapters(db, f"{KEY_PREFIX}m2-{uuid.uuid4().hex}").update_procurement(
        confirmed_payload(other))

    assert sorted(r[3] for r in records(db)) == [REFERENCE, REFERENCE]
    assert len({r[1] for r in records(db)}) == 2


def test_the_database_itself_rejects_a_duplicate_within_a_merchant(project):
    db = project.repository
    insert_record(db, project.project_id, project.merchant_id, "PR-DB-1")

    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_record(db, project.sibling_id, project.merchant_id, "PR-DB-1")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):     # Merchant pinned to Project
        insert_record(db, project.sibling_id, str(uuid.uuid4()), "PR-DB-2")
    insert_record(db, project.foreign_id, _merchant_of(db, project.foreign_id), "PR-DB-1")


def _merchant_of(repository, project_id):
    with repository.connection(read_only=True) as connection:
        return str(connection.execute(
            "SELECT merchant_id FROM merchant_ops.projects WHERE id = %s", (project_id,)
        ).fetchone()["merchant_id"])
