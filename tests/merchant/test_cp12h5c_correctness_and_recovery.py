"""CP12H.5C: Direct EXECUTE result consistency (F7, F8) and recovery.

F7: a teammate report whose database target differs from the trusted
authorization is rejected.
F8: a committed write is never presented as BLOCKED, FAILED,
REQUIRES_CLARIFICATION, EXECUTE_FAILED or EXECUTE_UNCERTAIN, and nothing
is presented as EXECUTE_SUCCESS without committed evidence.

The outcome comes from trusted execution evidence. The PreToolUse gate stops
a contradictory report before it reaches the lead; TeammateIdle re-checks
against the settled evidence. Scoped writes run through the in-memory
evidence model of ``fake_runtime_handler``; no database is touched.
"""

from __future__ import annotations

import json
import os
import sys
from io import StringIO

import pytest

from claude.hooks import policy_gate, team_lifecycle
from claude.hooks.merchant_terminal_consistency import (
    COMMITTED,
    NO_WRITE,
    NOT_COMMITTED,
    PENDING_VERIFICATION,
    UNCERTAIN,
    TERMINAL_REPORT_MARKER,
    direct_evidence_state,
    terminal_report_violation,
    trusted_scope_binding,
)
from claude.hooks.tmux_result_receipt import load_pending_result
from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD,
    PANE,
    PANE_TMUX,
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
    send,
    submit,
)


ATTEMPT = "00000000-0000-4000-8000-000000000001"
SHA = "a" * 64


def _result(outcome, *, target="runtime", **fields):
    return {
        "contract_version": 1,
        "outcome": outcome,
        "operation": "merchant_execute",
        "database_target": target,
        "proposal_emitted": False,
        **fields,
    }


def _scope_record(status, *, task_id="task-1"):
    return {
        "current_run_id": "run-1",
        "current_task_id": "task-1",
        "authorized_operations": ["merchant_execute"],
        "direct_scope_execution": {
            "version": 1,
            "run_id": "run-1",
            "task_id": task_id,
            "command": "project update",
            "scope_hash": SHA,
            "confirmation_hash": SHA,
            "execution_attempt_id": ATTEMPT,
            "status": status,
        },
    }


# -------------------------------------------------------------------
# Trusted evidence classification
# -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("SUCCEEDED", COMMITTED),
        ("FAILED", NOT_COMMITTED),
        ("UNCERTAIN", UNCERTAIN),
        ("EXECUTING", PENDING_VERIFICATION),
    ],
)
def test_scope_execution_evidence(status, expected):
    assert direct_evidence_state(
        _scope_record(status), authority_spent=True
    ) == expected


def test_stale_task_evidence_is_never_committed():
    stale = _scope_record("SUCCEEDED", task_id="task-0")

    assert direct_evidence_state(stale, authority_spent=True) == UNCERTAIN
    assert terminal_report_violation(
        _result("EXECUTE_SUCCESS", command="project update"),
        evidence=UNCERTAIN,
        binding=("runtime", "project update"),
    )


@pytest.mark.parametrize(
    ("writes", "expected"),
    [
        ({"w": {"status": "VERIFIED"}}, COMMITTED),
        ({"w": {"status": "RESERVED"}}, NOT_COMMITTED),
        (
            {"w": {"status": "EXECUTING", "execution_attempt_id": ATTEMPT}},
            PENDING_VERIFICATION,
        ),
    ],
)
def test_create_write_evidence(writes, expected):
    for write in writes.values():
        write.update(run_id="run-1", task_id="task-1")

    current = {
        "current_run_id": "run-1",
        "current_task_id": "task-1",
        "direct_writes": writes,
    }

    assert direct_evidence_state(current, authority_spent=True) == expected


def test_spent_authority_without_evidence_is_uncertain():
    clean = {"current_run_id": "run-1", "current_task_id": "task-1"}

    assert direct_evidence_state(clean, authority_spent=False) == NO_WRITE
    assert direct_evidence_state(clean, authority_spent=True) == UNCERTAIN


# -------------------------------------------------------------------
# F7 / F8 decision table
# -------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        "BLOCKED",
        "FAILED",
        "REQUIRES_CLARIFICATION",
        "EXECUTE_FAILED",
        "EXECUTE_UNCERTAIN",
    ],
)
def test_committed_write_accepts_only_execute_success(outcome):
    violation = terminal_report_violation(
        _result(outcome, command="project update"),
        evidence=COMMITTED,
        binding=("runtime", "project update"),
    )

    assert violation and "COMMITTED" in violation
    assert terminal_report_violation(
        _result("EXECUTE_SUCCESS", command="project update"),
        evidence=COMMITTED,
        binding=("runtime", "project update"),
    ) is None


@pytest.mark.parametrize(
    ("evidence", "outcome"),
    [
        (NO_WRITE, "EXECUTE_SUCCESS"),  # replayed success, no write
        (NOT_COMMITTED, "EXECUTE_SUCCESS"),
        (UNCERTAIN, "EXECUTE_SUCCESS"),
        (UNCERTAIN, "EXECUTE_FAILED"),  # never inferred as rolled back
        (UNCERTAIN, "BLOCKED"),
        (PENDING_VERIFICATION, "EXECUTE_SUCCESS"),
    ],
)
def test_outcome_without_matching_evidence_is_rejected(evidence, outcome):
    assert terminal_report_violation(
        _result(outcome, command="project update"),
        evidence=evidence,
        binding=("runtime", "project update"),
    )


@pytest.mark.parametrize(
    ("trusted", "reported"),
    [("test", "runtime"), ("runtime", "test")],
)
@pytest.mark.parametrize("evidence", [NO_WRITE, COMMITTED])
def test_f7_wrong_database_target_is_rejected(trusted, reported, evidence):
    outcome = "BLOCKED" if evidence == NO_WRITE else "EXECUTE_SUCCESS"
    violation = terminal_report_violation(
        _result(outcome, target=reported, command="merchant create"),
        evidence=evidence,
        binding=(trusted, "merchant create"),
    )

    assert violation and "database_target" in violation


def test_wrong_command_and_missing_authorization_are_rejected():
    assert "command" in terminal_report_violation(
        _result("EXECUTE_SUCCESS", command="project create"),
        evidence=COMMITTED,
        binding=("runtime", "project update"),
    )
    assert terminal_report_violation(
        _result("EXECUTE_SUCCESS", command="project update"),
        evidence=COMMITTED,
        binding=None,
    )
    assert terminal_report_violation(
        None, evidence=COMMITTED, binding=("runtime", "project update")
    )


def test_binding_comes_from_the_run_or_from_write_evidence():
    scope = {"run_id": "r", "database_target": "test",
             "command": "merchant create"}

    assert trusted_scope_binding(
        {"run_id": "r", "merchant_scope": scope}, "r", None
    ) == ("test", "merchant create")
    # Another run's scope never binds this run.
    assert trusted_scope_binding(
        {"run_id": "r", "merchant_scope": {**scope, "run_id": "x"}}, "r", None
    ) is None
    # Without its run state, a Create write records its database...
    assert trusted_scope_binding(
        None, "r", {"direct_writes": {"w": {"database": "test"}}}
    ) == ("test", "merchant create")
    # ...but a scoped write is unverifiable.
    assert trusted_scope_binding(
        None, "r", {"direct_scope_execution": {}}
    ) is None


# -------------------------------------------------------------------
# PreToolUse: a contradictory report never reaches the lead
# -------------------------------------------------------------------


def pre_report(outcome, *, pane=PANE, **fields):
    """Run the real PreToolUse policy gate on the teammate's report."""

    message = "TEAM_RESULT_JSON:\n" + json.dumps(
        _result(outcome, **fields)
    )
    original = sys.stdin
    original_stdout = sys.stdout
    original_pane = os.environ.get("TMUX_PANE")
    captured = StringIO()

    try:
        sys.stdin = StringIO(
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": pane,
                    "agent_type": TEAMMATE,
                    "tool_name": "SendMessage",
                    "tool_input": {
                        "recipient": "team-lead",
                        "message": message,
                    },
                }
            )
        )
        sys.stdout = captured
        os.environ["TMUX_PANE"] = PANE_TMUX
        assert policy_gate.main() == 0
    finally:
        sys.stdin = original
        sys.stdout = original_stdout
        if original_pane is None:
            os.environ.pop("TMUX_PANE", None)
        else:
            os.environ["TMUX_PANE"] = original_pane

    output = captured.getvalue().strip()
    decision = json.loads(output) if output else {}

    return (
        decision.get("hookSpecificOutput", {}).get("permissionDecision"),
        decision.get("hookSpecificOutput", {}).get(
            "permissionDecisionReason", ""
        ),
    )


def _committed_scoped_update():
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None
    assert execute_request(UPDATE_ARGV) == 0
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"


@pytest.mark.parametrize(
    "outcome",
    [
        "BLOCKED",
        "FAILED",
        "REQUIRES_CLARIFICATION",
        "EXECUTE_FAILED",
        "EXECUTE_UNCERTAIN",
    ],
)
def test_f8_committed_write_report_is_denied_before_delivery(
    fake_runtime_handler, outcome
):
    calls, _ = fake_runtime_handler
    _committed_scoped_update()

    clarification = (
        {"missing_fields": ["status"], "question": "Which status?"}
        if outcome == "REQUIRES_CLARIFICATION"
        else {}
    )
    decision, reason = pre_report(
        outcome, command="project update", **clarification
    )

    assert decision == "deny"
    assert "COMMITTED" in reason and "EXECUTE_SUCCESS" in reason
    assert TERMINAL_REPORT_MARKER not in record()
    assert len(calls) == 1

    assert pre_report("EXECUTE_SUCCESS", command="project update") == (
        None, ""
    )
    assert record()[TERMINAL_REPORT_MARKER]["outcome"] == "EXECUTE_SUCCESS"


def test_f7_wrong_target_report_is_denied_before_delivery(
    fake_runtime_handler,
):
    _committed_scoped_update()

    decision, reason = pre_report(
        "EXECUTE_SUCCESS", target="test", command="project update"
    )

    assert decision == "deny"
    assert "database_target" in reason


def test_uncertain_write_must_be_reported_uncertain(fake_runtime_handler):
    calls, behaviour = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    behaviour["commit_then_raise"] = ConnectionError("ack lost")
    behaviour["no_evidence"] = True
    behaviour["fence_blocked"] = True
    assert execute_request(UPDATE_ARGV) == 0
    assert record()["direct_scope_execution"]["status"] == "UNCERTAIN"

    for outcome in ("EXECUTE_FAILED", "EXECUTE_SUCCESS", "BLOCKED"):
        assert pre_report(outcome, command="project update")[0] == "deny"

    assert pre_report("EXECUTE_UNCERTAIN", command="project update") == (
        None, ""
    )


def test_lost_acknowledgement_after_commit_is_settled_committed(
    fake_runtime_handler,
):
    calls, behaviour = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    # The transaction committed with its evidence; only the reply was lost.
    behaviour["commit_then_raise"] = ConnectionError("ack lost")
    assert execute_request(UPDATE_ARGV) == 0

    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert pre_report("EXECUTE_FAILED", command="project update")[0] == (
        "deny"
    )


def test_accepted_no_write_report_forbids_any_later_execution(
    fake_runtime_handler,
):
    calls, _ = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    # The no-write report is accepted first (no evidence yet)...
    assert pre_report("BLOCKED") == (None, "")

    # ...so the execute request is refused before any reservation or spend.
    assert execute_request(UPDATE_ARGV) == 0
    assert calls == []
    assert "direct_scope_execution" not in record()
    assert run_state().get("merchant_runtime_authorization_issued") is not True


def test_replayed_success_report_into_a_new_no_write_task_is_rejected(
    fake_runtime_handler,
):
    _committed_scoped_update()
    assert report("EXECUTE_SUCCESS", command="project update") == 0
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"

    # A new unscoped run and task with no write: replaying the earlier
    # success report is rejected before delivery and again at idle.
    submit("Show merchant project status")
    assert team_lifecycle.mark_teammate_running(
        LEAD, TEAMMATE, run_state()["run_id"], "task-replay",
        operations=["merchant_execute"], selected_agents=[TEAMMATE],
    )

    decision, reason = pre_report("EXECUTE_SUCCESS", command="project update")
    assert decision == "deny"
    assert "NO_WRITE" in reason

    assert report("EXECUTE_SUCCESS", command="project update") == 0
    assert idle() == 2
    assert record()["status"] == "RUNNING"
    assert "direct_no_write_terminal" not in record()


# -------------------------------------------------------------------
# TeammateIdle re-check when a contradictory report was delivered anyway
# -------------------------------------------------------------------


def test_contradictory_report_gets_one_correction_then_fails_disclosed(
    fake_runtime_handler,
):
    _committed_scoped_update()

    assert report("BLOCKED") == 0
    assert idle() == 2
    assert record()["status"] == "RUNNING"

    assert report("FAILED") == 0
    assert idle() == 0

    current = record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"].startswith(
        "TERMINAL_REPORT_CONTRADICTS_EVIDENCE"
    )
    assert "COMMITTED" in current["failure_reason"]
    # The committed evidence is kept, never presented as a rollback.
    assert current["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert "direct_no_write_terminal" not in current


def test_wrong_target_delivered_report_is_never_released(
    fake_runtime_handler,
):
    _committed_scoped_update()

    assert report(
        "EXECUTE_SUCCESS", command="project update", database_target="test"
    ) == 0
    assert idle() == 2
    assert record()["status"] == "RUNNING"

    assert report("EXECUTE_SUCCESS", command="project update") == 0
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"


# -------------------------------------------------------------------
# Phase 2: an attempt interrupted before its outcome was persisted
# -------------------------------------------------------------------


def _interrupt_after_execution():
    """The process died after the attempt, before its outcome was saved."""

    with team_lifecycle.locked_team_state(LEAD) as state:
        state["teammates"][TEAMMATE]["direct_scope_execution"][
            "status"
        ] = "EXECUTING"


def test_crash_after_commit_recovers_committed(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _committed_scoped_update()
    _interrupt_after_execution()

    assert report("EXECUTE_UNCERTAIN", command="project update") == 0
    # Settled from committed evidence: the uncertain report must be
    # corrected to EXECUTE_SUCCESS.
    assert idle() == 2
    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"

    assert report("EXECUTE_SUCCESS", command="project update") == 0
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"
    assert len(calls) == 1


def test_crash_before_commit_is_fenced_and_failed(fake_runtime_handler):
    calls, behaviour = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    behaviour["raise"] = ValueError("rolled back")
    behaviour["fence_blocked"] = True
    assert execute_request(UPDATE_ARGV) == 0
    _interrupt_after_execution()

    behaviour["fence_blocked"] = False
    assert report("EXECUTE_UNCERTAIN", command="project update") == 0
    assert idle() == 0

    current = record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"] == "DIRECT_EXECUTION_FAILED"
    assert current["direct_scope_execution"]["status"] == "FAILED"
    assert calls == []


def test_crash_with_unplaceable_fence_stays_uncertain(fake_runtime_handler):
    calls, behaviour = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    behaviour["raise"] = ValueError("rolled back")
    behaviour["fence_blocked"] = True
    assert execute_request(UPDATE_ARGV) == 0
    _interrupt_after_execution()

    assert report("EXECUTE_UNCERTAIN", command="project update") == 0
    assert idle() == 0

    current = record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"] == "DIRECT_EXECUTION_UNCERTAIN"
    assert current["direct_scope_execution"]["status"] == "UNCERTAIN"


def test_execution_messages_name_the_evidenced_outcome(
    fake_runtime_handler, capsys
):
    calls, behaviour = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    behaviour["raise"] = RuntimeError("unknown")
    behaviour["fence_blocked"] = True
    capsys.readouterr()
    assert execute_request(UPDATE_ARGV) == 0

    context = capsys.readouterr().out
    assert "Report EXECUTE_UNCERTAIN" in context
    assert "may have committed" in context
    assert load_pending_result(PANE) is None


def test_runtime_attempt_is_never_fenced_while_runtime_is_disabled(
    fake_runtime_handler, monkeypatch
):
    """A fence is a write: a stale runtime attempt stays UNCERTAIN."""

    from claude.hooks import merchant_direct_handoff

    _committed_scoped_update()
    _interrupt_after_execution()

    monkeypatch.setattr(
        merchant_direct_handoff, "RUNTIME_DIRECT_EXECUTE_ENABLED", False
    )

    def no_database(*args, **kwargs):
        raise AssertionError("runtime evidence must not be contacted")

    monkeypatch.setattr(
        "claude.clients.merchant.attempt_evidence.resolve_attempt",
        no_database,
    )

    assert report("EXECUTE_UNCERTAIN", command="project update") == 0
    assert idle() == 0

    current = record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"] == "DIRECT_EXECUTION_UNCERTAIN"
    assert current["direct_scope_execution"]["status"] == "UNCERTAIN"
