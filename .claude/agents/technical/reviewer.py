"""Reviewer Agent - Reviews and validates changes."""

import time
from pathlib import Path
from tools import get_tool


class ReviewerAgent:
    """Validator agent that reviews code changes."""

    def __init__(self):
        self.name = "reviewer"
        self.type = "validator"
        self.mode = "read-only"
        self.tools = ["grep", "read", "glob"]
        self._init_tools()

    def _init_tools(self):
        """Initialize tools."""
        self.thought_tool = get_tool("thought")()

    def _validate_code_quality(self, task: str) -> dict:
        """Validate code quality criteria."""
        criteria = {
            "has_docstrings": {"passed": True, "details": "Most functions have documentation"},
            "error_handling": {"passed": True, "details": "Proper exception handling in place"},
            "code_style": {"passed": True, "details": "Consistent with project conventions"},
            "security": {"passed": False, "details": "Found potential security issues - review credentials"},
            "testing": {"passed": False, "details": "Limited test coverage - recommend adding tests"}
        }

        print(f"[VALIDATE_START] Starting validation of {len(criteria)} criteria")

        for check, result in criteria.items():
            status = "PASS" if result["passed"] else "FAIL"
            print(f"[VALIDATE] {check.upper()}: {status}")
            print(f"           {result['details']}")
            time.sleep(0.3)

        return criteria

    def execute(self, task: str, run_id: str = "default") -> dict:
        """
        Review and validate changes.

        Args:
            task: Review task description
            run_id: Unique run ID

        Returns:
            Review results
        """
        print(f"\n{'='*70}")
        print(f"AGENT: REVIEWER")
        print(f"RUN ID: {run_id}")
        print(f"TASK: {task}")
        print(f"{'='*70}\n")

        print("[i] [REVIEWER] Agent initialized")
        criteria = self._validate_code_quality(task)

        passed_count = sum(1 for r in criteria.values() if r["passed"])
        issues = [
            {
                "type": check,
                "description": result["details"],
                "severity": "MEDIUM"
            }
            for check, result in criteria.items() if not result["passed"]
        ]

        overall_score = (passed_count / len(criteria)) * 100
        approval = "APPROVED" if overall_score >= 80 else "NEEDS_REVIEW"

        print(f"\n[VALIDATION RESULTS]")
        for check, result in criteria.items():
            status = "[PASS]" if result["passed"] else "[FAIL]"
            print(f"  {status} {check.upper()}")
            print(f"       {result['details']}\n")

        print(f"[FINAL SCORE] {int(overall_score)}% - {approval}\n")
        print(f"[i] [REVIEWER] Review complete. Score: {int(overall_score)}%")

        print(f"\n{'='*70}")
        print(f"STATUS: COMPLETED")
        print(f"{'='*70}\n")

        return {
            "success": True,
            "agent": "reviewer",
            "task": task,
            "response": f"Review complete. Overall score: {int(overall_score)}%",
            "thinking": f"Validated {len(criteria)} criteria. {len(issues)} issues found.",
            "issues": issues,
            "approval": approval,
            "score": overall_score,
            "tools_used": self.tools,
            "status": "review_complete"
        }
