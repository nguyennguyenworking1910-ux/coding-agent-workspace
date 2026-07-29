"""Manager for opening Claude Code terminals for agents using tmux split panes."""

import subprocess
import sys
import os
import platform
import tempfile
from pathlib import Path
from typing import Optional

from .agent_utils import convert_to_class_name


class ClaudeTerminalManager:
    """Manages tmux split panes for agent execution."""

    def __init__(self, session_name: str = "coding-agents"):
        self.active_terminals = {}
        self.terminal_count = 0
        self.system = platform.system()
        self.temp_scripts = []
        self.session_name = session_name
        self.auto_attach = self._should_auto_attach()
        self._ensure_tmux_session()
        if self.auto_attach:
            self._auto_attach_to_session()

    def _should_auto_attach(self) -> bool:
        """Check if auto-attach is enabled in config."""
        try:
            config_path = Path(__file__).parent.parent / "settings.json"
            if config_path.exists():
                import json
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    prefs = config.get("preferences", {})
                    return prefs.get("tmuxAutoAttach", False)
        except Exception:
            pass
        return False

    def _auto_attach_to_session(self):
        """Automatically attach to tmux session."""
        try:
            print(f"\n[TMUX] Auto-attaching to session: {self.session_name}")
            print("[TMUX] Use Ctrl+B then 'n' for next window, 'p' for previous, 'd' to detach\n")
            subprocess.run(["tmux", "attach-session", "-t", self.session_name])
        except Exception as e:
            print(f"[WARNING] Could not auto-attach: {e}")

    def _ensure_tmux_session(self):
        """Ensure tmux session exists, create if needed."""
        try:
            subprocess.run(
                ["tmux", "has-session", "-t", self.session_name],
                capture_output=True,
                check=False
            )
            # Session doesn't exist, create it
            result = subprocess.run(
                ["tmux", "new-session", "-d", "-s", self.session_name, "-x", "200", "-y", "50"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"[TMUX] Created session: {self.session_name}")
            else:
                print(f"[TMUX] Session already exists: {self.session_name}")
        except FileNotFoundError:
            print("[WARNING] tmux not found. Ensure tmux is installed and in PATH")

    def open_agent_terminal(self, agent_name: str, task: str, run_id: str) -> Optional[str]:
        """Open a tmux split pane for an agent.

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
            script_path = self._create_agent_script_file(agent_name, task, run_id)

            print(f"\n[TMUX_PANE] Creating pane for {agent_name.upper()}")
            print(f"  Pane ID: {terminal_id}")
            print(f"  Task: {task}\n")

            success = self._create_tmux_pane(script_path, agent_name, terminal_id)

            self.active_terminals[terminal_id] = {
                "agent": agent_name,
                "task": task,
                "run_id": run_id,
                "status": "pane_active" if success else "pending",
                "script_path": str(script_path),
            }

            return terminal_id

        except Exception as e:
            print(f"[ERROR] Failed to create pane for {agent_name}: {e}")
            return None

    def _create_tmux_pane(self, script_path: Path, agent_name: str, terminal_id: str) -> bool:
        """Create a tmux split pane and execute agent script.

        Args:
            script_path: Path to agent script
            agent_name: Agent name
            terminal_id: Terminal ID

        Returns:
            True if pane created successfully
        """
        try:
            # Create split pane (horizontal layout for readability)
            split_result = subprocess.run(
                ["tmux", "split-window", "-h", "-t", self.session_name],
                capture_output=True,
                check=False
            )

            if split_result.returncode != 0:
                print(f"  [WARNING] Failed to create split pane: {split_result.stderr.decode()}")
                return False

            # Get pane ID from the newly created pane
            list_result = subprocess.run(
                ["tmux", "list-panes", "-t", self.session_name, "-F", "#{pane_id}"],
                capture_output=True,
                text=True,
                check=False
            )

            panes = list_result.stdout.strip().split('\n')
            target_pane = panes[-1] if panes else f"{self.session_name}.0"

            # Send command to execute agent script in the pane
            cmd = f"cd {Path.cwd()} && python '{script_path}'"
            subprocess.run(
                ["tmux", "send-keys", "-t", target_pane, cmd, "Enter"],
                capture_output=True,
                check=False
            )

            # Tile panes automatically for better visibility
            subprocess.run(
                ["tmux", "select-layout", "-t", self.session_name, "tiled"],
                capture_output=True,
                check=False
            )

            print(f"  [OK] Split pane created in tmux session '{self.session_name}'")
            print(f"  [INFO] Pane ID: {target_pane}")
            print(f"  [INFO] Command: {cmd}")
            return True

        except Exception as e:
            print(f"  [WARNING] Could not create tmux pane: {e}")
            return False

    def _create_agent_script_file(self, agent_name: str, task: str, run_id: str) -> Path:
        """Create and save a Python script file to run agent in tmux pane.

        Args:
            agent_name: Agent name
            task: Task description
            run_id: Run ID

        Returns:
            Path to created script file
        """
        script_content = f'''#!/usr/bin/env python
"""Auto-generated script to run {agent_name} agent in tmux pane."""
import sys
import os
from pathlib import Path

# Setup path to workspace root
script_dir = Path(__file__).parent
workspace_root = script_dir
for _ in range(5):
    if (workspace_root / ".claude").exists():
        break
    workspace_root = workspace_root.parent

agent_path = workspace_root / ".claude"
sys.path.insert(0, str(agent_path))
os.chdir(workspace_root)

try:
    from agents.technical.{agent_name} import {convert_to_class_name(agent_name)}

    run_id = "{run_id}"
    task = {repr(task)}

    print(f"[{agent_name.upper()}] Starting execution in tmux pane")
    print(f"[{agent_name.upper()}] Run ID: {{run_id}}")
    print(f"[{agent_name.upper()}] Task: {{task}}")
    print("[{agent_name.upper()}] " + "=" * 60)

    # Create and execute agent
    agent = {convert_to_class_name(agent_name)}()
    result = agent.execute(task, run_id=run_id)

    if isinstance(result, dict):
        print(f"\\n[{agent_name.upper()}] Status: {{result.get('status', 'unknown')}}")

    print(f"[{agent_name.upper()}] Execution complete")

except Exception as e:
    print(f"[ERROR] Failed to execute agent: {{e}}")
    import traceback
    traceback.print_exc()

finally:
    print("\\n[Agent pane will remain open for inspection - press Ctrl+D or type 'exit' to close]")
'''

        # Create temp directory if needed
        temp_dir = Path(tempfile.gettempdir()) / "claude_agent_scripts"
        temp_dir.mkdir(exist_ok=True)

        # Write script file
        script_path = temp_dir / f"{agent_name}_{run_id}_{self.terminal_count}.py"
        script_path.write_text(script_content)
        self.temp_scripts.append(script_path)

        return script_path

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

    def cleanup(self):
        """Clean up temporary script files."""
        for script_path in self.temp_scripts:
            try:
                if script_path.exists():
                    script_path.unlink()
            except Exception as e:
                print(f"[WARNING] Could not delete temp script {script_path}: {e}")
