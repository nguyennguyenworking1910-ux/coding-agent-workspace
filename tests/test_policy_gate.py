"""Tests for policy_gate.py hook with real team lifecycle integration."""

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

import policy_gate
import team_lifecycle
from team_lifecycle import (
    allocate_teammate,
    mark_teammate_idle_reusable,
    mark_teammate_running,
    TeammateAllocationDecision,
    TEAM_STATE_DIR_ENV_VAR,
)


class PolicyGateAgentDispatchTests(unittest.TestCase):
    """Test policy_gate Agent dispatch with team lifecycle."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(TEAM_STATE_DIR_ENV_VAR)
        os.environ[TEAM_STATE_DIR_ENV_VAR] = self.temp_dir.name
        self.session_id = "test-session"

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(TEAM_STATE_DIR_ENV_VAR, None)
        else:
            os.environ[TEAM_STATE_DIR_ENV_VAR] = self.original_env
        self.temp_dir.cleanup()

    def test_apply_call_allows_create_decision(self):
        """Agent dispatch for new role is allowed (CREATE decision)."""
        state = {
            "run_id": "run-1",
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
            "members_used": [],
        }
        tool_input = {"subagent_type": "reviewer", "name": "reviewer"}

        result = policy_gate.apply_call(state, "Agent", tool_input, self.session_id)

        self.assertIsNone(result)
        self.assertEqual(state["members_used"], ["reviewer"])

        record = team_lifecycle.load_team_state(
            self.session_id
        )["teammates"]["reviewer"]
        self.assertEqual(record["status"], "RUNNING")
        self.assertEqual(record["current_run_id"], "run-1")
        self.assertEqual(record["current_task_id"], "run-1:reviewer")

    def test_create_without_run_id_fails_closed(self):
        """A teammate cannot be created without an exact run binding."""
        state = {
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
            "members_used": [],
        }

        result = policy_gate.apply_call(
            state,
            "Agent",
            {"subagent_type": "reviewer", "name": "reviewer"},
            self.session_id,
        )

        self.assertIsNotNone(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("requires the current run_id", reason)
        self.assertIsNone(
            team_lifecycle.load_team_state(self.session_id)
        )

    def test_member_limit_denial_does_not_create_team_state(self):
        """Budget validation runs before lifecycle state reservation."""
        state = {
            "run_id": "run-1",
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 0, "max_total_tool_calls": 10},
            "members_used": [],
        }

        result = policy_gate.apply_call(
            state,
            "Agent",
            {"subagent_type": "reviewer", "name": "reviewer"},
            self.session_id,
        )

        self.assertIsNotNone(result)
        self.assertIsNone(
            team_lifecycle.load_team_state(self.session_id)
        )

    def test_apply_call_denies_reuse_decision(self):
        """Agent dispatch for idle teammate is denied with SendMessage instruction."""
        decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
        mark_teammate_idle_reusable(self.session_id, "reviewer")

        state = {
            "run_id": "run-2",
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
            "members_used": ["reviewer"],
        }
        tool_input = {"subagent_type": "reviewer", "name": "reviewer"}

        result = policy_gate.apply_call(state, "Agent", tool_input, self.session_id)

        self.assertIsNotNone(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("SendMessage", reason)

    def test_apply_call_denies_busy_decision(self):
        """Agent dispatch for busy teammate is denied."""
        decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
        mark_teammate_running(self.session_id, "reviewer", "run-1", "task-1")

        state = {
            "run_id": "run-2",
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
            "members_used": ["reviewer"],
        }
        tool_input = {"subagent_type": "reviewer", "name": "reviewer"}

        result = policy_gate.apply_call(state, "Agent", tool_input, self.session_id)

        self.assertIsNotNone(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("currently handling work", reason)

    def test_apply_call_denies_mismatched_name(self):
        """Agent dispatch with mismatched canonical name is denied."""
        state = {
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
        }
        tool_input = {"subagent_type": "reviewer", "name": "reviewer-2"}

        result = policy_gate.apply_call(state, "Agent", tool_input, self.session_id)

        self.assertIsNotNone(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("does not match the canonical name", reason)

    def test_canonical_names_for_all_roles(self):
        """All canonical roles are enforced."""
        roles = ["reviewer", "coder", "bug-fixer", "diagnostician", "red-team", "group-sales-manager", "merchant-manager", "scheduler"]

        for role in roles:
            state = {"selected_agents": [role], "limits": {"max_members": 1, "max_total_tool_calls": 10}, "members_used": []}
            result = policy_gate.apply_call(state, "Agent", {"subagent_type": role, "name": role}, None)
            self.assertIsNone(result, f"Canonical name should be allowed for {role}")


class PolicyGateHookTests(unittest.TestCase):
    """Test policy_gate.main() hook."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(TEAM_STATE_DIR_ENV_VAR)
        os.environ[TEAM_STATE_DIR_ENV_VAR] = self.temp_dir.name
        self.session_id = "test-session"

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(TEAM_STATE_DIR_ENV_VAR, None)
        else:
            os.environ[TEAM_STATE_DIR_ENV_VAR] = self.original_env
        self.temp_dir.cleanup()

    def run_hook(self, hook_input):
        """Run hook main with JSON input."""
        original_stdin = sys.stdin
        original_stdout = sys.stdout

        try:
            sys.stdin = StringIO(json.dumps(hook_input))
            sys.stdout = StringIO()
            policy_gate.main()
            output = sys.stdout.getvalue()
            return json.loads(output) if output else None
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

    def test_hook_ignores_request_without_run_state(self):
        """Hook ignores Agent dispatch when no run state exists (not a /solve run)."""
        output = self.run_hook({
            "session_id": self.session_id,
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "reviewer", "name": "reviewer"},
        })
        self.assertIsNone(output)


if __name__ == "__main__":
    unittest.main()
