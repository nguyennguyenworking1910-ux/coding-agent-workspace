"""CP12H.NL4C2A on the Merchant test database: confirmed Step Update execution.

Run A is the unscoped read-only ``step preview``: the real PostToolUse(Bash)
hook captures the CLI output and records the trusted pending Step Update.
The user's own ``/solve Xác nhận cập nhật`` then starts Run B, which executes
through the unchanged Direct EXECUTE pipeline: intent gate, policy gate,
pane identity, staging, completeness, team-state reservation, one-use spend,
evidence-bound transaction (claim + ledger + Step event) and TeammateIdle
settlement.

Each test seeds a throwaway ``PYTEST_NL4C2A_`` Merchant and Project and
removes exactly what it created; evidence uses ``pytest:`` operation keys.
Never touches the NL2/NL3 acceptance Projects. Must run alone: never
concurrently with another PostgreSQL test process on the same database.
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

from claude.agents.tools.merchant.write_adapters import (
    MerchantRepositoryWriteAdapters,
    MerchantWriteRepositories,
)
from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.clients.merchant import attempt_evidence, transition_repository
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository
from claude.hooks import merchant_attempt_resolution
from claude.hooks import merchant_direct_handoff as handoff
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks import team_lifecycle
from claude.hooks.merchant_preview_delivery import STEP_PREVIEW_MARKER
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
    policy_gate,
    record,
    run_hook,
    run_state,
    runtime_state,
    submit,
)
from tests.merchant.test_nl1_project_preview_postgres import _delete_fixtures
from tests.merchant.test_nl2f_execute_delivery import deliver, execute_body
from tests.merchant.test_nl3_conversational_confirmation_postgres import (
    reuse_teammate,
    user_says,
)
from tests.merchant.test_nl4b_step_preview_postgres import ask
from tests.merchant.test_nl4c1_step_confirmation import payload_of

pytestmark = pytest.mark.skipif(
    not TEST_DB_CONFIGURED, reason="Merchant test database not configured"
)

CLI = "python .claude/agents/tools/merchant/agent_cli.py"
PREFIX = "PYTEST_NL4C2A_"
KEY_PREFIX = "pytest:nl4c2a-scope:"
SHORT = f"Nlexec{uuid.uuid4().hex[:6]}"
TITLE = f"{SHORT} Nguyễn Văn Cừ"
REQUEST = f"Bắt đầu bước 1 của Project {TITLE} của Merchant {SHORT} Cinemas trên database test"


@pytest.fixture(autouse=True)
def pytest_operation_keys(monkeypatch):
    monkeypatch.setattr(merchant_attempt_resolution, "SCOPE_OPERATION_KEY_PREFIX", KEY_PREFIX)


def _delete_evidence(repository):
    with repository.connection() as connection, connection.transaction():
        for table in ("merchant_execution_claims", "merchant_execution_ledger"):
            connection.execute(
                f"DELETE FROM merchant_ops.{table} WHERE operation_key LIKE %s",
                (KEY_PREFIX + "%",),
            )


@pytest.fixture
def project():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    _delete_fixtures(repository, (), PREFIX)
    _delete_evidence(repository)
    merchant_id = uuid.uuid4()
    with repository.connection() as connection, connection.transaction():
        connection.execute(
            "INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
            "VALUES (%s, %s, %s, 'ACTIVE')",
            (merchant_id, f"{PREFIX}{uuid.uuid4().hex[:8].upper()}", f"{SHORT} Cinemas"),
        )
    created = MerchantWorkflowRepository(repository).create_project(
        merchant_id=str(merchant_id),
        template=get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD"),
        requires_procurement=False, title=TITLE,
    )
    try:
        yield repository, str(created.project_id), str(merchant_id)
    finally:
        _delete_fixtures(repository, (merchant_id,), PREFIX)
        _delete_evidence(repository)
        with repository.connection(read_only=True) as connection:
            left = connection.execute(
                "SELECT (SELECT count(*) FROM merchant_ops.merchants WHERE code LIKE %s)"
                " + (SELECT count(*) FROM merchant_ops.merchant_execution_claims"
                "    WHERE operation_key LIKE %s) AS n",
                (PREFIX + "%", KEY_PREFIX + "%"),
            ).fetchone()["n"]
        assert left == 0


# ------------------------------------------------------------------ helpers


def preview_run(repository, capsys):
    """Run A: the read-only preview; returns the captured requested_operation."""

    submit(REQUEST, confirmed=False, operations=[Operation.MERCHANT_READ])
    assert run_state()["merchant_read_target"] == "test"
    assert run_state()["operations"] == ["merchant_read"]
    assert dispatch(
        "operation: merchant_read\ndatabase_target: test\n"
        "Preview the Step update the user described."
    ) is None

    output = json.loads(json.dumps(ask(repository, REQUEST), default=str))
    assert output["outcome"] == "READY_FOR_CONFIRMATION", output["blocking"]
    assert run_hook({
        "hook_event_name": "PostToolUse", "session_id": PANE,
        "agent_type": TEAMMATE, "tool_name": "Bash",
        "tool_input": {"command": f'{CLI} step preview --request "{REQUEST}" --test-database'},
        "tool_response": {"stdout": json.dumps(output, ensure_ascii=False, indent=2),
                          "stderr": ""},
    }) == 0

    exact = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    assert deliver(f"Step 1 can start.\n{STEP_PREVIEW_MARKER}\n{exact}\n", capsys) is None
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"

    operation = output["requested_operation"]
    (live,) = pending.live_records(LEAD, pending.STEP_KIND)
    assert live["operation"] == operation
    return operation


def confirm():
    output = user_says("/solve Xác nhận cập nhật")
    assert "hookSpecificOutput" in output, output
    assert run_state()["merchant_scope"]["command"] == "step update"
    reuse_teammate()


def execute(operation, capsys):
    return deliver(execute_body(operation["argv"]), capsys, "execute-request")


def state(repository, project_id):
    with repository.connection(read_only=True) as connection:
        step = connection.execute(
            "SELECT status, version FROM merchant_ops.project_steps "
            "WHERE project_id = %s AND sequence_number = 1", (project_id,),
        ).fetchone()
        events = connection.execute(
            "SELECT count(*) AS n FROM merchant_ops.project_events "
            "WHERE project_id = %s AND entity_type = 'STEP'", (project_id,),
        ).fetchone()["n"]
    return step["status"], step["version"], events


def claims(repository):
    with repository.connection(read_only=True) as connection:
        return [row["claim_status"] for row in connection.execute(
            "SELECT claim_status FROM merchant_ops.merchant_execution_claims "
            "WHERE operation_key LIKE %s", (KEY_PREFIX + "%",),
        ).fetchall()]


def sql(repository, statement, *parameters):
    with repository.connection() as connection, connection.transaction():
        connection.execute(statement, parameters)


def spent():
    return run_state().get("merchant_runtime_authorization_issued") is True


def terminal(outcome):
    return "TEAM_RESULT_JSON:\n" + json.dumps({
        "contract_version": 1, "outcome": outcome, "operation": "merchant_execute",
        "database_target": "test", "proposal_emitted": False, "command": "step update",
    })


def identity_of_current_task():
    execution = record()["direct_scope_execution"]
    return merchant_attempt_resolution.scope_attempt_identity(LEAD, TEAMMATE, execution)


# ----------------------------------------------------------------- success


def test_confirmed_step_update_executes_once_with_a_reconciled_receipt(project, capsys):
    repository, project_id, merchant_id = project
    operation = preview_run(repository, capsys)
    assert state(repository, project_id) == ("READY", operation["step_version"], 0)

    confirm()
    assert execute(operation, capsys) is None

    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert run_state()[HANDOFF_STATE_KEY]["status"] == HANDOFF_SUCCESS
    assert state(repository, project_id) == ("IN_PROGRESS", operation["step_version"] + 1, 1)
    assert claims(repository) == ["COMPLETED"]

    receipt = run_state()[handoff.STEP_RECEIPT_STATE_KEY]
    identity = identity_of_current_task()
    assert receipt["status"] == "RECONCILED", receipt
    assert {k: receipt[k] for k in (
        "merchant_id", "project_id", "step_id", "step_sequence", "previous_status",
        "new_status", "previous_version", "new_version", "execution_attempt_id",
        "operation_key", "database_target",
    )} == {
        "merchant_id": merchant_id, "project_id": project_id,
        "step_id": operation["step_id"], "step_sequence": 1,
        "previous_status": "READY", "new_status": "IN_PROGRESS",
        "previous_version": operation["step_version"],
        "new_version": operation["step_version"] + 1,
        "execution_attempt_id": str(identity.execution_attempt_id),
        "operation_key": identity.operation_key, "database_target": "test",
    }
    # Independently reproducible from the durable evidence alone.
    again = attempt_evidence.step_update_receipt(repository, identity, operation["step_id"])
    assert again["event_id"] == receipt["event_id"]
    assert again["transaction_id"] == receipt["transaction_id"]

    # A contradictory terminal report is denied; the consistent one releases.
    assert deliver(terminal("EXECUTE_FAILED"), capsys) is not None
    assert deliver(terminal("EXECUTE_SUCCESS"), capsys) is None
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"

    # Replayed confirmation: the pending record was spent.
    run_id = run_state()["run_id"]
    assert user_says("/solve Xác nhận cập nhật")["decision"] == "block"
    assert run_state()["run_id"] == run_id
    assert state(repository, project_id)[2] == 1


def test_replayed_execute_request_in_the_same_task_never_writes_twice(project, capsys):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    confirm()
    assert execute(operation, capsys) is None
    after = state(repository, project_id)

    execute(operation, capsys)                           # replayed teammate message

    assert state(repository, project_id) == after
    assert claims(repository) == ["COMPLETED"]
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"


# ------------------------------------------------------- refused before spend


@pytest.mark.parametrize(
    "change,reason",
    [
        ("UPDATE merchant_ops.projects SET version = version + 1 WHERE id = %s",
         "STEP_BASIS_CHANGED"),
        ("UPDATE merchant_ops.project_steps SET version = version + 1 "
         "WHERE project_id = %s AND sequence_number = 1", "STEP_VERSION_CHANGED"),
        ("DELETE FROM merchant_ops.project_step_dependencies d USING merchant_ops.project_steps s "
         "WHERE d.to_step_id = s.id AND s.project_id = %s AND s.sequence_number = 3",
         "STEP_BASIS_CHANGED"),
    ],
    ids=["project-version", "step-version", "dependency-graph"],
)
def test_state_changed_after_confirmation_is_refused_before_any_spend(
    project, capsys, change, reason
):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    confirm()
    sql(repository, change, project_id)
    before = state(repository, project_id)

    assert execute(operation, capsys) is None

    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == f"PREFLIGHT:{reason}"
    assert not spent()
    assert state(repository, project_id) == before
    assert claims(repository) == []
    assert "direct_scope_execution" not in record()


def test_missing_confirmation_record_is_refused_before_any_spend(project, capsys):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    confirm()
    pending.store_path(LEAD, pending.STEP_KIND).unlink()      # stale/missing evidence
    before = state(repository, project_id)

    assert execute(operation, capsys) is None

    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == "PREFLIGHT:STEP_CONFIRMATION_REQUIRED"
    assert not spent()
    assert state(repository, project_id) == before


def test_unverified_pane_cannot_execute(project, capsys):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    confirm()
    before = state(repository, project_id)

    run_hook({
        "hook_event_name": "PostToolUse", "session_id": "intruder-pane",
        "agent_type": TEAMMATE, "tool_name": "SendMessage", "tool_use_id": "execute-request",
        "tool_input": {"recipient": "team-lead", "message": execute_body(operation["argv"])},
    }, tmux="%9")

    assert not spent()
    assert state(repository, project_id) == before
    assert claims(repository) == []


def test_stale_teammate_definition_is_never_reused(project, capsys):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    with team_lifecycle.locked_team_state(LEAD) as team:
        team["teammates"][TEAMMATE]["definition_sha256"] = "0" * 64   # definition changed

    assert "hookSpecificOutput" in user_says("/solve Xác nhận cập nhật")
    assert dispatch() is not None
    with runtime_state.locked_state(LEAD) as current:
        assert policy_gate.apply_call(
            current, "SendMessage",
            {"to": TEAMMATE, "message": "Perform the user's Merchant request."},
            session_id=LEAD,
        ) is not None

    assert not spent()
    assert state(repository, project_id) == ("READY", operation["step_version"], 0)


# ------------------------------------------------- failure and recovery


def test_change_between_preflight_and_write_is_refused_in_the_transaction(
    project, capsys, monkeypatch
):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    confirm()
    real = handoff._verify_step_preview

    def race(attempt, repository_):
        real(attempt, repository_)                   # preflight accepts
        sql(repository, "UPDATE merchant_ops.project_steps SET version = version + 1 "
                        "WHERE project_id = %s AND sequence_number = 3", project_id)

    monkeypatch.setattr(handoff, "_verify_step_preview", race)
    before = state(repository, project_id)

    execute(operation, capsys)

    assert spent()                                   # the single attempt is consumed
    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert state(repository, project_id) == before   # in-transaction re-judgement refused
    assert claims(repository) == ["REVOKED"]         # fenced: can never commit later


def test_crash_before_commit_rolls_back_everything(project, capsys, monkeypatch):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    confirm()

    def crash(*_a, **_k):
        raise RuntimeError("connection lost after UPDATE, before commit")

    monkeypatch.setattr(transition_repository, "should_activate_merchant_on_step_transition", crash)
    before = state(repository, project_id)

    execute(operation, capsys)

    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert state(repository, project_id) == before
    assert claims(repository) == ["REVOKED"]


def test_failed_evidence_persistence_rolls_back_the_mutation(project, capsys, monkeypatch):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    confirm()

    def ledger_lost(*_a, **_k):
        raise attempt_evidence.EvidenceBindingError("evidence could not be completed")

    monkeypatch.setattr(attempt_evidence, "complete_execution_claim", ledger_lost)
    before = state(repository, project_id)

    execute(operation, capsys)

    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert state(repository, project_id) == before   # the UPDATE ran, then rolled back
    assert claims(repository) == ["REVOKED"]


def test_crash_after_commit_before_delivery_settles_from_evidence(project, capsys, monkeypatch):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    confirm()
    real = merchant_runtime_handoff.invoke_authorized_scope_apply

    def lost_after_commit(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("hook process lost after commit")

    monkeypatch.setattr(merchant_runtime_handoff, "invoke_authorized_scope_apply", lost_after_commit)

    execute(operation, capsys)

    assert run_state()[HANDOFF_STATE_KEY]["status"] != HANDOFF_SUCCESS
    # Settled from committed evidence, never retried, never inferred rolled back.
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert state(repository, project_id) == ("IN_PROGRESS", operation["step_version"] + 1, 1)
    receipt = attempt_evidence.step_update_receipt(
        repository, identity_of_current_task(), operation["step_id"]
    )
    assert (receipt["previous_status"], receipt["new_status"]) == ("READY", "IN_PROGRESS")

    execute(operation, capsys)                       # a retry cannot write again
    assert state(repository, project_id)[2] == 1
    assert claims(repository) == ["COMPLETED"]


def test_two_claims_for_one_step_operation_write_once(project, capsys):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    payload = payload_of(operation["argv"])
    key = f"{KEY_PREFIX}race-{uuid.uuid4().hex}"
    outcomes = []
    barrier = threading.Barrier(4)

    def run():
        identity = attempt_evidence.AttemptIdentity(
            operation_key=key, payload_hash="a" * 64,
            execution_attempt_id=uuid.uuid4(), command="step update",
        )
        bound = attempt_evidence.evidence_bound_repository(repository, identity)
        adapters = MerchantRepositoryWriteAdapters(MerchantWriteRepositories.from_repository(bound))
        barrier.wait()
        try:
            adapters.update_step(dict(payload))
            outcomes.append("ok")
        except Exception as error:  # noqa: BLE001 - every loser must refuse
            outcomes.append(type(error).__name__)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("ok") == 1, outcomes
    assert state(repository, project_id) == ("IN_PROGRESS", operation["step_version"] + 1, 1)
    assert claims(repository) == ["COMPLETED"]


# ------------------------------------------------------ test-run isolation


def test_a_second_pytest_process_is_refused_while_this_one_holds_the_database(project):
    import os
    import subprocess
    import sys

    from tests.merchant import conftest

    assert conftest._lock.get("state") == "held"     # taken by this process
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/merchant/test_nl4c1_step_confirmation_postgres.py"],
        capture_output=True, text=True, env=dict(os.environ), timeout=300,
    )

    assert result.returncode == 3, result.stdout[-2000:]
    assert "must run sequentially" in result.stdout + result.stderr
