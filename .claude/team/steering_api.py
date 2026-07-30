"""Live steering API for managing running executions."""

from typing import Optional, List, Dict, Any

from .mailbox_manager import MailboxManager
from .session_manager import SessionManager
from .run_store import RunStore
from .schemas import RunStatus, AgentMessage
from .event_bus import EventBus


class SteeringAPI:
    """Live API for sending messages to agents and controlling execution."""

    def __init__(
        self,
        run_id: str,
        store: RunStore,
        mailbox_mgr: MailboxManager,
        session_mgr: SessionManager,
        event_bus: Optional[EventBus] = None,
    ):
        """Initialize steering API.

        Args:
            run_id: Run identifier
            store: RunStore for persistence
            mailbox_mgr: MailboxManager for messages
            session_mgr: SessionManager for state
            event_bus: Optional EventBus for events
        """
        self.run_id = run_id
        self.store = store
        self.mailbox_mgr = mailbox_mgr
        self.session_mgr = session_mgr
        self.event_bus = event_bus

    def send_message_to_agent(
        self,
        from_agent: str,
        to_agent: str,
        body: str,
        subject: str = "Message",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Send message to an agent.

        Args:
            from_agent: Sender agent ID (or "user" for external messages)
            to_agent: Receiver agent ID
            body: Message body
            subject: Message subject
            metadata: Optional metadata

        Returns:
            Message ID or None if failed
        """
        try:
            message_id = self.mailbox_mgr.send_message(
                sender_agent_id=from_agent,
                receiver_agent_id=to_agent,
                subject=subject,
                body=body,
                metadata=metadata or {},
            )

            # Emit event
            self.session_mgr.emit_session_event(
                "message",
                {
                    "message_id": message_id,
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "subject": subject,
                },
            )

            return message_id
        except Exception as e:
            print(f"[STEERING] Failed to send message: {e}")
            return None

    def get_mailbox(self, agent_id: str) -> List[AgentMessage]:
        """Get mailbox for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            List of messages
        """
        try:
            mailbox = self.mailbox_mgr.get_mailbox(agent_id)
            if mailbox is None:
                return []
            return mailbox.messages
        except Exception as e:
            print(f"[STEERING] Failed to get mailbox: {e}")
            return []

    def get_unread_messages(self, agent_id: str) -> List[AgentMessage]:
        """Get unread messages for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            List of unread messages
        """
        try:
            return self.mailbox_mgr.get_unread_messages(agent_id)
        except Exception as e:
            print(f"[STEERING] Failed to get unread messages: {e}")
            return []

    def read_message(self, agent_id: str, message_id: str) -> Optional[AgentMessage]:
        """Mark message as read and return it.

        Args:
            agent_id: Agent ID
            message_id: Message ID

        Returns:
            Message or None
        """
        try:
            return self.mailbox_mgr.read_message(agent_id, message_id)
        except Exception as e:
            print(f"[STEERING] Failed to read message: {e}")
            return None

    def pause_run(self) -> bool:
        """Pause the current run.

        Returns:
            True if successful
        """
        try:
            status = self.store.load_status(self.run_id)
            if status is None:
                print(f"[STEERING] Run {self.run_id} not found")
                return False

            # Can only pause if running
            if status.status != RunStatus.RUNNING:
                print(f"[STEERING] Cannot pause run with status {status.status}")
                return False

            # Update status to PAUSED
            status.status = RunStatus.PAUSED
            self.store.save_status(self.run_id, status)

            # Emit event
            self.session_mgr.emit_session_event("run_paused", {})

            return True
        except Exception as e:
            print(f"[STEERING] Failed to pause run: {e}")
            return False

    def resume_run(self) -> bool:
        """Resume a paused run.

        Returns:
            True if successful
        """
        try:
            status = self.store.load_status(self.run_id)
            if status is None:
                print(f"[STEERING] Run {self.run_id} not found")
                return False

            # Can only resume if paused
            if status.status != RunStatus.PAUSED:
                print(f"[STEERING] Cannot resume run with status {status.status}")
                return False

            # Update status to RUNNING
            status.status = RunStatus.RUNNING
            self.store.save_status(self.run_id, status)

            # Emit event
            self.session_mgr.emit_session_event("run_resumed", {})

            return True
        except Exception as e:
            print(f"[STEERING] Failed to resume run: {e}")
            return False

    def get_run_status(self) -> Optional[Dict[str, Any]]:
        """Get current run status.

        Returns:
            Status dict or None
        """
        try:
            status = self.store.load_status(self.run_id)
            if status is None:
                return None

            plan = self.store.load_plan(self.run_id)
            completed_tasks = self.session_mgr.get_completed_tasks()

            # Build unread message counts
            mailboxes = self.mailbox_mgr.get_all_mailboxes()
            unread_counts = {
                agent_id: mailbox.unread_count
                for agent_id, mailbox in mailboxes.items()
            }

            return {
                "run_id": self.run_id,
                "current_status": status.status.value,
                "total_tasks": len(plan.tasks) if plan else 0,
                "completed_tasks": len(completed_tasks),
                "pending_tasks": len(plan.tasks) - len(completed_tasks) if plan else 0,
                "agents": len(plan.agents) if plan else 0,
                "unread_messages": unread_counts,
                "created_at": status.created_at.isoformat() if status.created_at else None,
                "started_at": status.started_at.isoformat() if status.started_at else None,
            }
        except Exception as e:
            print(f"[STEERING] Failed to get run status: {e}")
            return None

    def cancel_run(self) -> bool:
        """Cancel a run.

        Returns:
            True if successful
        """
        try:
            status = self.store.load_status(self.run_id)
            if status is None:
                print(f"[STEERING] Run {self.run_id} not found")
                return False

            # Can cancel from most states except completed/failed
            if status.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                print(f"[STEERING] Cannot cancel run with status {status.status}")
                return False

            # Update status to CANCELLED
            status.status = RunStatus.CANCELLED
            self.store.save_status(self.run_id, status)

            # Emit event
            self.session_mgr.emit_session_event("run_cancelled", {})

            return True
        except Exception as e:
            print(f"[STEERING] Failed to cancel run: {e}")
            return False
