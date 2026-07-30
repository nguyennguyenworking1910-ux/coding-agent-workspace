"""CLI interface for the Coding Agent Workspace - Milestone 1 Orchestration.

Provides command-line interface for multi-agent orchestration using structured
planning, task graphs, and agent coordination.
"""

import argparse
import sys
from pathlib import Path

from .orchestration_commands import OrchestrationCLI


def create_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Coding Agent Workspace - Multi-Agent Orchestration (Milestone 1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
QUICK START:
  coding-agent-workspace team "Analyze the codebase"
  coding-agent-workspace runs
  coding-agent-workspace show <run-id>

COMMANDS:
  team TASK              - Multi-agent orchestration
  runs                   - List all runs
  show RUN_ID            - Show run details
  output RUN_ID AGT      - Show agent output
  message RUN_ID AGT MSG - Send message to agent (Milestone 5)
  stop RUN_ID            - Stop a run (Milestone 5)

OPTIONS:
  --workspace DIR        - Custom workspace directory (default: .agent-workspace)
  --max-agents N         - Maximum workers (default: 4)
  --mux MODE             - Multiplexer: auto|tmux|psmux|headless (default: auto)
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Orchestration subcommands
    team_parser = subparsers.add_parser("team", help="Multi-agent orchestration")
    team_parser.add_argument("request", help="Request description")
    team_parser.add_argument("--max-agents", type=int, default=4)
    team_parser.add_argument("--mux", default="auto", choices=["auto", "tmux", "psmux", "headless"])

    runs_parser = subparsers.add_parser("runs", help="List all runs")

    show_parser = subparsers.add_parser("show", help="Show run details")
    show_parser.add_argument("run_id", help="Run ID to show")

    message_parser = subparsers.add_parser("message", help="Send message to agent (Milestone 5)")
    message_parser.add_argument("run_id")
    message_parser.add_argument("agent_id")
    message_parser.add_argument("text")

    stop_parser = subparsers.add_parser("stop", help="Stop a run (Milestone 5)")
    stop_parser.add_argument("run_id")

    output_parser = subparsers.add_parser("output", help="Show agent output")
    output_parser.add_argument("run_id")
    output_parser.add_argument("agent_id")

    parser.add_argument(
        "--workspace",
        default=".agent-workspace",
        help="Workspace directory (default: .agent-workspace)"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.4.0-m1"
    )

    return parser


def execute_command(args: argparse.Namespace) -> int:
    """Execute the requested command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        orch_cli = OrchestrationCLI(args.workspace)

        if args.command == "team":
            return orch_cli.team(args.request, max_agents=args.max_agents, mux=args.mux)
        elif args.command == "runs":
            return orch_cli.runs()
        elif args.command == "show":
            return orch_cli.show(args.run_id)
        elif args.command == "message":
            return orch_cli.message(args.run_id, args.agent_id, args.text)
        elif args.command == "stop":
            return orch_cli.stop(args.run_id)
        elif args.command == "output":
            return orch_cli.output(args.run_id, args.agent_id)
        else:
            print("Error: Unknown command. Use --help for usage.")
            return 2

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        return 130
    except Exception as error:
        print(f"\n❌ Error: {error}", file=sys.stderr)
        import traceback
        traceback.print_exc()
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
