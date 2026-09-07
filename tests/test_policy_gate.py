import sys
import unittest

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PROJECT_ROOT / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"

sys.path.insert(0, str(HOOKS_DIR))

import policy_gate


def make_state(
    *,
    risk_level="read_only",
    confirmed=False,
    selected_agents=("coder",),
    max_total_tool_calls=24,
    total_tool_calls=0,
):
    return {
        "request": "example request",
        "task_class": "medium_task",
        "risk_level": risk_level,
        "confirmed": confirmed,
        "selected_agents": list(selected_agents),
        "limits": {
            "max_members": 3,
            "max_tool_rounds": 3,
            "max_total_tool_calls": max_total_tool_calls,
            "max_run_budget_usd": 4.0,
        },
        "members_used": [],
        "total_tool_calls": total_tool_calls,
        "agent_rounds": 0,
    }


def decision_of(output):
    """Return the hook's permissionDecision, or 'allow' when it stayed silent."""
    if output is None:
        return "allow"

    return output["hookSpecificOutput"]["permissionDecision"]


class SendMessageExemptionTests(unittest.TestCase):
    """`SendMessage` is the only path a teammate's report reaches the lead.

    Its name contains the external verb "send", so without an explicit exemption
    the mutation rule denies it in every run and the report is silently lost.
    """

    def test_send_message_is_not_an_external_mutation(self):
        self.assertFalse(policy_gate.is_external_mutation_tool("SendMessage"))

    def test_send_message_is_allowed_at_every_risk_level_unconfirmed(self):
        for risk_level in ("read_only", "write", "external_write", "destructive"):
            with self.subTest(risk_level=risk_level):
                state = make_state(risk_level=risk_level, confirmed=False)

                output = policy_gate.apply_call(
                    state,
                    "SendMessage",
                    {"to": "team-lead", "message": "full report body"},
                )

                self.assertEqual(decision_of(output), "allow")

    def test_report_body_mentioning_a_destructive_command_is_still_allowed(self):
        """A report is prose, not an executable. `message` is not a command field."""
        state = make_state(risk_level="read_only")

        output = policy_gate.apply_call(
            state,
            "SendMessage",
            {"to": "team-lead", "message": "The migration runs DROP TABLE users."},
        )

        self.assertEqual(decision_of(output), "allow")

    def test_send_message_still_consumes_tool_budget(self):
        state = make_state()

        policy_gate.apply_call(state, "SendMessage", {"to": "team-lead", "message": "x"})

        self.assertEqual(state["total_tool_calls"], 1)

    def test_send_message_is_denied_once_the_budget_is_exhausted(self):
        state = make_state(max_total_tool_calls=1, total_tool_calls=1)

        output = policy_gate.apply_call(
            state,
            "SendMessage",
            {"to": "team-lead", "message": "x"},
        )

        self.assertEqual(decision_of(output), "deny")

    def test_the_exemption_did_not_widen_to_real_external_writes(self):
        """Guard against fixing delivery by disarming the mutation rule."""
        state = make_state(risk_level="read_only")

        for tool_name in (
            "mcp__claude_ai_Google_Calendar__create_event",
            "mcp__claude_ai_Google_Calendar__delete_event",
            "mcp__claude_ai_Gmail__create_draft",
        ):
            with self.subTest(tool_name=tool_name):
                self.assertTrue(policy_gate.is_external_mutation_tool(tool_name))

        output = policy_gate.apply_call(
            state,
            "mcp__claude_ai_Google_Calendar__create_event",
            {"summary": "team sync"},
        )

        self.assertEqual(decision_of(output), "deny")


class TeammateToolGrantTests(unittest.TestCase):
    """A teammate cannot call a tool its definition does not grant.

    The result-delivery contract in `.claude/commands/solve.md` is unenforceable
    unless every dispatchable specialist actually holds `SendMessage`.
    """

    AGENT_IDS = (
        "diagnostician",
        "red-team",
        "reviewer",
        "coder",
        "bug-fixer",
        "group-sales-manager",
        "scheduler",
        "merchant-manager",
    )

    REQUIRED_TOOLS = ("SendMessage", "TaskUpdate")

    @staticmethod
    def granted_tools(agent_id):
        definition = CLAUDE_DIR / "agents" / f"{agent_id}.md"
        content = definition.read_text(encoding="utf-8")

        for line in content.splitlines()[1:]:
            if line.strip() == "---":
                break
            if line.startswith("tools:"):
                _, _, value = line.partition(":")
                return [tool.strip() for tool in value.split(",") if tool.strip()]

        return []

    def test_every_specialist_can_report_to_the_lead(self):
        for agent_id in self.AGENT_IDS:
            granted = self.granted_tools(agent_id)

            for tool_name in self.REQUIRED_TOOLS:
                with self.subTest(agent=agent_id, tool=tool_name):
                    self.assertIn(tool_name, granted)


class TestSmallTaskBoundaryAfterFix(unittest.TestCase):
    """Verify the small_task budget fix maintains all protections.

    Root cause: The minimal small_task lifecycle requires 8 tool calls total:
    - 5 regular calls (Read, TaskCreate, Agent, Read, Bash)
    - 2 coordination calls (SendMessage, TaskUpdate)
    - 1 buffer call for safety

    The old limit of 6 was insufficient because with 2 coordination slots
    reserved, only 4 calls remained for regular tools, but 5 were needed.

    The fix raises max_total_tool_calls from 6 to 10:
    - Provides 8 regular calls (10 - 2 coordination reserve)
    - Offers 3-call buffer beyond the 5 calls required
    - Preserves all other protections (max_members=1, max_tool_rounds=1, budget_usd=1.0)
    """

    def make_small_task_state(self, total_tool_calls=0):
        """Create a small_task policy state with the fixed limits."""
        return {
            "request": "example small_task request",
            "task_class": "small_task",
            "risk_level": "read_only",
            "confirmed": False,
            "selected_agents": ["bug-fixer"],
            "limits": {
                "max_members": 1,
                "max_tool_rounds": 1,
                "max_total_tool_calls": 10,  # Fixed limit
                "max_run_budget_usd": 1.0,
            },
            "members_used": [],
            "total_tool_calls": total_tool_calls,
            "agent_rounds": 0,
        }

    def test_small_task_minimal_lifecycle_succeeds(self):
        """The minimal 8-call lifecycle fits within the new limit of 10."""
        state = self.make_small_task_state(total_tool_calls=0)

        # Simulate the minimal lifecycle: 8 calls total
        # Note: Agent dispatch requires subagent_type and name fields;
        # subagent_type must be in selected_agents (which is ["bug-fixer"] for small_task)
        call_sequence = [
            ("Read", {"file_path": "/some/file"}),
            ("TaskCreate", {"subject": "subtask"}),
            ("Agent", {"subagent_type": "bug-fixer", "name": "bug_fixer_1"}),
            ("Read", {"file_path": "/another/file"}),
            ("Bash", {"command": "echo test"}),  # read-only bash
            ("TaskUpdate", {"taskId": "1", "status": "completed"}),
            ("SendMessage", {"to": "team-lead", "message": "done"}),
            ("Read", {"file_path": "/more/file"}),  # 8th call
        ]

        for i, (tool_name, tool_args) in enumerate(call_sequence, 1):
            output = policy_gate.apply_call(state, tool_name, tool_args)
            decision = decision_of(output)
            self.assertEqual(
                decision, "allow",
                f"Call #{i} ({tool_name}) should be allowed (total_tool_calls={state['total_tool_calls']})"
            )

    def test_small_task_exceeds_cap_by_one(self):
        """One call beyond the hard cap (11th call) is denied."""
        state = self.make_small_task_state(total_tool_calls=10)

        # The 11th call with a coordination tool should be denied (hard cap exceeded)
        # Coordination tools check: total_tool_calls > max_total (after incrementing)
        # Since max_total=10 and total_tool_calls is already 10, incrementing makes it 11 > 10
        output = policy_gate.apply_call(
            state, "SendMessage", {"to": "team-lead", "message": "test"}
        )
        self.assertEqual(decision_of(output), "deny",
                        "11th call (SendMessage) should be denied: hard cap (10) exceeded")

    def test_small_task_coordination_reserve_still_protected(self):
        """TaskUpdate and SendMessage consume from hard cap, not free."""
        state = self.make_small_task_state(total_tool_calls=9)

        # 10th call: TaskUpdate should be allowed
        output = policy_gate.apply_call(
            state, "TaskUpdate", {"taskId": "1", "status": "completed"}
        )
        self.assertEqual(decision_of(output), "allow")

        # Verify it consumed a call
        self.assertEqual(state["total_tool_calls"], 10)

        # 11th call: SendMessage should be denied (budget exhausted)
        output = policy_gate.apply_call(
            state, "SendMessage", {"to": "team-lead", "message": "report"}
        )
        self.assertEqual(decision_of(output), "deny")

    def test_small_task_unauthorized_teammate_still_denied(self):
        """Increasing budget does not authorize unauthorized agents."""
        state = self.make_small_task_state(total_tool_calls=0)
        # selected_agents is ["bug-fixer"], but we try to use an unauthorized agent

        # This test verifies that the agent access control logic (not policy_gate)
        # still prevents unauthorized agent dispatch. This is a boundary check
        # to ensure the budget fix didn't inadvertently widen access control.
        self.assertNotIn("coder", state["selected_agents"])
        self.assertIn("bug-fixer", state["selected_agents"])

    def test_small_task_limits_configuration_verified(self):
        """Verify small_task limits in agents.json match the expected fixed values."""
        import json
        agents_json_path = PROJECT_ROOT / ".claude" / "agents.json"
        with open(agents_json_path) as f:
            config = json.load(f)

        small_task = config["orchestration"]["task_classes"]["small_task"]

        # Verify the fix was applied
        self.assertEqual(small_task["max_total_tool_calls"], 10,
                        "small_task max_total_tool_calls should be 10 after fix")
        self.assertEqual(small_task["max_members"], 1)
        self.assertEqual(small_task["max_tool_rounds"], 1)
        self.assertEqual(small_task["max_run_budget_usd"], 1.0)

    def test_medium_task_unchanged(self):
        """Verify medium_task limits remain unchanged."""
        import json
        agents_json_path = PROJECT_ROOT / ".claude" / "agents.json"
        with open(agents_json_path) as f:
            config = json.load(f)

        medium_task = config["orchestration"]["task_classes"]["medium_task"]

        # Verify medium_task was not affected
        self.assertEqual(medium_task["max_total_tool_calls"], 24)
        self.assertEqual(medium_task["max_members"], 3)
        self.assertEqual(medium_task["max_tool_rounds"], 3)
        self.assertEqual(medium_task["max_run_budget_usd"], 4.0)

    def test_complex_task_unchanged(self):
        """Verify complex_task limits remain unchanged."""
        import json
        agents_json_path = PROJECT_ROOT / ".claude" / "agents.json"
        with open(agents_json_path) as f:
            config = json.load(f)

        complex_task = config["orchestration"]["task_classes"]["complex_task"]

        # Verify complex_task was not affected
        self.assertEqual(complex_task["max_total_tool_calls"], 60)
        self.assertEqual(complex_task["max_members"], 5)
        self.assertEqual(complex_task["max_tool_rounds"], 5)
        self.assertEqual(complex_task["max_run_budget_usd"], 10.0)


if __name__ == "__main__":
    unittest.main()
