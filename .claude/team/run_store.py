"""Persistent storage for runs using the file system."""

import json
from pathlib import Path
from typing import Optional, List
from datetime import datetime
import tempfile
import os

from .schemas import RunContext, AgentPlan, AgentEvent, RunStatus


class RunStore:
    """Store runs persistently in .agent-workspace/runs/{run_id}/"""

    def __init__(self, workspace_dir: str = ".agent-workspace"):
        self.workspace_dir = Path(workspace_dir)
        self.runs_dir = self.workspace_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create_run_dir(self, run_id: str) -> Path:
        """Create directory for a run."""
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "agents").mkdir(exist_ok=True)
        return run_dir

    def get_run_dir(self, run_id: str) -> Path:
        """Get run directory."""
        return self.runs_dir / run_id

    def save_request(self, run_id: str, request: str) -> Path:
        """Save the original request."""
        run_dir = self.get_run_dir(run_id)
        request_file = run_dir / "request.md"
        request_file.write_text(request)
        return request_file

    def load_request(self, run_id: str) -> Optional[str]:
        """Load the original request."""
        request_file = self.get_run_dir(run_id) / "request.md"
        if request_file.exists():
            return request_file.read_text()
        return None

    def save_plan(self, run_id: str, plan: AgentPlan) -> Path:
        """Save the execution plan atomically."""
        run_dir = self.get_run_dir(run_id)
        plan_file = run_dir / "plan.json"
        self._atomic_write_json(plan_file, plan.model_dump(mode="json"))
        return plan_file

    def load_plan(self, run_id: str) -> Optional[AgentPlan]:
        """Load the execution plan."""
        plan_file = self.get_run_dir(run_id) / "plan.json"
        if plan_file.exists():
            data = json.loads(plan_file.read_text())
            return AgentPlan(**data)
        return None

    def save_status(self, run_id: str, context: RunContext) -> Path:
        """Save the current run status atomically."""
        run_dir = self.get_run_dir(run_id)
        status_file = run_dir / "status.json"
        self._atomic_write_json(status_file, context.model_dump(mode="json"))
        return status_file

    def load_status(self, run_id: str) -> Optional[RunContext]:
        """Load the run status."""
        status_file = self.get_run_dir(run_id) / "status.json"
        if status_file.exists():
            data = json.loads(status_file.read_text())
            return RunContext(**data)
        return None

    def append_event(self, run_id: str, event: AgentEvent) -> None:
        """Append an event to the JSONL events file."""
        run_dir = self.get_run_dir(run_id)
        events_file = run_dir / "events.jsonl"
        with open(events_file, "a") as f:
            f.write(json.dumps(event.model_dump(mode="json")) + "\n")

    def load_events(self, run_id: str) -> List[AgentEvent]:
        """Load all events for a run."""
        events_file = self.get_run_dir(run_id) / "events.jsonl"
        events = []
        if events_file.exists():
            with open(events_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            events.append(AgentEvent(**data))
                        except (json.JSONDecodeError, ValueError) as e:
                            print(f"Warning: Failed to parse event: {e}")
        return events

    def save_agent_task(self, run_id: str, agent_id: str, task_data: dict) -> Path:
        """Save task details for an agent."""
        agent_dir = self.get_run_dir(run_id) / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        task_file = agent_dir / "task.json"
        self._atomic_write_json(task_file, task_data)
        return task_file

    def save_agent_status(self, run_id: str, agent_id: str, status_data: dict) -> Path:
        """Save status for an agent."""
        agent_dir = self.get_run_dir(run_id) / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        status_file = agent_dir / "status.json"
        self._atomic_write_json(status_file, status_data)
        return status_file

    def append_agent_output(self, run_id: str, agent_id: str, output_line: str) -> None:
        """Append a line to agent's output JSONL."""
        agent_dir = self.get_run_dir(run_id) / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        output_file = agent_dir / "output.jsonl"
        with open(output_file, "a") as f:
            f.write(output_line + "\n")

    def load_agent_output(self, run_id: str, agent_id: str) -> List[dict]:
        """Load all output lines for an agent."""
        output_file = self.get_run_dir(run_id) / "agents" / agent_id / "output.jsonl"
        output = []
        if output_file.exists():
            with open(output_file, "r") as f:
                for line in f:
                    if line.strip():
                        output.append(json.loads(line))
        return output

    def save_final_response(self, run_id: str, response: str) -> Path:
        """Save the final synthesized response."""
        run_dir = self.get_run_dir(run_id)
        response_file = run_dir / "final-response.md"
        response_file.write_text(response)
        return response_file

    def load_final_response(self, run_id: str) -> Optional[str]:
        """Load the final response."""
        response_file = self.get_run_dir(run_id) / "final-response.md"
        if response_file.exists():
            return response_file.read_text()
        return None

    def list_runs(self) -> List[str]:
        """List all run IDs."""
        if not self.runs_dir.exists():
            return []
        return sorted([d.name for d in self.runs_dir.iterdir() if d.is_dir()])

    def run_exists(self, run_id: str) -> bool:
        """Check if a run exists."""
        return self.get_run_dir(run_id).exists()

    def _atomic_write_json(self, target: Path, data: dict) -> None:
        """Write JSON atomically by writing to temp file and renaming."""
        target.parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file in same directory
        fd, temp_path = tempfile.mkstemp(dir=str(target.parent), text=True)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            # Atomic rename
            os.replace(temp_path, str(target))
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
