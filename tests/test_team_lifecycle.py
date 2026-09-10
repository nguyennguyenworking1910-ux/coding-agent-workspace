"""Tests for session-scoped Agent Team lifecycle and result ledger."""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PROJECT_ROOT / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"

sys.path.insert(0, str(HOOKS_DIR))

import team_lifecycle
from team_lifecycle import (
    TeammateAllocationDecision,
    TeammateLifecycleStatus,
    allocate_teammate,
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
    LOCK_TIMEOUT_SECONDS,
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


class TeammateAllocationDecisionTests(unittest.TestCase):
    """Test explicit TeammateAllocationDecision enum."""

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

    def test_allocate_returns_create_decision_on_first_dispatch(self):
        """First dispatch should return CREATE decision."""
        decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(decision, TeammateAllocationDecision.CREATE)
        self.assertEqual(name, "reviewer")

    def test_allocate_returns_reuse_decision_on_idle_teammate(self):
        """Dispatch of idle teammate should return REUSE decision."""
        decision1, name1 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(decision1, TeammateAllocationDecision.CREATE)

        mark_teammate_idle_reusable(self.session_id, name1)

        decision2, name2 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(decision2, TeammateAllocationDecision.REUSE)
        self.assertEqual(name2, name1)

    def test_allocate_returns_busy_decision_on_running_teammate(self):
        """Dispatch of busy teammate should return BUSY decision."""
        decision1, name1 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(decision1, TeammateAllocationDecision.CREATE)

        mark_teammate_running(self.session_id, name1, "run-1", "task-1")

        decision2, name2 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(decision2, TeammateAllocationDecision.BUSY)
        self.assertEqual(name2, name1)

    def test_allocate_returns_denied_on_lock_timeout(self):
        """Lock timeout should return DENIED decision."""
        decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(decision, TeammateAllocationDecision.CREATE)

        with patch("team_lifecycle.locked_team_state") as mock_lock:
            mock_lock.return_value.__enter__.return_value = None

            decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
            self.assertEqual(decision, TeammateAllocationDecision.DENIED)
            self.assertEqual(name, "reviewer")


class CanonicalNamingTests(unittest.TestCase):
    """Test canonical naming: one role = exactly one name, no suffixes."""

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

    def test_reviewer_always_has_canonical_name(self):
        """Reviewer should always use 'reviewer' name, never suffixed."""
        names = []
        for _ in range(5):
            decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
            names.append(name)
            mark_teammate_idle_reusable(self.session_id, name)

        self.assertEqual(set(names), {"reviewer"})
        self.assertTrue(all(n == "reviewer" for n in names))

    def test_coder_always_has_canonical_name(self):
        """Coder should always use 'coder' name, never suffixed."""
        names = []
        for _ in range(3):
            decision, name = allocate_teammate(self.session_id, "coder", "coder")
            names.append(name)
            mark_teammate_idle_reusable(self.session_id, name)

        self.assertEqual(set(names), {"coder"})

    def test_all_roles_have_canonical_names(self):
        """All canonical roles should use their exact role name."""
        roles = [
            "reviewer", "coder", "bug-fixer", "diagnostician",
            "red-team", "group-sales-manager", "merchant-manager", "scheduler"
        ]

        for role in roles:
            decision, name = allocate_teammate(self.session_id, role, role)
            self.assertEqual(name, role, f"Role {role} should have canonical name {role}, got {name}")
            self.assertEqual(decision, TeammateAllocationDecision.CREATE)
            clear_team_state(self.session_id)

    def test_multiple_roles_maintain_separate_canonical_names(self):
        """Multiple roles should each have their own canonical name."""
        decision1, name1 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        decision2, name2 = allocate_teammate(self.session_id, "coder", "coder")
        decision3, name3 = allocate_teammate(self.session_id, "bug-fixer", "bug-fixer")

        self.assertEqual(name1, "reviewer")
        self.assertEqual(name2, "coder")
        self.assertEqual(name3, "bug-fixer")
        self.assertEqual(len({name1, name2, name3}), 3)


class LockTimeoutTests(unittest.TestCase):
    """Test lock timeout behavior: fail closed with DENIED."""

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

    def test_lock_timeout_returns_denied(self):
        """Lock timeout should return DENIED decision."""
        from filelock import Timeout

        with patch("team_lifecycle.FileLock") as mock_lock_class:
            mock_lock = mock_lock_class.return_value
            mock_lock.__enter__.side_effect = Timeout("dummy_lock_file")

            decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
            self.assertEqual(decision, TeammateAllocationDecision.DENIED)

    def test_lock_timeout_fails_closed_for_new_teammate(self):
        """Lock timeout should not create a teammate; fail closed."""
        with patch("team_lifecycle.locked_team_state") as mock_lock:
            mock_lock.return_value.__enter__.return_value = None

            decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
            self.assertEqual(decision, TeammateAllocationDecision.DENIED)

            state = team_lifecycle.load_team_state(self.session_id)
            self.assertIsNone(state)

    def test_locked_team_state_context_handles_timeout(self):
        """locked_team_state should yield None on timeout."""
        from filelock import Timeout

        with patch("team_lifecycle.FileLock") as mock_lock_class:
            mock_lock = mock_lock_class.return_value
            mock_lock.__enter__.side_effect = Timeout("dummy_lock_file")

            with team_lifecycle.locked_team_state(self.session_id) as state:
                self.assertIsNone(state)


class ConcurrentReservationTests(unittest.TestCase):
    """Test concurrent reservation attempts."""

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

    def test_two_concurrent_allocations_only_one_succeeds_with_create(self):
        """Two concurrent allocations for same role; first gets CREATE, second gets BUSY or REUSE."""
        results = []
        barrier = threading.Barrier(2)

        def allocate_and_record(thread_id):
            barrier.wait()
            decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
            results.append((thread_id, decision, name))

        t1 = threading.Thread(target=allocate_and_record, args=(1,))
        t2 = threading.Thread(target=allocate_and_record, args=(2,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(results), 2)
        decisions = [r[1] for r in results]
        names = [r[2] for r in results]

        self.assertEqual(set(names), {"reviewer"})
        self.assertEqual(
            sorted([d.value for d in decisions]),
            sorted([TeammateAllocationDecision.CREATE.value, TeammateAllocationDecision.BUSY.value])
        )

    def test_concurrent_reuse_after_idle(self):
        """Sequential reuse after idle simulates concurrent behavior on same idle teammate."""
        decision1, name1 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        mark_teammate_idle_reusable(self.session_id, name1)

        results = []

        decision2, name2 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        results.append(("thread1", decision2, name2))
        mark_teammate_running(self.session_id, name2, "run-2", "task-2")

        decision3, name3 = allocate_teammate(self.session_id, "reviewer", "reviewer")
        results.append(("thread2", decision3, name3))

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][1], TeammateAllocationDecision.REUSE)
        self.assertEqual(results[1][1], TeammateAllocationDecision.BUSY)


if __name__ == "__main__":
    unittest.main()
