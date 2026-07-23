"""Diagnostician Agent - Analyzes code and finds issues."""

from tools import get_tool


class DiagnosticianAgent:
    """Analyzer agent that finds bugs and issues."""

    def __init__(self):
        self.name = "diagnostician"
        self.type = "analyzer"
        self.mode = "read-only"
        self.tools = ["thought"]
        self._init_tools()

    def _init_tools(self):
        """Initialize tools."""
        self.thought_tool = get_tool("thought")()

    def execute(self, task: str) -> dict:
        """
        Analyze code and find issues.

        Args:
            task: Analysis task description

        Returns:
            Analysis results
        """
        # Use thought tool to analyze
        analysis_result = self.thought_tool.analyze(task)

        return {
            "success": True,
            "agent": "diagnostician",
            "task": task,
            "response": f"Diagnostician analyzing: {task}",
            "thinking": analysis_result,
            "findings": [],
            "tools_used": self.tools,
            "status": "analysis_complete"
        }
