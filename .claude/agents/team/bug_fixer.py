"""Bug Fixer agent - identifies and fixes issues.

⚠️ CRITICAL REQUIREMENT: This agent MUST read ARCHITECTURE.md before execution.
See .claude/documents/AGENT_INITIALIZATION.md for mandatory initialization checklist.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from ..base_agent import BaseAgent, AgentConfig
from ..system_init import get_architecture_check, architecture_acknowledgment
from ...system.schemas import TaskResult


@dataclass
class BugFixerConfig(AgentConfig):
    """Configuration for Bug Fixer agent."""
    name: str = "bug_fixer"
    model: str = "claude-opus-5"
    tools: list = None

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["debugging", "code-analysis", "testing"]


class BugFixerAgent(BaseAgent):
    """
    Agent: Bug Identification & Fix

    ⚠️ STEP 1: READ ARCHITECTURE.md BEFORE EXECUTING ANY TASK
    See .claude/documents/AGENT_INITIALIZATION.md

    Responsibilities:
    - Analyze test failures and errors
    - Identify root causes
    - Propose and implement fixes
    - Verify fixes resolve issues

    Must understand: System architecture, folder structure, and critical rules
    especially documentation placement (.md files go in .claude/documents/)
    """

    SYSTEM_PROMPT = """You are an expert debugger and problem solver. Your role is to:
1. Analyze test failures, error logs, and bug reports
2. Identify root causes of issues
3. Propose fixes and improvements
4. Implement solutions
5. Verify fixes resolve the problem

When debugging, focus on:
- Understanding the error context
- Tracing the execution flow
- Identifying the actual vs expected behavior
- Root cause analysis
- Proposing minimal, targeted fixes
- Ensuring fixes don't introduce regressions"""

    DEFAULT_CONFIG = BugFixerConfig()

    def __init__(self, config: Optional[BugFixerConfig] = None):
        super().__init__(config or self.DEFAULT_CONFIG)

    async def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute bug fix task.

        Input schema:
        {
            "test_failure": str,
            "error_logs": str,
            "code": str,
            "context": str
        }

        Output schema:
        {
            "root_cause": str,
            "fix_candidates": list[str],
            "recommended_fix": str,
            "explanation": str,
            "test_verification": str
        }
        """
        try:
            test_failure = task.get("test_failure", "")
            error_logs = task.get("error_logs", "")

            if not test_failure and not error_logs:
                return TaskResult(
                    status="error",
                    error="Missing test_failure or error_logs in task",
                    output={}
                )

            result = {
                "root_cause": "",
                "fix_candidates": [],
                "recommended_fix": "",
                "explanation": "",
                "test_verification": "",
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
