"""Bug Fixer Agent - Fixes bugs and implements changes."""

import re
import time
from pathlib import Path
from tools import get_tool


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

    def _plan_fixes(self, task: str) -> list:
        """Plan fixes based on task description."""
        fixes = []
        task_lower = task.lower()

        print(f"[ANALYZE_TASK] Analyzing task: {task_lower[:50]}...")

        if "bug" in task_lower or "error" in task_lower or "fix" in task_lower:
            fixes.append({
                "type": "code_review",
                "description": "Review code for logical errors and edge cases",
                "priority": "HIGH"
            })
            print("[PLAN_CREATED] Code review strategy planned")
            time.sleep(0.2)

            fixes.append({
                "type": "error_handling",
                "description": "Add proper exception handling",
                "priority": "HIGH"
            })
            print("[PLAN_CREATED] Error handling strategy planned")
            time.sleep(0.2)

        if "security" in task_lower or "vulnerability" in task_lower:
            fixes.append({
                "type": "security_hardening",
                "description": "Remove hardcoded credentials and sensitive data",
                "priority": "CRITICAL"
            })
            print("[PLAN_CREATED] Security hardening strategy planned")
            time.sleep(0.2)

            fixes.append({
                "type": "input_validation",
                "description": "Add input validation and sanitization",
                "priority": "HIGH"
            })
            print("[PLAN_CREATED] Input validation strategy planned")
            time.sleep(0.2)

        if "performance" in task_lower or "optimize" in task_lower:
            fixes.append({
                "type": "optimization",
                "description": "Optimize algorithms and reduce complexity",
                "priority": "MEDIUM"
            })
            print("[PLAN_CREATED] Optimization strategy planned")
            time.sleep(0.2)

        if "test" in task_lower or "coverage" in task_lower:
            fixes.append({
                "type": "testing",
                "description": "Add unit tests and improve code coverage",
                "priority": "MEDIUM"
            })
            print("[PLAN_CREATED] Testing strategy planned")
            time.sleep(0.2)

        if not fixes:
            fixes.append({
                "type": "general_improvement",
                "description": "Review and improve code quality",
                "priority": "MEDIUM"
            })
            print("[PLAN_CREATED] General improvement strategy planned")

        return fixes

    def execute(self, task: str, run_id: str = "default") -> dict:
        """
        Fix bugs and implement changes.

        Args:
            task: Fix/implementation task description
            run_id: Unique run ID

        Returns:
            Fix results
        """
        print(f"\n{'='*70}")
        print(f"AGENT: BUG_FIXER")
        print(f"RUN ID: {run_id}")
        print(f"TASK: {task}")
        print(f"{'='*70}\n")

        print("[i] [BUG_FIXER] Agent initialized")
        fixes = self._plan_fixes(task)

        print(f"\n[FIX PLAN]")
        for i, fix in enumerate(fixes, 1):
            print(f"  {i}. {fix['type'].upper()}")
            print(f"     {fix['description']}")
            print(f"     Priority: {fix['priority']}\n")

        print(f"[i] [BUG_FIXER] Fix plan ready. {len(fixes)} strategies prepared")

        print(f"\n{'='*70}")
        print(f"STATUS: COMPLETED")
        print(f"{'='*70}\n")

        return {
            "success": True,
            "agent": "bug_fixer",
            "task": task,
            "response": f"Prepared {len(fixes)} fix strategies for: {task}",
            "thinking": f"Analyzed task and created fix plan with {len(fixes)} strategies",
            "changes": fixes,
            "files_modified": [],
            "tools_used": self.tools,
            "status": "ready_to_fix"
        }
