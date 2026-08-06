"""Event bus for publish/subscribe coordination."""

from typing import Callable, Dict, List
from .schemas import AgentEvent
import threading


class EventBus:
    """Publish/subscribe event system for inter-agent communication."""

    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.all_type_subscribers: List[Callable] = []
        self.lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable[[AgentEvent], None]) -> None:
        """Subscribe callback to specific event type."""
        with self.lock:
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            self.subscribers[event_type].append(callback)

    def subscribe_all(self, callback: Callable[[AgentEvent], None]) -> None:
        """Subscribe callback to all event types."""
        with self.lock:
            self.all_type_subscribers.append(callback)

    def publish(self, event: AgentEvent) -> None:
        """Publish event to subscribers of that type and all-type subscribers."""
        with self.lock:
            type_callbacks = self.subscribers.get(event.event_type, [])
            all_callbacks = self.all_type_subscribers.copy()

        # Call type-specific subscribers
        for callback in type_callbacks:
            try:
                callback(event)
            except Exception as e:
                print(f"Error in event callback: {e}")

        # Call all-type subscribers
        for callback in all_callbacks:
            try:
                callback(event)
            except Exception as e:
                print(f"Error in all-type callback: {e}")

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Unsubscribe callback from event type."""
        with self.lock:
            if event_type in self.subscribers:
                self.subscribers[event_type] = [
                    cb for cb in self.subscribers[event_type] if cb != callback
                ]

    def unsubscribe_all(self, callback: Callable) -> None:
        """Unsubscribe callback from all events."""
        with self.lock:
            self.all_type_subscribers = [cb for cb in self.all_type_subscribers if cb != callback]
