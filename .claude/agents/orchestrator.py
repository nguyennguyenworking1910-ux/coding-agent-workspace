"""Orchestrator - Multi-terminal agent execution coordinator."""

import time
import uuid
from datetime import datetime
from typing import Dict, List, Any
from .workspace import Workspace
from tools import get_tool
from config import get_config


class Orchestrator:
    """Coordinates multi-terminal agent execution."""

    def __init__(self, workspace: str = ".claude-workspace"):
        self.workspace = Workspace(workspace)
        self.config = get_config()
        self.trace_id = str(uuid.uuid4())[:8]
        self.logs = []

        self.thought_tool = get_tool("thought")()

    def _log(self, event: str, message: str):
        """Log event.

        Args:
            event: Event type
            message: Event message
        """
        timestamp = datetime.now().isoformat()
        log_entry = f"[{timestamp}] [{event}] {message}"
        self.logs.append(log_entry)

        if self.config.experimental_agent_teams_enabled:
            print(log_entry)

    def execute(
        self,
        title: str,
        description: str,
        subtasks: List[str]
    ) -> Dict[str, Any]:
        """Execute plan with parallel agents.

        Args:
            title: Plan title
            description: Plan description
            subtasks: List of subtasks

        Returns:
            Execution result
        """
        self._log("EXECUTE", f"Starting: {title}")

        # Create job
        job_id = self.workspace.create_job(title, description, subtasks)
        self._log("JOB_CREATED", job_id)

        # Spawn agents
        agents = []
        terminals = []

        for i, subtask in enumerate(subtasks, 1):
            agent_id, agent = self.workspace.spawn_agent(job_id, subtask)
            agents.append(agent)

            terminal = self.workspace.register_terminal(agent_id, job_id, subtask)
            terminals.append(terminal)

            self._log("AGENT_SPAWNED", f"{agent_id} for: {subtask[:40]}...")

            print(f"  Agent {i}: {agent_id}")
            print(f"    Task: {subtask[:60]}...")

        print(f"\nSpawned {len(agents)} agents\n")

        return {
            "job_id": job_id,
            "agents": agents,
            "terminals": terminals,
            "count": len(agents)
        }

    def show_status(self, job_id: str) -> None:
        """Show job status.

        Args:
            job_id: Job ID
        """
        progress = self.workspace.get_job_progress(job_id)

        print(f"Job {job_id} Status:")
        print("=" * 60)

        for agent in progress["agents"]:
            status_mark = {
                "pending": "[WAIT]",
                "running": "[RUN]",
                "completed": "[DONE]",
                "failed": "[FAIL]"
            }.get(agent["status"], "[?]")

            print(f"{status_mark} {agent['id']}: {agent['task'][:50]}...")

        print(f"\nProgress: {progress['completed']}/{progress['total']} completed ({progress['percentage']:.0f}%)\n")

    def wait(self, job_id: str, timeout: int = 3600, interval: int = 5) -> bool:
        """Wait for job completion.

        Args:
            job_id: Job ID
            timeout: Timeout in seconds
            interval: Check interval in seconds

        Returns:
            True if completed, False if timeout
        """
        self._log("WAIT_START", f"Waiting for {job_id}")

        start = time.time()

        while time.time() - start < timeout:
            progress = self.workspace.get_job_progress(job_id)

            if progress["completed"] == progress["total"]:
                self._log("COMPLETE", f"Job {job_id} completed")
                print(f"\n[DONE] All agents completed!\n")
                return True

            status = f"[WAIT] {progress['completed']}/{progress['total']} complete ({progress['percentage']:.0f}%)"
            print(f"\r{status}", end="", flush=True)

            time.sleep(interval)

        self._log("TIMEOUT", f"Job {job_id} timed out")
        print(f"\n[TIMEOUT] Job did not complete within {timeout}s\n")
        return False

    def get_progress(self, job_id: str) -> Dict[str, Any]:
        """Get job progress.

        Args:
            job_id: Job ID

        Returns:
            Progress information
        """
        return self.workspace.get_job_progress(job_id)

    def get_output(self, job_id: str) -> str:
        """Get aggregated job output.

        Args:
            job_id: Job ID

        Returns:
            Aggregated output
        """
        return self.workspace.get_aggregated_output(job_id)

    def send_message(self, from_id: str, to_id: str, message: str, job_id: str) -> None:
        """Send message between agents.

        Args:
            from_id: Sender ID
            to_id: Recipient ID
            message: Message content
            job_id: Job ID
        """
        self.workspace.send_message(from_id, to_id, message, job_id)
        self._log("MESSAGE", f"{from_id} -> {to_id}")

    def broadcast(self, message: str, job_id: str, to_agents: List[str] = None) -> None:
        """Broadcast message to agents.

        Args:
            message: Message content
            job_id: Job ID
            to_agents: Optional list of agent IDs (all if None)
        """
        agents = self.workspace.get_job_agents(job_id)

        if to_agents:
            agents = [a for a in agents if a["id"] in to_agents]

        for agent in agents:
            self.workspace.send_message("orchestrator", agent["id"], message, job_id)

        self._log("BROADCAST", f"Message sent to {len(agents)} agents")

    def mark_started(self, agent_id: str, terminal_id: str = None) -> None:
        """Mark agent as started.

        Args:
            agent_id: Agent ID
            terminal_id: Optional terminal ID
        """
        self.workspace.update_agent(
            agent_id,
            status="running",
            started_at=datetime.now().isoformat()
        )
        self.workspace.update_terminal(
            agent_id,
            status="running",
            started_at=datetime.now().isoformat()
        )

    def mark_completed(self, agent_id: str, result: str = None, tokens: Dict = None) -> None:
        """Mark agent as completed.

        Args:
            agent_id: Agent ID
            result: Optional result
            tokens: Optional token usage
        """
        update = {
            "status": "completed",
            "completed_at": datetime.now().isoformat()
        }

        if result:
            update["result"] = result

        if tokens:
            update["tokens"] = tokens

        self.workspace.update_agent(agent_id, **update)
        self.workspace.update_terminal(
            agent_id,
            status="completed",
            completed_at=datetime.now().isoformat()
        )

    def mark_failed(self, agent_id: str, error: str) -> None:
        """Mark agent as failed.

        Args:
            agent_id: Agent ID
            error: Error message
        """
        self.workspace.update_agent(
            agent_id,
            status="failed",
            error=error,
            completed_at=datetime.now().isoformat()
        )
        self.workspace.update_terminal(
            agent_id,
            status="failed",
            completed_at=datetime.now().isoformat()
        )
