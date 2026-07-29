"""Technical Department - Code analysis and quality assurance agents."""

from .team_leader import TeamLeaderAgent
from .diagnostician import DiagnosticianAgent
from .bug_fixer import BugFixerAgent
from .reviewer import ReviewerAgent
from .agent_architect import AgentArchitectAgent

__all__ = [
    "TeamLeaderAgent",
    "DiagnosticianAgent",
    "BugFixerAgent",
    "ReviewerAgent",
    "AgentArchitectAgent",
]

# Technical agents registry
TECHNICAL_AGENTS = {
    "team_leader": TeamLeaderAgent,
    "diagnostician": DiagnosticianAgent,
    "bug_fixer": BugFixerAgent,
    "reviewer": ReviewerAgent,
    "agent_architect": AgentArchitectAgent,
}

def get_technical_agent(name: str):
    """Get a technical department agent by name."""
    return TECHNICAL_AGENTS.get(name)

def list_technical_agents():
    """List all technical department agents."""
    return list(TECHNICAL_AGENTS.keys())
