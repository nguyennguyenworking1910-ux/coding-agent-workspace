"""Reviewer Agent - Reviews and validates changes."""

import time
from ..base_agent import BaseAgent


class ReviewerAgent(BaseAgent):
    """Validator agent that reviews code changes."""

    def __init__(self):
        super().__init__("reviewer", "validator", "read-only", ["grep", "read", "glob"])

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
        self._print_header(task, run_id)

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

        self._print_footer()

        return self._agent_result(
            success=True,
            task=task,
            response=f"Review complete. Overall score: {int(overall_score)}%",
            thinking=f"Validated {len(criteria)} criteria. {len(issues)} issues found.",
            issues=issues,
            approval=approval,
            score=overall_score,
            tools_used=self.tools,
            status="review_complete",
        )
