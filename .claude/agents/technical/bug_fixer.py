"""Bug Fixer Agent - Fixes bugs and implements changes."""

import re
import time
from pathlib import Path
from tools import get_tool
from ..stream_handler import StreamHandler


class BugFixerAgent:
    """Implementer agent with write access."""

    def __init__(self):
        self.name = "bug_fixer"
        self.type = "implementer"
        self.mode = "write"
        self.has_write_access = True
        self.tools = ["grep", "read", "edit"]
        self._init_tools()

    def _init_tools(self):
        """Initialize tools."""
        self.thought_tool = get_tool("thought")()

    def _plan_fixes(self, task: str, stream: StreamHandler) -> list:
        """Plan fixes based on task description."""
        fixes = []
        project_root = Path(__file__).parent.parent.parent.parent

        # Parse task to understand what needs fixing
        task_lower = task.lower()
        stream.stream_event("ANALYZE_TASK", f"Analyzing task: {task_lower[:50]}...")

        if "bug" in task_lower or "error" in task_lower or "fix" in task_lower:
            fixes.append({
                "type": "code_review",
                "description": "Review code for logical errors and edge cases",
                "priority": "HIGH"
            })
            stream.stream_event("PLAN_CREATED", "Code review strategy planned", {"priority": "HIGH"})
            time.sleep(0.2)

            fixes.append({
                "type": "error_handling",
                "description": "Add proper exception handling",
                "priority": "HIGH"
            })
            stream.stream_event("PLAN_CREATED", "Error handling strategy planned", {"priority": "HIGH"})
            time.sleep(0.2)

        if "security" in task_lower or "vulnerability" in task_lower:
            fixes.append({
                "type": "security_hardening",
                "description": "Remove hardcoded credentials and sensitive data",
                "priority": "CRITICAL"
            })
            stream.stream_event("PLAN_CREATED", "Security hardening strategy planned", {"priority": "CRITICAL"})
            time.sleep(0.2)

            fixes.append({
                "type": "input_validation",
                "description": "Add input validation and sanitization",
                "priority": "HIGH"
            })
            stream.stream_event("PLAN_CREATED", "Input validation strategy planned", {"priority": "HIGH"})
            time.sleep(0.2)

        if "performance" in task_lower or "optimize" in task_lower:
            fixes.append({
                "type": "optimization",
                "description": "Optimize algorithms and reduce complexity",
                "priority": "MEDIUM"
            })
            stream.stream_event("PLAN_CREATED", "Optimization strategy planned", {"priority": "MEDIUM"})
            time.sleep(0.2)

        if "test" in task_lower or "coverage" in task_lower:
            fixes.append({
                "type": "testing",
                "description": "Add unit tests and improve code coverage",
                "priority": "MEDIUM"
            })
            stream.stream_event("PLAN_CREATED", "Testing strategy planned", {"priority": "MEDIUM"})
            time.sleep(0.2)

        # Default fixes if none matched
        if not fixes:
            fixes.append({
                "type": "general_improvement",
                "description": "Review and improve code quality",
                "priority": "MEDIUM"
            })
            stream.stream_event("PLAN_CREATED", "General improvement strategy planned", {"priority": "MEDIUM"})

        return fixes

    def execute(self, task: str, run_id: str = "default") -> dict:
        """
        Fix bugs and implement changes.

        Args:
            task: Fix/implementation task description
            run_id: Unique run ID for streaming

        Returns:
            Fix results
        """
        stream = StreamHandler(self.name, task, run_id)
        stream.stream_header()

        stream.stream_event("INIT", "Bug Fixer agent initialized")
        fixes = self._plan_fixes(task, stream)
        stream.stream_plan(fixes)
        stream.stream_event("COMPLETE", f"Fix plan ready. {len(fixes)} strategies prepared")
        stream.stream_footer()

        return {
            "success": True,
            "agent": "bug_fixer",
            "task": task,
            "response": f"Prepared {len(fixes)} fix strategies for: {task}",
            "thinking": f"Analyzed task and created fix plan with {len(fixes)} strategies",
            "changes": fixes,
            "files_modified": [],
            "tools_used": self.tools,
            "status": "ready_to_fix",
            "stream": stream.get_summary()
        }
