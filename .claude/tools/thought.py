"""Thought Tool - Reasoning and thinking capability."""

from .tool_result import ToolResult


class ThoughtTool:
    """Tool for agent reasoning and thinking."""

    def __init__(self):
        self.name = "thought"
        self.description = "Reasoning tool for agents to think through problems"
        self.type = "reasoning"

    def execute(self, thought: str) -> dict:
        """
        Execute a thought/reasoning step.

        Args:
            thought: Description of what to think about

        Returns:
            Thought result
        """
        return ToolResult.ok(
            "thought",
            input=thought,
            type="reasoning_step",
        )

    def analyze(self, task: str, context: dict = None) -> dict:
        """
        Analyze a task through reasoning.

        Args:
            task: Task to analyze
            context: Optional context for analysis

        Returns:
            Analysis result
        """
        return ToolResult.ok(
            "thought",
            task=task,
            context=context or {},
            analysis=f"Analyzed: {task}",
            type="analysis",
        )

    def plan(self, goal: str, constraints: list = None) -> dict:
        """
        Create a plan through reasoning.

        Args:
            goal: What to plan for
            constraints: Optional constraints

        Returns:
            Plan result
        """
        return ToolResult.ok(
            "thought",
            goal=goal,
            constraints=constraints or [],
            plan=[
                "1. Understand the goal",
                "2. Identify constraints",
                "3. Generate options",
                "4. Evaluate options",
                "5. Select best approach"
            ],
            type="planning",
        )

    def evaluate(self, statement: str, criteria: list = None) -> dict:
        """
        Evaluate something through reasoning.

        Args:
            statement: What to evaluate
            criteria: Evaluation criteria

        Returns:
            Evaluation result
        """
        return ToolResult.ok(
            "thought",
            statement=statement,
            criteria=criteria or [],
            evaluation=f"Evaluated: {statement}",
            type="evaluation",
        )
