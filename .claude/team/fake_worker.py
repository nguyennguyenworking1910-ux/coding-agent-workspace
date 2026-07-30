"""Fake worker for testing concurrent execution in Milestone 1."""

import time
import threading
import uuid
from typing import Optional, Callable
from datetime import datetime
from .schemas import AgentTask, AgentEvent


class FakeWorker:
    """Simulates a worker agent for Milestone 1 testing."""

    def __init__(
        self,
        agent_id: str,
        task: AgentTask,
        run_id: str,
        delay_seconds: float = 0.5,
        fail: bool = False,
        on_event: Optional[Callable[[AgentEvent], None]] = None,
    ):
        self.agent_id = agent_id
        self.task = task
        self.run_id = run_id
        self.delay_seconds = delay_seconds
        self.fail = fail
        self.on_event = on_event or (lambda e: None)
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start worker in background thread."""
        self.thread = threading.Thread(target=self._execute, daemon=True)
        self.thread.start()

    def _execute(self) -> None:
        """Simulate work: emit started event, delay, emit completed/failed."""
        # Emit started
        self.on_event(
            AgentEvent(
                event_id=str(uuid.uuid4()),
                run_id=self.run_id,
                agent_id=self.agent_id,
                task_id=self.task.task_id,
                timestamp=datetime.utcnow().isoformat(),
                event_type="agent_started",
                payload={"task_id": self.task.task_id, "title": self.task.title},
            )
        )

        # Simulate work
        time.sleep(self.delay_seconds)

        # Emit progress
        self.on_event(
            AgentEvent(
                event_id=str(uuid.uuid4()),
                run_id=self.run_id,
                agent_id=self.agent_id,
                task_id=self.task.task_id,
                timestamp=datetime.utcnow().isoformat(),
                event_type="progress",
                payload={"message": f"Executing {self.task.title}"},
            )
        )

        # Emit completed or failed
        if self.fail:
            self.on_event(
                AgentEvent(
                    event_id=str(uuid.uuid4()),
                    run_id=self.run_id,
                    agent_id=self.agent_id,
                    task_id=self.task.task_id,
                    timestamp=datetime.utcnow().isoformat(),
                    event_type="task_failed",
                    payload={"error": "Simulated failure"},
                )
            )
        else:
            self.on_event(
                AgentEvent(
                    event_id=str(uuid.uuid4()),
                    run_id=self.run_id,
                    agent_id=self.agent_id,
                    task_id=self.task.task_id,
                    timestamp=datetime.utcnow().isoformat(),
                    event_type="task_completed",
                    payload={"result": f"Task {self.task.task_id} complete"},
                )
            )

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for worker to finish; return True if completed."""
        if self.thread:
            self.thread.join(timeout=timeout)
            return not self.thread.is_alive()
        return False
