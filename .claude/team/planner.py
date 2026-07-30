"""Planner for creating and validating execution plans."""

from typing import Tuple, List, Dict, Set, Optional
from .schemas import (
    AgentPlan,
    AgentTask,
    AgentAssignment,
    TaskStatus,
    AgentRole,
)
from .claude_planner import ClaudePlanner


class Planner:
    """Creates agent plans; validates for execution; falls back gracefully."""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.claude_planner = ClaudePlanner(max_workers=max_workers)

    def create_plan(
        self, run_id: str, request: str, use_claude: bool = False
    ) -> Tuple[AgentPlan, bool]:
        """
        Create plan for request.

        Returns: (plan, is_valid)
        If invalid, returns fallback lead-only plan with is_valid=False
        """
        try:
            if use_claude:
                # Try Claude-powered planning (M4)
                plan = self._claude_plan(run_id, request)
                if plan is not None:
                    validation_errors = plan.validate_plan()
                    if not validation_errors:
                        print(f"[PLANNER] Claude-based plan created: {plan.summary}")
                        return plan, True
                    else:
                        print(f"[PLANNER] Claude plan validation failed: {validation_errors}")
                # Fall through to heuristic if Claude fails

            # Heuristic rules (M1) or fallback from Claude
            plan = self._heuristic_plan(run_id, request)

            # Validate
            validation_errors = plan.validate_plan()
            if validation_errors:
                print(f"[PLANNER] Validation errors: {validation_errors}")
                return self._fallback_lead_only_plan(run_id, request), False

            return plan, True
        except Exception as e:
            print(f"[PLANNER] Planning failed: {e}")
            return self._fallback_lead_only_plan(run_id, request), False

    def _heuristic_plan(self, run_id: str, request: str) -> AgentPlan:
        """Default heuristic: decide lead-only vs multi-agent based on keywords."""
        if self._is_multi_agent_worthy(request):
            return self._create_multi_agent_plan(run_id, request)
        else:
            return self._fallback_lead_only_plan(run_id, request)

    def _is_multi_agent_worthy(self, request: str) -> bool:
        """Heuristic: does request justify parallelism?"""
        keywords = [
            "review",
            "analyze",
            "test",
            "investigate",
            "multiple",
            "concurrent",
            "parallel",
            "audit",
            "check",
            "validate",
        ]
        request_lower = request.lower()
        return any(kw in request_lower for kw in keywords)

    def _create_multi_agent_plan(self, run_id: str, request: str) -> AgentPlan:
        """Create a 2-3 worker plan with researcher and reviewer."""
        tasks = [
            AgentTask(
                task_id="task_researcher",
                title="Initial Research",
                instructions=request,
                owner_agent_id="researcher",
                depends_on=[],
                acceptance_criteria=["findings documented", "analysis complete"],
            ),
            AgentTask(
                task_id="task_reviewer",
                title="Review Findings",
                instructions=f"Review the research findings from the initial investigation. Original request: {request}",
                owner_agent_id="reviewer",
                depends_on=["task_researcher"],
                acceptance_criteria=["feedback provided", "review complete"],
            ),
            AgentTask(
                task_id="task_synthesis",
                title="Lead Synthesis",
                instructions="Synthesize findings and feedback from all agents into final response",
                owner_agent_id="lead",
                depends_on=["task_reviewer"],
                acceptance_criteria=["final response ready"],
            ),
        ]

        agents = [
            AgentAssignment(
                agent_id="researcher",
                role=AgentRole.RESEARCHER,
                objective="Investigate the codebase and document findings",
                owned_paths=[],
                read_only=True,
            ),
            AgentAssignment(
                agent_id="reviewer",
                role=AgentRole.REVIEWER,
                objective="Review findings and identify gaps or improvements",
                owned_paths=[],
                read_only=True,
            ),
        ]

        return AgentPlan(
            run_id=run_id,
            summary=f"Multi-agent plan: research + review for '{request}'",
            parallelism_justified=True,
            synthesis_task_id="task_synthesis",
            agents=agents,
            tasks=tasks,
        )

    def _claude_plan(self, run_id: str, request: str) -> Optional[AgentPlan]:
        """Generate plan using Claude (M4)."""
        return self.claude_planner.create_plan(run_id, request)

    def _fallback_lead_only_plan(self, run_id: str, request: str) -> AgentPlan:
        """Fallback: lead-only execution (no workers)."""
        return AgentPlan(
            run_id=run_id,
            summary=f"Lead-only execution: {request}",
            parallelism_justified=False,
            synthesis_task_id="task_lead",
            agents=[],
            tasks=[
                AgentTask(
                    task_id="task_lead",
                    title="Lead Execution",
                    instructions=request,
                    owner_agent_id="lead",
                    depends_on=[],
                    acceptance_criteria=["response provided"],
                )
            ],
        )
