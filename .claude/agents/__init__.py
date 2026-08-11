"""Agent implementations.

The specialist personas — reviewer, red-team, bug-fixer, diagnostician, coder,
group-sales-manager, scheduler — are defined as Claude Code subagents in
``.claude/agents/*.md``. That is what the harness discovers and dispatches.

The Python below is only for what has to run outside a Claude Code session:
currently the Scheduler, which ``.claude/schedule.py`` drives directly against
the Google Calendar API.
"""

from .team import SchedulerAgent
from .tools import (
    ToolRegistry,
    get_registry,
    register_tool,
    get_tool,
    list_tools,
)


def get_agent(agent_name: str):
    """Get a Python agent by name, or None if there isn't one."""
    agents = {
        "scheduler": SchedulerAgent,
    }
    agent_class = agents.get(agent_name)
    return agent_class() if agent_class else None


def list_agents() -> list:
    """List the Python agents. The subagents live in ``.claude/agents/*.md``."""
    return ["scheduler"]


__all__ = [
    "SchedulerAgent",
    "ToolRegistry",
    "get_agent",
    "list_agents",
    "get_registry",
    "register_tool",
    "get_tool",
    "list_tools",
]
