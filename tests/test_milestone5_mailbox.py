"""Tests for Milestone 5: Inter-agent messaging (Mailbox system)."""

import sys
import tempfile
import time
from pathlib import Path

# Add .claude to path
claude_path = Path(__file__).parent.parent / ".claude"
if str(claude_path) not in sys.path:
    sys.path.insert(0, str(claude_path))

from team.mailbox_manager import MailboxManager
from team.run_store import RunStore
from team.schemas import AgentMessage, AgentMailbox


def test_mailbox_send_message():
    """Test sending a message between agents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MailboxManager("test_run_1", RunStore(tmpdir))

        # Send message from researcher to reviewer
        msg_id = manager.send_message(
            sender_agent_id="researcher",
            receiver_agent_id="reviewer",
            subject="Research findings",
            body="Found 3 critical issues in auth module",
            metadata={"severity": "high"},
        )

        assert msg_id is not None, "Message ID should be generated"
        assert len(msg_id) > 0, "Message ID should not be empty"

        # Verify message in receiver's mailbox
        mailbox = manager.get_mailbox("reviewer")
        assert mailbox is not None, "Receiver should have mailbox"
        assert len(mailbox.messages) == 1, "Should have 1 message"
        assert mailbox.messages[0].sender_agent_id == "researcher"
        assert mailbox.messages[0].subject == "Research findings"


def test_mailbox_unread_messages():
    """Test getting unread messages."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MailboxManager("test_run_2", RunStore(tmpdir))

        # Send 3 messages
        for i in range(3):
            manager.send_message(
                sender_agent_id="researcher",
                receiver_agent_id="reviewer",
                subject=f"Finding {i+1}",
                body=f"Issue {i+1} details",
            )

        # Get unread messages
        unread = manager.get_unread_messages("reviewer")
        assert len(unread) == 3, "Should have 3 unread messages"
        assert manager.unread_count("reviewer") == 3, "Unread count should be 3"


def test_mailbox_read_message():
    """Test marking message as read."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MailboxManager("test_run_3", RunStore(tmpdir))

        # Send message
        msg_id = manager.send_message(
            sender_agent_id="researcher",
            receiver_agent_id="reviewer",
            subject="Test",
            body="Test message",
        )

        # Verify unread
        assert manager.unread_count("reviewer") == 1, "Should have 1 unread"

        # Read the message
        message = manager.read_message("reviewer", msg_id)
        assert message is not None, "Message should be found"
        assert message.read_at is not None, "Message should have read_at timestamp"

        # Verify unread count updated
        assert manager.unread_count("reviewer") == 0, "Should have 0 unread"


def test_mailbox_message_persistence():
    """Test messages are persisted to disk."""
    run_id = "test_run_4"

    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)
        manager = MailboxManager(run_id, store)

        # Send message
        manager.send_message(
            sender_agent_id="agent1",
            receiver_agent_id="agent2",
            subject="Persistent test",
            body="This message should be saved to disk",
        )

        # Verify file was created
        agent_dir = store.get_run_dir(run_id) / "agents" / "agent2"
        messages_file = agent_dir / "messages.jsonl"
        assert messages_file.exists(), "Messages file should exist"

        # Load messages from disk
        loaded_messages = store.get_agent_messages(run_id, "agent2")
        assert len(loaded_messages) == 1, "Should have 1 loaded message"
        assert loaded_messages[0].subject == "Persistent test"


def test_mailbox_load_from_store():
    """Test loading messages from persistent store."""
    run_id = "test_run_5"

    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(tmpdir)

        # First manager: send messages
        manager1 = MailboxManager(run_id, store)
        manager1.send_message(
            sender_agent_id="agent1",
            receiver_agent_id="agent2",
            subject="Message 1",
            body="Content 1",
        )
        manager1.send_message(
            sender_agent_id="agent1",
            receiver_agent_id="agent2",
            subject="Message 2",
            body="Content 2",
        )

        # Second manager: load from store
        manager2 = MailboxManager(run_id, store)
        manager2.load_from_store()

        # Verify messages loaded
        mailbox = manager2.get_mailbox("agent2")
        assert mailbox is not None, "Mailbox should exist after load"
        assert len(mailbox.messages) == 2, "Should have 2 messages after load"
        assert manager2.message_count("agent2") == 2, "Message count should be 2"


def test_mailbox_multiple_agents():
    """Test mailboxes for multiple agents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MailboxManager("test_run_6", RunStore(tmpdir))

        # Send messages to different agents
        manager.send_message("lead", "researcher", "Start task", "Begin analysis")
        manager.send_message("lead", "reviewer", "Start task", "Begin review")
        manager.send_message("researcher", "reviewer", "Findings", "Here are my findings")

        # Verify each agent has their messages
        assert manager.message_count("researcher") == 1
        assert manager.message_count("reviewer") == 2
        assert manager.message_count("lead") == 0, "Lead has no incoming messages"


def test_mailbox_metadata():
    """Test message metadata storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MailboxManager("test_run_7", RunStore(tmpdir))

        metadata = {
            "priority": "high",
            "tags": ["security", "critical"],
            "issue_id": "SEC-123",
        }

        manager.send_message(
            sender_agent_id="researcher",
            receiver_agent_id="reviewer",
            subject="Security issue",
            body="Found SQL injection vulnerability",
            metadata=metadata,
        )

        messages = manager.get_unread_messages("reviewer")
        assert len(messages) == 1
        assert messages[0].metadata == metadata, "Metadata should be preserved"


def test_mailbox_clear():
    """Test clearing mailbox."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MailboxManager("test_run_8", RunStore(tmpdir))

        # Send multiple messages
        for i in range(3):
            manager.send_message(
                sender_agent_id="agent1",
                receiver_agent_id="agent2",
                subject=f"Msg {i}",
                body=f"Body {i}",
            )

        assert manager.message_count("agent2") == 3

        # Clear mailbox
        manager.clear_mailbox("agent2")
        assert manager.message_count("agent2") == 0
        assert manager.unread_count("agent2") == 0


def test_mailbox_thread_safety():
    """Test mailbox is thread-safe under concurrent access."""
    import threading

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MailboxManager("test_run_9", RunStore(tmpdir))
        errors = []

        def send_messages(agent_id, count):
            """Send messages from agent."""
            try:
                for i in range(count):
                    manager.send_message(
                        sender_agent_id=f"agent_{agent_id}",
                        receiver_agent_id="receiver",
                        subject=f"Msg {i}",
                        body=f"Body {i}",
                    )
            except Exception as e:
                errors.append(e)

        # Create threads to send messages concurrently
        threads = []
        for i in range(5):
            t = threading.Thread(target=send_messages, args=(i, 10))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        assert len(errors) == 0, f"No errors should occur: {errors}"
        assert manager.message_count("receiver") == 50, "Should have 50 total messages"


def test_mailbox_message_ordering():
    """Test messages are ordered by creation time."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MailboxManager("test_run_10", RunStore(tmpdir))

        # Send messages with small delay
        ids = []
        for i in range(3):
            msg_id = manager.send_message(
                sender_agent_id="sender",
                receiver_agent_id="receiver",
                subject=f"Message {i}",
                body=f"Content {i}",
            )
            ids.append(msg_id)
            time.sleep(0.01)  # Small delay to ensure different timestamps

        # Get messages
        messages = manager.get_unread_messages("receiver")
        assert len(messages) == 3

        # Verify ordering by creation time
        for i in range(len(messages) - 1):
            assert messages[i].created_at <= messages[i + 1].created_at


def test_mailbox_nonexistent_agent():
    """Test handling of messages to/from nonexistent agents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MailboxManager("test_run_11", RunStore(tmpdir))

        # Send to nonexistent agent (should still work)
        msg_id = manager.send_message(
            sender_agent_id="agent1",
            receiver_agent_id="agent_unknown",
            subject="Test",
            body="Test",
        )

        assert msg_id is not None, "Should create message ID"

        # Getting mailbox for unknown agent should create it or return empty
        mailbox = manager.get_mailbox("agent_unknown")
        assert mailbox is not None, "Mailbox should be created"
        assert len(mailbox.messages) == 1


if __name__ == "__main__":
    print("Running M5 Mailbox tests...")

    test_mailbox_send_message()
    print("[PASS] Send message test passed")

    test_mailbox_unread_messages()
    print("[PASS] Unread messages test passed")

    test_mailbox_read_message()
    print("[PASS] Read message test passed")

    test_mailbox_message_persistence()
    print("[PASS] Message persistence test passed")

    test_mailbox_load_from_store()
    print("[PASS] Load from store test passed")

    test_mailbox_multiple_agents()
    print("[PASS] Multiple agents test passed")

    test_mailbox_metadata()
    print("[PASS] Metadata test passed")

    test_mailbox_clear()
    print("[PASS] Clear mailbox test passed")

    test_mailbox_thread_safety()
    print("[PASS] Thread safety test passed")

    test_mailbox_message_ordering()
    print("[PASS] Message ordering test passed")

    test_mailbox_nonexistent_agent()
    print("[PASS] Nonexistent agent test passed")

    print("\n[SUCCESS] ALL M5 MAILBOX TESTS PASSED (11/11)")
