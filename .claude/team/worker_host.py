"""Worker host interface for running agents."""

from typing import Optional, Callable
from .schemas import AgentTask, AgentEvent


class WorkerHost:
    """Base class for worker execution hosts."""

    def __init__(self, agent_id: str, task: AgentTask, on_event: Optional[Callable] = None):
        self.agent_id = agent_id
        self.task = task
        self.on_event = on_event or (lambda e: None)

    def start(self) -> None:
        """Start the worker."""
        raise NotImplementedError

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for worker to complete."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stop the worker gracefully."""
        raise NotImplementedError
