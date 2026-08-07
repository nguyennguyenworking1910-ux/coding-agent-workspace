"""Red Team agent - performs adversarial testing and security review.

⚠️ CRITICAL REQUIREMENT: This agent MUST read ARCHITECTURE.md before execution.
See .claude/documents/AGENT_INITIALIZATION.md for mandatory initialization checklist.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from ..base_agent import BaseAgent, AgentConfig
from ...system.schemas import TaskResult
from ..system_init import get_architecture_check, architecture_acknowledgment


@dataclass
class RedTeamConfig(AgentConfig):
    """Configuration for Red Team agent."""
    name: str = "red_team"
    model: str = "claude-opus-5"
    tools: list = None

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["security-scan", "testing", "fuzzing"]


class RedTeamAgent(BaseAgent):
    """
    Agent: Security & Edge-Case Testing

    ⚠️ STEP 1: READ ARCHITECTURE.md BEFORE EXECUTING ANY TASK
    See .claude/documents/AGENT_INITIALIZATION.md

    Responsibilities:
    - Identify security vulnerabilities
    - Test edge cases and error scenarios
    - Perform adversarial testing
    - Find potential exploits

    Must understand: System architecture, folder structure, and critical rules
    """

    SYSTEM_PROMPT = """You are a security expert and adversarial tester. Your role is to:
1. Identify security vulnerabilities and attack vectors
2. Test for edge cases, boundary conditions, and error scenarios
3. Perform fuzzing and adversarial testing
4. Find potential exploits or misuse cases
5. Validate security controls and error handling

When testing, focus on:
- Input validation and sanitization
- Authentication and authorization
- Cryptographic security
- Concurrency and race conditions
- Resource exhaustion and DoS vectors
- Error messages revealing sensitive information"""

    DEFAULT_CONFIG = RedTeamConfig()

    def __init__(self, config: Optional[RedTeamConfig] = None):
        super().__init__(config or self.DEFAULT_CONFIG)

    async def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute security testing task.

        Input schema:
        {
            "feature_spec": str,
            "code": str,
            "threat_model": str
        }

        Output schema:
        {
            "vulnerabilities": list[{type, severity, description}],
            "test_cases": list[str],
            "recommendations": list[str]
        }
        """
        try:
            feature_spec = task.get("feature_spec", "")
            code = task.get("code", "")

            if not feature_spec and not code:
                return TaskResult(
                    status="error",
                    error="Missing feature_spec or code in task",
                    output={}
                )

            result = {
                "vulnerabilities": [],
                "test_cases": [],
                "recommendations": [],
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
