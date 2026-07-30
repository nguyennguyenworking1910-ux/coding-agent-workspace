"""Tests for Milestone 2: Real Claude runner."""

import sys
import tempfile
from pathlib import Path

# Add .claude to path
claude_path = Path(__file__).parent.parent / ".claude"
if str(claude_path) not in sys.path:
    sys.path.insert(0, str(claude_path))

from team.claude_runner import ClaudeRunner
from team.real_worker import RealWorker
from team.schemas import AgentTask, TaskStatus


def test_claude_runner_initialization():
    """Test that ClaudeRunner initializes correctly."""
    runner = ClaudeRunner(
        agent_id="researcher",
        task_id="task_1",
        run_id="test_run",
        timeout=30.0,
    )

    assert runner.agent_id == "researcher"
    assert runner.task_id == "task_1"
    assert runner.run_id == "test_run"
    assert runner.timeout == 30.0
    assert runner.process is None
    assert runner.exit_code is None
    assert len(runner.output_lines) == 0

    print("[PASS] ClaudeRunner initialization test")


def test_real_worker_initialization():
    """Test that RealWorker initializes correctly."""
    task = AgentTask(
        task_id="task_1",
        title="Test Task",
        instructions="Test instructions",
        owner_agent_id="researcher",
    )

    worker = RealWorker(
        agent_id="researcher",
        task=task,
        run_id="test_run",
        timeout=30.0,
    )

    assert worker.agent_id == "researcher"
    assert worker.task == task
    assert worker.run_id == "test_run"
    assert worker.thread is None
    assert worker.success is False

    print("[PASS] RealWorker initialization test")


def test_runner_metadata():
    """Test runner metadata collection."""
    runner = ClaudeRunner(
        agent_id="researcher",
        task_id="task_1",
        run_id="test_run",
    )

    # Simulate completed run
    runner.exit_code = 0
    runner.output_lines = ["line1", "line2"]
    runner.stderr_lines = []
    runner.start_time = 0.0
    runner.end_time = 1.5

    metadata = runner.get_metadata()

    assert metadata["agent_id"] == "researcher"
    assert metadata["task_id"] == "task_1"
    assert metadata["run_id"] == "test_run"
    assert metadata["exit_code"] == 0
    assert metadata["output_lines"] == 2
    assert metadata["stderr_lines"] == 0
    assert abs(metadata["elapsed_seconds"] - 1.5) < 0.01  # Allow small float variance
    assert metadata["error"] is None

    print("[PASS] Runner metadata test")


def test_event_emission():
    """Test that runner emits events correctly."""
    events = []

    def capture_event(event):
        events.append(event)

    runner = ClaudeRunner(
        agent_id="researcher",
        task_id="task_1",
        run_id="test_run",
        on_event=capture_event,
    )

    # Emit some test events
    runner._emit_event("test_event", {"key": "value"})

    assert len(events) == 1
    assert events[0].event_type == "test_event"
    assert events[0].agent_id == "researcher"
    assert events[0].task_id == "task_1"
    assert events[0].payload == {"key": "value"}

    print("[PASS] Event emission test")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("MILESTONE 2: CLAUDE RUNNER TESTS")
    print("=" * 60 + "\n")

    try:
        test_claude_runner_initialization()
        test_real_worker_initialization()
        test_runner_metadata()
        test_event_emission()

        print("\n" + "=" * 60)
        print("[SUCCESS] ALL TESTS PASSED")
        print("=" * 60 + "\n")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n[FAILED] Test failed: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
