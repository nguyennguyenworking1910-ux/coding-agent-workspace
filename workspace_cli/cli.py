"""CLI interface for the Coding Agent Workspace.

Provides command-line interface for coordinating Claude Code agents,
planning requests into DAG of worker steps, and managing execution.
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from .claude_provider import run_claude, ClaudeError

# Try to import team leader agent and config
try:
    agent_path = Path(__file__).parent.parent / ".claude"
    if str(agent_path) not in sys.path:
        sys.path.insert(0, str(agent_path))
    from agents.technical import TeamLeaderAgent
    from config import get_config, is_experimental_mode
    TEAM_LEADER_AVAILABLE = True
except ImportError:
    TEAM_LEADER_AVAILABLE = False
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

    def execute_solve(self, task: str, multi_terminal: bool = True) -> Dict[str, Any]:
        """Execute task using team leader agent directly (no file creation).

        Args:
            task: Task description
            multi_terminal: Whether to spawn agents in separate terminals

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
            # Create team leader and execute with run_id and multi_terminal flag
            team_leader = TeamLeaderAgent(run_id=run_id)
            team_leader.multi_terminal = multi_terminal
            result = team_leader.execute(task, run_id=run_id)

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
        description="Coding Agent Workspace - Claude Code CLI Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
QUICK START (Claude Code Terminal):
  coding-agent-workspace solve "Analyze the codebase"
  coding-agent-workspace team "Find and fix bugs"
  coding-agent-workspace analyze "Check for security issues"

AGENT MODES:
  solve      - Team Leader coordinates full workflow
  analyze    - Diagnostician only (fast analysis)
  plan       - Create execution plan
  review     - Reviewer validation only
  fix        - Bug Fixer implementation
  execute    - Full execution with multi-terminal

OPTIONS:
  --multi-terminal  - Open each agent in separate Claude Code terminal
  --no-team-leader  - Skip Team Leader coordination
  --workspace DIR   - Custom workspace directory
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
        "--single-terminal",
        action="store_true",
        help="Run all agents in single terminal (default is multi-terminal)"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.3.0"
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

        # Multi-terminal is now DEFAULT (unless --single-terminal is used)
        use_multi_terminal = not args.single_terminal

        # For "solve" command, ALWAYS use Team Leader (it handles multi-terminal internally)
        if args.command == "solve":
            print("\n[MULTI-TERMINAL MODE - DEFAULT]")
            print("    Team Leader will coordinate agent execution\n")
            # Pass multi-terminal flag to orchestrator
            result = orchestrator.execute_solve(task=args.task, multi_terminal=use_multi_terminal)

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
