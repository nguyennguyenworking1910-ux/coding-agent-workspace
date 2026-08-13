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


if __name__ == "__main__":
    unittest.main()
