"""Tests for session-scoped Agent Team lifecycle and result ledger."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PROJECT_ROOT / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"

sys.path.insert(0, str(HOOKS_DIR))

import team_lifecycle
from team_lifecycle import (
    TeammateLifecycleStatus,
    clear_team_state,
    get_or_create_teammate,
    get_teammate_status,
    init_teammate_record,
    mark_report_received,
    mark_teammate_acknowledged,
    mark_teammate_failed,
    mark_teammate_idle_reusable,
    mark_teammate_running,
    new_team_state,
    TEAM_STATE_DIR_ENV_VAR,
)


class TeamStateInitializationTests(unittest.TestCase):
    """Test team state creation and initialization."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(TEAM_STATE_DIR_ENV_VAR)
        os.environ[TEAM_STATE_DIR_ENV_VAR] = self.temp_dir.name

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(TEAM_STATE_DIR_ENV_VAR, None)
        else:
            os.environ[TEAM_STATE_DIR_ENV_VAR] = self.original_env
        self.temp_dir.cleanup()

    def test_new_team_state_is_empty(self):
        state = new_team_state()
        self.assertEqual(state, {"teammates": {}})

    def test_init_teammate_record(self):
        record = init_teammate_record("reviewer", "reviewer")
        self.assertEqual(record["role"], "reviewer")
        self.assertEqual(record["canonical_name"], "reviewer")
        self.assertEqual(record["status"], TeammateLifecycleStatus.CREATED.value)
        self.assertIsNone(record["current_run_id"])
        self.assertIsNone(record["current_task_id"])


class TeammateReuseTests(unittest.TestCase):
    """Test that teammates are reused across runs, not duplicated."""

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

    def test_first_dispatch_creates_teammate(self):
        """First dispatch of a role creates a new teammate."""
        name, is_new = get_or_create_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(name, "reviewer")
        self.assertTrue(is_new)

    def test_second_dispatch_reuses_idle_teammate(self):
        """Second dispatch of same role reuses the teammate if idle."""
        name1, is_new1 = get_or_create_teammate(self.session_id, "reviewer", "reviewer")
        self.assertTrue(is_new1)

        mark_teammate_idle_reusable(self.session_id, "reviewer")

        name2, is_new2 = get_or_create_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(name2, "reviewer")
        self.assertFalse(is_new2)

    def test_three_sequential_runs_use_same_teammate(self):
        """Three sequential runs should all use the same canonical teammate."""
        teammates_created = []

        for run in range(3):
            name, is_new = get_or_create_teammate(self.session_id, "reviewer", "reviewer")
            teammates_created.append((name, is_new))
            mark_teammate_idle_reusable(self.session_id, "reviewer")

        self.assertEqual(len(teammates_created), 3)
        self.assertTrue(teammates_created[0][1])
        self.assertFalse(teammates_created[1][1])
        self.assertFalse(teammates_created[2][1])
        self.assertEqual(teammates_created[0][0], "reviewer")
        self.assertEqual(teammates_created[1][0], "reviewer")
        self.assertEqual(teammates_created[2][0], "reviewer")

    def test_no_suffixed_duplicates_on_reuse(self):
        """Reuse should never create reviewer-2, reviewer-3, etc."""
        names = []
        for _ in range(5):
            name, _ = get_or_create_teammate(self.session_id, "reviewer", "reviewer")
            names.append(name)
            mark_teammate_idle_reusable(self.session_id, "reviewer")

        self.assertEqual(len(set(names)), 1)
        self.assertEqual(names[0], "reviewer")
        self.assertNotIn("-2", names[0])
        self.assertNotIn("-3", names[0])

    def test_role_busy_does_not_create_duplicate(self):
        """When a role is busy, reuse should still return the same name."""
        name1, is_new1 = get_or_create_teammate(self.session_id, "reviewer", "reviewer")
        self.assertTrue(is_new1)

        mark_teammate_running(self.session_id, "reviewer", "run-1", "task-1")

        name2, is_new2 = get_or_create_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(name2, "reviewer")
        self.assertFalse(is_new2)

    def test_different_roles_create_separate_teammates(self):
        """Different roles should get their own teammates."""
        name1, is_new1 = get_or_create_teammate(self.session_id, "reviewer", "reviewer")
        name2, is_new2 = get_or_create_teammate(self.session_id, "coder", "coder")

        self.assertTrue(is_new1)
        self.assertTrue(is_new2)
        self.assertEqual(name1, "reviewer")
        self.assertEqual(name2, "coder")


class TeammateLifecycleStatusTests(unittest.TestCase):
    """Test teammate lifecycle state transitions."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(TEAM_STATE_DIR_ENV_VAR)
        os.environ[TEAM_STATE_DIR_ENV_VAR] = self.temp_dir.name
        self.session_id = "test-session"
        self.name, _ = get_or_create_teammate(self.session_id, "reviewer", "reviewer")

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(TEAM_STATE_DIR_ENV_VAR, None)
        else:
            os.environ[TEAM_STATE_DIR_ENV_VAR] = self.original_env
        self.temp_dir.cleanup()

    def test_lifecycle_transitions(self):
        """Test the expected lifecycle: CREATED -> DISPATCHED -> RUNNING -> REPORT_RECEIVED -> ACKNOWLEDGED -> IDLE_REUSABLE."""
        self.assertEqual(
            get_teammate_status(self.session_id, self.name),
            TeammateLifecycleStatus.CREATED.value
        )

        mark_teammate_running(self.session_id, self.name, "run-1", "task-1")
        self.assertEqual(
            get_teammate_status(self.session_id, self.name),
            TeammateLifecycleStatus.RUNNING.value
        )

        mark_report_received(self.session_id, self.name, "task-1")
        self.assertEqual(
            get_teammate_status(self.session_id, self.name),
            TeammateLifecycleStatus.REPORT_RECEIVED.value
        )

        mark_teammate_acknowledged(self.session_id, self.name)
        self.assertEqual(
            get_teammate_status(self.session_id, self.name),
            TeammateLifecycleStatus.ACKNOWLEDGED.value
        )

        mark_teammate_idle_reusable(self.session_id, self.name)
        self.assertEqual(
            get_teammate_status(self.session_id, self.name),
            TeammateLifecycleStatus.IDLE_REUSABLE.value
        )

    def test_report_received_is_idempotent(self):
        """Receiving a report twice should be idempotent."""
        mark_teammate_running(self.session_id, self.name, "run-1", "task-1")

        result1 = mark_report_received(self.session_id, self.name, "task-1", source="sendmessage")
        self.assertTrue(result1)

        result2 = mark_report_received(self.session_id, self.name, "task-1", source="automatic")
        self.assertTrue(result2)

        status = get_teammate_status(self.session_id, self.name)
        self.assertEqual(status, TeammateLifecycleStatus.REPORT_RECEIVED.value)

    def test_mark_teammate_failed(self):
        """Teammates can be marked as failed."""
        mark_teammate_failed(self.session_id, self.name, reason="connection lost")
        status = get_teammate_status(self.session_id, self.name)
        self.assertEqual(status, TeammateLifecycleStatus.FAILED.value)


class TeamStateCleanupTests(unittest.TestCase):
    """Test cleanup of team state."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(TEAM_STATE_DIR_ENV_VAR)
        os.environ[TEAM_STATE_DIR_ENV_VAR] = self.temp_dir.name
        self.session_id = "test-session"
        get_or_create_teammate(self.session_id, "reviewer", "reviewer")

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(TEAM_STATE_DIR_ENV_VAR, None)
        else:
            os.environ[TEAM_STATE_DIR_ENV_VAR] = self.original_env
        self.temp_dir.cleanup()

    def test_clear_team_state_removes_state(self):
        """Clearing team state should remove the session's team record."""
        state = team_lifecycle.load_team_state(self.session_id)
        self.assertIsNotNone(state)

        clear_team_state(self.session_id)

        state = team_lifecycle.load_team_state(self.session_id)
        self.assertIsNone(state)

    def test_clear_missing_team_state_does_not_error(self):
        """Clearing team state for a session that has none should not error."""
        result = clear_team_state("nonexistent-session")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
