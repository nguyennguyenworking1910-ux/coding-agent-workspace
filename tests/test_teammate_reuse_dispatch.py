"""End-to-end contracts for create and reuse dispatch paths."""

from __future__ import annotations

import json
import sys
import tempfile
from io import StringIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import policy_gate
import team_result_hook
from runtime_state import (
    STATE_DIR_ENV_VAR,
    clear_state,
    new_state,
    save_state,
)
from team_lifecycle import (
    TEAM_STATE_DIR_ENV_VAR,
    TeammateLifecycleStatus,
    get_teammate_status,
)


def controlled_state(run_id: str) -> dict:
    return new_state(
        request="Review README.md without changing files",
        task_class="small_task",
        risk_level="read_only",
        selected_agents=["reviewer"],
        limits={
            "max_members": 1,
            "max_tool_rounds": 1,
            "max_total_tool_calls": 10,
        },
        confirmed=False,
        run_id=run_id,
    )


def run_result_hook(payload: dict) -> int:
    original_stdin = sys.stdin
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    try:
        sys.stdin = StringIO(json.dumps(payload))
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        return team_result_hook.main()
    finally:
        sys.stdin = original_stdin
        sys.stdout = original_stdout
        sys.stderr = original_stderr


def test_two_runs_reuse_one_reviewer_without_a_second_agent(monkeypatch):
    with tempfile.TemporaryDirectory() as runtime_directory:
        with tempfile.TemporaryDirectory() as team_directory:
            monkeypatch.setenv(STATE_DIR_ENV_VAR, runtime_directory)
            monkeypatch.setenv(TEAM_STATE_DIR_ENV_VAR, team_directory)
            session_id = "reuse-session"

            first_state = controlled_state("run-1")
            decision = policy_gate.apply_call(
                first_state,
                "Agent",
                {"subagent_type": "reviewer", "name": "reviewer"},
                session_id,
            )

            assert decision is None
            assert get_teammate_status(session_id, "reviewer") == (
                TeammateLifecycleStatus.RUNNING.value
            )

            save_state(session_id, first_state)
            assert run_result_hook(
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": session_id,
                    "agent_id": "agent-reviewer-1",
                    "agent_type": "reviewer",
                    "tool_name": "SendMessage",
                    "tool_input": {
                        "recipient": "team-lead",
                        "content": "Complete README review",
                    },
                }
            ) == 0

            # Claude Code fires Stop before TeammateIdle. Stop clears only
            # run state; the accepted result remains in session team state.
            assert clear_state(session_id)

            assert run_result_hook(
                {
                    "hook_event_name": "TeammateIdle",
                    "session_id": session_id,
                    "teammate_name": "reviewer",
                }
            ) == 0
            assert get_teammate_status(session_id, "reviewer") == (
                TeammateLifecycleStatus.IDLE_REUSABLE.value
            )

            second_state = controlled_state("run-2")
            reuse_decision = policy_gate.apply_call(
                second_state,
                "SendMessage",
                {
                    "recipient": "reviewer",
                    "content": "Review CLAUDE.md without changing files",
                },
                session_id,
            )

            assert reuse_decision is None
            assert second_state["members_used"] == ["reviewer"]
            assert get_teammate_status(session_id, "reviewer") == (
                TeammateLifecycleStatus.RUNNING.value
            )


def test_new_agent_is_bound_to_internal_task_before_result(monkeypatch):
    with tempfile.TemporaryDirectory() as team_directory:
        monkeypatch.setenv(TEAM_STATE_DIR_ENV_VAR, team_directory)
        state = controlled_state("run-1")

        assert policy_gate.apply_call(
            state,
            "Agent",
            {"subagent_type": "reviewer", "name": "reviewer"},
            "binding-session",
        ) is None

        from team_lifecycle import load_team_state

        record = load_team_state("binding-session")["teammates"]["reviewer"]
        assert record["current_run_id"] == "run-1"
        assert record["current_task_id"] == "run-1:reviewer"


def test_busy_teammate_cannot_receive_a_new_assignment(monkeypatch):
    with tempfile.TemporaryDirectory() as team_directory:
        monkeypatch.setenv(TEAM_STATE_DIR_ENV_VAR, team_directory)
        first_state = controlled_state("run-1")
        assert policy_gate.apply_call(
            first_state,
            "Agent",
            {"subagent_type": "reviewer", "name": "reviewer"},
            "busy-session",
        ) is None

        second_state = controlled_state("run-2")
        decision = policy_gate.apply_call(
            second_state,
            "SendMessage",
            {"recipient": "reviewer", "content": "New work"},
            "busy-session",
        )

        assert decision is not None
        reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
        assert "status=RUNNING" in reason


def test_unselected_or_peer_assignment_is_denied(monkeypatch):
    with tempfile.TemporaryDirectory() as team_directory:
        monkeypatch.setenv(TEAM_STATE_DIR_ENV_VAR, team_directory)
        state = controlled_state("run-1")

        unselected = policy_gate.apply_call(
            state,
            "SendMessage",
            {"recipient": "coder", "content": "Do work"},
            "selection-session",
        )
        peer = policy_gate.apply_call(
            state,
            "SendMessage",
            {"recipient": "reviewer", "content": "Do work"},
            "selection-session",
            sender_agent_type="coder",
        )

        assert unselected is not None
        assert peer is not None


def test_solve_routes_snapshot_to_agent_or_sendmessage():
    content = (PROJECT_ROOT / ".claude" / "commands" / "solve.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(content.split())

    assert "If `exists` is false, invoke `Agent`" in normalized
    assert "exactly `IDLE_REUSABLE`, do not call `Agent`" in normalized
    assert "canonical teammate with `SendMessage`" in normalized
    assert (
        "Do not invoke `Agent`, create another pane, or add a suffix"
        in normalized
    )
