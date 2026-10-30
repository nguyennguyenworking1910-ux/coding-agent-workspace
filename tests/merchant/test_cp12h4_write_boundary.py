"""CP12H.4A: every Direct EXECUTE mutation is preceded by durable evidence.

The write boundary itself (authority spend, capability consumption and the
reserved Create executor) refuses to run without a persisted reservation
bound to the exact owner, teammate, run, task, command, payload and
execution attempt. The no-write terminal gate rejects any task whose
authority was spent. All writes here use the in-memory handler or a fake
repository; no database is touched.
"""

from __future__ import annotations

import threading
import uuid
from types import SimpleNamespace

import pytest

from claude.hooks import merchant_direct_handoff, team_lifecycle
from claude.hooks import merchant_reserved_execution
from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_STATE_KEY,
    stage_runtime_handoff_attempt,
)
from claude.hooks.runtime_state import locked_state
from claude.system import merchant_runtime_handoff

from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD,
    PANE,
    PROJECT_ID,
    TEAMMATE,
    UPDATE_ARGV,
    dispatch,
    execute_request,
    fake_runtime_handler,
    idle,
    isolated,
    record,
    report,
    run_state,
    submit,
)


CREATE_ARGV = ["merchant", "create", "--code", "CP12H4X", "--name", "CP12H4"]


def _scoped_update():
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None


def _authority_spent():
    return run_state().get("merchant_runtime_authorization_issued") is True


def _stage(argv):
    current = record()

    with locked_state(LEAD) as state:
        attempt, reason = stage_runtime_handoff_attempt(
            state,
            owner_session_id=LEAD,
            teammate_name=TEAMMATE,
            run_id=current["current_run_id"],
            task_id=current["current_task_id"],
            candidate={
                "arguments": tuple(argv),
                "database_target": "runtime",
            },
        )

    assert attempt is not None, reason
    return attempt


def _bind_pane():
    """Bind the executing pane through the trusted hook path, no write."""

    assert execute_request(["project", "list"]) == 0


# -------------------------------------------------------------------
# F1 reproduction: the lower-level executors refuse without evidence
# -------------------------------------------------------------------


def test_direct_scope_apply_without_reservation_is_refused(
    fake_runtime_handler,
):
    calls, _ = fake_runtime_handler
    _scoped_update()

    with pytest.raises(TypeError):
        merchant_runtime_handoff.invoke_authorized_scope_apply(
            LEAD, UPDATE_ARGV
        )

    assert calls == []
    assert not _authority_spent()


def test_direct_scope_apply_with_forged_attempt_is_refused(
    fake_runtime_handler,
):
    calls, _ = fake_runtime_handler
    _scoped_update()
    _bind_pane()
    current = record()

    with pytest.raises(
        merchant_runtime_handoff.MerchantRuntimeHandoffError,
        match="reservation does not match",
    ):
        merchant_runtime_handoff.invoke_authorized_scope_apply(
            LEAD,
            UPDATE_ARGV,
            teammate_name=TEAMMATE,
            task_id=current["current_task_id"],
            execution_attempt_id=str(uuid.uuid4()),
        )

    assert calls == []
    assert not _authority_spent()


def test_reserve_authority_requires_staged_handoff(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()
    _bind_pane()
    current = record()

    with pytest.raises(
        merchant_runtime_handoff.MerchantRuntimeHandoffError,
        match="reservation does not match",
    ):
        merchant_runtime_handoff.reserve_direct_scope_authorization(
            LEAD,
            UPDATE_ARGV,
            teammate_name=TEAMMATE,
            task_id=current["current_task_id"],
            reservation={
                "kind": "scope",
                "execution_attempt_id": str(uuid.uuid4()),
            },
        )

    assert not _authority_spent()


def test_issuing_runtime_capability_requires_execution_guard():
    from claude.agents.tools.merchant.cli_contract import (
        issue_runtime_apply_authorization,
    )

    with pytest.raises(TypeError):
        issue_runtime_apply_authorization({}, {})


def test_reserved_create_executor_requires_spent_user_scope(monkeypatch):
    """Reserve + execute directly, skipping the scope, never reaches SQL."""

    submit("Create merchant CP12H4", argv=CREATE_ARGV)
    assert dispatch() is None
    _bind_pane()

    protected = []
    monkeypatch.setattr(
        merchant_reserved_execution,
        "execute_protected_merchant_create",
        lambda **kwargs: protected.append(kwargs),
    )

    from claude.hooks.merchant_direct_write_state import (
        reserve_merchant_create,
    )

    current = record()
    payload = {"code": "ROGUE", "name": "Not the user's scope"}
    identity = dict(
        owner_session_id=LEAD,
        teammate_name=TEAMMATE,
        pane_session_id=current["trusted_pane_session_id"],
        run_id=current["current_run_id"],
        task_id=current["current_task_id"],
        write_id="rogue-write",
        database="test",
        payload=payload,
    )

    try:
        reserve_merchant_create(**identity)
    except PermissionError:
        pass

    repository = SimpleNamespace(
        config=SimpleNamespace(database="coding_agent_merchant_test")
    )

    with pytest.raises(PermissionError):
        merchant_reserved_execution.execute_reserved_merchant_create(
            repository=repository, **identity
        )

    assert protected == []
    assert not _authority_spent()


# -------------------------------------------------------------------
# Spent authority can never become a no-write completion
# -------------------------------------------------------------------


def test_spent_authority_blocks_no_write_release(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()
    _bind_pane()

    # Any path that spent the one-use authority, with or without team
    # evidence, leaves the run-state marker behind.
    with locked_state(LEAD) as state:
        state["merchant_runtime_authorization_issued"] = True

    assert report("BLOCKED") == 0
    idle()

    current = record()
    assert current["status"] == "FAILED"
    assert "direct_no_write_terminal" not in current
    assert current["failure_reason"] == "DIRECT_AUTHORITY_SPENT_WITHOUT_RELEASE"

    # Bounded: repeated idle changes nothing.
    assert idle() == 0
    assert record()["status"] == "FAILED"
    assert calls == []


def test_persistence_failure_before_spend_never_writes(
    fake_runtime_handler,
    monkeypatch,
):
    calls, _ = fake_runtime_handler
    _scoped_update()
    _bind_pane()

    original = merchant_direct_handoff._begin_scope_execution

    def failing_begin(attempt):
        raise OSError("disk full")

    monkeypatch.setattr(
        merchant_direct_handoff, "_begin_scope_execution", failing_begin
    )

    execute_request(UPDATE_ARGV)

    monkeypatch.setattr(
        merchant_direct_handoff, "_begin_scope_execution", original
    )

    assert calls == []
    assert not _authority_spent()
    assert "direct_scope_execution" not in record()


def test_persistence_failure_after_commit_is_never_no_write(
    fake_runtime_handler,
    monkeypatch,
):
    calls, _ = fake_runtime_handler
    _scoped_update()

    monkeypatch.setattr(
        merchant_direct_handoff,
        "_finish_scope_execution",
        lambda attempt, status, **_: False,
    )

    execute_request(UPDATE_ARGV)
    assert len(calls) == 1

    execution = record()["direct_scope_execution"]
    assert execution["status"] == "EXECUTING"

    assert report("BLOCKED") == 0
    idle()

    current = record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"] == "DIRECT_EXECUTION_EXECUTING"
    assert "direct_no_write_terminal" not in current
    assert current["direct_scope_execution"]["status"] == "EXECUTING"


def test_concurrent_invocation_writes_once(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()
    _bind_pane()

    attempt = _stage(UPDATE_ARGV)
    barrier = threading.Barrier(2)
    outcomes = []

    def run():
        barrier.wait()
        try:
            outcomes.append(
                merchant_direct_handoff.invoke_direct_merchant_execute(
                    attempt
                )
            )
        except Exception as exc:  # noqa: BLE001
            outcomes.append(type(exc).__name__)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert outcomes.count(0) == 1


def test_stale_task_attempt_cannot_spend_or_write(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()
    _bind_pane()

    attempt = _stage(UPDATE_ARGV)

    with team_lifecycle.locked_team_state(LEAD) as state:
        state["teammates"][TEAMMATE]["current_task_id"] = "task-later"

    with pytest.raises(PermissionError):
        merchant_direct_handoff.invoke_direct_merchant_execute(attempt)

    assert calls == []
    assert not _authority_spent()


def test_finalized_reservation_blocks_consumption(
    fake_runtime_handler,
    monkeypatch,
):
    """The capability re-checks the reservation when it is consumed."""

    calls, _ = fake_runtime_handler
    _scoped_update()

    original = merchant_runtime_handoff._invoke_authorized_apply

    def finalize_then_invoke(*args, **kwargs):
        with team_lifecycle.locked_team_state(LEAD) as state:
            execution = state["teammates"][TEAMMATE][
                "direct_scope_execution"
            ]
            execution["status"] = "FAILED"
        return original(*args, **kwargs)

    monkeypatch.setattr(
        merchant_runtime_handoff,
        "_invoke_authorized_apply",
        finalize_then_invoke,
    )

    execute_request(UPDATE_ARGV)

    assert calls == []
    assert _authority_spent()


def test_committed_but_unreported_write_is_never_released(
    fake_runtime_handler,
):
    calls, _ = fake_runtime_handler
    _scoped_update()

    assert execute_request(UPDATE_ARGV) == 0
    assert len(calls) == 1

    # No report yet: the task stays RUNNING with its evidence.
    idle()
    current = record()
    assert current["status"] == "RUNNING"
    assert current["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert run_state()[HANDOFF_STATE_KEY]["status"] == "SUCCESS"

    # A later contradictory report is settled from the evidence.
    assert report("BLOCKED") == 0
    idle()
    current = record()
    assert current["status"] == "IDLE_REUSABLE"
    assert "direct_no_write_terminal" not in current
    assert current["completed_scope_execution_history"][0]["status"] == (
        "SUCCEEDED"
    )


# -------------------------------------------------------------------
# F5: never infer rollback from an unverifiable outcome
# -------------------------------------------------------------------


def test_success_exit_with_unparseable_output_is_uncertain(
    fake_runtime_handler,
    monkeypatch,
):
    calls, _ = fake_runtime_handler
    _scoped_update()

    monkeypatch.setattr(
        merchant_direct_handoff,
        "bounded_runtime_apply_result",
        lambda *_args, **_kwargs: None,
    )

    execute_request(UPDATE_ARGV)

    assert len(calls) == 1
    assert record()["direct_scope_execution"]["status"] == "UNCERTAIN"


def test_unclassified_command_error_is_uncertain(fake_runtime_handler):
    calls, behaviour = fake_runtime_handler
    _scoped_update()

    behaviour["raise"] = ConnectionError("connection lost during commit")
    execute_request(UPDATE_ARGV)

    assert record()["direct_scope_execution"]["status"] == "UNCERTAIN"

    assert report("EXECUTE_FAILED", command="project update") == 0
    idle()
    current = record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"] == "DIRECT_EXECUTION_UNCERTAIN"
    assert "direct_scope_execution" in current


def test_classified_pre_commit_error_is_failed(fake_runtime_handler):
    calls, behaviour = fake_runtime_handler
    _scoped_update()

    behaviour["raise"] = ValueError("expected_version mismatch")
    execute_request(UPDATE_ARGV)

    assert record()["direct_scope_execution"]["status"] == "FAILED"
