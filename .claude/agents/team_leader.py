"""Team Leader - master orchestrator for multi-agent coordination."""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from ..system.event_bus import EventBus
from ..system.session_manager import SessionManager
from ..system.schemas import TaskResult
from .tools import ToolRegistry
from .team import (
    ReviewerAgent,
    RedTeamAgent,
    BugFixerAgent,
    DiagnosticianAgent,
    CoderAgent,
    GroupSalesManagerAgent,
    SchedulerAgent,
)


@dataclass
class TeamLeaderConfig:
    """Configuration for Team Leader."""
    model: str = "claude-opus-5"
    max_concurrent_tasks: int = 4
    timeout: int = 3600


class TeamLeader:
    """
    Master Coordinator for Multi-Agent Team
    Orchestrates collaboration between specialized agents:
    - reviewer: Code review and validation
    - red_team: Security and edge-case testing
    - bug_fixer: Issue identification and fixes
    - diagnostician: System analysis and diagnostics
    - coder: Implementation and execution
    - group_sales_manager: Resource orchestration
    - scheduler: Calendar and scheduling management
    """

    SYSTEM_PROMPT = """You are the Team Leader orchestrating a specialized team of agents. Your role is to:
1. Coordinate work across all team members
2. Delegate tasks based on agent expertise
3. Manage dependencies and sequencing
4. Ensure quality and consistency
5. Handle escalations and complex scenarios

Team Members:
- Reviewer: Code quality and validation
- Red Team: Security and edge cases
- Bug Fixer: Issue resolution
- Diagnostician: System analysis
- Coder: Implementation
- Group Sales Manager: Resource allocation
- Scheduler: Calendar and task scheduling"""

    def __init__(self, config: Optional[TeamLeaderConfig] = None):
        """Initialize Team Leader with team members."""
        self.config = config or TeamLeaderConfig()
        self.name = "team_leader"

        # Core infrastructure
        self.event_bus = EventBus()
        self.tools_registry = ToolRegistry()

        # Initialize team members
        self.teammates: Dict[str, Any] = {
            "reviewer": ReviewerAgent(),
            "red_team": RedTeamAgent(),
            "bug_fixer": BugFixerAgent(),
            "diagnostician": DiagnosticianAgent(),
            "coder": CoderAgent(),
            "group_sales_manager": GroupSalesManagerAgent(),
            "scheduler": SchedulerAgent(),
        }

        # Running tasks
        self.running_tasks: Dict[str, Dict[str, Any]] = {}
        self.completed_tasks: Dict[str, Dict[str, Any]] = {}

    def get_team_config(self) -> Dict[str, Any]:
        """
        Get complete team configuration and capabilities.

        Returns:
            Dict with team structure and agent capabilities
        """
        return {
            "team_leader": {
                "name": self.name,
                "system_prompt": self.SYSTEM_PROMPT,
                "model": self.config.model,
                "role": "Master Coordinator",
            },
            "teammates": {
                name: agent.get_capabilities()
                for name, agent in self.teammates.items()
            },
            "configuration": {
                "max_concurrent_tasks": self.config.max_concurrent_tasks,
                "timeout": self.config.timeout,
            },
        }

    def get_agent(self, agent_name: str) -> Optional[Any]:
        """
        Get a specific team member by name.

        Args:
            agent_name: Name of agent to retrieve

        Returns:
            Agent instance or None
        """
        return self.teammates.get(agent_name)

    def list_agents(self) -> List[str]:
        """
        List all available team members.

        Returns:
            List of agent names
        """
        return list(self.teammates.keys())

    def get_system_prompt(self) -> str:
        """Return the system prompt for the team leader."""
        return self.SYSTEM_PROMPT

    def register_tool(self, tool: Any) -> None:
        """
        Register a custom tool available to all agents.

        Args:
            tool: Tool instance with name and execute method
        """
        self.tools_registry.register(tool)

    def get_available_tools(self) -> List[str]:
        """
        Get list of all available tools.

        Returns:
            List of tool names
        """
        return self.tools_registry.list_tools()

    async def orchestrate_task(self, task: Dict[str, Any]) -> TaskResult:
        """
        Orchestrate a complex task across team members.

        Args:
            task: Task specification

        Returns:
            Aggregated result from team execution
        """
        try:
            task_id = task.get("id", "unknown")
            task_type = task.get("type", "general")

            self.running_tasks[task_id] = {
                "type": task_type,
                "status": "in_progress",
                "agents_executed": [],
            }

            result = {
                "task_id": task_id,
                "type": task_type,
                "results": {},
                "summary": "",
            }

            self.running_tasks[task_id]["status"] = "completed"
            self.completed_tasks[task_id] = self.running_tasks.pop(task_id)

            return TaskResult(
                status="success",
                output=result
            )
        except Exception as e:
            return TaskResult(
                status="error",
                error=str(e),
                output={}
            )
