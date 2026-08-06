"""Claude-powered planning for team composition and task generation."""

import json
import re
from typing import Tuple, Optional, Dict, Any, List

from ..system.schemas import (
    AgentPlan,
    AgentTask,
    AgentAssignment,
    AgentRole,
    TaskStatus,
)
from .claude_runner import ClaudeRunner


class ClaudePlanner:
    """Uses Claude to intelligently plan multi-agent execution."""

    def __init__(self, max_workers: int = 4, timeout: float = 60.0):
        self.max_workers = max_workers
        self.timeout = timeout
        self.runner = ClaudeRunner(
            agent_id="planner",
            task_id="planning",
            run_id="planning",
            timeout=timeout,
        )

    def create_plan(self, run_id: str, request: str) -> Optional[AgentPlan]:
        """
        Create plan using Claude analysis.

        Returns: plan or None if planning fails/is invalid
        """
        try:
            # Call Claude to analyze request
            plan_data = self._get_claude_plan(request)

            if not plan_data:
                return None

            # Convert Claude's output to AgentPlan
            plan = self._build_agent_plan(run_id, request, plan_data)

            # Validate
            validation_errors = plan.validate_plan()
            if validation_errors:
                print(f"[CLAUDE_PLANNER] Validation errors: {validation_errors}")
                return None

            return plan

        except Exception as e:
            print(f"[CLAUDE_PLANNER] Planning failed: {e}")
            return None

    def _get_claude_plan(self, request: str) -> Optional[Dict[str, Any]]:
        """Call Claude to analyze request and return plan data."""

        system_prompt = """You are a planning expert for multi-agent systems.
Analyze the user's request and decide:
1. How many agents needed (1-4)
2. What roles: researcher, implementer, reviewer, tester, custom
3. What tasks with clear dependencies
4. Task descriptions and acceptance criteria

Respond with ONLY valid JSON (no markdown, no explanation)."""

        user_prompt = f"""Analyze this request and create a multi-agent plan:

REQUEST: {request}

Return a JSON object with this exact structure:
{{
  "agent_count": <1-4>,
  "agents": [
    {{
      "agent_id": "string (researcher/implementer/reviewer/tester/custom_name)",
      "role": "string (RESEARCHER|IMPLEMENTER|REVIEWER|TESTER|CUSTOM)",
      "objective": "string",
      "read_only": boolean
    }}
  ],
  "tasks": [
    {{
      "title": "string",
      "instructions": "string",
      "owner_agent_id": "string",
      "depends_on": ["task_id", ...],
      "acceptance_criteria": ["string", ...]
    }}
  ]
}}

CONSTRAINTS:
- agent_count must be 1-4
- Each task must have a valid owner_agent_id from agents list OR "lead"
- Tasks can depend on other tasks (use their index as task_id: "task_0", "task_1", etc)
- Lead always does final synthesis if there are workers
- No cycles in dependencies
- Be concise but complete"""

        # Call Claude via subprocess
        try:
            success = self.runner.run(
                prompt=user_prompt,
                system_prompt=system_prompt,
                timeout=self.timeout,
            )

            if not success:
                return None

            # Get the output from runner
            output = self.runner.get_result()
            if not output:
                return None

            # Parse JSON from output
            return self._parse_claude_json(output)

        except Exception as e:
            print(f"[CLAUDE_PLANNER] Claude call failed: {e}")
            return None

    def _parse_claude_json(self, output: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON from Claude's response."""
        try:
            # Try to find JSON block
            json_match = re.search(r"\{[\s\S]*\}", output)
            if not json_match:
                return None

            json_str = json_match.group(0)
            data = json.loads(json_str)

            # Validate required structure
            if not isinstance(data, dict):
                return None
            if "agents" not in data or "tasks" not in data:
                return None
            if not isinstance(data["agents"], list) or not isinstance(data["tasks"], list):
                return None
            if len(data["tasks"]) == 0:
                return None

            return data

        except (json.JSONDecodeError, AttributeError) as e:
            print(f"[CLAUDE_PLANNER] Failed to parse JSON: {e}")
            return None

    def _build_agent_plan(
        self, run_id: str, request: str, plan_data: Dict[str, Any]
    ) -> AgentPlan:
        """Convert Claude's plan data to AgentPlan schema."""

        # Extract and validate agent_count
        agent_count = plan_data.get("agent_count", 1)
        if not isinstance(agent_count, int) or agent_count < 1 or agent_count > 4:
            agent_count = 1

        # Build agent assignments
        agents = []
        agent_id_map = {}  # Map from agent_id to AgentRole
        for agent_data in plan_data.get("agents", []):
            agent_id = agent_data.get("agent_id", "unknown")
            role_str = agent_data.get("role", "CUSTOM").upper()

            # Map role string to enum
            try:
                role = AgentRole[role_str]
            except KeyError:
                role = AgentRole.CUSTOM

            agents.append(
                AgentAssignment(
                    agent_id=agent_id,
                    role=role,
                    objective=agent_data.get("objective", f"{agent_id} task"),
                    owned_paths=[],
                    read_only=agent_data.get("read_only", True),
                )
            )
            agent_id_map[agent_id] = role

        # Build tasks
        tasks = []
        task_id_map = {}  # Map task index to task_id

        for idx, task_data in enumerate(plan_data.get("tasks", [])):
            task_id = f"task_{idx}"
            task_id_map[idx] = task_id

            # Resolve dependencies (from indices to task_ids)
            depends_on = []
            for dep_idx in task_data.get("depends_on", []):
                if isinstance(dep_idx, int) and dep_idx in task_id_map:
                    depends_on.append(task_id_map[dep_idx])

            owner_agent_id = task_data.get("owner_agent_id", "lead")

            tasks.append(
                AgentTask(
                    task_id=task_id,
                    title=task_data.get("title", f"Task {idx}"),
                    instructions=task_data.get("instructions", task_data.get("title", "")),
                    owner_agent_id=owner_agent_id,
                    depends_on=depends_on,
                    acceptance_criteria=task_data.get(
                        "acceptance_criteria", ["task completed"]
                    ),
                    status=TaskStatus.PENDING,
                )
            )

        # Add synthesis task if there are workers
        if agents:
            synthesis_task_id = f"task_{len(tasks)}"
            synthesis_deps = [
                t.task_id for t in tasks if t.owner_agent_id != "lead"
            ]

            tasks.append(
                AgentTask(
                    task_id=synthesis_task_id,
                    title="Synthesis",
                    instructions="Synthesize findings from all agents into final response",
                    owner_agent_id="lead",
                    depends_on=synthesis_deps,
                    acceptance_criteria=["final response ready"],
                    status=TaskStatus.PENDING,
                )
            )
            synthesis_id = synthesis_task_id
        else:
            # Lead-only: synthesis is the only task
            synthesis_id = tasks[0].task_id if tasks else "task_0"

        return AgentPlan(
            run_id=run_id,
            summary=f"Claude-planned: {request[:100]}",
            parallelism_justified=len(agents) > 0,
            synthesis_task_id=synthesis_id,
            agents=agents,
            tasks=tasks,
        )
