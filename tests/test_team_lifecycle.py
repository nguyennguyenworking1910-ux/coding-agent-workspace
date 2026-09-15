"""Tests for session-scoped Agent Team lifecycle and result ledger."""

import json
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


class AtomicTeamStatePersistenceTests(unittest.TestCase):
    """Regression tests for atomic save_team_state on Windows.

    os.replace intermittently raised PermissionError (WinError 5) because a
    fixed "<session>.json.tmp" name collided between writers and retries, and
    because the temporary file was not flushed and fsynced before replacement.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(TEAM_STATE_DIR_ENV_VAR)
        os.environ[TEAM_STATE_DIR_ENV_VAR] = self.temp_dir.name
        self.session_id = "test-session"
        self.state_dir = Path(self.temp_dir.name)
        self.state_path = team_lifecycle.team_state_path(self.session_id)

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(TEAM_STATE_DIR_ENV_VAR, None)
        else:
            os.environ[TEAM_STATE_DIR_ENV_VAR] = self.original_env
        self.temp_dir.cleanup()

    def temporary_files(self):
        """Every scratch file save_team_state could have left behind."""
        return sorted(
            entry.name
            for entry in self.state_dir.iterdir()
            if entry.name.endswith(".tmp")
        )

    # A. Normal save and replacement preserves valid JSON.
    def test_save_writes_valid_json_and_leaves_no_temporary_file(self):
        state = {"teammates": {"reviewer": init_teammate_record("reviewer", "reviewer")}}

        team_lifecycle.save_team_state(self.session_id, state)

        self.assertTrue(self.state_path.exists())
        with self.state_path.open("r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), state)
        self.assertEqual(self.temporary_files(), [])

    def test_save_uses_a_unique_temporary_name_in_the_destination_directory(self):
        """The scratch file is unique and a sibling of the destination."""
        observed = []
        real_replace = os.replace

        def record(source, destination):
            observed.append((Path(source), Path(destination)))
            real_replace(source, destination)

        with patch("team_lifecycle.os.replace", side_effect=record):
            team_lifecycle.save_team_state(self.session_id, {"teammates": {}})
            team_lifecycle.save_team_state(self.session_id, {"teammates": {}})

        first, second = observed
        self.assertNotEqual(first[0].name, second[0].name)
        self.assertNotEqual(first[0].name, f"{self.state_path.name}.tmp")
        for source, destination in observed:
            self.assertEqual(source.parent, self.state_path.parent)
            self.assertEqual(destination, self.state_path)

    # B. First os.replace raises PermissionError; the next attempt succeeds.
    def test_transient_permission_error_is_retried_and_succeeds(self):
        state = {"teammates": {"coder": init_teammate_record("coder", "coder")}}
        real_replace = os.replace
        attempts = []

        def flaky(source, destination):
            attempts.append(source)
            if len(attempts) == 1:
                raise PermissionError(5, "Access is denied")
            real_replace(source, destination)

        with patch.object(team_lifecycle, "IS_WINDOWS", True):
            with patch("team_lifecycle.time.sleep") as sleep:
                with patch("team_lifecycle.os.replace", side_effect=flaky):
                    team_lifecycle.save_team_state(self.session_id, state)

        self.assertEqual(len(attempts), 2)
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(
            sleep.call_args.args[0],
            team_lifecycle.REPLACE_RETRY_BACKOFF_SECONDS[0],
        )

        with self.state_path.open("r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), state)
        self.assertEqual(self.temporary_files(), [])

    # C. Persistent PermissionError is raised after the bounded retry limit.
    def test_persistent_permission_error_is_raised_after_bounded_retries(self):
        def always_denied(source, destination):
            raise PermissionError(5, "Access is denied")

        with patch.object(team_lifecycle, "IS_WINDOWS", True):
            with patch("team_lifecycle.time.sleep") as sleep:
                with patch(
                    "team_lifecycle.os.replace",
                    side_effect=always_denied,
                ) as replace:
                    with self.assertRaises(PermissionError):
                        team_lifecycle.save_team_state(
                            self.session_id,
                            {"teammates": {}},
                        )

        self.assertEqual(
            replace.call_count,
            team_lifecycle.REPLACE_RETRY_ATTEMPTS,
        )
        self.assertEqual(
            sleep.call_count,
            team_lifecycle.REPLACE_RETRY_ATTEMPTS - 1,
        )
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            list(team_lifecycle.REPLACE_RETRY_BACKOFF_SECONDS),
        )

    def test_permission_error_is_not_retried_off_windows(self):
        """Non-Windows platforms re-raise immediately."""
        def always_denied(source, destination):
            raise PermissionError(13, "Permission denied")

        with patch.object(team_lifecycle, "IS_WINDOWS", False):
            with patch("team_lifecycle.time.sleep") as sleep:
                with patch(
                    "team_lifecycle.os.replace",
                    side_effect=always_denied,
                ) as replace:
                    with self.assertRaises(PermissionError):
                        team_lifecycle.save_team_state(
                            self.session_id,
                            {"teammates": {}},
                        )

        self.assertEqual(replace.call_count, 1)
        sleep.assert_not_called()

    def test_non_permission_errors_are_not_retried(self):
        """Only PermissionError is transient; other OSErrors fail at once."""
        def failed(source, destination):
            raise OSError(28, "No space left on device")

        with patch.object(team_lifecycle, "IS_WINDOWS", True):
            with patch("team_lifecycle.time.sleep") as sleep:
                with patch(
                    "team_lifecycle.os.replace",
                    side_effect=failed,
                ) as replace:
                    with self.assertRaises(OSError):
                        team_lifecycle.save_team_state(
                            self.session_id,
                            {"teammates": {}},
                        )

        self.assertEqual(replace.call_count, 1)
        sleep.assert_not_called()

    # D. Failed replacement leaves the previous state file unchanged.
    def test_failed_replacement_leaves_previous_state_unchanged(self):
        original = {
            "teammates": {"reviewer": init_teammate_record("reviewer", "reviewer")}
        }
        team_lifecycle.save_team_state(self.session_id, original)

        def always_denied(source, destination):
            raise PermissionError(5, "Access is denied")

        with patch.object(team_lifecycle, "IS_WINDOWS", True):
            with patch("team_lifecycle.time.sleep"):
                with patch("team_lifecycle.os.replace", side_effect=always_denied):
                    with self.assertRaises(PermissionError):
                        team_lifecycle.save_team_state(
                            self.session_id,
                            {"teammates": {"coder": init_teammate_record("coder", "coder")}},
                        )

        self.assertTrue(self.state_path.exists())
        with self.state_path.open("r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), original)
        self.assertEqual(
            team_lifecycle.load_team_state(self.session_id),
            original,
        )

    # E. Failed replacement leaves no generated temporary files.
    def test_failed_replacement_leaves_no_temporary_files(self):
        def always_denied(source, destination):
            raise PermissionError(5, "Access is denied")

        with patch.object(team_lifecycle, "IS_WINDOWS", True):
            with patch("team_lifecycle.time.sleep"):
                with patch("team_lifecycle.os.replace", side_effect=always_denied):
                    with self.assertRaises(PermissionError):
                        team_lifecycle.save_team_state(
                            self.session_id,
                            {"teammates": {}},
                        )

        self.assertEqual(self.temporary_files(), [])

    def test_cleanup_failure_does_not_mask_the_original_error(self):
        """An unlink that fails must not replace the PermissionError."""
        def always_denied(source, destination):
            raise PermissionError(5, "Access is denied")

        with patch.object(team_lifecycle, "IS_WINDOWS", True):
            with patch("team_lifecycle.time.sleep"):
                with patch("team_lifecycle.os.replace", side_effect=always_denied):
                    with patch.object(
                        Path,
                        "unlink",
                        side_effect=OSError(5, "Access is denied"),
                    ):
                        with self.assertRaises(PermissionError):
                            team_lifecycle.save_team_state(
                                self.session_id,
                                {"teammates": {}},
                            )

    def test_save_failure_inside_lock_leaves_state_readable(self):
        """locked_team_state holds the lock across the whole save."""
        original = {"teammates": {}}
        team_lifecycle.save_team_state(self.session_id, original)

        def always_denied(source, destination):
            raise PermissionError(5, "Access is denied")

        with patch.object(team_lifecycle, "IS_WINDOWS", True):
            with patch("team_lifecycle.time.sleep"):
                with patch("team_lifecycle.os.replace", side_effect=always_denied):
                    with self.assertRaises(PermissionError):
                        with team_lifecycle.locked_team_state(
                            self.session_id,
                        ) as state:
                            state["teammates"]["reviewer"] = init_teammate_record(
                                "reviewer",
                                "reviewer",
                            )

        self.assertEqual(
            team_lifecycle.load_team_state(self.session_id),
            original,
        )
        self.assertEqual(self.temporary_files(), [])

        # The lock is released, so the next writer still succeeds.
        decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
        self.assertEqual(decision, TeammateAllocationDecision.CREATE)


class RepeatedTeamStateWriteTests(unittest.TestCase):
    """Many real saves in one directory must never collide on a scratch file."""

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

    def test_repeated_lifecycle_writes_stay_consistent(self):
        allocate_teammate(self.session_id, "reviewer", "reviewer")

        for index in range(25):
            mark_teammate_running(
                self.session_id,
                "reviewer",
                f"run-{index}",
                f"task-{index}",
            )
            mark_report_received(self.session_id, "reviewer", f"task-{index}")
            mark_teammate_acknowledged(self.session_id, "reviewer")
            mark_teammate_idle_reusable(self.session_id, "reviewer")

        self.assertEqual(
            get_teammate_status(self.session_id, "reviewer"),
            TeammateLifecycleStatus.IDLE_REUSABLE.value,
        )
        self.assertEqual(
            sorted(
                entry.name
                for entry in Path(self.temp_dir.name).iterdir()
                if entry.name.endswith(".tmp")
            ),
            [],
        )

    def test_concurrent_writers_never_corrupt_state(self):
        allocate_teammate(self.session_id, "reviewer", "reviewer")
        errors = []
        barrier = threading.Barrier(4)

        def write(index):
            barrier.wait()
            try:
                for _ in range(10):
                    mark_teammate_running(
                        self.session_id,
                        "reviewer",
                        f"run-{index}",
                        f"task-{index}",
                    )
                    mark_teammate_idle_reusable(self.session_id, "reviewer")
            except Exception as error:  # noqa: BLE001 - recorded and re-asserted
                errors.append(error)

        threads = [threading.Thread(target=write, args=(index,)) for index in range(4)]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        state = team_lifecycle.load_team_state(self.session_id)
        self.assertIsNotNone(state)
        self.assertIn("reviewer", state["teammates"])


if __name__ == "__main__":
    unittest.main()
