"""CLI interface for the Coding Agent Workspace.

Provides command-line interface for coordinating Claude Code agents,
planning requests into DAG of worker steps, and managing execution.
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from .claude_provider import run_claude, ClaudeError

# Try to import team leader agent and config
try:
    import sys
    from pathlib import Path
    agent_path = Path(__file__).parent.parent / ".claude"
    if str(agent_path) not in sys.path:
        sys.path.insert(0, str(agent_path))
    from agents.technical import TeamLeaderAgent
    from agents.multi_terminal_orchestrator import MultiTerminalOrchestrator
    from config import get_config, is_experimental_mode
    TEAM_LEADER_AVAILABLE = True
    MULTI_TERMINAL_AVAILABLE = True
except ImportError:
    TEAM_LEADER_AVAILABLE = False
    MULTI_TERMINAL_AVAILABLE = False
    def get_config():
        class DummyConfig:
            experimental_agent_teams_enabled = False
        return DummyConfig()
    def is_experimental_mode():
        return False


class AgentOrchestrator:
    """Orchestrates execution of agent tasks."""

    def __init__(self, workspace_dir: Optional[str] = None):
        """Initialize orchestrator.

        Args:
            workspace_dir: Optional workspace directory for persisting missions
        """
        self.workspace_dir = Path(workspace_dir or ".agent-workspace")
        self.workspace_dir.mkdir(exist_ok=True)
        self.runs_dir = self.workspace_dir / "runs"
        self.runs_dir.mkdir(exist_ok=True)

    def create_run_id(self) -> str:
        """Create unique run identifier."""
        timestamp = datetime.now().isoformat().replace(":", "-")
        return f"run-{timestamp}"

    def save_mission(self, run_id: str, task: str, result: str) -> Path:
        """Save mission execution details.

        Args:
            run_id: Unique run identifier
            task: Original task description
            result: Execution result

        Returns:
            Path to saved mission file
        """
        mission = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "result": result
        }

        mission_file = self.runs_dir / f"{run_id}.json"
        mission_file.write_text(json.dumps(mission, indent=2))
        return mission_file

    def execute_solve(self, task: str) -> Dict[str, Any]:
        """Execute task using team leader agent directly (no file creation).

        Args:
            task: Task description

        Returns:
            Execution result
        """
        run_id = self.create_run_id()

        if not TEAM_LEADER_AVAILABLE:
            return {
                "success": False,
                "run_id": run_id,
                "task": task,
                "error": "Team leader agent not available",
                "status": "failed"
            }

        try:
            # Create team leader and execute
            team_leader = TeamLeaderAgent()
            result = team_leader.execute(task)

            # Format output
            output = f"""
TEAM LEADER EXECUTION REPORT
{'='*60}

Task: {task}
Classification: {result.get('task_type', 'general').upper()}
Workflow: {result.get('workflow_type', 'General Workflow')}
Status: {result.get('status', 'completed')}

Spawned Agents:
"""
            for agent in result.get('spawned_agents', []):
                output += f"  - {agent['agent'].upper()} ({agent['role']})\n"

            output += f"\nWorkflow Steps:\n"
            for step in result.get('workflow_steps', []):
                output += f"  Step {step['step']}: {step['agent'].upper()}\n"
                output += f"    Task: {step['task']}\n"

            output += f"\n[RESULT] Task routed to appropriate agents\n"
            output += f"Status: {result.get('status', 'completed')}\n"

            self.save_mission(run_id, task, output)

            return {
                "success": True,
                "run_id": run_id,
                "task": task,
                "result": output,
                "status": "completed"
            }

        except Exception as error:
            return {
                "success": False,
                "run_id": run_id,
                "task": task,
                "error": str(error),
                "status": "failed"
            }

    def execute_multi_terminal(self, task: str) -> Dict[str, Any]:
        """Execute task with agents in separate terminals.

        Args:
            task: Task description

        Returns:
            Execution result
        """
        run_id = self.create_run_id()

        if not MULTI_TERMINAL_AVAILABLE:
            return {
                "success": False,
                "run_id": run_id,
                "task": task,
                "error": "Multi-terminal orchestrator not available",
                "status": "failed"
            }

        try:
            orchestrator = MultiTerminalOrchestrator(use_multi_terminal=True)
            result = orchestrator.execute(task)

            output = f"""
MULTI-TERMINAL EXECUTION REPORT
{'='*60}

Task: {task}
Task Type: {result.get('task_type', 'unknown').upper()}
Run ID: {result['run_id']}
Trace ID: {result['trace_id']}
Mode: Multi-Terminal (Separate Windows)

Spawned Agents:
"""
            for agent in result.get('agents_spawned', []):
                output += f"  ✓ {agent.upper()} (in separate terminal)\n"

            output += f"\nExecution Log:\n"
            for log_entry in result.get('execution_log', []):
                output += f"  [{log_entry['event']}] {log_entry['message']}\n"

            output += f"\n✓ Agents are running in separate terminal windows\n"
            output += f"✓ Each agent shows its own execution details\n"
            output += f"✓ Check the open terminals to track progress\n"

            self.save_mission(run_id, task, output)

            return {
                "success": True,
                "run_id": run_id,
                "task": task,
                "result": output,
                "status": "agents_spawned_in_terminals"
            }

        except Exception as error:
            return {
                "success": False,
                "run_id": run_id,
                "task": task,
                "error": str(error),
                "status": "failed"
            }

    def execute_task(self, task: str, use_team_leader: bool = True) -> Dict[str, Any]:
        """Execute a task using Claude agents.

        Args:
            task: Task description
            use_team_leader: Whether to use team leader for coordination

        Returns:
            Execution result
        """
        run_id = self.create_run_id()

        if use_team_leader:
            prompt = f"""You are the team_leader agent. Analyze this task and create a plan:

Task: {task}

Using the team_leader agent from .claude/agents/team_leader.py:
1. Create an execution plan (DAG of steps)
2. Identify which agents are needed (diagnostician, bug_fixer, reviewer)
3. Show the coordination steps
4. Provide analysis and recommendations

Report your findings and next steps."""
        else:
            prompt = f"""Execute this task:

{task}

Provide:
1. Analysis
2. Findings
3. Recommendations
4. Next steps"""

        try:
            result = run_claude(
                prompt=prompt,
                tools=["read", "grep"],
                permission_mode="default",
                stream=True
            )

            self.save_mission(run_id, task, result)

            return {
                "success": True,
                "run_id": run_id,
                "task": task,
                "result": result,
                "status": "completed"
            }

        except ClaudeError as error:
            return {
                "success": False,
                "run_id": run_id,
                "task": task,
                "error": str(error),
                "status": "failed"
            }


def create_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Coding Agent Workspace - Claude Code agent orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s analyze "Check my code for bugs"
  %(prog)s plan "Design a new feature"
  %(prog)s review "Review these changes"
  %(prog)s fix "Fix the authentication issue"
        """
    )

    parser.add_argument(
        "command",
        choices=["analyze", "plan", "review", "fix", "execute", "solve"],
        help="Command to execute"
    )

    parser.add_argument(
        "task",
        help="Task description"
    )

    parser.add_argument(
        "--no-team-leader",
        action="store_true",
        help="Execute without team leader coordination"
    )

    parser.add_argument(
        "--workspace",
        default=".agent-workspace",
        help="Workspace directory for persisting missions (default: .agent-workspace)"
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output streaming"
    )

    parser.add_argument(
        "--multi-terminal",
        action="store_true",
        help="Run agents in separate terminal windows for real-time tracking"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0"
    )

    return parser


def execute_command(args: argparse.Namespace) -> int:
    """Execute the requested command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    orchestrator = AgentOrchestrator(args.workspace)

    command_task_map = {
        "analyze": f"Analyze this task and identify issues: {args.task}",
        "plan": f"Create an execution plan for: {args.task}",
        "review": f"Review and validate: {args.task}",
        "fix": f"Fix the following issue: {args.task}",
        "execute": args.task,
        "solve": args.task  # Direct team leader invocation
    }

    task_description = command_task_map.get(args.command, args.task)

    try:
        # Show configuration if experimental mode enabled
        config = get_config()
        if is_experimental_mode():
            print(f"\n{config.log_config()}\n")

        print(f"\n🚀 Team Leader Agent Executing: {args.command}")
        print(f"📋 Task: {args.task}\n")
        print("=" * 60)

        # Use multi-terminal mode if requested
        if args.multi_terminal:
            print("\n🖥️  MULTI-TERMINAL MODE")
            print("    Spawning agents in separate terminal windows...\n")
            result = orchestrator.execute_multi_terminal(task=args.task)
        # Use direct team leader execution for "solve" command
        elif args.command == "solve":
            result = orchestrator.execute_solve(task=args.task)

            # Show tracing info if experimental mode
            if is_experimental_mode() and result.get("success"):
                print("\n" + "=" * 60)
                print("EXECUTION TRACE")
                print("=" * 60)
                if "trace_id" in result.get("result", ""):
                    print(f"Trace ID: {result['result'].get('trace_id', 'N/A')}")
                    if "execution_log" in result["result"]:
                        print("\nExecution Log:")
                        for entry in result["result"]["execution_log"]:
                            print(f"  {entry}")
        else:
            result = orchestrator.execute_task(
                task=task_description,
                use_team_leader=not args.no_team_leader
            )

        if result["success"]:
            print("\n" + "=" * 60)
            print(f"✅ Completed (Run ID: {result['run_id']})")
            run_id = result['run_id']
            mission_file = orchestrator.runs_dir / f'{run_id}.json'
            print(f"📁 Saved to: {mission_file}")
            return 0
        else:
            print(f"\n❌ Failed: {result.get('error', 'Unknown error')}")
            return 1

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        return 130
    except Exception as error:
        print(f"\n❌ Error: {error}", file=sys.stderr)
        return 1


def main() -> int:
    """Main CLI entry point.

    Returns:
        Exit code
    """
    parser = create_parser()
    args = parser.parse_args()
    return execute_command(args)


if __name__ == "__main__":
    sys.exit(main())
