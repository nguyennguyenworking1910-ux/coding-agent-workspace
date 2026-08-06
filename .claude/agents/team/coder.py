"""Coder agent - implements features and refactoring."""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from ..base_agent import BaseAgent, AgentConfig
from ...system.schemas import TaskResult


@dataclass
class CoderConfig(AgentConfig):
    """Configuration for Coder agent."""
    name: str = "coder"
    model: str = "claude-opus-5"
    tools: list = None

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["git", "file-ops", "compiler"]


class CoderAgent(BaseAgent):
    """
    Agent: Implementation & Execution
    Responsibilities:
    - Implement features and changes
    - Perform refactoring
    - Execute tasks
    - Ensure test coverage
    """

    SYSTEM_PROMPT = """You are an expert software engineer and architect. Your role is to:
1. Implement features based on specifications
2. Perform refactoring and code improvements
3. Execute complex technical tasks
4. Ensure proper testing and validation
5. Follow code standards and best practices

When implementing, focus on:
- Clear understanding of requirements
- Design before implementation
- Clean, maintainable code
- Comprehensive test coverage
- Documentation and comments
- Performance and efficiency
- Security considerations"""

    DEFAULT_CONFIG = CoderConfig()

    def __init__(self, config: Optional[CoderConfig] = None):
        super().__init__(config or self.DEFAULT_CONFIG)

    async def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute coding task.

        Input schema:
        {
            "task_spec": str,
            "requirements": str,
            "context": str,
            "language": str
        }

        Output schema:
        {
            "changes": list[{file, modifications}],
            "test_coverage": dict,
            "documentation": str,
            "summary": str
        }
        """
        try:
            task_spec = task.get("task_spec", "")
            requirements = task.get("requirements", "")

            if not task_spec and not requirements:
                return TaskResult(
                    status="error",
                    error="Missing task_spec or requirements in task",
                    output={}
                )

            result = {
                "changes": [],
                "test_coverage": {},
                "documentation": "",
                "summary": "",
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
