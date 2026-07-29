"""Terminal Manager - Spawns and manages separate terminals for agents."""

import subprocess
import sys
import platform
import time
from pathlib import Path
from typing import Dict, Optional


class TerminalManager:
    """Manages separate terminals for agent execution."""

    def __init__(self):
        self.system = platform.system()
        self.terminals: Dict[str, subprocess.Popen] = {}
        self.project_root = Path(__file__).parent.parent.parent
        self.agent_scripts_dir = self.project_root / ".claude" / "agent_runners"
        self.agent_scripts_dir.mkdir(exist_ok=True)

    def create_agent_runner(self, agent_name: str, task: str, run_id: str) -> Path:
        """Create a temporary script to run an agent in a terminal.

        Args:
            agent_name: Name of the agent (diagnostician, bug_fixer, reviewer)
            task: Task description
            run_id: Unique run ID for tracking

        Returns:
            Path to the created script
        """
        script_path = self.agent_scripts_dir / f"{agent_name}_{run_id}.py"

        script_content = f'''"""Agent runner script - executed in separate terminal."""

import sys
from pathlib import Path

# Add .claude to path
claude_path = Path(__file__).parent.parent
sys.path.insert(0, str(claude_path))

from agents.technical import get_technical_agent
from config import get_config

agent_class = get_technical_agent("{agent_name}")
if not agent_class:
    print(f"ERROR: Agent '{agent_name}' not found")
    sys.exit(1)

print(f"\\n{'='*70}")
print(f"AGENT: {agent_name.upper()}")
print(f"RUN ID: {run_id}")
print(f"TASK: {task}")
print(f"{'='*70}\\n")

try:
    agent = agent_class()
    result = agent.execute("{task}")

    print(f"\\n{'-'*70}")
    print(f"RESULT: SUCCESS")
    print(f"{'-'*70}")
    print(f"Status: {{result.get('status', 'unknown')}}")
    print(f"Tools used: {{', '.join(result.get('tools_used', []))}}")

    if result.get('thinking'):
        print(f"\\nThinking Process:")
        print(f"{{result.get('thinking')}}")

    print(f"\\n[Agent {agent_name} completed. Press Enter to close...]")
    input()

except Exception as e:
    print(f"\\nERROR: {{e}}")
    print(f"[Press Enter to close...]")
    input()
'''

        script_path.write_text(script_content)
        return script_path

    def spawn_terminal_windows(self, agent_name: str, task: str, run_id: str) -> bool:
        """Spawn a new terminal window on Windows."""
        script_path = self.create_agent_runner(agent_name, task, run_id)

        try:
            # Windows: Use start command to open new cmd window
            cmd = f'start cmd /k "cd {self.project_root} && python {script_path}"'
            subprocess.Popen(cmd, shell=True)
            self.terminals[agent_name] = True
            print(f"✓ Terminal spawned for {agent_name}: {script_path}")
            return True
        except Exception as e:
            print(f"✗ Failed to spawn terminal for {agent_name}: {e}")
            return False

    def spawn_terminal_unix(self, agent_name: str, task: str, run_id: str) -> bool:
        """Spawn a new terminal window on Unix/Linux/Mac."""
        script_path = self.create_agent_runner(agent_name, task, run_id)

        try:
            if self.system == "Darwin":  # macOS
                cmd = f'open -a Terminal {script_path}'
            else:  # Linux
                cmd = f'gnome-terminal -- bash -c "cd {self.project_root} && python {script_path}; bash"'

            subprocess.Popen(cmd, shell=True)
            self.terminals[agent_name] = True
            print(f"✓ Terminal spawned for {agent_name}: {script_path}")
            return True
        except Exception as e:
            print(f"✗ Failed to spawn terminal for {agent_name}: {e}")
            return False

    def spawn_terminal(self, agent_name: str, task: str, run_id: str) -> bool:
        """Spawn a new terminal for an agent (cross-platform).

        Args:
            agent_name: Name of the agent
            task: Task description
            run_id: Unique run ID

        Returns:
            True if successful, False otherwise
        """
        if self.system == "Windows":
            return self.spawn_terminal_windows(agent_name, task, run_id)
        else:
            return self.spawn_terminal_unix(agent_name, task, run_id)

    def wait_for_agent(self, agent_name: str, timeout: int = 300) -> bool:
        """Wait for an agent to complete (timeout in seconds).

        Args:
            agent_name: Name of the agent
            timeout: Max seconds to wait

        Returns:
            True if agent completed, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if agent_name not in self.terminals:
                return False
            time.sleep(1)
        return False

    def cleanup(self):
        """Clean up temporary scripts."""
        for script in self.agent_scripts_dir.glob("*.py"):
            try:
                script.unlink()
            except Exception as e:
                print(f"Warning: Could not delete {script}: {e}")
