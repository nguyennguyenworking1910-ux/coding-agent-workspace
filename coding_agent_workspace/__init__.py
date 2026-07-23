"""Coding Agent Workspace — a CLI for coordinating Claude Code agents.

A team leader agent plans each request into a DAG of worker-agent steps, the
orchestrator runs them (in parallel where independent, writes serialized), and
the leader reports back. Write agents edit the working tree directly and never
commit; the user reviews the diff and approves. Runs and missions are persisted
to ``.agent-workspace/``.
"""

from .cli import main
from .claude_provider import run_claude, ClaudeError

__version__ = "0.1.0"
__all__ = ["main", "run_claude", "ClaudeError"]
