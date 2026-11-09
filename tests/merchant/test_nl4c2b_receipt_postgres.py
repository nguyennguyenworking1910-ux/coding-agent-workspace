"""CP12H.NL4C2B-PREP: the Step Update receipt is database-derived and recoverable.

Through the real hooks on the Merchant test database (NL4C2A helpers):

- the reconciled receipt carries every required field, and claim + ledger agree;
- after the local run, team and pending state are lost, the same receipt is
  rebuilt from PostgreSQL alone;
- a teammate cannot invent one: its success report without evidence is
  denied, a fabricated identity does not reconcile, and a transition made
  outside Direct EXECUTE has no receipt.

Must run alone (no concurrent PostgreSQL test process).
"""

from __future__ import annotations

import shutil
import uuid

import pytest

from claude.clients.merchant import attempt_evidence
from claude.clients.merchant.transition_repository import MerchantStepTransitionRepository
from claude.hooks import merchant_direct_handoff as handoff
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks import team_lifecycle
from tests.merchant.test_nl4c2a_step_execution_postgres import (  # noqa: F401 (fixtures)
    LEAD,
    TEST_DB_CONFIGURED,
    confirm,
    deliver,
    execute,
    idle,
    identity_of_current_task,
    isolated,
    preview_run,
    project,
    pytest_operation_keys,
    record,
    run_state,
    runtime_state,
    sql,
    state,
    terminal,
)

pytestmark = pytest.mark.skipif(
    not TEST_DB_CONFIGURED, reason="Merchant test database not configured"
)

REQUIRED = {
    "merchant_id", "project_id", "step_id", "step_sequence", "previous_status",
    "new_status", "previous_version", "new_version", "event_id",
    "execution_attempt_id", "operation_key", "payload_hash", "claim_status",
    "ledger_command", "transaction_id",
}


def test_receipt_is_complete_and_rebuilt_from_postgres_alone(project, capsys):
    repository, project_id, merchant_id = project
    operation = preview_run(repository, capsys)
    confirm()
    assert execute(operation, capsys) is None
    stored = run_state()[handoff.STEP_RECEIPT_STATE_KEY]
    identity = identity_of_current_task()

    assert stored["status"] == "RECONCILED" and REQUIRED <= set(stored)
    assert (stored["claim_status"], stored["ledger_command"]) == ("COMPLETED", "step update")
    assert stored["payload_hash"] == identity.payload_hash
    assert (stored["merchant_id"], stored["project_id"], stored["step_id"]) == (
        merchant_id, project_id, operation["step_id"])
    assert (stored["previous_version"], stored["new_version"]) == (
        operation["step_version"], operation["step_version"] + 1)

    # Lose every piece of local state: run state, team state, pending store.
    runtime_state.clear_state(LEAD)
    pending.store_path(LEAD, pending.STEP_KIND).unlink()
    shutil.rmtree(team_lifecycle.team_state_dir())
    assert runtime_state.load_state(LEAD) is None
    assert not (team_lifecycle.load_team_state(LEAD) or {}).get("teammates")

    (recovered,) = attempt_evidence.recover_step_update_receipts(repository, operation["step_id"])
    assert recovered == {k: v for k, v in stored.items()
                         if k not in {"status", "run_id", "task_id", "database_target"}}


def test_a_teammate_cannot_invent_a_successful_receipt(project, capsys):
    repository, project_id, _ = project
    operation = preview_run(repository, capsys)
    confirm()
    sql(repository, "UPDATE merchant_ops.projects SET version = version + 1 WHERE id = %s",
        project_id)                                       # the attempt is refused unspent
    assert execute(operation, capsys) is None
    assert run_state()["merchant_runtime_handoff"]["failure_type"].startswith("PREFLIGHT:")

    forged = terminal("EXECUTE_SUCCESS")[:-1] + (
        ', "receipt": {"status": "RECONCILED", "step_id": "%s"}}' % operation["step_id"])
    assert deliver(forged, capsys) is not None              # no evidence: denied
    assert deliver(terminal("EXECUTE_SUCCESS"), capsys) is not None
    assert handoff.STEP_RECEIPT_STATE_KEY not in run_state()
    assert attempt_evidence.recover_step_update_receipts(repository, operation["step_id"]) == []

    fabricated = attempt_evidence.AttemptIdentity(
        operation_key=f"pytest:nl4c2a-scope:{uuid.uuid4().hex}", payload_hash="f" * 64,
        execution_attempt_id=uuid.uuid4(), command="step update",
    )
    with pytest.raises(attempt_evidence.EvidenceBindingError):
        attempt_evidence.step_update_receipt(repository, fabricated, operation["step_id"])


def test_a_transition_outside_direct_execute_has_no_receipt(project):
    repository, project_id, _ = project
    with repository.connection(read_only=True) as connection:
        row = connection.execute(
            "SELECT id::text, version FROM merchant_ops.project_steps "
            "WHERE project_id = %s AND sequence_number = 1", (project_id,),
        ).fetchone()
    MerchantStepTransitionRepository(repository).transition_step(
        step_id=row["id"], target_status="IN_PROGRESS", expected_version=row["version"],
    )

    assert state(repository, project_id)[0] == "IN_PROGRESS"
    assert attempt_evidence.recover_step_update_receipts(repository, row["id"]) == []
