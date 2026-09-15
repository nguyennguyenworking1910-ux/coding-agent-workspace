"""Regression tests for serialized run-state cleanup."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from filelock import Timeout

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import runtime_state


class RuntimeStateCleanupTests(unittest.TestCase):
    """Run cleanup must serialize with every hook state writer."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_directory = os.environ.get(
            runtime_state.STATE_DIR_ENV_VAR
        )
        os.environ[runtime_state.STATE_DIR_ENV_VAR] = (
            self.temporary_directory.name
        )
        self.session_id = "cleanup-test-session"
        runtime_state.save_state(
            self.session_id,
            runtime_state.new_state(
                request="read-only test",
                task_class="small_task",
                risk_level="read_only",
                selected_agents=["reviewer"],
                limits={"max_members": 1},
                confirmed=False,
                run_id="run-1",
            ),
        )

    def tearDown(self):
        if self.original_directory is None:
            os.environ.pop(runtime_state.STATE_DIR_ENV_VAR, None)
        else:
            os.environ[runtime_state.STATE_DIR_ENV_VAR] = (
                self.original_directory
            )

        self.temporary_directory.cleanup()

    def test_clear_removes_existing_run_state(self):
        self.assertTrue(runtime_state.clear_state(self.session_id))
        self.assertIsNone(runtime_state.load_state(self.session_id))

    def test_clear_missing_state_is_idempotent(self):
        self.assertTrue(runtime_state.clear_state(self.session_id))
        self.assertFalse(runtime_state.clear_state(self.session_id))

    def test_clear_timeout_preserves_run_state(self):
        with patch("runtime_state.FileLock") as lock_class:
            lock_class.return_value.__enter__.side_effect = Timeout(
                "busy-run-state"
            )

            self.assertFalse(runtime_state.clear_state(self.session_id))

        self.assertIsNotNone(runtime_state.load_state(self.session_id))

    def test_clear_os_error_preserves_run_state(self):
        state_path = runtime_state.state_path(self.session_id)

        with patch.object(
            Path,
            "unlink",
            side_effect=PermissionError(5, "Access is denied"),
        ):
            self.assertFalse(runtime_state.clear_state(self.session_id))

        self.assertTrue(state_path.exists())

    def test_new_run_can_be_saved_after_cleanup(self):
        self.assertTrue(runtime_state.clear_state(self.session_id))

        replacement = runtime_state.new_state(
            request="next run",
            task_class="small_task",
            risk_level="read_only",
            selected_agents=["reviewer"],
            limits={"max_members": 1},
            confirmed=False,
            run_id="run-2",
        )
        runtime_state.save_state(self.session_id, replacement)

        self.assertEqual(
            runtime_state.load_state(self.session_id)["run_id"],
            "run-2",
        )


class AtomicRuntimeStatePersistenceTests(unittest.TestCase):
    """Run-state writes use the same Windows-safe contract as team state."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_directory = os.environ.get(
            runtime_state.STATE_DIR_ENV_VAR
        )
        os.environ[runtime_state.STATE_DIR_ENV_VAR] = (
            self.temporary_directory.name
        )
        self.session_id = "persistence-test-session"
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self):
        if self.original_directory is None:
            os.environ.pop(runtime_state.STATE_DIR_ENV_VAR, None)
        else:
            os.environ[runtime_state.STATE_DIR_ENV_VAR] = (
                self.original_directory
            )

        self.temporary_directory.cleanup()

    def state(self, run_id: str) -> dict:
        return runtime_state.new_state(
            request="test",
            task_class="small_task",
            risk_level="read_only",
            selected_agents=["reviewer"],
            limits={"max_members": 1},
            confirmed=False,
            run_id=run_id,
        )

    def temporary_files(self) -> list[str]:
        return sorted(
            entry.name
            for entry in self.directory.iterdir()
            if entry.name.endswith(".tmp")
        )

    def test_save_uses_unique_sibling_temporary_files(self):
        observed = []
        real_replace = os.replace

        def record(source, destination):
            observed.append((Path(source), Path(destination)))
            real_replace(source, destination)

        with patch("runtime_state.os.replace", side_effect=record):
            runtime_state.save_state(self.session_id, self.state("run-1"))
            runtime_state.save_state(self.session_id, self.state("run-2"))

        first, second = observed
        destination = runtime_state.state_path(self.session_id)
        self.assertNotEqual(first[0].name, second[0].name)
        self.assertEqual(first[0].parent, destination.parent)
        self.assertEqual(second[0].parent, destination.parent)
        self.assertEqual(first[1], destination)
        self.assertEqual(second[1], destination)
        self.assertEqual(self.temporary_files(), [])

    def test_transient_windows_permission_error_is_retried(self):
        attempts = []
        real_replace = os.replace

        def flaky(source, destination):
            attempts.append(Path(source))

            if len(attempts) == 1:
                raise PermissionError(5, "Access is denied")

            real_replace(source, destination)

        with patch.object(runtime_state, "IS_WINDOWS", True):
            with patch("runtime_state.time.sleep") as sleep:
                with patch(
                    "runtime_state.os.replace",
                    side_effect=flaky,
                ):
                    runtime_state.save_state(
                        self.session_id,
                        self.state("run-1"),
                    )

        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once_with(
            runtime_state.REPLACE_RETRY_BACKOFF_SECONDS[0]
        )
        self.assertEqual(
            runtime_state.load_state(self.session_id)["run_id"],
            "run-1",
        )
        self.assertEqual(self.temporary_files(), [])

    def test_persistent_replace_failure_preserves_previous_state(self):
        runtime_state.save_state(self.session_id, self.state("original"))

        with patch.object(runtime_state, "IS_WINDOWS", True):
            with patch("runtime_state.time.sleep"):
                with patch(
                    "runtime_state.os.replace",
                    side_effect=PermissionError(5, "Access is denied"),
                ) as replace:
                    with self.assertRaises(PermissionError):
                        runtime_state.save_state(
                            self.session_id,
                            self.state("replacement"),
                        )

        self.assertEqual(
            replace.call_count,
            runtime_state.REPLACE_RETRY_ATTEMPTS,
        )
        self.assertEqual(
            runtime_state.load_state(self.session_id)["run_id"],
            "original",
        )
        self.assertEqual(self.temporary_files(), [])

    def test_permission_error_is_not_retried_off_windows(self):
        with patch.object(runtime_state, "IS_WINDOWS", False):
            with patch("runtime_state.time.sleep") as sleep:
                with patch(
                    "runtime_state.os.replace",
                    side_effect=PermissionError(13, "Permission denied"),
                ) as replace:
                    with self.assertRaises(PermissionError):
                        runtime_state.save_state(
                            self.session_id,
                            self.state("run-1"),
                        )

        self.assertEqual(replace.call_count, 1)
        sleep.assert_not_called()
        self.assertEqual(self.temporary_files(), [])

    def test_concurrent_locked_updates_do_not_lose_counts(self):
        runtime_state.save_state(self.session_id, self.state("run-1"))
        errors = []
        barrier = threading.Barrier(4)

        def update_state():
            barrier.wait()

            try:
                for _ in range(10):
                    with runtime_state.locked_state(
                        self.session_id
                    ) as state:
                        state["total_tool_calls"] += 1
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=update_state) for _ in range(4)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(
            runtime_state.load_state(self.session_id)["total_tool_calls"],
            40,
        )
        self.assertEqual(self.temporary_files(), [])


if __name__ == "__main__":
    unittest.main()
