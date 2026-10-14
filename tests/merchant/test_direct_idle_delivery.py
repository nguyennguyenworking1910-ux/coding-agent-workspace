"""Test the actual Direct Merchant TeammateIdle delivery branch."""

from contextlib import contextmanager
from dataclasses import replace

import pytest

from claude.hooks import team_result_hook
from claude.hooks.teammate_idle_orchestrator import (
    handle_teammate_idle,
)


OWNER = "owner-test"
PANE = "pane-test"
TEAMMATE = "merchant-manager"
RUN = "run-test"
TASK = "task-test"


def make_record(*, selected_agents=None):
    return {
        "canonical_name": TEAMMATE,
        "status": "RUNNING",
        "current_run_id": RUN,
        "current_task_id": TASK,
        "authorized_operations": ["merchant_execute"],
        "authorized_selected_agents": (
            [TEAMMATE]
            if selected_agents is None
            else selected_agents
        ),
    }


def build_environment(
    *,
    verified,
    selected_agents=None,
):
    calls = []
    record = make_record(
        selected_agents=selected_agents
    )

    pending = {
        "owner_session_id": OWNER,
        "teammate_name": TEAMMATE,
        "run_id": RUN,
        "task_id": TASK,
        "message": "Merchant operation completed",
    }

    @contextmanager
    def fake_locked_state(_session_id):
        yield {}

    def reconcile(**kwargs):
        calls.append(("reconcile", kwargs))
        return verified

    def mark(*args):
        calls.append(("mark", args))
        assert verified is True
        return True

    def release(*args):
        calls.append(("release", args))
        return True, "REPORT_RECEIVED"

    def clear(*args):
        calls.append(("clear", args))

    def record_result(*args):
        calls.append(("record", args))

    deps = replace(
        team_result_hook._teammate_idle_dependencies(),
        load_team_state=lambda session: None,
        find_unique_active_teammate_owner=(
            lambda name: (OWNER, record, "FOUND")
        ),
        load_pending_result=lambda session: pending,
        reconcile_direct_writes=reconcile,
        mark_bound_report_received=mark,
        release_reported_teammate_to_idle=release,
        locked_state=fake_locked_state,
        record_teammate_result=record_result,
        clear_pending_result=clear,
        clear_pending_merchant_completeness=clear,
        clear_pending_merchant_proposal=clear,
        _clear_merchant_resolution_after_release=clear,
    )

    return deps, calls


def invoke(deps):
    return handle_teammate_idle(
        state=None,
        payload={
            "hook_event_name": "TeammateIdle",
            "session_id": PANE,
            "agent_type": TEAMMATE,
            "teammate_name": TEAMMATE,
        },
        session_id=PANE,
        dependencies=deps,
    )


def names(calls):
    return [entry[0] for entry in calls]


def test_verified_direct_write_releases():
    deps, calls = build_environment(verified=True)

    feedback = invoke(deps)

    assert feedback == ""
    assert names(calls).count("reconcile") == 1
    assert names(calls).count("mark") == 1
    assert names(calls).count("release") == 1

    assert (
        names(calls).index("reconcile")
        < names(calls).index("mark")
        < names(calls).index("release")
    )

    args = next(
        value for name, value in calls
        if name == "reconcile"
    )

    assert args == {
        "owner_session_id": OWNER,
        "teammate_name": TEAMMATE,
        "run_id": RUN,
        "task_id": TASK,
    }


def test_missing_evidence_blocks_report_and_release():
    deps, calls = build_environment(verified=False)

    feedback = invoke(deps)

    assert feedback == deps.PENDING_RESULT_FEEDBACK
    assert names(calls) == ["reconcile"]


def test_invalid_selected_agent_cannot_fallback():
    deps, calls = build_environment(
        verified=True,
        selected_agents=["wrong-agent"],
    )

    feedback = invoke(deps)

    assert feedback == deps.PENDING_RESULT_FEEDBACK
    assert "reconcile" not in names(calls)
    assert "mark" not in names(calls)
    assert "release" not in names(calls)


def test_reconciliation_exception_blocks_release():
    deps, calls = build_environment(verified=True)

    def fail(**kwargs):
        raise RuntimeError("PostgreSQL unavailable")

    deps = replace(
        deps,
        reconcile_direct_writes=fail,
    )

    feedback = invoke(deps)

    assert feedback == deps.PENDING_RESULT_FEEDBACK
    assert "mark" not in names(calls)
    assert "release" not in names(calls)


def test_mismatched_sendmessage_blocks_reconciliation():
    deps, calls = build_environment(verified=True)

    deps = replace(
        deps,
        load_pending_result=lambda session: {
            "owner_session_id": OWNER,
            "teammate_name": TEAMMATE,
            "run_id": RUN,
            "task_id": "different-task",
            "message": "Completed",
        },
    )

    feedback = invoke(deps)

    assert feedback == deps.MISSING_RESULT_FEEDBACK
    assert calls == []
