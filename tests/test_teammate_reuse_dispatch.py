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


def test_completed_merchant_proposal_report_can_reconcile_before_reuse(
    monkeypatch,
):
    """A fully evidenced Merchant proposal must not stay stuck forever.

    This reproduces the live Phase 8 ordering defect:

    - Merchant proposal task delivered its exact SendMessage result;
    - lifecycle reached REPORT_RECEIVED;
    - TeammateIdle finalization was missed;
    - a later confirmed Merchant run tries to reuse the same canonical
      merchant-manager.

    Generic REPORT_RECEIVED teammates must remain non-reusable. Only an exact,
    fully validated Merchant proposal completion may be reconciled.
    """

    import json
    import tempfile

    from runtime_state import (
        STATE_DIR_ENV_VAR,
        clear_state,
    )
    from team_lifecycle import (
        TEAM_STATE_DIR_ENV_VAR,
        TeammateLifecycleStatus,
        get_teammate_status,
        load_team_state,
    )
    from tmux_merchant_completeness import (
        RUNTIME_DIR_ENV_VAR,
    )
    from tmux_merchant_proposal import (
        PENDING_MERCHANT_PROPOSAL_DIR_ENV_VAR,
    )
    from tmux_result_receipt import (
        PENDING_RESULT_DIR_ENV_VAR,
    )

    with tempfile.TemporaryDirectory() as runtime_directory:
        with tempfile.TemporaryDirectory() as team_directory:
            with tempfile.TemporaryDirectory() as completeness_directory:
                with tempfile.TemporaryDirectory() as proposal_directory:
                    with tempfile.TemporaryDirectory() as result_directory:
                        preferences_directory = (
                            f"{result_directory}/merchant_preferences"
                        )

                        monkeypatch.setenv(
                            STATE_DIR_ENV_VAR,
                            runtime_directory,
                        )
                        monkeypatch.setenv(
                            TEAM_STATE_DIR_ENV_VAR,
                            team_directory,
                        )
                        monkeypatch.setenv(
                            RUNTIME_DIR_ENV_VAR,
                            completeness_directory,
                        )
                        monkeypatch.setenv(
                            PENDING_MERCHANT_PROPOSAL_DIR_ENV_VAR,
                            proposal_directory,
                        )
                        monkeypatch.setenv(
                            PENDING_RESULT_DIR_ENV_VAR,
                            result_directory,
                        )

                        from merchant_confirmation_preferences import (
                            PREFERENCES_DIR_ENV_VAR,
                            MODE_LOCAL_AUTO,
                            current_mode,
                            handle_toggle_command,
                        )

                        monkeypatch.setenv(
                            PREFERENCES_DIR_ENV_VAR,
                            preferences_directory,
                        )

                        session_id = "merchant-reconcile-session"
                        pane_session_id = "merchant-reconcile-pane"

                        toggle_result = handle_toggle_command(
                            "/merchant-confirmation off",
                            session_id,
                            env={
                                "MERCHANT_ALLOW_LOCAL_AUTO_CONFIRM": "1",
                                "MERCHANT_DB_HOST": "127.0.0.1",
                                "INTERACTIVE_MODE_ENABLED": "1",
                            },
                        )

                        assert toggle_result is not None

                        assert (
                            current_mode(
                                session_id
                            )
                            == MODE_LOCAL_AUTO
                        )

                        first_state = controlled_state("merchant-proposal-run")
                        first_state["selected_agents"] = [
                            "merchant-manager",
                        ]
                        first_state["operations"] = [
                            "merchant_propose",
                        ]

                        assert policy_gate.apply_call(
                            first_state,
                            "Agent",
                            {
                                "subagent_type": "merchant-manager",
                                "name": "merchant-manager",
                                "prompt": (
                                    "Objective: create a temporary Merchant "
                                    "record for lifecycle validation.\n"
                                    "Operation: merchant_propose\n"
                                    "Database target: runtime\n"
                                    "Authorized mode: PROPOSE\n"
                                    "Resolve authoritative Merchant state "
                                    "through registered reads.\n"
                                    "Resolve the normalized write command from "
                                    "the registered Merchant contract.\n"
                                    "Run deterministic completeness before "
                                    "proposing.\n"
                                    "Do not apply any mutation."
                                ),
                            },
                            session_id,
                        ) is None

                        record = (
                            load_team_state(session_id)[
                                "teammates"
                            ][
                                "merchant-manager"
                            ]
                        )

                        assert (
                            record["status"]
                            == TeammateLifecycleStatus.RUNNING.value
                        )

                        # Bind the exact tmux pane and stage the same evidence
                        # that a valid Merchant PROPOSAL_READY run produces.
                        from team_lifecycle import (
                            bind_reported_teammate_pane_session,
                            mark_report_received,
                        )
                        from tmux_merchant_completeness import (
                            stage_pending_merchant_completeness,
                        )
                        from tmux_merchant_proposal import (
                            stage_pending_merchant_proposal,
                        )
                        from tmux_result_receipt import (
                            stage_pending_result,
                        )

                        run_id = record["current_run_id"]
                        task_id = record["current_task_id"]

                        from claude.agents.tools.merchant.cli_contract import (
                            build_proposal,
                        )

                        proposal = {
                            **build_proposal(
                                "merchant create",
                                "runtime",
                                {
                                    "merchant_id": (
                                        "00000000-0000-0000-0000-000000000123"
                                    ),
                                    "code": "P8_RECONCILE_TEST",
                                    "name": "Phase 8 Reconciliation Test",
                                    "region_code": "VN",
                                    "created_by": None,
                                },
                            ).to_dict(),
                            "success": True,
                        }

                        stage_pending_merchant_completeness(
                            pane_session_id=pane_session_id,
                            owner_session_id=session_id,
                            teammate_name="merchant-manager",
                            run_id=run_id,
                            task_id=task_id,
                            tool_use_id="completeness-tool",
                            result={
                                "success": True,
                                "mode": "COMPLETENESS",
                                "command": "merchant create",
                                "complete": True,
                                "missing_fields": [],
                                "missing_one_of": [],
                                "clarification": None,
                            },
                        )

                        assert stage_pending_merchant_proposal(
                            pane_session_id=pane_session_id,
                            owner_session_id=session_id,
                            teammate_name="merchant-manager",
                            run_id=run_id,
                            task_id=task_id,
                            tool_use_id="proposal-tool",
                            proposal=proposal,
                        ), "Valid Merchant proposal failed to stage"

                        message = (
                            "TEAM_RESULT_JSON:\n"
                            + json.dumps(
                                {
                                    "contract_version": 1,
                                    "outcome": "PROPOSAL_READY",
                                    "operation": "merchant_propose",
                                    "database_target": "runtime",
                                    "proposal_emitted": True,
                                }
                            )
                            + "\nMERCHANT_PROPOSAL_RESULT_JSON:\n"
                            + json.dumps(proposal)
                        )

                        assert stage_pending_result(
                            session_id=pane_session_id,
                            owner_session_id=session_id,
                            teammate_name="merchant-manager",
                            run_id=run_id,
                            task_id=task_id,
                            message=message,
                            tool_use_id="result-tool",
                            operations=["merchant_propose"],
                            selected_agents=["merchant-manager"],
                        )

                        assert mark_report_received(
                            session_id,
                            "merchant-manager",
                            task_id,
                            "sendmessage",
                        )

                        assert bind_reported_teammate_pane_session(
                            session_id,
                            "merchant-manager",
                            pane_session_id,
                            run_id,
                            task_id,
                            required_operation="merchant_propose",
                        )[0]

                        assert (
                            get_teammate_status(
                                session_id,
                                "merchant-manager",
                            )
                            == TeammateLifecycleStatus.REPORT_RECEIVED.value
                        )

                        # Mirror the live ordering: Stop clears run state, but
                        # the expected TeammateIdle finalization never arrives.
                        clear_state(session_id)

                        second_state = controlled_state(
                            "merchant-proposal-run-2"
                        )
                        second_state["selected_agents"] = [
                            "merchant-manager",
                        ]
                        second_state["operations"] = [
                            "merchant_propose",
                        ]
                        second_state["confirmed"] = False

                        from tmux_result_receipt import (
                            load_pending_result,
                        )
                        from tmux_merchant_proposal import (
                            load_pending_merchant_proposal,
                        )

                        before_record = (
                            load_team_state(session_id)[
                                "teammates"
                            ][
                                "merchant-manager"
                            ]
                        )

                        pane_id = before_record[
                            "trusted_pane_session_id"
                        ]

                        assert (
                            get_teammate_status(
                                session_id,
                                "merchant-manager",
                            )
                            == TeammateLifecycleStatus.REPORT_RECEIVED.value
                        )

                        assert (
                            load_pending_result(
                                pane_id
                            )
                            is not None
                        )

                        assert (
                            load_pending_merchant_proposal(
                                pane_id
                            )
                            is not None
                        )

                        capture_calls = []

                        def unexpected_capture(
                            session_id,
                            proposal,
                        ):
                            capture_calls.append(
                                (
                                    session_id,
                                    proposal,
                                )
                            )
                            raise AssertionError(
                                "merchant create must not capture "
                                "a LOCAL_AUTO proposal receipt"
                            )

                        monkeypatch.setattr(
                            team_result_hook,
                            "capture_proposal_receipt",
                            unexpected_capture,
                        )

                        assert (
                            get_teammate_status(
                                session_id,
                                "merchant-manager",
                            )
                            == TeammateLifecycleStatus.REPORT_RECEIVED.value
                        )

                        assert (
                            load_pending_merchant_proposal(
                                pane_id
                            )
                            is not None
                        )

                        decision = policy_gate.apply_call(
                            second_state,
                            "SendMessage",
                            {
                                "recipient": "merchant-manager",
                                "message": (
                                    "Objective: prepare another temporary Merchant "
                                    "proposal for lifecycle validation.\n"
                                    "Operation: merchant_propose\n"
                                    "Database target: runtime\n"
                                    "Authorized mode: PROPOSE\n"
                                    "Resolve authoritative Merchant state through "
                                    "registered reads.\n"
                                    "Resolve the normalized write command from the "
                                    "registered Merchant contract.\n"
                                    "Run deterministic completeness before proposing.\n"
                                    "Do not apply any mutation."
                                ),
                            },
                            session_id,
                        )

                        # Desired post-fix behavior:
                        # reconcile the exact completed prior proposal first,
                        # then reserve the canonical teammate for the new run.
                        assert decision is None

                        assert capture_calls == []

                        assert (
                            load_pending_merchant_proposal(
                                pane_id
                            )
                            is None
                        )

                        final_record = (
                            load_team_state(session_id)[
                                "teammates"
                            ][
                                "merchant-manager"
                            ]
                        )

                        assert (
                            final_record["status"]
                            == TeammateLifecycleStatus.RUNNING.value
                        )
                        assert (
                            final_record["current_run_id"]
                            == "merchant-proposal-run-2"
                        )

                        assert (
                            final_record["last_completed_task_id"]
                            == task_id
                        )
