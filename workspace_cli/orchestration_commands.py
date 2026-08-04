"""CLI handlers for team orchestration commands."""

from pathlib import Path
from datetime import datetime
import sys

# Add .claude to path
claude_path = Path(__file__).parent.parent / ".claude"
if str(claude_path) not in sys.path:
    sys.path.insert(0, str(claude_path))

from team.planner import Planner
from team.coordinator import Coordinator
from team.run_store import RunStore


class OrchestrationCLI:
    """Handlers for 'team', 'runs', 'show', 'message', 'stop' commands."""

    def __init__(self, workspace_dir: str = ".agent-workspace"):
        self.workspace_dir = workspace_dir
        self.store = RunStore(workspace_dir)
        self.planner = Planner(max_workers=4)

    def team(self, request: str, max_agents: int = 4, mux: str = "auto", use_real_workers: bool = False) -> int:
        """Execute 'team' command: plan and execute multi-agent run."""
        run_id = f"run-{datetime.now().isoformat().replace(':', '-')}"

        print(f"\n[ORCHESTRATION] Starting run: {run_id}")
        print(f"[ORCHESTRATION] Request: {request}\n")

        # Plan
        plan, is_valid = self.planner.create_plan(run_id, request)
        if not is_valid:
            print("[PLANNER] Fallback to lead-only execution")
        else:
            print(f"[PLANNER] Created plan with {len(plan.agents)} worker(s)")

        # Execute
        coordinator = Coordinator(run_id, self.workspace_dir)
        # Use longer timeout for real workers (300s = 5 minutes)
        timeout = 300.0 if use_real_workers else 30.0
        success = coordinator.execute_run(request, plan, timeout=timeout)

        if success:
            print(f"\n[OK] Run completed: {run_id}")
            print(f"[DIR] Results stored at: {self.store.get_run_dir(run_id)}")
            return 0
        else:
            print(f"\n[FAIL] Run failed: {run_id}")
            return 1

    def runs(self) -> int:
        """List all runs."""
        runs = self.store.list_runs()
        if not runs:
            print("\nNo runs found.")
            return 0

        print(f"\nAvailable runs ({len(runs)}):")
        for run_id in runs:
            print(f"  - {run_id}")
        return 0

    def show(self, run_id: str) -> int:
        """Show run details."""
        if not self.store.run_exists(run_id):
            print(f"[ERROR] Run not found: {run_id}")
            return 1

        plan = self.store.load_plan(run_id)
        context = self.store.load_status(run_id)
        events = self.store.load_events(run_id)

        print(f"\n[RUN] {run_id}")
        if context:
            print(f"   Status: {context.status.value}")
            print(f"   Created: {context.created_at}")

        if plan:
            print(f"\n[PLAN] {plan.summary}")
            print(f"   Agents: {len(plan.agents)}")
            print(f"   Tasks: {len(plan.tasks)}")

        if events:
            print(f"\n[EVENTS] ({len(events)}):")
            for event in events[-10:]:  # Show last 10 events
                print(f"   - [{event.event_type}] {event.agent_id} @ {event.task_id}")

        return 0

    def stop(self, run_id: str) -> int:
        """Stop a run (Milestone 5)."""
        print(f"[WARNING] Stop run {run_id} (not implemented in Milestone 1)")
        return 0

    def message(self, run_id: str, agent_id: str, text: str) -> int:
        """Send message to agent (Milestone 5)."""
        print(f"[WARNING] Message to {agent_id} in {run_id} (not implemented in Milestone 1)")
        return 0

    def output(self, run_id: str, agent_id: str) -> int:
        """Show agent output."""
        if not self.store.run_exists(run_id):
            print(f"[ERROR] Run not found: {run_id}")
            return 1

        output_lines = self.store.load_agent_output(run_id, agent_id)
        if not output_lines:
            print(f"No output found for agent {agent_id} in run {run_id}")
            return 1

        print(f"\n[OUTPUT] {agent_id} in {run_id}:")
        for line in output_lines:
            print(f"   {line}")

        return 0
