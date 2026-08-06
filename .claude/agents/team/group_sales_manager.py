"""Group Sales Manager agent - orchestrates resource allocation and task scheduling."""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from ..base_agent import BaseAgent, AgentConfig
from ...system.schemas import TaskResult


@dataclass
class GroupSalesManagerConfig(AgentConfig):
    """Configuration for Group Sales Manager agent."""
    name: str = "group_sales_manager"
    model: str = "claude-opus-5"
    tools: list = None

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["queue-manager", "resource-monitor", "scheduler"]


class GroupSalesManagerAgent(BaseAgent):
    """
    Agent: Resource Orchestration & Scheduling
    Responsibilities:
    - Allocate resources and agents
    - Schedule and prioritize tasks
    - Load balancing
    - Resource monitoring
    """

    SYSTEM_PROMPT = """You are an expert resource manager and orchestrator. Your role is to:
1. Allocate resources and team members to tasks
2. Schedule and prioritize work
3. Manage team capacity and availability
4. Monitor resource utilization
5. Balance workload across team

When orchestrating, focus on:
- Task dependencies and critical paths
- Resource constraints and availability
- Priority and urgency assessment
- Load balancing
- Bottleneck identification
- Optimal resource allocation
- Risk mitigation"""

    DEFAULT_CONFIG = GroupSalesManagerConfig()

    def __init__(self, config: Optional[GroupSalesManagerConfig] = None):
        super().__init__(config or self.DEFAULT_CONFIG)

    async def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute resource orchestration task.

        Input schema:
        {
            "task_queue": list[dict],
            "available_resources": dict,
            "constraints": dict,
            "priorities": dict
        }

        Output schema:
        {
            "allocation_plan": dict,
            "schedule": list[dict],
            "resource_utilization": dict,
            "warnings": list[str]
        }
        """
        try:
            task_queue = task.get("task_queue", [])
            available_resources = task.get("available_resources", {})

            if not task_queue and not available_resources:
                return TaskResult(
                    status="error",
                    error="Missing task_queue or available_resources in task",
                    output={}
                )

            result = {
                "allocation_plan": {},
                "schedule": [],
                "resource_utilization": {},
                "warnings": [],
            }

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
