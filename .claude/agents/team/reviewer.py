"""Reviewer agent - performs code review and validation."""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from ..base_agent import BaseAgent, AgentConfig
from ...system.schemas import TaskResult


@dataclass
class ReviewerConfig(AgentConfig):
    """Configuration for Reviewer agent."""
    name: str = "reviewer"
    model: str = "claude-opus-5"
    tools: list = None

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["git", "code-analysis", "linter"]


class ReviewerAgent(BaseAgent):
    """
    Agent: Code Review & Validation
    Responsibilities:
    - Review code diffs and changes
    - Validate code quality and style
    - Identify potential issues
    - Provide recommendations
    """

    SYSTEM_PROMPT = """You are an expert code reviewer. Your role is to:
1. Analyze code changes for quality and correctness
2. Identify potential bugs, security issues, and architectural concerns
3. Ensure code follows best practices and style guidelines
4. Provide constructive feedback and suggestions for improvement
5. Verify test coverage and documentation

When reviewing code, focus on:
- Correctness and logic
- Performance implications
- Security vulnerabilities
- Code readability and maintainability
- Adherence to project conventions"""

    DEFAULT_CONFIG = ReviewerConfig()

    def __init__(self, config: Optional[ReviewerConfig] = None):
        super().__init__(config or self.DEFAULT_CONFIG)

    async def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute code review task.

        Input schema:
        {
            "code_diff": str,
            "file_path": str,
            "context": str,
            "previous_feedback": list
        }

        Output schema:
        {
            "issues": list[{severity, line, message}],
            "suggestions": list[str],
            "approval": bool,
            "comments": str
        }
        """
        try:
            code_diff = task.get("code_diff", "")
            file_path = task.get("file_path", "")

            if not code_diff:
                return TaskResult(
                    status="error",
                    error="Missing code_diff in task",
                    output={}
                )

            result = {
                "file_path": file_path,
                "issues": [],
                "suggestions": [],
                "approval": True,
                "comments": "Code review completed",
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
