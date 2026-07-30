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
        self.split_panes_enabled = self._is_split_panes_enabled()
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

    def _is_split_panes_enabled(self) -> bool:
        """Check if split panes mode is enabled in config."""
        try:
            config_path = Path(__file__).parent.parent / "settings.json"
            if config_path.exists():
                import json
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    prefs = config.get("preferences", {})
                    return prefs.get("tmuxSplitPanes", False)
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
            # Use cmd /c for Windows PowerShell to ensure command execution
            cmd = f"python '{script_path}'"
            subprocess.run(
                ["tmux", "send-keys", "-t", target_pane, f"cd {Path.cwd()}", "Enter"],
                capture_output=True,
                check=False
            )
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
            print(f"  [INFO] Script: {script_path}")
            print(f"  [INFO] Working Dir: {Path.cwd()}")
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
        terminal_id = f"{agent_name}_{run_id}_{self.terminal_count}"
        workspace_root = Path.cwd().resolve()  # Capture actual workspace root
        agent_path = workspace_root / ".claude"

        script_content = f'''#!/usr/bin/env python
"""Auto-generated script to run {agent_name} agent in tmux pane."""
import sys
import os
import json
from pathlib import Path

# Setup path to workspace root (absolute path)
workspace_root = Path(r"{workspace_root}").resolve()
agent_path = workspace_root / ".claude"
sys.path.insert(0, str(workspace_root))
sys.path.insert(0, str(agent_path))
os.chdir(workspace_root)

result = None
terminal_id = "{terminal_id}"

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
    result = {{"success": False, "agent": "{agent_name}", "error": str(e), "status": "failed"}}

finally:
    # Write result to file for parent process to read
    try:
        result_dir = Path(__import__("tempfile").gettempdir()) / "claude_agent_results"
        result_dir.mkdir(exist_ok=True)
        result_file = result_dir / f"{{terminal_id}}.json"
        if result:
            with open(result_file, 'w') as f:
                json.dump(result if isinstance(result, dict) else {{"result": str(result)}}, f)
    except Exception as e:
        print(f"[WARNING] Could not write result file: {{e}}")

    print("\\n[Agent pane will remain open for inspection - press Ctrl+D or type 'exit' to close]")
'''

        # Create temp directory if needed
        temp_dir = Path(tempfile.gettempdir()) / "claude_agent_scripts"
        temp_dir.mkdir(exist_ok=True)

        # Write script file with absolute path
        script_path = temp_dir / f"{agent_name}_{run_id}_{self.terminal_count}.py"
        script_path.write_text(script_content)
        self.temp_scripts.append(str(script_path))

        return script_path

    def wait_for_pane_completion(self, terminal_id: str, timeout: int = 900) -> Optional[dict]:
        """Wait for a pane to complete execution and retrieve results.

        Args:
            terminal_id: Terminal/pane ID to monitor
            timeout: Maximum seconds to wait (default 15 min)

        Returns:
            Execution results from the agent pane, or None if timeout
        """
        import time
        import json

        if terminal_id not in self.active_terminals:
            return None

        terminal_info = self.active_terminals[terminal_id]
        result_file = None

        try:
            # Look for result file in temp directory
            result_dir = Path(tempfile.gettempdir()) / "claude_agent_results"
            result_dir.mkdir(exist_ok=True)
            result_file = result_dir / f"{terminal_id}.json"

            start_time = time.time()
            last_status_time = start_time
            check_count = 0

            while time.time() - start_time < timeout:
                check_count += 1

                if result_file.exists():
                    try:
                        with open(result_file, 'r') as f:
                            result = json.load(f)
                            elapsed = time.time() - start_time
                            terminal_info["status"] = "completed"
                            terminal_info["wait_time_seconds"] = elapsed
                            # Clean up result file
                            result_file.unlink()
                            print(f"[PANE_COMPLETE] {terminal_id} completed in {elapsed:.1f}s")
                            return result
                    except (json.JSONDecodeError, IOError):
                        pass  # File still being written, retry

                # Show progress every 30 seconds
                current_time = time.time()
                if current_time - last_status_time >= 30:
                    elapsed = current_time - start_time
                    remaining = timeout - elapsed
                    print(f"[PANE_WAIT] {terminal_id}: {elapsed:.0f}s elapsed, {remaining:.0f}s remaining...")
                    last_status_time = current_time

                time.sleep(1)  # Check every second

            # Timeout reached
            terminal_info["status"] = "timeout"
            print(f"[WARNING] Timeout waiting for {terminal_id} completion after {timeout}s")
            return None

        except Exception as e:
            print(f"[WARNING] Error waiting for pane completion: {e}")
            return None

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
