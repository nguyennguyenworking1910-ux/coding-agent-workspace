"""Tests for Milestone 5: Steering API and Session Management."""

import sys
import tempfile
from pathlib import Path
from datetime import datetime

# Add .claude to path
claude_path = Path(__file__).parent.parent / ".claude"
if str(claude_path) not in sys.path:
    sys.path.insert(0, str(claude_path))

from team.session_manager import SessionManager
from team.steering_api import SteeringAPI
from team.mailbox_manager import MailboxManager
from team.run_store import RunStore
from team.event_bus import EventBus
from team.schemas import RunStatus, TaskStatus, RunContext, AgentPlan, AgentTask


def test_session_save_checkpoint():
    """Test saving a checkpoint."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run")

        mgr = SessionManager("test_run", store)

        completed = ["task_1", "task_2"]
        pending = ["task_3"]

        success = mgr.save_checkpoint(
            status=RunStatus.PAUSED,
            completed_task_ids=completed,
            pending_task_ids=pending,
            worker_count=2,
            plan_summary="Test plan",
        )

        assert success, "Save checkpoint should succeed"

        # Verify checkpoint saved
        checkpoint = mgr.load_checkpoint()
        assert checkpoint is not None
        assert checkpoint.status == RunStatus.PAUSED
        assert checkpoint.completed_task_ids == completed
        assert checkpoint.pending_task_ids == pending
        assert checkpoint.worker_count == 2


def test_session_load_checkpoint():
    """Test loading a checkpoint."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run")

        # Save checkpoint with one manager
        mgr1 = SessionManager("test_run", store)
        mgr1.save_checkpoint(
            status=RunStatus.PAUSED,
            completed_task_ids=["task_1"],
            pending_task_ids=["task_2"],
            worker_count=1,
            plan_summary="Original plan",
        )

        # Load with another manager
        mgr2 = SessionManager("test_run", store)
        checkpoint = mgr2.load_checkpoint()

        assert checkpoint is not None
        assert checkpoint.completed_task_ids == ["task_1"]
        assert checkpoint.pending_task_ids == ["task_2"]


def test_session_is_resumable():
    """Test checking if run is resumable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run")

        mgr = SessionManager("test_run", store)

        # No checkpoint yet
        assert not mgr.is_resumable()

        # Save paused checkpoint
        mgr.save_checkpoint(
            status=RunStatus.PAUSED,
            completed_task_ids=[],
            pending_task_ids=["task_1"],
            worker_count=1,
            plan_summary="Test",
        )

        # Now it's resumable
        assert mgr.is_resumable()


def test_session_get_completed_tasks():
    """Test getting completed task list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run")

        mgr = SessionManager("test_run", store)

        completed = ["task_1", "task_2", "task_3"]
        mgr.save_checkpoint(
            status=RunStatus.RUNNING,
            completed_task_ids=completed,
            pending_task_ids=[],
            worker_count=1,
            plan_summary="Test",
        )

        loaded = mgr.get_completed_tasks()
        assert loaded == completed


def test_steering_send_message():
    """Test sending message via steering API."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run_1")

        mailbox = MailboxManager("test_run_1", store)
        session = SessionManager("test_run_1", store)
        api = SteeringAPI("test_run_1", store, mailbox, session)

        msg_id = api.send_message_to_agent(
            from_agent="user",
            to_agent="researcher",
            body="Please focus on security issues",
            subject="Task update",
        )

        assert msg_id is not None, "Message ID should be generated"

        # Verify message in mailbox
        messages = api.get_mailbox("researcher")
        assert len(messages) == 1
        assert messages[0].subject == "Task update"


def test_steering_get_mailbox():
    """Test getting agent mailbox."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run_2")

        mailbox = MailboxManager("test_run_2", store)
        session = SessionManager("test_run_2", store)
        api = SteeringAPI("test_run_2", store, mailbox, session)

        # Send multiple messages
        api.send_message_to_agent("user", "agent1", "Message 1", "Subj 1")
        api.send_message_to_agent("user", "agent1", "Message 2", "Subj 2")
        api.send_message_to_agent("user", "agent2", "Message 3", "Subj 3")

        # Get mailbox for agent1
        msgs = api.get_mailbox("agent1")
        assert len(msgs) == 2

        # Get mailbox for agent2
        msgs2 = api.get_mailbox("agent2")
        assert len(msgs2) == 1


def test_steering_read_message():
    """Test marking message as read."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run_3")

        mailbox = MailboxManager("test_run_3", store)
        session = SessionManager("test_run_3", store)
        api = SteeringAPI("test_run_3", store, mailbox, session)

        msg_id = api.send_message_to_agent("user", "agent1", "Test", "Test")

        # Message should be unread
        unread = api.get_unread_messages("agent1")
        assert len(unread) == 1

        # Mark as read
        read_msg = api.read_message("agent1", msg_id)
        assert read_msg is not None
        assert read_msg.read_at is not None

        # Should have no unread now
        unread = api.get_unread_messages("agent1")
        assert len(unread) == 0


def test_steering_pause_run():
    """Test pausing a run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run_4")

        # Create a running run context
        context = RunContext(
            run_id="test_run_4",
            request="Test",
            status=RunStatus.RUNNING,
        )
        store.save_status("test_run_4", context)

        mailbox = MailboxManager("test_run_4", store)
        session = SessionManager("test_run_4", store)
        api = SteeringAPI("test_run_4", store, mailbox, session)

        # Pause the run
        success = api.pause_run()
        assert success, "Pause should succeed"

        # Verify status changed
        status = store.load_status("test_run_4")
        assert status.status == RunStatus.PAUSED


def test_steering_resume_run():
    """Test resuming a paused run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run_5")

        # Create a paused run context
        context = RunContext(
            run_id="test_run_5",
            request="Test",
            status=RunStatus.PAUSED,
        )
        store.save_status("test_run_5", context)

        mailbox = MailboxManager("test_run_5", store)
        session = SessionManager("test_run_5", store)
        api = SteeringAPI("test_run_5", store, mailbox, session)

        # Resume the run
        success = api.resume_run()
        assert success, "Resume should succeed"

        # Verify status changed
        status = store.load_status("test_run_5")
        assert status.status == RunStatus.RUNNING


def test_steering_get_status():
    """Test getting run status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run_6")

        # Create context and plan
        context = RunContext(
            run_id="test_run_6",
            request="Test",
            status=RunStatus.RUNNING,
        )
        store.save_status("test_run_6", context)

        plan = AgentPlan(
            run_id="test_run_6",
            summary="Test plan",
            parallelism_justified=True,
            synthesis_task_id="task_3",
            agents=[],
            tasks=[
                AgentTask(
                    task_id="task_1",
                    title="Task 1",
                    instructions="Do task 1",
                    owner_agent_id="lead",
                    depends_on=[],
                    acceptance_criteria=["done"],
                ),
                AgentTask(
                    task_id="task_2",
                    title="Task 2",
                    instructions="Do task 2",
                    owner_agent_id="lead",
                    depends_on=["task_1"],
                    acceptance_criteria=["done"],
                ),
                AgentTask(
                    task_id="task_3",
                    title="Task 3",
                    instructions="Do task 3",
                    owner_agent_id="lead",
                    depends_on=["task_2"],
                    acceptance_criteria=["done"],
                ),
            ],
        )
        store.save_plan("test_run_6", plan)

        # Send some messages
        mailbox = MailboxManager("test_run_6", store)
        mailbox.send_message("agent1", "agent2", "Test", "Hello")
        mailbox.send_message("agent1", "agent2", "Test", "Hello")

        session = SessionManager("test_run_6", store)
        api = SteeringAPI("test_run_6", store, mailbox, session)

        status = api.get_run_status()
        assert status is not None
        assert status["run_id"] == "test_run_6"
        assert status["total_tasks"] == 3
        assert status["current_status"] == "running"


def test_steering_cancel_run():
    """Test canceling a run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run_7")

        context = RunContext(
            run_id="test_run_7",
            request="Test",
            status=RunStatus.RUNNING,
        )
        store.save_status("test_run_7", context)

        mailbox = MailboxManager("test_run_7", store)
        session = SessionManager("test_run_7", store)
        api = SteeringAPI("test_run_7", store, mailbox, session)

        # Cancel the run
        success = api.cancel_run()
        assert success, "Cancel should succeed"

        # Verify status
        status = store.load_status("test_run_7")
        assert status.status == RunStatus.CANCELLED


def test_steering_cannot_resume_completed():
    """Test that completed runs cannot be resumed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        store.create_run_dir("test_run_8")

        context = RunContext(
            run_id="test_run_8",
            request="Test",
            status=RunStatus.COMPLETED,
        )
        store.save_status("test_run_8", context)

        mailbox = MailboxManager("test_run_8", store)
        session = SessionManager("test_run_8", store)
        api = SteeringAPI("test_run_8", store, mailbox, session)

        # Try to resume
        success = api.resume_run()
        assert not success, "Should not be able to resume completed run"


if __name__ == "__main__":
    print("Running M5 Steering API tests...")

    test_session_save_checkpoint()
    print("[PASS] Save checkpoint test passed")

    test_session_load_checkpoint()
    print("[PASS] Load checkpoint test passed")

    test_session_is_resumable()
    print("[PASS] Is resumable test passed")

    test_session_get_completed_tasks()
    print("[PASS] Get completed tasks test passed")

    test_steering_send_message()
    print("[PASS] Send message test passed")

    test_steering_get_mailbox()
    print("[PASS] Get mailbox test passed")

    test_steering_read_message()
    print("[PASS] Read message test passed")

    test_steering_pause_run()
    print("[PASS] Pause run test passed")

    test_steering_resume_run()
    print("[PASS] Resume run test passed")

    test_steering_get_status()
    print("[PASS] Get status test passed")

    test_steering_cancel_run()
    print("[PASS] Cancel run test passed")

    test_steering_cannot_resume_completed()
    print("[PASS] Cannot resume completed test passed")

    print("\n[SUCCESS] ALL M5 STEERING TESTS PASSED (11/11)")
