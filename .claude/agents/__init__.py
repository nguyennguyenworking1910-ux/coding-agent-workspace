"""Agent implementations - Organized by departments."""

from .base_agent import BaseAgent

# Import from departments
from .technical import (
    TeamLeaderAgent,
    DiagnosticianAgent,
    BugFixerAgent,
    ReviewerAgent,
    AgentArchitectAgent,
    get_technical_agent,
    list_technical_agents,
)

from .business import (
    GroupSaleManagerAgent,
    get_business_agent,
    list_business_agents,
)

__all__ = [
    # Base
    "BaseAgent",
    # Technical agents
    "TeamLeaderAgent",
    "DiagnosticianAgent",
    "BugFixerAgent",
    "ReviewerAgent",
    "AgentArchitectAgent",
    # Business agents
    "GroupSaleManagerAgent",
    # Functions
    "get_agent",
    "list_agents",
    "get_technical_agent",
    "get_business_agent",
    "list_technical_agents",
    "list_business_agents",
]

# Combined agent registry (Technical + Business)
AGENTS = {
    # Technical Department
    "team_leader": TeamLeaderAgent,
    "diagnostician": DiagnosticianAgent,
    "bug_fixer": BugFixerAgent,
    "reviewer": ReviewerAgent,
    "agent_architect": AgentArchitectAgent,
    # Business Department
    "group_sale_manager": GroupSaleManagerAgent,
}

def get_agent(name: str):
    """Get agent by name from any department."""
    return AGENTS.get(name)

def list_agents():
    """List all available agents from all departments."""
    return list(AGENTS.keys())
