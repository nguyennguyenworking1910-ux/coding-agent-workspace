"""Agent communication system for visible coordination."""

import sys
from typing import Dict, List, Optional
from datetime import datetime


class AgentMessage:
    """Represents a message from an agent."""

    def __init__(self, sender: str, message: str, msg_type: str = "info", data: dict = None):
        self.sender = sender
        self.message = message
        self.msg_type = msg_type  # info, decision, finding, warning, error
        self.data = data or {}
        self.timestamp = datetime.now().isoformat()

    def __str__(self):
        icon_map = {
            "info": "[i]",
            "decision": "[*]",
            "finding": "[!]",
            "warning": "[?]",
            "error": "[x]",
        }
        icon = icon_map.get(self.msg_type, "[*]")
        return f"{icon} [{self.sender.upper()}] {self.message}"


class AgentCommunicationChannel:
    """Communication channel for inter-agent messages."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.messages: List[AgentMessage] = []
        self.subscribers: Dict[str, callable] = {}

    def send_message(self, sender: str, message: str, msg_type: str = "info", data: dict = None):
        """Send a message from an agent.

        Args:
            sender: Agent name
            message: Message content
            msg_type: Message type (info, decision, finding, warning, error)
            data: Optional data dict
        """
        msg = AgentMessage(sender, message, msg_type, data)
        self.messages.append(msg)
        self._display_message(msg)
        self._notify_subscribers(msg)

    def _display_message(self, msg: AgentMessage):
        """Display message to stdout."""
        output = str(msg)
        print(output, flush=True)

    def _notify_subscribers(self, msg: AgentMessage):
        """Notify subscribed agents of message."""
        for agent_name, callback in self.subscribers.items():
            if agent_name != msg.sender:
                try:
                    callback(msg)
                except Exception as e:
                    print(f"[ERROR] Subscriber notification failed: {e}", flush=True)

    def subscribe(self, agent_name: str, callback: callable):
        """Subscribe agent to messages.

        Args:
            agent_name: Agent to subscribe
            callback: Function to call on message (receives AgentMessage)
        """
        self.subscribers[agent_name] = callback

    def get_messages(self, sender: Optional[str] = None) -> List[AgentMessage]:
        """Get messages, optionally filtered by sender."""
        if sender:
            return [m for m in self.messages if m.sender == sender]
        return self.messages

    def get_summary(self) -> Dict:
        """Get communication summary."""
        return {
            "run_id": self.run_id,
            "total_messages": len(self.messages),
            "messages": [
                {
                    "timestamp": m.timestamp,
                    "sender": m.sender,
                    "type": m.msg_type,
                    "message": m.message,
                    "data": m.data,
                }
                for m in self.messages
            ],
        }


# Global communication channel (per run)
_channels: Dict[str, AgentCommunicationChannel] = {}


def get_channel(run_id: str) -> AgentCommunicationChannel:
    """Get or create communication channel for a run."""
    if run_id not in _channels:
        _channels[run_id] = AgentCommunicationChannel(run_id)
    return _channels[run_id]


def broadcast_message(run_id: str, sender: str, message: str, msg_type: str = "info", data: dict = None):
    """Broadcast a message to the channel."""
    channel = get_channel(run_id)
    channel.send_message(sender, message, msg_type, data)
