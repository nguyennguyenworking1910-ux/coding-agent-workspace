"""Mailbox management for inter-agent communication."""

import uuid
from typing import Dict, List, Optional
from datetime import datetime
from threading import Lock

from .schemas import AgentMessage, AgentMailbox
from .run_store import RunStore


class MailboxManager:
    """Manages agent mailboxes for inter-agent communication."""

    def __init__(self, run_id: str, store: Optional[RunStore] = None):
        """Initialize mailbox manager.

        Args:
            run_id: Run identifier
            store: Optional RunStore for persistence
        """
        self.run_id = run_id
        self.store = store or RunStore()
        self.mailboxes: Dict[str, AgentMailbox] = {}
        self.lock = Lock()

    def send_message(
        self,
        sender_agent_id: str,
        receiver_agent_id: str,
        subject: str,
        body: str,
        metadata: Optional[Dict] = None,
    ) -> str:
        """Send a message from one agent to another.

        Args:
            sender_agent_id: Sender agent ID
            receiver_agent_id: Receiver agent ID
            subject: Message subject
            body: Message body
            metadata: Optional metadata dict

        Returns:
            Message ID
        """
        message_id = str(uuid.uuid4())[:8]

        message = AgentMessage(
            message_id=message_id,
            run_id=self.run_id,
            sender_agent_id=sender_agent_id,
            receiver_agent_id=receiver_agent_id,
            subject=subject,
            body=body,
            metadata=metadata or {},
        )

        with self.lock:
            # Get or create receiver's mailbox
            if receiver_agent_id not in self.mailboxes:
                self.mailboxes[receiver_agent_id] = AgentMailbox(
                    agent_id=receiver_agent_id,
                    run_id=self.run_id,
                )

            # Add message to mailbox
            self.mailboxes[receiver_agent_id].add_message(message)

        # Persist message
        self.store.append_agent_message(self.run_id, receiver_agent_id, message)

        return message_id

    def get_unread_messages(self, agent_id: str) -> List[AgentMessage]:
        """Get all unread messages for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            List of unread messages
        """
        with self.lock:
            if agent_id not in self.mailboxes:
                return []
            return self.mailboxes[agent_id].get_unread_messages()

    def read_message(self, agent_id: str, message_id: str) -> Optional[AgentMessage]:
        """Mark message as read and return it.

        Args:
            agent_id: Agent ID
            message_id: Message ID

        Returns:
            Message or None if not found
        """
        with self.lock:
            if agent_id not in self.mailboxes:
                return None
            return self.mailboxes[agent_id].read_message(message_id)

    def get_mailbox(self, agent_id: str) -> Optional[AgentMailbox]:
        """Get mailbox for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            AgentMailbox or None
        """
        with self.lock:
            return self.mailboxes.get(agent_id)

    def load_from_store(self) -> None:
        """Load all messages from persistent store."""
        messages = self.store.load_agent_messages(self.run_id)
        with self.lock:
            for message in messages:
                receiver_id = message.receiver_agent_id
                if receiver_id not in self.mailboxes:
                    self.mailboxes[receiver_id] = AgentMailbox(
                        agent_id=receiver_id,
                        run_id=self.run_id,
                    )
                self.mailboxes[receiver_id].add_message(message)

    def clear_mailbox(self, agent_id: str) -> None:
        """Clear all messages from an agent's mailbox.

        Args:
            agent_id: Agent ID
        """
        with self.lock:
            if agent_id in self.mailboxes:
                self.mailboxes[agent_id].clear_messages()

    def get_all_mailboxes(self) -> Dict[str, AgentMailbox]:
        """Get all mailboxes.

        Returns:
            Dictionary of agent_id -> AgentMailbox
        """
        with self.lock:
            return {agent_id: mailbox for agent_id, mailbox in self.mailboxes.items()}

    def message_count(self, agent_id: str) -> int:
        """Get total message count for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            Total message count
        """
        with self.lock:
            if agent_id not in self.mailboxes:
                return 0
            return len(self.mailboxes[agent_id].messages)

    def unread_count(self, agent_id: str) -> int:
        """Get unread message count for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            Unread message count
        """
        with self.lock:
            if agent_id not in self.mailboxes:
                return 0
            return self.mailboxes[agent_id].unread_count
