"""Reviewer Agent - Reviews and validates changes."""

from tools import get_tool


class ReviewerAgent:
    """Validator agent that reviews code changes."""

    def __init__(self):
        self.name = "reviewer"
        self.type = "validator"
        self.mode = "read-only"
        self.tools = ["thought"]
        self._init_tools()

    def _init_tools(self):
        """Initialize tools."""
        self.thought_tool = get_tool("thought")()

    def execute(self, task: str) -> dict:
        """
        Review and validate changes.

        Args:
            task: Review task description

        Returns:
            Review results
        """
        # Use thought tool to evaluate
        evaluation_result = self.thought_tool.evaluate(
            task,
            ["code_quality", "functionality", "best_practices"]
        )

        return {
            "success": True,
            "agent": "reviewer",
            "task": task,
            "response": f"Reviewer validating: {task}",
            "thinking": evaluation_result,
            "issues": [],
            "approval": "pending",
            "tools_used": self.tools,
            "status": "review_complete"
        }
