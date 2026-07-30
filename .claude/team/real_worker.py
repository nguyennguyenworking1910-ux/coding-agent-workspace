"""Real Claude worker using subprocess runner."""

import threading
from typing import Optional, Callable, Dict, Any

from .schemas import AgentTask
from .claude_runner import ClaudeRunner


class RealWorker:
    """Executes a task using real Claude Code subprocess."""

    def __init__(
        self,
        agent_id: str,
        task: AgentTask,
        run_id: str,
        cwd: Optional[str] = None,
        timeout: float = 300.0,
        on_event: Optional[Callable] = None,
    ):
        """Initialize real worker.

        Args:
            agent_id: Agent identifier
            task: Task to execute
            run_id: Run identifier
            cwd: Working directory
            timeout: Timeout in seconds
            on_event: Event callback
        """
        self.agent_id = agent_id
        self.task = task
        self.run_id = run_id
        self.cwd = cwd
        self.timeout = timeout
        self.on_event = on_event or (lambda e: None)

        self.runner = ClaudeRunner(
            agent_id=agent_id,
            task_id=task.task_id,
            run_id=run_id,
            cwd=cwd,
            timeout=timeout,
            on_event=self.on_event,
        )

        self.thread: Optional[threading.Thread] = None
        self.success = False

    def start(self) -> None:
        """Start worker in background thread."""
        self.thread = threading.Thread(target=self._execute, daemon=True)
        self.thread.start()

    def _execute(self) -> None:
        """Execute the task."""
        # System prompt for the worker
        system_prompt = f"""You are a {self.agent_id.title()} agent in a multi-agent system.
Your objective is: {next((a.objective for a in []), "Complete your assigned task")}
You are read-only - do not modify files.
Respond with clear findings and analysis."""

        # Run the task
        self.success = self.runner.run(
            prompt=self.task.instructions,
            system_prompt=system_prompt,
        )

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for worker to complete.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            True if completed successfully
        """
        if self.thread:
            self.thread.join(timeout=timeout)
            return not self.thread.is_alive()
        return False

    def get_result(self) -> Optional[str]:
        """Get the task result."""
        return self.runner.get_result()

    def get_metadata(self) -> Dict[str, Any]:
        """Get execution metadata."""
        return self.runner.get_metadata()
