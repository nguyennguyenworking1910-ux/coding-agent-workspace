"""Claude Code subprocess runner for executing worker tasks."""

import subprocess
import json
import time
import signal
import os
import sys
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
from pathlib import Path
import threading

from ..system.schemas import AgentEvent


class ClaudeRunner:
    """Runs Claude Code in subprocess with structured output streaming."""

    def __init__(
        self,
        agent_id: str,
        task_id: str,
        run_id: str,
        cwd: Optional[str] = None,
        timeout: float = 300.0,
        on_event: Optional[Callable[[AgentEvent], None]] = None,
    ):
        """Initialize Claude runner.

        Args:
            agent_id: Agent identifier
            task_id: Task identifier
            run_id: Run identifier
            cwd: Working directory for Claude process
            timeout: Timeout in seconds
            on_event: Callback for events
        """
        self.agent_id = agent_id
        self.task_id = task_id
        self.run_id = run_id
        self.cwd = cwd or os.getcwd()
        self.timeout = timeout
        self.on_event = on_event or (lambda e: None)

        self.process: Optional[subprocess.Popen] = None
        self.exit_code: Optional[int] = None
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.output_lines: List[str] = []
        self.stderr_lines: List[str] = []
        self.error: Optional[str] = None

    def run(self, prompt: str, system_prompt: Optional[str] = None) -> bool:
        """Execute Claude with the given prompt.

        Args:
            prompt: Task prompt for Claude
            system_prompt: Optional system prompt

        Returns:
            True if execution completed successfully
        """
        try:
            self._emit_event("agent_started", {"prompt": prompt[:100] + "..."})

            self.start_time = time.time()

            # Build Claude command
            cmd = [
                "claude",
                "--print",
                "--verbose",
                "--output-format", "stream-json",
            ]

            # Build full prompt
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"

            # Start process
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,  # Line buffering
            )

            # Send prompt and close stdin
            if self.process.stdin:
                self.process.stdin.write(full_prompt)
                self.process.stdin.close()

            # Read output streams in threads
            stdout_thread = threading.Thread(
                target=self._read_stdout,
                daemon=True
            )
            stderr_thread = threading.Thread(
                target=self._read_stderr,
                daemon=True
            )

            stdout_thread.start()
            stderr_thread.start()

            # Wait for process with timeout
            try:
                self.exit_code = self.process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                self._emit_event("progress", {"message": "Timeout - terminating process"})
                self._cancel_process()
                self.error = f"Process timeout after {self.timeout} seconds"
                return False

            self.end_time = time.time()

            # Wait for read threads
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)

            if self.exit_code == 0:
                self._emit_event("task_completed", {
                    "exit_code": self.exit_code,
                    "elapsed": self.end_time - self.start_time,
                    "output_lines": len(self.output_lines),
                })
                return True
            else:
                error_msg = self.stderr_lines[-1] if self.stderr_lines else "Unknown error"
                self._emit_event("task_failed", {
                    "exit_code": self.exit_code,
                    "error": error_msg,
                })
                self.error = error_msg
                return False

        except Exception as e:
            self.error = str(e)
            self._emit_event("task_failed", {"error": str(e)})
            return False

    def _read_stdout(self) -> None:
        """Read stdout and parse structured JSON lines."""
        if not self.process or not self.process.stdout:
            return

        for line in self.process.stdout:
            line = line.rstrip('\n')
            if line:
                self.output_lines.append(line)

                # Try to parse as JSON (structured output)
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        if "type" in data:
                            # Emit progress for thinking/output events
                            if data.get("type") in ("thinking", "text"):
                                content = data.get("content", "")
                                if content:
                                    self._emit_event("progress", {
                                        "message": content[:100],
                                        "event_type": data["type"],
                                    })
                except json.JSONDecodeError:
                    # Not JSON, just regular output
                    self._emit_event("progress", {"message": line[:100]})

    def _read_stderr(self) -> None:
        """Read stderr for error messages."""
        if not self.process or not self.process.stderr:
            return

        for line in self.process.stderr:
            line = line.rstrip('\n')
            if line:
                self.stderr_lines.append(line)

    def _cancel_process(self) -> None:
        """Cancel process gracefully: SIGTERM then SIGKILL."""
        if not self.process:
            return

        try:
            # Try graceful termination
            if sys.platform == "win32":
                self.process.terminate()
            else:
                self.process.send_signal(signal.SIGTERM)

            # Wait a bit for graceful shutdown
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if still running
                self.process.kill()
                self.process.wait()
        except Exception as e:
            print(f"Error canceling process: {e}")

    def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit event."""
        import uuid
        self.on_event(
            AgentEvent(
                event_id=str(uuid.uuid4()),
                run_id=self.run_id,
                agent_id=self.agent_id,
                task_id=self.task_id,
                timestamp=datetime.utcnow().isoformat(),
                event_type=event_type,
                payload=payload,
            )
        )

    def get_result(self) -> Optional[str]:
        """Get the final result from output."""
        if not self.output_lines:
            return None

        # Combine all output lines
        result = "\n".join(self.output_lines)
        return result

    def get_metadata(self) -> Dict[str, Any]:
        """Get execution metadata."""
        elapsed = None
        if self.end_time is not None and self.start_time is not None:
            elapsed = self.end_time - self.start_time

        return {
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "exit_code": self.exit_code,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "elapsed_seconds": elapsed,
            "output_lines": len(self.output_lines),
            "stderr_lines": len(self.stderr_lines),
            "error": self.error,
        }
