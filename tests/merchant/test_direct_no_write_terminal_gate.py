"""CP12H.2C.7: trusted no-write terminal gate for Merchant Direct EXECUTE.

A merchant_execute task may end as REQUIRES_CLARIFICATION, BLOCKED or
FAILED without a write. That outcome is accepted only when trusted team
state proves no write attempt exists for the exact run/task, and the
proof is re-verified at both the report and release boundaries.
"""

from __future__ import annotations

import json
import sys
from io import StringIO

import pytest

from claude.hooks import team_lifecycle as lifecycle
from claude.hooks import team_result_hook
from claude.hooks.merchant_direct_completion import (
    direct_task_is_write_free,
    establish_no_write_terminal,
)
from claude.hooks.merchant_direct_write_state import (
    DirectWriteReservationError,
    reserve_merchant_create,
)
from claude.hooks.runtime_state import STATE_DIR_ENV_VAR
from claude.hooks.tmux_result_receipt import load_pending_result
from tests.merchant.direct_reservation_support import trust_teammate_pane


@pytest.fixture(autouse=True)
def _trusted_teammate_pane(monkeypatch):
    # Subject here is completion, not pane identity (see test_cp12h5b_*).
    trust_teammate_pane(monkeypatch)



TEAMMATE = "merchant-manager"
OWNER = "owner-no-write"
PANE = "pane-no-write"
RUN = "run-no-write"
TASK = "task-no-write"

ATTEMPT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MERCHANT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _running_record(**overrides):
    record = {
        "canonical_name": TEAMMATE,
        "status": "RUNNING",
        "current_run_id": RUN,
        "current_task_id": TASK,
        "trusted_pane_session_id": PANE,
        "authorized_operations": ["merchant_execute"],
        "authorized_selected_agents": [TEAMMATE],
        "result_received": False,
        "report_source": None,
        "terminal_recovery_sent": False,
    }
    record.update(overrides)
    return record


def _write(status, **overrides):
    write = {
        "write_id": "write-1",
        "run_id": RUN,
        "task_id": TASK,
        "command": "merchant create",
        "database": "test",
        "operation_key": "merchant-direct:v1:" + "a" * 64,
        "payload_hash": "b" * 64,
        "status": status,
    }
    if status in {"EXECUTING", "VERIFIED"}:
        write["execution_attempt_id"] = ATTEMPT_ID
        write["claim_generation"] = 1
    if status == "VERIFIED":
        write["merchant_id"] = MERCHANT_ID
    write.update(overrides)
    return write


def _historical_receipt(run_id, task_id):
    return {
        "version": 1,
        "run_id": run_id,
        "task_id": task_id,
        "writes": {
            "old-write": {
                "write_id": "old-write",
                "run_id": run_id,
                "task_id": task_id,
                "database": "test",
                "command": "merchant create",
                "operation_key": "merchant-direct:v1:" + "c" * 64,
                "payload_hash": "d" * 64,
                "execution_attempt_id": ATTEMPT_ID,
                "claim_generation": 1,
                "merchant_id": MERCHANT_ID,
            }
        },
    }


@pytest.fixture
def team(tmp_path, monkeypatch):
    monkeypatch.setattr(
        lifecycle, "team_state_dir", lambda: tmp_path
    )

    with lifecycle.locked_team_state(OWNER) as state:
        state.setdefault("teammates", {})[TEAMMATE] = (
            _running_record()
        )

    return OWNER


def update(callback):
    with lifecycle.locked_team_state(OWNER) as state:
        callback(state["teammates"][TEAMMATE])


def record():
    return lifecycle.load_team_state(OWNER)["teammates"][TEAMMATE]


def establish(outcome="REQUIRES_CLARIFICATION", **binding):
    arguments = {
        "owner_session_id": OWNER,
        "teammate_name": TEAMMATE,
        "run_id": RUN,
        "task_id": TASK,
        "outcome": outcome,
    }
    arguments.update(binding)
    return establish_no_write_terminal(**arguments)


def report(run_id=RUN, task_id=TASK):
    return lifecycle.mark_bound_report_received(
        OWNER, TEAMMATE, run_id, task_id, "sendmessage"
    )


def release():
    return lifecycle.release_reported_teammate_to_idle(
        OWNER, TEAMMATE
    )


# ---------------------------------------------------------------
# Clean no-write terminal outcome.
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    ["REQUIRES_CLARIFICATION", "BLOCKED", "FAILED"],
)
def test_clean_task_establishes_bound_marker_and_releases(
    team, outcome
):
    assert direct_task_is_write_free(
        owner_session_id=OWNER,
        teammate_name=TEAMMATE,
        run_id=RUN,
        task_id=TASK,
    ) is True

    assert establish(outcome) is True

    assert record()["direct_no_write_terminal"] == {
        "version": 1,
        "run_id": RUN,
        "task_id": TASK,
        "outcome": outcome,
    }

    assert report() is True
    assert record()["status"] == "REPORT_RECEIVED"

    released, _ = release()
    assert released is True

    current = record()
    assert current["status"] == "IDLE_REUSABLE"
    assert current["last_completed_task_id"] == TASK
    assert "direct_no_write_terminal" not in current
    assert "direct_writes" not in current


def test_establish_is_idempotent_for_same_outcome(team):
    assert establish() is True
    assert establish() is True
    assert establish("BLOCKED") is False


def test_report_without_no_write_marker_is_rejected(team):
    # Absent direct_writes alone is never no-write authority.
    assert report() is False
    assert record()["status"] == "RUNNING"

    update(lambda r: r.update(direct_writes={}))
    assert report() is False


def test_forged_report_received_cannot_release_without_marker(team):
    update(
        lambda r: r.update(
            status="REPORT_RECEIVED",
            result_received=True,
            report_source="sendmessage",
        )
    )

    released, reason = release()

    assert released is False
    assert reason == "INVALID_DIRECT_COMPLETION_RECEIPT"
    assert record()["status"] == "REPORT_RECEIVED"


# ---------------------------------------------------------------
# Outcome semantics: only non-success outcomes may be no-write.
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        "EXECUTE_SUCCESS",
        "EXECUTE_FAILED",
        "PROPOSAL_READY",
        "APPLY_SUCCESS",
        "",
        None,
    ],
)
def test_execution_or_legacy_outcome_cannot_be_no_write(
    team, outcome
):
    assert establish(outcome) is False
    assert "direct_no_write_terminal" not in record()
    assert report() is False


# ---------------------------------------------------------------
# Any write footprint blocks the no-write gate.
# ---------------------------------------------------------------


FOOTPRINTS = {
    "reserved": {"direct_writes": {"write-1": _write("RESERVED")}},
    "executing": {"direct_writes": {"write-1": _write("EXECUTING")}},
    "committed": {"direct_writes": {"write-1": _write("VERIFIED")}},
    "writes-none": {"direct_writes": None},
    "writes-list": {"direct_writes": []},
    "writes-garbage": {"direct_writes": {"write-1": "garbage"}},
    "receipt-without-writes": {
        "direct_completion_receipt": {"version": 1}
    },
    "same-task-history": {
        "completed_direct_write_history": [
            _historical_receipt(RUN, TASK)
        ]
    },
    "malformed-history": {
        "completed_direct_write_history": [{"run_id": RUN}]
    },
    "history-not-list": {"completed_direct_write_history": {}},
}


@pytest.mark.parametrize("footprint", sorted(FOOTPRINTS))
def test_write_footprint_blocks_no_write_terminal(team, footprint):
    update(lambda r: r.update(FOOTPRINTS[footprint]))

    assert direct_task_is_write_free(
        owner_session_id=OWNER,
        teammate_name=TEAMMATE,
        run_id=RUN,
        task_id=TASK,
    ) is False

    assert establish() is False
    assert "direct_no_write_terminal" not in record()
    assert report() is False
    assert record()["status"] == "RUNNING"


@pytest.mark.parametrize("footprint", sorted(FOOTPRINTS))
def test_injected_marker_cannot_mask_write_footprint(team, footprint):
    """A marker that coexists with any footprint never authorizes."""

    def prepare(r):
        r.update(FOOTPRINTS[footprint])
        r["direct_no_write_terminal"] = {
            "version": 1,
            "run_id": RUN,
            "task_id": TASK,
            "outcome": "BLOCKED",
        }

    update(prepare)

    assert report() is False

    update(
        lambda r: r.update(
            status="REPORT_RECEIVED",
            result_received=True,
            report_source="sendmessage",
        )
    )

    released, _ = release()
    assert released is False
    assert record()["status"] == "REPORT_RECEIVED"


def test_previous_task_history_does_not_block_new_clean_task(team):
    update(
        lambda r: r.update(
            completed_direct_write_history=[
                _historical_receipt("old-run", "old-task")
            ]
        )
    )

    assert establish() is True
    assert report() is True

    released, _ = release()
    assert released is True

    # Prior-write history is preserved for audit.
    assert record()["completed_direct_write_history"] == [
        _historical_receipt("old-run", "old-task")
    ]


# ---------------------------------------------------------------
# Exact lifecycle binding.
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "REPORT_RECEIVED"},
        {"status": "IDLE_REUSABLE"},
        {"status": "FAILED"},
        {"canonical_name": "other"},
        {"current_run_id": "other-run"},
        {"current_task_id": "other-task"},
        {"authorized_operations": ["merchant_propose"]},
        {"authorized_operations": ["merchant_apply"]},
        {"authorized_operations": ["merchant_read"]},
        {"authorized_operations": ["merchant_execute", "merchant_read"]},
        {"authorized_selected_agents": ["other-agent"]},
        {"authorized_selected_agents": []},
        {"result_received": True},
    ],
)
def test_binding_mismatch_cannot_establish_no_write(team, overrides):
    update(lambda r: r.update(overrides))

    assert establish() is False
    assert "direct_no_write_terminal" not in record()


@pytest.mark.parametrize(
    "binding",
    [
        {"run_id": "other-run"},
        {"task_id": "other-task"},
        {"teammate_name": "reviewer"},
        {"owner_session_id": "other-owner"},
    ],
)
def test_wrong_caller_binding_cannot_establish(team, binding):
    assert establish(**binding) is False
    assert "direct_no_write_terminal" not in record()


def test_marker_for_other_task_cannot_report_or_release(team):
    update(
        lambda r: r.update(
            direct_no_write_terminal={
                "version": 1,
                "run_id": RUN,
                "task_id": "earlier-task",
                "outcome": "BLOCKED",
            }
        )
    )

    assert report() is False

    update(
        lambda r: r.update(
            status="REPORT_RECEIVED",
            result_received=True,
            report_source="sendmessage",
        )
    )

    released, _ = release()
    assert released is False


@pytest.mark.parametrize(
    "marker",
    [
        {"version": 2, "run_id": RUN, "task_id": TASK, "outcome": "BLOCKED"},
        {"run_id": RUN, "task_id": TASK, "outcome": "BLOCKED"},
        {
            "version": 1,
            "run_id": RUN,
            "task_id": TASK,
            "outcome": "EXECUTE_SUCCESS",
        },
        {
            "version": 1,
            "run_id": RUN,
            "task_id": TASK,
            "outcome": "BLOCKED",
            "proposal_emitted": False,
        },
        "BLOCKED",
        True,
    ],
)
def test_malformed_marker_cannot_report(team, marker):
    update(lambda r: r.update(direct_no_write_terminal=marker))
    assert report() is False


# ---------------------------------------------------------------
# Reservation and no-write terminal are mutually exclusive.
# ---------------------------------------------------------------


RESERVATION = {
    "owner_session_id": OWNER,
    "teammate_name": TEAMMATE,
    "pane_session_id": PANE,
    "run_id": RUN,
    "task_id": TASK,
    "write_id": "write-1",
    "database": "test",
    "payload": {"code": "NOWRITE", "name": "No Write Merchant"},
}


def test_reserved_write_blocks_no_write_terminal(team):
    reserve_merchant_create(**RESERVATION)

    assert establish() is False
    assert report() is False
    assert record()["direct_writes"]["write-1"]["status"] == "RESERVED"


def test_no_write_terminal_blocks_later_reservation(team):
    assert establish() is True

    with pytest.raises(DirectWriteReservationError):
        reserve_merchant_create(**RESERVATION)

    assert "direct_writes" not in record()


def test_write_injected_after_marker_blocks_report(team):
    assert establish() is True

    update(
        lambda r: r.update(
            direct_writes={"write-1": _write("EXECUTING")}
        )
    )

    assert report() is False
    assert record()["status"] == "RUNNING"


def test_write_injected_after_report_blocks_release(team):
    assert establish() is True
    assert report() is True

    update(
        lambda r: r.update(
            direct_writes={"write-1": _write("VERIFIED")}
        )
    )

    released, _ = release()

    assert released is False
    assert record()["status"] == "REPORT_RECEIVED"


# ---------------------------------------------------------------
# Teammate reuse: earlier evidence never authorizes a new task.
# ---------------------------------------------------------------


def test_released_marker_cannot_authorize_next_task(team):
    assert establish() is True
    assert report() is True
    assert release()[0] is True

    assert lifecycle.mark_teammate_running(
        OWNER,
        TEAMMATE,
        "run-next",
        "task-next",
        operations=["merchant_execute"],
        selected_agents=[TEAMMATE],
    )

    assert report("run-next", "task-next") is False
    assert record()["status"] == "RUNNING"


def test_stale_marker_is_dropped_on_reassignment(team):
    update(
        lambda r: r.update(
            status="IDLE_REUSABLE",
            current_run_id=None,
            current_task_id=None,
            authorized_operations=[],
            authorized_selected_agents=[],
            direct_no_write_terminal={
                "version": 1,
                "run_id": RUN,
                "task_id": TASK,
                "outcome": "BLOCKED",
            },
        )
    )

    assert lifecycle.mark_teammate_running(
        OWNER,
        TEAMMATE,
        RUN,
        TASK,
        operations=["merchant_execute"],
        selected_agents=[TEAMMATE],
    )

    assert "direct_no_write_terminal" not in record()
    assert report() is False


def test_failed_teammate_drops_marker(team):
    assert establish() is True

    assert lifecycle.mark_teammate_failed(
        OWNER, TEAMMATE, reason="test"
    )

    assert "direct_no_write_terminal" not in record()


# ---------------------------------------------------------------
# Bounded terminal recovery for direct no-write tasks.
# ---------------------------------------------------------------


def test_direct_terminal_recovery_is_bounded(team):
    assert lifecycle.claim_terminal_recovery(
        OWNER, TEAMMATE, RUN, TASK
    ) == (True, "RECOVERY_CLAIMED")

    assert record()["status"] == "RUNNING"
    assert record()["result_received"] is False

    assert lifecycle.claim_terminal_recovery(
        OWNER, TEAMMATE, RUN, TASK
    ) == (False, "ALREADY_SENT")


@pytest.mark.parametrize("footprint", sorted(FOOTPRINTS))
def test_direct_terminal_recovery_refuses_write_footprint(
    team, footprint
):
    update(lambda r: r.update(FOOTPRINTS[footprint]))

    claimed, reason = lifecycle.claim_terminal_recovery(
        OWNER, TEAMMATE, RUN, TASK
    )

    assert claimed is False
    assert reason == "DIRECT_WRITE_PRESENT"
    assert record()["terminal_recovery_sent"] is False


def test_direct_terminal_recovery_requires_exact_task(team):
    claimed, reason = lifecycle.claim_terminal_recovery(
        OWNER, TEAMMATE, RUN, "other-task"
    )

    assert claimed is False
    assert reason == "BINDING_MISMATCH"


# ---------------------------------------------------------------
# Hook-level routing: trusted state, never message content,
# chooses between the write path and the no-write path.
# ---------------------------------------------------------------


@pytest.fixture
def hook_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "run_state"))
    monkeypatch.setenv("CLAUDE_TEAM_STATE_DIR", str(tmp_path / "team"))
    monkeypatch.setenv(
        "CLAUDE_PENDING_TEAM_RESULT_DIR", str(tmp_path / "pending")
    )
    monkeypatch.setenv(
        "CLAUDE_PENDING_MERCHANT_PROPOSAL_DIR",
        str(tmp_path / "proposals"),
    )
    monkeypatch.setenv("CLAUDE_RUNTIME_DIR", str(tmp_path / "runtime"))

    reconcile_calls = []

    def reconcile(**kwargs):
        reconcile_calls.append(kwargs)
        return False

    monkeypatch.setattr(
        team_result_hook,
        "_reconcile_direct_merchant_writes",
        reconcile,
    )

    decision, name = lifecycle.allocate_teammate(
        "lead-hook", TEAMMATE, TEAMMATE
    )
    assert name == TEAMMATE

    assert lifecycle.mark_teammate_running(
        "lead-hook",
        TEAMMATE,
        "run-hook",
        "task-hook",
        operations=["merchant_execute"],
        selected_agents=[TEAMMATE],
    )

    return reconcile_calls


def _run_hook(payload):
    original = sys.stdin
    try:
        sys.stdin = StringIO(json.dumps(payload))
        return team_result_hook.main()
    finally:
        sys.stdin = original


def _send(result):
    assert _run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "pane-hook",
            "agent_type": TEAMMATE,
            "tool_name": "SendMessage",
            "tool_use_id": "send",
            "tool_input": {
                "recipient": "team-lead",
                "message": "TEAM_RESULT_JSON:\n" + json.dumps(result),
            },
        }
    ) == 0


def _idle():
    return _run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": "pane-hook",
            "agent_type": TEAMMATE,
            "teammate_name": TEAMMATE,
        }
    )


def _hook_record():
    return lifecycle.load_team_state("lead-hook")["teammates"][TEAMMATE]


BLOCKED_RESULT = {
    "contract_version": 1,
    "outcome": "BLOCKED",
    "operation": "merchant_execute",
    "database_target": "runtime",
    "proposal_emitted": False,
}


def test_hook_blocked_with_reserved_write_uses_write_path(hook_runtime):
    with lifecycle.locked_team_state("lead-hook") as state:
        state["teammates"][TEAMMATE]["direct_writes"] = {
            "write-1": _write(
                "RESERVED", run_id="run-hook", task_id="task-hook"
            )
        }

    _send(BLOCKED_RESULT)

    # CP12H.4A: a reservation that was never claimed for execution ends
    # the task FAILED (bounded) with the reservation kept; the no-write
    # outcome never bypasses it and the teammate cannot be reused.
    assert _idle() == 0

    current = _hook_record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"] == "DIRECT_WRITE_NEVER_EXECUTED"
    assert "direct_no_write_terminal" not in current
    assert current["direct_writes"]["write-1"]["status"] == "RESERVED"
    assert lifecycle.has_unresolved_direct_writes(current)

    assert _idle() == 0
    assert _hook_record()["status"] == "FAILED"


def test_hook_blocked_with_executing_write_uses_write_path(hook_runtime):
    with lifecycle.locked_team_state("lead-hook") as state:
        state["teammates"][TEAMMATE]["direct_writes"] = {
            "write-1": {
                **_write("RESERVED", run_id="run-hook", task_id="task-hook"),
                "status": "EXECUTING",
                "execution_attempt_id": "00000000-0000-4000-8000-000000000001",
            }
        }

    _send(BLOCKED_RESULT)

    assert _idle() == 2

    # A claimed write is routed to committed-evidence reconciliation;
    # the no-write outcome did not bypass it.
    assert len(hook_runtime) == 1

    current = _hook_record()
    assert current["status"] == "RUNNING"
    assert "direct_no_write_terminal" not in current
    assert load_pending_result("pane-hook") is not None


def test_hook_blocked_without_write_releases(hook_runtime):
    _send(BLOCKED_RESULT)

    assert _idle() == 0
    assert hook_runtime == []

    current = _hook_record()
    assert current["status"] == "IDLE_REUSABLE"
    assert current["last_completed_task_id"] == "task-hook"
    assert "direct_no_write_terminal" not in current
    assert load_pending_result("pane-hook") is None


@pytest.mark.parametrize(
    "result",
    [
        # Execution claims without any trusted reservation.
        {**BLOCKED_RESULT, "outcome": "EXECUTE_SUCCESS",
         "command": "merchant create"},
        {**BLOCKED_RESULT, "outcome": "EXECUTE_FAILED",
         "command": "merchant create"},
        # Legacy operation names are not accepted for direct tasks.
        {**BLOCKED_RESULT, "operation": "merchant_propose"},
        {**BLOCKED_RESULT, "operation": "merchant_apply"},
        {**BLOCKED_RESULT, "database_target": "test"},
        # proposal_emitted=False is not execution evidence.
        {"contract_version": 1, "proposal_emitted": False},
    ],
)
def test_hook_unsupported_no_write_result_is_bounded(
    hook_runtime, result
):
    _send(result)

    # One correction turn.
    assert _idle() == 2
    current = _hook_record()
    assert current["status"] == "RUNNING"
    assert current["terminal_recovery_sent"] is True

    # Second identical idle terminates without another turn.
    assert _idle() == 0
    current = _hook_record()
    assert current["status"] == "FAILED"
    assert current["current_run_id"] is None
    assert current["current_task_id"] is None
    assert "direct_no_write_terminal" not in current
    assert hook_runtime == []
