"""Tests for team_result_hook.py idempotent result delivery."""

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PROJECT_ROOT / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"

sys.path.insert(0, str(HOOKS_DIR))

import team_result_hook
from runtime_state import (
    new_state,
    locked_state,
    clear_state,
    STATE_DIR_ENV_VAR,
)


class TeamResultHookTests(unittest.TestCase):
    """Test team_result_hook idempotent result delivery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(STATE_DIR_ENV_VAR)
        os.environ[STATE_DIR_ENV_VAR] = self.temp_dir.name
        self.original_team_state_env = os.environ.get(
            "CLAUDE_TEAM_STATE_DIR"
        )
        self.team_state_temp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_TEAM_STATE_DIR"] = self.team_state_temp.name
        self.session_id = "test-session"
        self.run_id = "test-run-1"

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(STATE_DIR_ENV_VAR, None)
        else:
            os.environ[STATE_DIR_ENV_VAR] = self.original_env

        if self.original_team_state_env is None:
            os.environ.pop("CLAUDE_TEAM_STATE_DIR", None)
        else:
            os.environ["CLAUDE_TEAM_STATE_DIR"] = (
                self.original_team_state_env
            )

        clear_state(self.session_id)
        self.temp_dir.cleanup()
        self.team_state_temp.cleanup()

    def setup_run_state(self):
        """Create run state for testing."""
        with locked_state(self.session_id) as state:
            if state is None:
                state_obj = new_state(
                    request="test request",
                    task_class="small_task",
                    risk_level="read_only",
                    selected_agents=["reviewer"],
                    limits={"max_members": 1, "max_total_tool_calls": 10},
                    confirmed=False,
                    run_id=self.run_id,
                )
                from runtime_state import save_state
                save_state(self.session_id, state_obj)

    def run_hook(self, hook_input):
        """Run hook main with JSON input."""
        original_stdin = sys.stdin
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        try:
            sys.stdin = StringIO(json.dumps(hook_input))
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            exit_code = team_result_hook.main()
            self.last_stderr = sys.stderr.getvalue()
            return exit_code
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout
            sys.stderr = original_stderr

    def test_record_sendmessage_delivery(self):
        """PostToolUse records SendMessage result delivery."""
        self.setup_run_state()

        hook_input = {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "agent_id": "agent-reviewer-1",
            "agent_type": "reviewer",
            "tool_name": "SendMessage",
            "tool_input": {
                "to": "team-lead",
                "task_id": "task-1",
                "message": "Work completed",
            },
        }

        self.run_hook(hook_input)

        with locked_state(self.session_id) as state:
            self.assertIsNotNone(state)
            ledger = state.get("result_ledger", {})
            dedup_key = f"{self.run_id}:task-1:reviewer"
            self.assertIn(dedup_key, ledger)
            self.assertTrue(ledger[dedup_key]["result_received"])
            self.assertIn("sendmessage", ledger[dedup_key]["delivery_sources"])

    def test_idle_without_sendmessage_is_blocked(self):
        """TeammateIdle cannot invent an automatic result."""
        self.setup_run_state()

        hook_input = {
            "hook_event_name": "TeammateIdle",
            "session_id": self.session_id,
            "teammate_name": "reviewer",
            "task_id": "task-1",
        }

        exit_code = self.run_hook(hook_input)

        self.assertEqual(exit_code, 2)
        self.assertIn("SendMessage", self.last_stderr)
        self.assertIn("do not redo", self.last_stderr)

        with locked_state(self.session_id) as state:
            self.assertIsNotNone(state)
            ledger = state.get("result_ledger", {})
            dedup_key = f"{self.run_id}:task-1:reviewer"
            self.assertIn(dedup_key, ledger)
            self.assertFalse(ledger[dedup_key]["result_received"])
            self.assertTrue(ledger[dedup_key]["recovery_sent"])
            self.assertEqual(ledger[dedup_key]["delivery_sources"], [])

    def test_deduplication_same_delivery_twice(self):
        """Repeated SendMessage delivery is one logical result."""
        self.setup_run_state()

        hook_input1 = {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "agent_id": "agent-reviewer-1",
            "agent_type": "reviewer",
            "tool_name": "SendMessage",
            "tool_input": {
                "recipient": "team-lead",
                "task_id": "task-1",
                "content": "Complete report",
            },
        }

        self.run_hook(hook_input1)
        self.run_hook(hook_input1)

        with locked_state(self.session_id) as state:
            ledger = state.get("result_ledger", {})
            dedup_key = f"{self.run_id}:task-1:reviewer"
            self.assertIn(dedup_key, ledger)
            record = ledger[dedup_key]
            self.assertTrue(record["result_received"])
            self.assertEqual(record["delivery_sources"], ["sendmessage"])

    def test_empty_sendmessage_does_not_satisfy_delivery(self):
        """An empty body is not a complete teammate report."""
        self.setup_run_state()

        hook_input = {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "agent_id": "agent-reviewer-1",
            "agent_type": "reviewer",
            "tool_name": "SendMessage",
            "tool_input": {
                "recipient": "team-lead",
                "task_id": "task-1",
                "content": "   ",
            },
        }

        self.assertEqual(self.run_hook(hook_input), 0)

        with locked_state(self.session_id) as state:
            self.assertEqual(state.get("result_ledger", {}), {})

    def test_missing_report_recovers_without_repeating_work(self):
        """Idle blocks until the existing report arrives via SendMessage."""
        self.setup_run_state()

        idle_input = {
            "hook_event_name": "TeammateIdle",
            "session_id": self.session_id,
            "teammate_name": "reviewer",
            "task_id": "task-1",
        }

        self.assertEqual(self.run_hook(idle_input), 2)
        self.assertIn("do not redo", self.last_stderr)

        # A second idle attempt still cannot create a synthetic result.
        self.assertEqual(self.run_hook(idle_input), 2)
        self.assertIn("do not repeat", self.last_stderr)

        report_input = {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "agent_id": "agent-reviewer-1",
            "agent_type": "reviewer",
            "tool_name": "SendMessage",
            "tool_input": {
                "recipient": "team-lead",
                "task_id": "task-1",
                "content": "Existing complete report",
            },
        }

        self.assertEqual(self.run_hook(report_input), 0)
        self.assertEqual(self.run_hook(idle_input), 0)

        with locked_state(self.session_id) as state:
            record = state["result_ledger"][
                f"{self.run_id}:task-1:reviewer"
            ]
            self.assertTrue(record["result_received"])
            self.assertTrue(record["recovery_sent"])
            self.assertEqual(
                record["delivery_sources"],
                ["sendmessage"],
            )

    def test_ignores_wrong_sendmessage_recipient(self):
        """SendMessage to non-team-lead is ignored."""
        self.setup_run_state()

        hook_input = {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "tool_name": "SendMessage",
            "tool_input": {
                "to": "coder",
                "task_id": "task-1",
                "message": "Some message",
            },
        }

        self.run_hook(hook_input)

        with locked_state(self.session_id) as state:
            ledger = state.get("result_ledger", {})
            self.assertEqual(len(ledger), 0)

    def test_ignores_other_tools(self):
        """PostToolUse ignores non-SendMessage tools."""
        self.setup_run_state()

        hook_input = {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "tool_name": "Read",
            "tool_input": {
                "file_path": "/some/file",
            },
        }

        self.run_hook(hook_input)

        with locked_state(self.session_id) as state:
            ledger = state.get("result_ledger", {})
            self.assertEqual(len(ledger), 0)

    def test_rejects_self_declared_post_tool_sender(self):
        """An agent-controlled from_teammate field is not sender proof."""
        self.setup_run_state()

        hook_input = {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "tool_name": "SendMessage",
            "tool_input": {
                "to": "team-lead",
                "from_teammate": "reviewer",
                "task_id": "task-1",
                "message": "Forged report",
            },
        }

        self.run_hook(hook_input)

        with locked_state(self.session_id) as state:
            self.assertEqual(state.get("result_ledger", {}), {})

    def test_merchant_sender_requires_harness_identity(self):
        """Merchant proposal capture trusts agent_id plus agent_type only."""
        self.assertEqual(
            team_result_hook.merchant_report_sender(
                {
                    "agent_id": "agent-merchant-1",
                    "agent_type": "merchant-manager",
                    "tool_input": {"from_teammate": "reviewer"},
                }
            ),
            "merchant-manager",
        )
        self.assertEqual(
            team_result_hook.merchant_report_sender(
                {
                    "tool_input": {
                        "from_teammate": "merchant-manager",
                    }
                }
            ),
            "",
        )

    def test_recovery_sent_prevents_duplicates(self):
        """recovery_sent flag prevents multiple recovery requests."""
        with locked_state(self.session_id) as state:
            if state is None:
                state_obj = new_state(
                    request="test",
                    task_class="small_task",
                    risk_level="read_only",
                    selected_agents=["reviewer"],
                    limits={"max_members": 1, "max_total_tool_calls": 10},
                    confirmed=False,
                    run_id=self.run_id,
                )
                from runtime_state import save_state
                save_state(self.session_id, state_obj)

        with locked_state(self.session_id) as state:
            result1 = team_result_hook.mark_recovery_sent(state, "reviewer", "task-1")
            self.assertTrue(result1)

            result2 = team_result_hook.mark_recovery_sent(state, "reviewer", "task-1")
            self.assertFalse(result2)

    def test_result_received_blocks_recovery(self):
        """Once result_received is true, recovery request is blocked."""
        with locked_state(self.session_id) as state:
            if state is None:
                state_obj = new_state(
                    request="test",
                    task_class="small_task",
                    risk_level="read_only",
                    selected_agents=["reviewer"],
                    limits={"max_members": 1, "max_total_tool_calls": 10},
                    confirmed=False,
                    run_id=self.run_id,
                )
                from runtime_state import save_state
                save_state(self.session_id, state_obj)

        with locked_state(self.session_id) as state:
            team_result_hook.record_teammate_result(
                state,
                "reviewer",
                "task-1",
                "sendmessage",
            )

        with locked_state(self.session_id) as state:
            result = team_result_hook.mark_recovery_sent(state, "reviewer", "task-1")
            self.assertFalse(result)

    def test_multiple_tasks_separate_ledger_entries(self):
        """Different task IDs have separate ledger entries."""
        self.setup_run_state()

        with locked_state(self.session_id) as state:
            for i in range(3):
                team_result_hook.record_teammate_result(
                    state,
                    "reviewer",
                    f"task-{i}",
                    "sendmessage",
                )

        with locked_state(self.session_id) as state:
            ledger = state.get("result_ledger", {})
            self.assertEqual(len(ledger), 3)
            for i in range(3):
                dedup_key = f"{self.run_id}:task-{i}:reviewer"
                self.assertIn(dedup_key, ledger)

    def test_multiple_teammates_separate_ledger_entries(self):
        """Different teammate names have separate ledger entries."""
        self.setup_run_state()

        teammates = ["reviewer", "coder", "bug-fixer"]
        with locked_state(self.session_id) as state:
            for teammate in teammates:
                team_result_hook.record_teammate_result(
                    state,
                    teammate,
                    "task-1",
                    "sendmessage",
                )

        with locked_state(self.session_id) as state:
            ledger = state.get("result_ledger", {})
            self.assertEqual(len(ledger), 3)
            for teammate in teammates:
                dedup_key = f"{self.run_id}:task-1:{teammate}"
                self.assertIn(dedup_key, ledger)

    def test_hook_ignores_request_without_run_state(self):
        """Hook ignores request when no run state exists."""
        hook_input = {
            "hook_event_name": "PostToolUse",
            "session_id": "unknown-session",
            "tool_name": "SendMessage",
            "tool_input": {
                "to": "team-lead",
                "task_id": "task-1",
            },
        }

        self.run_hook(hook_input)

        from runtime_state import load_state
        state = load_state("unknown-session")
        self.assertIsNone(state)

    def test_hook_ignores_unknown_hook_event(self):
        """Hook ignores unknown hook event names."""
        self.setup_run_state()

        hook_input = {
            "hook_event_name": "UnknownEvent",
            "session_id": self.session_id,
            "tool_name": "Something",
        }

        self.run_hook(hook_input)

        with locked_state(self.session_id) as state:
            ledger = state.get("result_ledger", {})
            self.assertEqual(len(ledger), 0)

    def test_idle_after_stop_releases_sendmessage_report(self):
        """Real hook order releases from team state after run cleanup."""
        from team_lifecycle import (
            TeammateLifecycleStatus,
            allocate_teammate,
            get_teammate_status,
            mark_teammate_running,
        )

        self.setup_run_state()
        allocate_teammate(self.session_id, "reviewer", "reviewer")
        mark_teammate_running(
            self.session_id,
            "reviewer",
            self.run_id,
            "task-1",
        )

        report_input = {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "agent_id": "agent-reviewer-1",
            "agent_type": "reviewer",
            "tool_name": "SendMessage",
            "tool_input": {
                "recipient": "team-lead",
                "content": "Complete report",
            },
        }
        idle_input = {
            "hook_event_name": "TeammateIdle",
            "session_id": self.session_id,
            "teammate_name": "reviewer",
        }

        self.assertEqual(self.run_hook(report_input), 0)
        self.assertTrue(clear_state(self.session_id))
        self.assertEqual(self.run_hook(idle_input), 0)
        self.assertEqual(
            get_teammate_status(self.session_id, "reviewer"),
            TeammateLifecycleStatus.IDLE_REUSABLE.value,
        )

    def test_missing_report_after_stop_remains_blocked(self):
        """Run cleanup cannot turn an unreported teammate into reusable."""
        from team_lifecycle import (
            TeammateLifecycleStatus,
            allocate_teammate,
            get_teammate_status,
            mark_teammate_running,
        )

        self.setup_run_state()
        allocate_teammate(self.session_id, "reviewer", "reviewer")
        mark_teammate_running(
            self.session_id,
            "reviewer",
            self.run_id,
            "task-1",
        )
        self.assertTrue(clear_state(self.session_id))

        exit_code = self.run_hook(
            {
                "hook_event_name": "TeammateIdle",
                "session_id": self.session_id,
                "teammate_name": "reviewer",
            }
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("SendMessage", self.last_stderr)
        self.assertEqual(
            get_teammate_status(self.session_id, "reviewer"),
            TeammateLifecycleStatus.RUNNING.value,
        )


class RegressionTeammateReuseCycleTests(unittest.TestCase):
    """Regression tests for the exact observed sequence in Gate 4 defects.

    These tests reproduce the exact observed sequence:
    1. SendMessage complete report (PostToolUse)
    2. Automatic finished notification (TeammateIdle)
    3. Next run selects reviewer again

    Expected outcome:
    - One logical report (deduplicated)
    - Teammate transitions to IDLE_REUSABLE
    - Next run reuses the same teammate
    - No recovery messages after result received
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(STATE_DIR_ENV_VAR)
        os.environ[STATE_DIR_ENV_VAR] = self.temp_dir.name

        self.original_team_state_env = os.environ.get("CLAUDE_TEAM_STATE_DIR")
        self.team_state_temp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_TEAM_STATE_DIR"] = self.team_state_temp.name

        self.session_id = "regression-test-session"
        self.run_id_1 = "run-1"
        self.run_id_2 = "run-2"

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(STATE_DIR_ENV_VAR, None)
        else:
            os.environ[STATE_DIR_ENV_VAR] = self.original_env

        if self.original_team_state_env is None:
            os.environ.pop("CLAUDE_TEAM_STATE_DIR", None)
        else:
            os.environ["CLAUDE_TEAM_STATE_DIR"] = self.original_team_state_env

        clear_state(self.session_id)
        self.temp_dir.cleanup()
        self.team_state_temp.cleanup()

    def setup_run_state(self, run_id: str):
        """Create run state for a given run."""
        with locked_state(self.session_id) as state:
            if state is None:
                state_obj = new_state(
                    request="test request",
                    task_class="small_task",
                    risk_level="read_only",
                    selected_agents=["reviewer"],
                    limits={"max_members": 1, "max_total_tool_calls": 10},
                    confirmed=False,
                    run_id=run_id,
                )
                from runtime_state import save_state
                save_state(self.session_id, state_obj)

    def run_hook(self, hook_input):
        """Run hook main with JSON input."""
        original_stdin = sys.stdin
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        try:
            sys.stdin = StringIO(json.dumps(hook_input))
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            exit_code = team_result_hook.main()
            self.last_stderr = sys.stderr.getvalue()
            return exit_code
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout
            sys.stderr = original_stderr

    def test_idle_without_report_keeps_same_teammate_running(self):
        """Official idle shape is blocked until SendMessage is recorded."""
        from team_lifecycle import (
            TeammateLifecycleStatus,
            allocate_teammate,
            get_teammate_status,
            mark_teammate_running,
        )

        self.setup_run_state(self.run_id_1)
        decision, name = allocate_teammate(
            self.session_id,
            "reviewer",
            "reviewer",
        )
        self.assertEqual(decision.value, "CREATE")
        self.assertEqual(name, "reviewer")
        self.assertTrue(
            mark_teammate_running(
                self.session_id,
                "reviewer",
                self.run_id_1,
                "task-1",
            )
        )

        exit_code = self.run_hook(
            {
                "hook_event_name": "TeammateIdle",
                "session_id": self.session_id,
                "teammate_name": "reviewer",
            }
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(
            get_teammate_status(self.session_id, "reviewer"),
            TeammateLifecycleStatus.RUNNING.value,
        )

        with locked_state(self.session_id) as state:
            record = state["result_ledger"][
                f"{self.run_id_1}:task-1:reviewer"
            ]
            self.assertFalse(record["result_received"])
            self.assertTrue(record["recovery_sent"])

    def test_complete_lifecycle_sendmessage_then_idle(self):
        """Test complete lifecycle: SendMessage report, then TeammateIdle.

        Sequence:
        1. First run setup
        2. Reviewer completes and sends report (SendMessage)
        3. Automatic finish notification (TeammateIdle)
        4. Verify: one logical report, no recovery needed, IDLE_REUSABLE

        Expected:
        - One ledger entry with the canonical sendmessage source
        - Team state is IDLE_REUSABLE
        - No recovery message needed
        """
        from team_lifecycle import (
            allocate_teammate,
            get_teammate_status,
            mark_teammate_running,
            TeammateLifecycleStatus,
            TEAM_STATE_DIR_ENV_VAR,
        )

        self.setup_run_state(self.run_id_1)

        # Simulate: reviewer created and dispatched
        decision1, name1 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(name1, "reviewer")

        # Mark as running
        mark_teammate_running(self.session_id, "reviewer", self.run_id_1, "task-1")
        status = get_teammate_status(self.session_id, "reviewer")
        self.assertEqual(status, TeammateLifecycleStatus.RUNNING.value)

        # 1. SendMessage: report delivered
        hook_input_sendmessage = {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "agent_id": "agent-reviewer-1",
            "agent_type": "reviewer",
            "tool_name": "SendMessage",
            "tool_input": {
                "recipient": "team-lead",
                "content": "Completed work",
            },
        }

        self.run_hook(hook_input_sendmessage)

        # Verify result recorded in run ledger
        with locked_state(self.session_id) as state:
            ledger = state.get("result_ledger", {})
            dedup_key = f"{self.run_id_1}:task-1:reviewer"
            self.assertIn(dedup_key, ledger)
            record = ledger[dedup_key]
            self.assertTrue(record["result_received"])
            self.assertIn("sendmessage", record["delivery_sources"])

        # Verify team state is REPORT_RECEIVED
        status = get_teammate_status(self.session_id, "reviewer")
        self.assertEqual(status, TeammateLifecycleStatus.REPORT_RECEIVED.value)

        # 2. TeammateIdle: automatic finish (happens after report already received)
        hook_input_idle = {
            "hook_event_name": "TeammateIdle",
            "session_id": self.session_id,
            "teammate_name": "reviewer",
        }

        self.run_hook(hook_input_idle)

        # Verify result ledger still has one entry and no invented source
        with locked_state(self.session_id) as state:
            ledger = state.get("result_ledger", {})
            dedup_key = f"{self.run_id_1}:task-1:reviewer"
            self.assertIn(dedup_key, ledger)
            record = ledger[dedup_key]
            self.assertTrue(record["result_received"])
            # Should have sendmessage source (added by PostToolUse)
            self.assertIn("sendmessage", record["delivery_sources"])

        # Verify team state is now IDLE_REUSABLE
        status = get_teammate_status(self.session_id, "reviewer")
        self.assertEqual(status, TeammateLifecycleStatus.IDLE_REUSABLE.value)

        # 3. Next run: reviewer should be reusable
        self.setup_run_state(self.run_id_2)

        decision2, name2 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(decision2.value, "REUSE")
        self.assertEqual(name2, "reviewer")

        # Status should transition to DISPATCHED for reuse
        status = get_teammate_status(self.session_id, "reviewer")
        self.assertEqual(status, TeammateLifecycleStatus.DISPATCHED.value)


if __name__ == "__main__":
    unittest.main()
