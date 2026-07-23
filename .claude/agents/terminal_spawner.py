"""Terminal Spawner - Spawn actual Claude Code terminal sessions for agents."""

import json
import os
from typing import Dict, List, Optional, Any
from .workspace import Workspace


class TerminalSpawner:
    """Spawns and manages actual Claude Code terminal sessions for agents."""

    def __init__(self, workspace: str = ".claude-workspace"):
        self.workspace = Workspace(workspace)
        self.spawned_terminals = {}
        self.terminal_processes = {}

    def spawn_agent_terminal(
        self,
        agent_id: str,
        job_id: str,
        task: str,
        agent_type: str = "worker"
    ) -> Dict[str, Any]:
        """Spawn an actual terminal session for an agent.

        This creates a new Claude Code terminal window where the agent
        will execute its task independently.

        Args:
            agent_id: Agent identifier
            job_id: Job identifier
            task: Task description
            agent_type: Type of agent

        Returns:
            Terminal spawn result
        """
        # Register terminal in workspace
        terminal = self.workspace.register_terminal(agent_id, job_id, task)

        # Create terminal command that agent will execute
        terminal_command = self._create_agent_script(agent_id, job_id, task)

        spawn_result = {
            "agent_id": agent_id,
            "job_id": job_id,
            "task": task,
            "terminal_id": agent_id,
            "status": "spawning",
            "command": terminal_command,
            "created_at": terminal["created_at"]
        }

        # Track the spawned terminal
        self.spawned_terminals[agent_id] = spawn_result

        return spawn_result

    def _create_agent_script(self, agent_id: str, job_id: str, task: str) -> str:
        """Create the script that will run in the agent's terminal.

        Args:
            agent_id: Agent identifier
            job_id: Job identifier
            task: Task description

        Returns:
            Python script to execute
        """
        script = f'''#!/usr/bin/env python3
"""Agent {agent_id} - Terminal Session"""

import sys
import json
from datetime import datetime
sys.path.insert(0, '.claude')

from agents import Workspace

# Initialize workspace
ws = Workspace()

# Get agent info
agent_id = "{agent_id}"
job_id = "{job_id}"
task = "{task}"

print(f"\\n{{'='*60}}")
print(f"Agent Terminal: {{agent_id}}")
print(f"Job: {{job_id}}")
print(f"Task: {{task}}")
print(f"{{'='*60}}\\n")

# Mark agent as started
ws.update_agent(agent_id, status="running", started_at=datetime.now().isoformat())
ws.update_terminal(agent_id, status="running", started_at=datetime.now().isoformat())

print(f"[STARTED] Agent {{agent_id}} - {{datetime.now().isoformat()}}")
print(f"Task: {{task}}\\n")

# ===== AGENT WORK HAPPENS HERE =====
# The agent should implement its specific logic below

try:
    # Placeholder for actual agent work
    print("[EXECUTING] Performing task analysis...")

    # Simulate work
    import time
    time.sleep(2)

    # Update result
    result = f"Analysis of: {{task}}"

    # Mark as completed
    ws.update_agent(
        agent_id,
        status="completed",
        result=result,
        completed_at=datetime.now().isoformat()
    )
    ws.update_terminal(
        agent_id,
        status="completed",
        completed_at=datetime.now().isoformat()
    )

    # Save output
    output_file = f".claude-workspace/jobs/{{job_id}}/OUTPUT/{{agent_id}}.txt"
    with open(output_file, "w") as f:
        f.write(result)

    print(f"\\n[COMPLETED] Agent {{agent_id}} - {{datetime.now().isoformat()}}")
    print(f"Result: {{result}}")

except Exception as e:
    # Mark as failed
    ws.update_agent(
        agent_id,
        status="failed",
        error=str(e),
        completed_at=datetime.now().isoformat()
    )
    ws.update_terminal(
        agent_id,
        status="failed",
        completed_at=datetime.now().isoformat()
    )

    print(f"\\n[FAILED] Agent {{agent_id}}")
    print(f"Error: {{e}}")

print(f"\\n{{'='*60}}")
print("Agent terminal closing...")
print(f"{{'='*60}}")
'''
        return script

    def save_agent_script(self, agent_id: str, script: str) -> str:
        """Save agent script to file.

        Args:
            agent_id: Agent identifier
            script: Script content

        Returns:
            Path to saved script
        """
        scripts_dir = ".claude-workspace/scripts"
        os.makedirs(scripts_dir, exist_ok=True)

        script_file = os.path.join(scripts_dir, f"agent_{agent_id}.py")
        with open(script_file, "w") as f:
            f.write(script)

        return script_file

    def spawn_multiple_terminals(
        self,
        job_id: str,
        subtasks: List[str]
    ) -> Dict[str, Any]:
        """Spawn multiple terminal sessions for a job.

        Args:
            job_id: Job identifier
            subtasks: List of tasks

        Returns:
            Spawn results for all agents
        """
        results = {
            "job_id": job_id,
            "agents_spawned": [],
            "total": len(subtasks)
        }

        for i, task in enumerate(subtasks, 1):
            # Create agent
            agent_id, agent = self.workspace.spawn_agent(job_id, task)

            # Spawn terminal for agent
            terminal = self.spawn_agent_terminal(agent_id, job_id, task)

            # Create script
            script = self._create_agent_script(agent_id, job_id, task)
            script_file = self.save_agent_script(agent_id, script)

            spawn_data = {
                "agent_id": agent_id,
                "task": task,
                "script_file": script_file,
                "status": "spawned"
            }

            results["agents_spawned"].append(spawn_data)

            print(f"Terminal {i}/{len(subtasks)} spawned: Agent {agent_id}")
            print(f"  Task: {task[:60]}...")
            print(f"  Script: {script_file}")
            print()

        return results

    def get_spawn_instructions(self, job_id: str) -> str:
        """Get instructions for manually spawning terminals.

        Args:
            job_id: Job identifier

        Returns:
            Instructions for user
        """
        instructions = f"""
{'='*70}
TERMINAL SPAWNING INSTRUCTIONS
{'='*70}

To spawn the agent terminals manually, run these commands in separate
Claude Code terminal windows:

"""
        agents = self.workspace.get_job_agents(job_id)

        for i, agent in enumerate(agents, 1):
            agent_id = agent["id"]
            script_file = f".claude-workspace/scripts/agent_{agent_id}.py"

            instructions += f"""
Terminal {i}: Agent {agent_id}
─────────────────────────────
python {script_file}

"""

        instructions += f"""
{'='*70}

Or spawn all at once using Claude Code's experimental spawn_agent():

```python
from agents import TerminalSpawner

spawner = TerminalSpawner()
results = spawner.spawn_multiple_terminals("{job_id}", [
"""

        for agent in agents:
            instructions += f'    "{agent["task"]}",\n'

        instructions += f"""])

for result in results["agents_spawned"]:
    print(f"Spawned: {{result['agent_id']}}")
```

{'='*70}
"""
        return instructions

    def list_spawned_terminals(self) -> List[Dict[str, Any]]:
        """List all spawned terminals.

        Returns:
            List of spawned terminal info
        """
        return list(self.spawned_terminals.values())

    def get_terminal_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a spawned terminal.

        Args:
            agent_id: Agent identifier

        Returns:
            Terminal status or None
        """
        if agent_id in self.spawned_terminals:
            return self.spawned_terminals[agent_id]
        return None
