import os
import uuid

import pytest

from claude.hooks import team_lifecycle
from claude.hooks.merchant_direct_write_state import (
    reserve_merchant_create,
)
from claude.hooks.merchant_reserved_execution import (
    execute_reserved_merchant_create,
    ReservedExecutionError,
)
from claude.hooks.merchant_direct_recovery import (
    reconcile_committed_merchant_create,
)
from claude.clients.merchant.repository import MerchantRepository


pytestmark = pytest.mark.skipif(
    os.environ.get("MERCHANT_TEST_DB_NAME")
    != "coding_agent_merchant_test"
    or not os.environ.get("MERCHANT_TEST_PASSWORD"),
    reason="Merchant test database not configured",
)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(
        team_lifecycle,
        "team_state_dir",
        lambda: tmp_path,
    )

    owner = "pytest-e2e-" + uuid.uuid4().hex
    pane = "pane-" + uuid.uuid4().hex
    run_id = "run-" + uuid.uuid4().hex
    task_id = "task-" + uuid.uuid4().hex
    write_id = "write-" + uuid.uuid4().hex

    context = {
        "owner_session_id": owner,
        "teammate_name": "merchant-manager",
        "pane_session_id": pane,
        "run_id": run_id,
        "task_id": task_id,
        "write_id": write_id,
        "database": "test",
    }

    with team_lifecycle.locked_team_state(owner) as state:
        state.setdefault("teammates", {})[
            "merchant-manager"
        ] = {
            "canonical_name": "merchant-manager",
            "status": "RUNNING",
            "current_run_id": run_id,
            "current_task_id": task_id,
            "trusted_pane_session_id": pane,
            "authorized_operations": ["merchant_execute"],
            "authorized_selected_agents": ["merchant-manager"],
            "result_received": False,
            "report_source": None,
        }

    return MerchantRepository(role="test"), context


def record(context):
    state = team_lifecycle.load_team_state(
        context["owner_session_id"]
    )
    return state["teammates"]["merchant-manager"]


def counts(repo, merchant_id, operation_key):
    with repo.connection(read_only=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM merchant_ops.merchants
                WHERE id = %s
                """,
                (uuid.UUID(merchant_id),),
            )
            merchant_count = cur.fetchone()["n"]

            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM merchant_ops.project_events
                WHERE merchant_id = %s
                  AND entity_type = 'MERCHANT'
                """,
                (uuid.UUID(merchant_id),),
            )
            event_count = cur.fetchone()["n"]

            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM merchant_ops.merchant_execution_ledger
                WHERE operation_key = %s
                """,
                (operation_key,),
            )
            ledger_count = cur.fetchone()["n"]

    return merchant_count, event_count, ledger_count


def cleanup(repo, merchant_id, operation_key):
    with repo.connection() as conn:
        with conn.transaction():
            conn.execute(
                """
                DELETE FROM merchant_ops.merchant_execution_claims
                WHERE operation_key = %s
                """,
                (operation_key,),
            )

            conn.execute(
                """
                DELETE FROM merchant_ops.merchant_execution_ledger
                WHERE operation_key = %s
                """,
                (operation_key,),
            )

            if merchant_id is not None:
                mid = uuid.UUID(merchant_id)

                conn.execute(
                    """
                    DELETE FROM merchant_ops.project_events
                    WHERE merchant_id = %s
                      AND entity_type = 'MERCHANT'
                    """,
                    (mid,),
                )

                conn.execute(
                    """
                    DELETE FROM merchant_ops.merchants
                    WHERE id = %s
                    """,
                    (mid,),
                )


def test_reserved_execution_commit_and_recovery(environment):
    repo, context = environment

    payload = {
        "code": "T" + uuid.uuid4().hex[:18].upper(),
        "name": "Reserved E2E Merchant",
    }

    merchant_id = None
    operation_key = None

    try:
        reserved = reserve_merchant_create(
            **context,
            payload=payload,
        )

        operation_key = reserved["operation_key"]

        stored = record(context)["direct_writes"][
            context["write_id"]
        ]

        assert stored == reserved
        assert reserved["status"] == "RESERVED"

        result = execute_reserved_merchant_create(
            repository=repo,
            **context,
            payload=payload,
        )

        assert result["success"] is True
        assert result["replayed"] is False
        assert result["result"]["success"] is True

        merchant_id = result["result"]["merchant_id"]

        persisted_reservation = record(context)["direct_writes"][
            context["write_id"]
        ]

        persisted_attempt = uuid.UUID(
            persisted_reservation["execution_attempt_id"]
        )

        with repo.connection(read_only=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT execution_attempt_id,
                           claim_generation,
                           claim_status
                    FROM merchant_ops.merchant_execution_claims
                    WHERE operation_key = %s
                    """,
                    (operation_key,),
                )
                claim = cur.fetchone()

        assert claim is not None
        assert claim["execution_attempt_id"] == persisted_attempt
        assert claim["claim_generation"] == 1
        assert claim["claim_status"] == "COMPLETED"

        assert counts(
            repo, merchant_id, operation_key
        ) == (1, 1, 1)

        # Simulate interruption after PostgreSQL COMMIT:
        # reservation remains RESERVED on disk.
        assert record(context)["direct_writes"][
            context["write_id"]
        ]["status"] == "EXECUTING"

        recovered = reconcile_committed_merchant_create(
            repo,
            **{
                key: value
                for key, value in context.items()
                if key != "pane_session_id"
            },
        )

        assert recovered is not None
        assert recovered["status"] == "VERIFIED"
        assert recovered["merchant_id"] == merchant_id
        assert recovered["claim_generation"] == 1

        persisted = record(context)
        assert persisted["direct_writes"][
            context["write_id"]
        ]["status"] == "VERIFIED"

        assert persisted["direct_writes"][
            context["write_id"]
        ]["claim_generation"] == 1

        assert persisted["status"] == "RUNNING"
        assert persisted["result_received"] is False

        # Once verified, execution is not reissued.
        with pytest.raises(ReservedExecutionError):
            execute_reserved_merchant_create(
                repository=repo,
                **context,
                payload=payload,
            )

        assert counts(
            repo, merchant_id, operation_key
        ) == (1, 1, 1)

    finally:
        if operation_key is not None:
            cleanup(repo, merchant_id, operation_key)


def test_tampered_payload_never_creates_merchant(environment):
    repo, context = environment

    payload = {
        "code": "T" + uuid.uuid4().hex[:18].upper(),
        "name": "Original Merchant",
    }

    reserved = reserve_merchant_create(
        **context,
        payload=payload,
    )

    changed_payload = {
        **payload,
        "name": "Unauthorized Change",
    }

    with pytest.raises(ReservedExecutionError):
        execute_reserved_merchant_create(
            repository=repo,
            **context,
            payload=changed_payload,
        )

    with repo.connection(read_only=True) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM merchant_ops.merchant_execution_ledger
            WHERE operation_key = %s
            """,
            (reserved["operation_key"],),
        ).fetchone()

    assert row["n"] == 0

    assert record(context)["direct_writes"][
        context["write_id"]
    ]["status"] == "RESERVED"



def test_committed_write_releases_through_idle_hook(
    environment,
):
    """Real DB + real filesystem + real lifecycle release.

    Only staged SendMessage and tmux owner discovery are simulated.
    """
    from dataclasses import replace

    from claude.hooks import team_result_hook
    from claude.hooks.teammate_idle_orchestrator import (
        handle_teammate_idle,
    )

    repo, context = environment

    payload = {
        "code": "T" + uuid.uuid4().hex[:18].upper(),
        "name": "Idle Lifecycle E2E Merchant",
    }

    merchant_id = None
    operation_key = None

    owner = context["owner_session_id"]
    teammate = context["teammate_name"]
    pane = context["pane_session_id"]
    run_id = context["run_id"]
    task_id = context["task_id"]

    try:
        reserved = reserve_merchant_create(
            **context,
            payload=payload,
        )
        operation_key = reserved["operation_key"]

        executed = execute_reserved_merchant_create(
            repository=repo,
            payload=payload,
            **context,
        )

        assert executed["success"] is True
        merchant_id = executed["result"]["merchant_id"]

        assert record(context)["direct_writes"][
            context["write_id"]
        ]["status"] == "EXECUTING"

        executed_attempt = record(context)["direct_writes"][
            context["write_id"]
        ]["execution_attempt_id"]

        owner_record = record(context)

        pending = {
            "owner_session_id": owner,
            "teammate_name": teammate,
            "run_id": run_id,
            "task_id": task_id,
            "message": "Merchant operation completed",
        }

        # Keep the real reconciliation callback, report
        # gate and lifecycle release functions.
        deps = replace(
            team_result_hook._teammate_idle_dependencies(),

            # Pane session is not a lead team-state document.
            load_team_state=lambda session: (
                None if session == pane
                else team_lifecycle.load_team_state(session)
            ),

            find_unique_active_teammate_owner=(
                lambda name: (
                    (owner, owner_record, "FOUND")
                    if name == teammate
                    else (None, None, "NOT_FOUND")
                )
            ),

            load_pending_result=lambda session: (
                pending if session == pane else None
            ),

            # Simulate only external bookkeeping/cleanup.
            record_teammate_result=lambda *a, **k: None,
            clear_pending_result=lambda *a, **k: None,
            clear_pending_merchant_completeness=(
                lambda *a, **k: None
            ),
            clear_pending_merchant_proposal=(
                lambda *a, **k: None
            ),
            _clear_merchant_resolution_after_release=(
                lambda *a, **k: None
            ),
        )

        feedback = handle_teammate_idle(
            state=None,
            payload={
                "hook_event_name": "TeammateIdle",
                "session_id": pane,
                "agent_type": teammate,
                "teammate_name": teammate,
            },
            session_id=pane,
            dependencies=deps,
        )

        assert feedback == ""

        settled = record(context)

        assert settled["status"] == "IDLE_REUSABLE"
        assert settled["current_run_id"] is None
        assert settled["current_task_id"] is None
        assert settled["authorized_operations"] == []
        assert settled["last_completed_task_id"] == task_id

        # Completed writes are archived before IDLE_REUSABLE.
        assert "direct_writes" not in settled
        assert "direct_completion_receipt" not in settled

        history = settled["completed_direct_write_history"]
        assert len(history) == 1

        receipt = history[0]
        assert receipt["run_id"] == run_id
        assert receipt["task_id"] == task_id
        assert set(receipt["writes"]) == {context["write_id"]}

        verified = receipt["writes"][context["write_id"]]
        assert verified["merchant_id"] == merchant_id
        assert verified["claim_generation"] == 1
        assert (
            verified["execution_attempt_id"]
            == executed_attempt
        )

        # Lifecycle delivery must not create another write.
        assert counts(
            repo, merchant_id, operation_key
        ) == (1, 1, 1)

    finally:
        if operation_key is not None:
            cleanup(repo, merchant_id, operation_key)
