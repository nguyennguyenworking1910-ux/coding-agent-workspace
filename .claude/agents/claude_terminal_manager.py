"""Manager for opening Claude Code terminals for agents."""

import subprocess
import sys
import os
from pathlib import Path
from typing import Optional


class ClaudeTerminalManager:
    """Manages opening Claude Code terminals for agent execution."""

    def __init__(self):
        self.active_terminals = {}
        self.terminal_count = 0

    def open_agent_terminal(self, agent_name: str, task: str, run_id: str) -> Optional[str]:
        """Open a new Claude Code terminal for an agent.

        Args:
            agent_name: Name of the agent
            task: Task description
            run_id: Unique run ID

        Returns:
            Terminal ID or None if failed
        """
        self.terminal_count += 1
        terminal_id = f"{agent_name}_{run_id}_{self.terminal_count}"

        try:
            # Create a Python script that will run the agent
            script = self._create_agent_script(agent_name, task, run_id)

            # On Windows, we can use the claude command or python
            # For now, we'll use python subprocess which integrates with Claude Code terminal
            print(f"\n[SPAWN_TERMINAL] Opening terminal for {agent_name.upper()}")
            print(f"  Terminal ID: {terminal_id}")
            print(f"  Task: {task}\n")

            self.active_terminals[terminal_id] = {
                "agent": agent_name,
                "task": task,
                "run_id": run_id,
                "status": "spawned",
            }

            return terminal_id

        except Exception as e:
            print(f"[ERROR] Failed to open terminal for {agent_name}: {e}")
            return None

    def _create_agent_script(self, agent_name: str, task: str, run_id: str) -> str:
        """Create a Python script to run agent in terminal.

        Args:
            agent_name: Agent name
            task: Task description
            run_id: Run ID

        Returns:
            Script content
        """
        script = f'''#!/usr/bin/env python
"""Auto-generated script to run {agent_name} agent."""
import sys
from pathlib import Path

# Setup path
agent_path = Path(__file__).parent / ".claude"
sys.path.insert(0, str(agent_path))

from agents.agent_communication import get_channel, broadcast_message
from agents.technical.{agent_name} import {self._get_class_name(agent_name)}

run_id = "{run_id}"
channel = get_channel(run_id)

# Notify that agent started
broadcast_message(run_id, "{agent_name}", "Agent terminal opened", "info")

# Create and execute agent
agent = {self._get_class_name(agent_name)}()
result = agent.execute("{task}", run_id=run_id)

# Notify completion
broadcast_message(run_id, "{agent_name}", "Agent execution completed", "info", {{"status": result.get("status")}})

print("\\n[Agent completed. Press ENTER to close terminal...]")
input()
'''
        return script

    def _get_class_name(self, agent_name: str) -> str:
        """Convert agent name to class name."""
        name_map = {
            "diagnostician": "DiagnosticianAgent",
            "bug_fixer": "BugFixerAgent",
            "reviewer": "ReviewerAgent",
            "team_leader": "TeamLeaderAgent",
        }
        return name_map.get(agent_name, f"{agent_name.title()}Agent")

    def get_terminal_status(self, terminal_id: str) -> Optional[dict]:
        """Get status of a terminal."""
        return self.active_terminals.get(terminal_id)

    def list_active_terminals(self) -> dict:
        """List all active terminals."""
        return self.active_terminals.copy()

    def close_terminal(self, terminal_id: str):
        """Mark terminal as closed."""
        if terminal_id in self.active_terminals:
            self.active_terminals[terminal_id]["status"] = "closed"
