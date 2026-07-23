"""Enhanced Orchestrator - With actual terminal spawning support."""

import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from .workspace import Workspace
from .orchestrator import Orchestrator
from .terminal_spawner import TerminalSpawner
from tools import get_tool
from config import get_config


class OrchestratorWithTerminals(Orchestrator):
    """Orchestrator with actual Claude Code terminal spawning."""

    def __init__(self, workspace: str = ".claude-workspace", spawn_terminals: bool = False):
        super().__init__(workspace)
        self.spawn_terminals = spawn_terminals
        self.terminal_spawner = TerminalSpawner(workspace)

    def execute(
        self,
        title: str,
        description: str,
        subtasks: List[str],
        spawn_actual_terminals: bool = None
    ) -> Dict[str, Any]:
        """Execute plan with optional actual terminal spawning.

        Args:
            title: Plan title
            description: Plan description
            subtasks: List of subtasks
            spawn_actual_terminals: Override default terminal spawning behavior

        Returns:
            Execution result
        """
        use_terminals = spawn_actual_terminals if spawn_actual_terminals is not None else self.spawn_terminals

        self._log("EXECUTE", f"Starting: {title}")

        # Create job
        job_id = self.workspace.create_job(title, description, subtasks)
        self._log("JOB_CREATED", job_id)
        print(f"[TARGET] Job created: {job_id}\n")

        if use_terminals:
            # Spawn actual terminals
            return self._execute_with_terminals(job_id, title, subtasks)
        else:
            # Use file-based coordination (original behavior)
            return super().execute(title, description, subtasks)

    def _execute_with_terminals(self, job_id: str, title: str, subtasks: List[str]) -> Dict[str, Any]:
        """Execute with actual terminal spawning.

        Args:
            job_id: Job identifier
            title: Plan title
            subtasks: List of subtasks

        Returns:
            Execution result
        """
        print(f"[TERMINALS] Spawning actual terminal sessions...\n")

        # Spawn multiple terminals
        spawn_results = self.terminal_spawner.spawn_multiple_terminals(job_id, subtasks)

        terminals = []
        agents = []

        for spawn_data in spawn_results["agents_spawned"]:
            agent_id = spawn_data["agent_id"]
            agent = self.workspace.get_agent(agent_id)
            agents.append(agent)

            terminal = self.workspace.get_terminal(agent_id)
            terminals.append(terminal)

            self._log("AGENT_SPAWNED", f"Agent spawned: {agent_id}")

        print(f"[TERMINALS] Spawned {len(agents)} terminal sessions in parallel\n")

        # Store instructions in result but don't print (encoding issues on Windows)
        instructions = self.terminal_spawner.get_spawn_instructions(job_id)

        # Show status
        self.show_terminal_status(job_id)

        return {
            "success": True,
            "job_id": job_id,
            "title": title,
            "agents": agents,
            "terminals": terminals,
            "count": len(agents),
            "status": "terminals_spawned_waiting_execution",
            "spawn_mode": "actual_terminals",
            "instructions": instructions,
            "trace_id": self.trace_id if self.config.experimental_agent_teams_enabled else None
        }

    def show_terminal_status(self, job_id: str):
        """Show detailed terminal status.

        Args:
            job_id: Job identifier
        """
        print(f"[STATUS] Terminal Status for {job_id}")
        print("=" * 70)

        agents = self.workspace.get_job_agents(job_id)
        terminals = self.workspace.get_job_terminals(job_id)

        for i, agent in enumerate(agents, 1):
            agent_id = agent["id"]
            status = agent["status"]

            # Find corresponding terminal
            terminal = next((t for t in terminals if t["agent_id"] == agent_id), None)

            status_icon = {
                "pending": "[WAIT]",
                "running": "[RUN]",
                "completed": "[DONE]",
                "failed": "[FAIL]"
            }.get(status, "[?]")

            print(f"{i}. {status_icon} agent-{agent_id}")
            print(f"   Task: {agent['task'][:60]}...")
            print(f"   Status: {status}")

            if terminal and terminal.get("started_at"):
                print(f"   Started: {terminal['started_at'][:19]}")

            print()

    def execute_and_monitor(
        self,
        title: str,
        description: str,
        subtasks: List[str],
        spawn_actual_terminals: bool = True,
        auto_wait: bool = True,
        timeout: int = 3600
    ) -> Dict[str, Any]:
        """Execute plan with terminals and optionally wait for completion.

        Args:
            title: Plan title
            description: Plan description
            subtasks: List of subtasks
            spawn_actual_terminals: Whether to spawn actual terminals
            auto_wait: Whether to wait for completion
            timeout: Timeout in seconds

        Returns:
            Execution result with completion status
        """
        # Execute with terminals
        result = self.execute(
            title,
            description,
            subtasks,
            spawn_actual_terminals=spawn_actual_terminals
        )

        job_id = result["job_id"]

        if auto_wait and result.get("spawn_mode") == "actual_terminals":
            print("\n" + "=" * 70)
            print("MONITORING TERMINALS...")
            print("=" * 70 + "\n")

            # Wait for completion
            completed = self.wait(job_id, timeout=timeout)

            if completed:
                progress = self.get_progress(job_id)
                print(f"\n[DONE] All terminals completed!")
                print(f"Results: {progress['completed']}/{progress['total']} agents\n")

            result["auto_waited"] = True
            result["completion_status"] = "completed" if completed else "timeout"

        return result

    def spawn_single_terminal(
        self,
        job_id: str,
        task: str,
        agent_type: str = "worker"
    ) -> Dict[str, Any]:
        """Spawn a single agent terminal.

        Args:
            job_id: Job identifier
            task: Task description
            agent_type: Agent type

        Returns:
            Spawn result
        """
        # Create agent
        agent_id, agent = self.workspace.spawn_agent(job_id, task, agent_type)

        # Spawn terminal
        terminal = self.terminal_spawner.spawn_agent_terminal(
            agent_id,
            job_id,
            task,
            agent_type
        )

        # Create script
        script = self.terminal_spawner._create_agent_script(agent_id, job_id, task)
        script_file = self.terminal_spawner.save_agent_script(agent_id, script)

        self._log("TERMINAL_SPAWNED", f"Single terminal spawned: {agent_id}")

        return {
            "agent_id": agent_id,
            "job_id": job_id,
            "task": task,
            "script_file": script_file,
            "terminal_id": agent_id,
            "status": "spawned"
        }

    def show_spawn_commands(self, job_id: str) -> str:
        """Show individual spawn commands for each agent terminal.

        Args:
            job_id: Job identifier

        Returns:
            Spawn commands
        """
        commands = f"\n{'='*70}\n"
        commands += "SPAWN COMMANDS - Copy and run in separate terminals\n"
        commands += f"{'='*70}\n\n"

        agents = self.workspace.get_job_agents(job_id)

        for i, agent in enumerate(agents, 1):
            agent_id = agent["id"]
            script_file = f".claude-workspace/scripts/agent_{agent_id}.py"

            commands += f"Terminal {i}:\n"
            commands += f"python {script_file}\n\n"

        commands += f"{'='*70}\n"
        return commands
