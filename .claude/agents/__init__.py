"""Multi-agent orchestration system."""

from .team_leader import TeamLeader
from .team import (
    ReviewerAgent,
    RedTeamAgent,
    BugFixerAgent,
    DiagnosticianAgent,
    CoderAgent,
    GroupSalesManagerAgent,
    SchedulerAgent,
)
from .tools import (
    ToolRegistry,
    get_registry,
    register_tool,
    get_tool,
    list_tools,
)

# Alias for compatibility
TeamLeaderAgent = TeamLeader


def get_agent(agent_name: str):
    """Get an agent by name from the team."""
    agents = {
        "team_leader": TeamLeader,
        "reviewer": ReviewerAgent,
        "red_team": RedTeamAgent,
        "bug_fixer": BugFixerAgent,
        "diagnostician": DiagnosticianAgent,
        "coder": CoderAgent,
        "group_sales_manager": GroupSalesManagerAgent,
        "scheduler": SchedulerAgent,
    }
    agent_class = agents.get(agent_name)
    return agent_class() if agent_class else None


def list_agents() -> list:
    """List all available agents."""
    return [
        "team_leader",
        "reviewer",
        "red_team",
        "bug_fixer",
        "diagnostician",
        "coder",
        "group_sales_manager",
        "scheduler",
    ]


__all__ = [
    "TeamLeader",
    "TeamLeaderAgent",
    "ReviewerAgent",
    "RedTeamAgent",
    "BugFixerAgent",
    "DiagnosticianAgent",
    "CoderAgent",
    "GroupSalesManagerAgent",
    "ToolRegistry",
    "get_agent",
    "list_agents",
    "get_registry",
    "register_tool",
    "get_tool",
    "list_tools",
]
