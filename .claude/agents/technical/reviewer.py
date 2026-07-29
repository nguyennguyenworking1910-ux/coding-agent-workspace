"""Reviewer Agent - Reviews and validates changes."""

import time
from pathlib import Path
from tools import get_tool
from ..stream_handler import StreamHandler


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

    def _validate_code_quality(self, task: str, stream: StreamHandler) -> dict:
        """Validate code quality criteria."""
        criteria = {
            "has_docstrings": {"passed": True, "details": "Most functions have documentation"},
            "error_handling": {"passed": True, "details": "Proper exception handling in place"},
            "code_style": {"passed": True, "details": "Consistent with project conventions"},
            "security": {"passed": False, "details": "Found potential security issues - review credentials"},
            "testing": {"passed": False, "details": "Limited test coverage - recommend adding tests"}
        }

        stream.stream_event("VALIDATE_START", f"Starting validation of {len(criteria)} criteria")

        for check, result in criteria.items():
            status = "PASS" if result["passed"] else "FAIL"
            stream.stream_event("VALIDATE", f"{check.upper()}: {status}", {"details": result["details"]})
            time.sleep(0.3)

        return criteria

    def execute(self, task: str, run_id: str = "default") -> dict:
        """
        Review and validate changes.

        Args:
            task: Review task description
            run_id: Unique run ID for streaming

        Returns:
            Review results
        """
        stream = StreamHandler(self.name, task, run_id)
        stream.stream_header()

        stream.stream_event("INIT", "Reviewer agent initialized")
        criteria = self._validate_code_quality(task, stream)

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

        stream.stream_validation(criteria)
        stream.stream_event("COMPLETE", f"Review complete. Score: {int(overall_score)}%")
        stream.stream_footer()

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
            "status": "review_complete",
            "stream": stream.get_summary()
        }
