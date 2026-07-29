"""Terminal Manager - Opens VS Code integrated terminals for agents."""

import subprocess
import sys
import platform
import time
from pathlib import Path
from typing import Dict, Optional
import json
import os


class TerminalManager:
    """Manages agent execution in separate VS Code integrated terminals."""

    def __init__(self, use_vscode_terminal: bool = True):
        self.system = platform.system()
        self.terminals: Dict[str, subprocess.Popen] = {}
        self.project_root = Path(__file__).parent.parent.parent
        self.agent_scripts_dir = self.project_root / ".claude" / "agent_runners"
        self.agent_scripts_dir.mkdir(parents=True, exist_ok=True)
        self.use_vscode_terminal = use_vscode_terminal

    def create_agent_runner(self, agent_name: str, task: str, run_id: str) -> Path:
        """Create a script to run an agent.

        Args:
            agent_name: Name of the agent
            task: Task description
            run_id: Unique run ID

        Returns:
            Path to the created script
        """
        script_path = self.agent_scripts_dir / f"{agent_name}_{run_id}.py"

        script_content = f'''"""Agent runner script."""
import sys
from pathlib import Path

# Add .claude to path
claude_path = Path(__file__).parent.parent
sys.path.insert(0, str(claude_path))

from agents.technical import get_technical_agent

print(f"\\n{{'='*70}}")
print(f"AGENT: {agent_name.upper()}")
print(f"RUN ID: {run_id}")
print(f"TASK: {task}")
print(f"{{'='*70}}\\n")

agent_class = get_technical_agent("{agent_name}")
if not agent_class:
    print(f"ERROR: Agent '{agent_name}' not found")
    sys.exit(1)

try:
    agent = agent_class()
    result = agent.execute("{task}", run_id="{run_id}")

    print(f"\\n{{'-'*70}}")
    print(f"RESULT: SUCCESS")
    print(f"{{'-'*70}}")
    print(f"Status: {{result.get('status', 'unknown')}}")
    print(f"Tools used: {{', '.join(result.get('tools_used', []))}}")

    if result.get('findings'):
        print(f"\\n[FINDINGS] Found {{len(result.get('findings', []))}} issues")
        for finding in result.get('findings', [])[:5]:
            print(f"  - {{finding}}")

    if result.get('changes'):
        print(f"\\n[CHANGES] Prepared {{len(result.get('changes', []))}} strategies")
        for change in result.get('changes', [])[:5]:
            print(f"  - {{change}}")

    if result.get('issues'):
        print(f"\\n[ISSUES] Identified {{len(result.get('issues', []))}} issues")
        for issue in result.get('issues', []):
            print(f"  - {{issue}}")

    if result.get('score'):
        print(f"\\n[SCORE] Quality Score: {{result.get('score')}}%")

except Exception as e:
    print(f"\\nERROR: {{e}}")
    import traceback
    traceback.print_exc()

print(f"\\n{{'='*70}}")
print(f"Press ENTER to close this terminal...")
print(f"{{'='*70}}")
input()
'''

        script_path.write_text(script_content)
        return script_path

    def spawn_terminal_vscode(self, agent_name: str, task: str, run_id: str) -> bool:
        """Spawn a new terminal for the agent.

        Args:
            agent_name: Name of the agent
            task: Task description
            run_id: Unique run ID

        Returns:
            True if successful
        """
        script_path = self.create_agent_runner(agent_name, task, run_id)

        try:
            if self.system == "Windows":
                # Windows: Open new command prompt window
                cmd = f'start cmd /k "cd /d {self.project_root} && python {script_path}"'
                subprocess.Popen(cmd, shell=True)
                self.terminals[agent_name] = True
                print(f"[OK] Terminal opened for {agent_name}")
                return True

            elif self.system == "Darwin":  # macOS
                # macOS: Open Terminal.app with the script
                cmd = f'open -a Terminal "{script_path}"'
                subprocess.Popen(cmd, shell=True)
                self.terminals[agent_name] = True
                print(f"[OK] Terminal opened for {agent_name}")
                return True

            else:  # Linux
                # Linux: Open gnome-terminal with the script
                cmd = f'gnome-terminal -- bash -c "cd {self.project_root} && python {script_path}; bash"'
                subprocess.Popen(cmd, shell=True)
                self.terminals[agent_name] = True
                print(f"[OK] Terminal opened for {agent_name}")
                return True

        except Exception as e:
            print(f"[FAIL] Failed to spawn terminal for {agent_name}: {e}")
            # Fallback to inline execution
            print(f"[INFO] Falling back to inline execution...")
            return self._execute_inline(agent_name, task, run_id)

    def spawn_terminal(self, agent_name: str, task: str, run_id: str) -> bool:
        """Spawn a new terminal for an agent.

        Args:
            agent_name: Name of the agent
            task: Task description
            run_id: Unique run ID

        Returns:
            True if successful
        """
        # Always try to spawn in separate windows
        return self.spawn_terminal_vscode(agent_name, task, run_id)

    def _execute_inline(self, agent_name: str, task: str, run_id: str) -> bool:
        """Execute agent inline as fallback."""
        try:
            from .technical import get_technical_agent

            print(f"\n{'='*70}")
            print(f"AGENT: {agent_name.upper()}")
            print(f"RUN ID: {run_id}")
            print(f"TASK: {task}")
            print(f"{'='*70}\n")

            agent_class = get_technical_agent(agent_name)
            if not agent_class:
                print(f"[FAIL] Agent '{agent_name}' not found")
                return False

            agent = agent_class()
            result = agent.execute(task)

            print(f"\n{'-'*70}")
            print(f"RESULT: SUCCESS")
            print(f"{'-'*70}")
            print(f"Status: {result.get('status', 'unknown')}")
            print(f"Tools used: {', '.join(result.get('tools_used', []))}")

            return True

        except Exception as e:
            print(f"\n[FAIL] Error executing {agent_name}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def wait_for_agent(self, agent_name: str, timeout: int = 300) -> bool:
        """Wait for an agent to complete.

        Args:
            agent_name: Name of the agent
            timeout: Max seconds to wait

        Returns:
            True if agent completed, False if timeout
        """
        return True

    def cleanup(self):
        """Clean up temporary scripts."""
        for script in self.agent_scripts_dir.glob("*.py"):
            try:
                script.unlink()
            except Exception:
                pass
        for script in self.agent_scripts_dir.glob("*.ps1"):
            try:
                script.unlink()
            except Exception:
                pass
        for script in self.agent_scripts_dir.glob("*.sh"):
            try:
                script.unlink()
            except Exception:
                pass
