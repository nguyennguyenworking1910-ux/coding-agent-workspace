"""Worker for executing tasks."""

from typing import Optional, Callable, Dict, Any
from .schemas import TaskResult


class Worker:
    """Generic worker for task execution."""

    def __init__(self, name: str):
        """Initialize worker."""
        self.name = name

    def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute a task.

        Args:
            task: Task specification

        Returns:
            TaskResult with execution outcome
        """
        return TaskResult(
            status="success",
            output={"result": "Task executed"}
        )
