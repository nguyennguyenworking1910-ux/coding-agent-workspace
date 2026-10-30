"""CP12H.4C: a pane is bound only from harness-written identity.

Self-declared ``agent_type`` and ``session_id`` never bind a pane. The hook
process must run in the tmux pane the harness recorded for merchant-manager
(``TMUX_PANE`` == ``members[].tmuxPaneId``). In-memory handler only.
"""

from __future__ import annotations

import os
import shutil
import threading

from claude.hooks import harness_team_identity, team_lifecycle

from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD,
    PANE,
    PANE_SERVER,
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
    submit,
    write_harness_team,
)


def _scoped_update():
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None


def _authority_spent():
    return run_state().get("merchant_runtime_authorization_issued") is True


def _bind(pane=PANE, tmux=None):
    """Bind as the given pane's own hook subprocess would."""

    original = os.environ.get("TMUX_PANE")
    os.environ["TMUX_PANE"] = PANE_TMUX if tmux is None else tmux

    try:
        return team_lifecycle.bind_running_teammate_pane_session(
            LEAD,
            TEAMMATE,
            pane,
            record()["current_run_id"],
            record()["current_task_id"],
            required_operation="merchant_execute",
        )
    finally:
        if original is None:
            os.environ.pop("TMUX_PANE", None)
        else:
            os.environ["TMUX_PANE"] = original


def test_rogue_pane_arriving_first_cannot_bind_or_write(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()

    # Same self-declared agent_type, its own session and tmux pane.
    assert execute_request(UPDATE_ARGV, pane="rogue-pane") == 0

    assert calls == []
    assert not record().get("trusted_pane_session_id")
    assert not _authority_spent()

    # The real teammate pane still binds and executes exactly once.
    assert execute_request(UPDATE_ARGV) == 0
    assert len(calls) == 1
    assert record()["trusted_pane_session_id"] == PANE
    assert record()["trusted_tmux_pane_id"] == f"{PANE_SERVER}:{PANE_TMUX}"


def test_self_declared_identity_without_pane_is_rejected(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()

    # The real session id and agent_type, but not from the harness pane.
    assert execute_request(UPDATE_ARGV, tmux="") == 0
    assert execute_request(UPDATE_ARGV, tmux="%8") == 0

    assert calls == []
    assert not record().get("trusted_pane_session_id")
    assert not _authority_spent()


def test_correct_pane_first_then_rogue_cannot_write_or_loop(
    fake_runtime_handler,
):
    calls, _ = fake_runtime_handler
    _scoped_update()

    assert execute_request(UPDATE_ARGV) == 0
    assert len(calls) == 1

    assert execute_request(UPDATE_ARGV, pane="rogue-pane") == 0
    assert report(
        "EXECUTE_SUCCESS", pane="rogue-pane", command="project update"
    ) == 0

    # A foreign pane is ignored: no feedback, no state change, no loop.
    assert [idle("rogue-pane") for _ in range(3)] == [0, 0, 0]
    assert record()["status"] == "RUNNING"
    assert len(calls) == 1

    # The bound pane settles normally.
    assert report("EXECUTE_SUCCESS", command="project update") == 0
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"


def test_replayed_payload_from_another_pane_is_rejected(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()

    _bind()

    # Byte-identical request replayed from another pane.
    assert execute_request(UPDATE_ARGV, pane="replay-pane", tmux="%11") == 0

    assert calls == []
    assert record()["trusted_pane_session_id"] == PANE
    assert not _authority_spent()


def test_concurrent_binding_race_binds_only_the_verified_pane(
    fake_runtime_handler,
    monkeypatch,
):
    _scoped_update()

    local = threading.local()
    monkeypatch.setattr(
        harness_team_identity,
        "current_tmux_pane",
        lambda: getattr(local, "tmux", ""),
    )

    barrier = threading.Barrier(3)
    results = {}

    def bind(name, pane, tmux):
        local.tmux = tmux
        barrier.wait()
        results[name] = _bind(pane)

    threads = [
        threading.Thread(target=bind, args=("real", PANE, PANE_TMUX)),
        threading.Thread(target=bind, args=("real-again", PANE, PANE_TMUX)),
        threading.Thread(target=bind, args=("rogue", "rogue-pane", "%99")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted([results["real"][1], results["real-again"][1]]) == [
        "ALREADY_BOUND",
        "BOUND",
    ]
    assert results["rogue"] == (False, "PANE_IDENTITY_UNVERIFIED")
    assert record()["trusted_pane_session_id"] == PANE
    assert record()["status"] == "RUNNING"


def test_binding_conflict_is_terminal_and_bounded(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()

    _bind()

    # The verified harness pane presents a different session for the
    # already-bound task: fail closed, once, without a loop.
    assert idle("restarted-session", tmux=PANE_TMUX) == 0

    current = record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"] == "PANE_BINDING_CONFLICT"

    assert [idle("restarted-session", tmux=PANE_TMUX) for _ in range(3)] == [
        0,
        0,
        0,
    ]
    assert [idle() for _ in range(2)] == [0, 0]
    assert record()["status"] == "FAILED"

    # Nothing can execute for the failed task.
    assert execute_request(UPDATE_ARGV) == 0
    assert execute_request(UPDATE_ARGV, pane="restarted-session",
                           tmux=PANE_TMUX) == 0
    assert calls == []
    assert not _authority_spent()


def test_conflicting_execute_request_fails_closed(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()

    _bind()

    assert execute_request(
        UPDATE_ARGV, pane="restarted-session", tmux=PANE_TMUX
    ) == 0

    assert calls == []
    assert record()["status"] == "FAILED"
    assert record()["failure_reason"] == "PANE_BINDING_CONFLICT"


def test_stale_pane_from_previous_task_cannot_execute(
    fake_runtime_handler,
    tmp_path,
):
    calls, _ = fake_runtime_handler
    _scoped_update()

    _bind()

    # The teammate was respawned in tmux pane %8 for a new task.
    write_harness_team(tmp_path / "harness_teams", "%8")
    with team_lifecycle.locked_team_state(LEAD) as state:
        state["teammates"][TEAMMATE]["current_task_id"] = "task-next"

    # The previous task's pane and session can no longer execute.
    assert execute_request(UPDATE_ARGV) == 0
    assert calls == []
    assert record()["trusted_pane_task_id"] != "task-next"

    # The verified new pane binds for the new task and executes once.
    assert execute_request(UPDATE_ARGV, pane="pane-next", tmux="%8") == 0
    assert len(calls) == 1
    assert record()["trusted_pane_session_id"] == "pane-next"
    assert record()["trusted_pane_task_id"] == "task-next"


def test_unavailable_harness_identity_fails_closed(
    fake_runtime_handler,
    tmp_path,
):
    calls, _ = fake_runtime_handler
    _scoped_update()

    shutil.rmtree(tmp_path / "harness_teams")

    assert execute_request(UPDATE_ARGV) == 0
    assert calls == []
    assert not record().get("trusted_pane_session_id")
    assert not _authority_spent()
