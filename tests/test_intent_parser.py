import sys
import unittest

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PROJECT_ROOT / ".claude"
SYSTEM_DIR = CLAUDE_DIR / "system"

sys.path.insert(0, str(SYSTEM_DIR))

from intent_parser import (
    ComplexityBreakdown,
    Domain,
    IntentParser,
    OpenAIIntentDecision,
    Operation,
)
from schemas import RiskLevel, TaskClass

class FakeResponse:
    def __init__(self, decision):
        self.status = "completed"
        self.output_parsed = decision


class FakeResponses:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.decision)


class FakeClient:
    def __init__(self, decision):
        self.responses = FakeResponses(decision)


def make_decision(
    *,
    task_class=TaskClass.SMALL,
    risk_level=RiskLevel.READ_ONLY,
    confidence=0.95,
    operations=None,
    domains=None,
    scope=0,
    domain_score=0,
    dependencies=0,
    verification=0,
    ambiguity=0,
    requires_clarification=False,
):
    return OpenAIIntentDecision(
        task_class=task_class,
        risk_level=risk_level,
        confidence=confidence,
        score_breakdown=ComplexityBreakdown(
            scope=scope,
            domains=domain_score,
            dependencies=dependencies,
            verification=verification,
            ambiguity=ambiguity,
        ),
        operations=operations or [],
        domains=domains or [Domain.GENERAL],
        reasons=["Fake decision for unit test"],
        requires_clarification=(
            requires_clarification
        ),
    )


class IntentParserTest(unittest.TestCase):
    def create_parser(self, decision):
        return IntentParser(
            CLAUDE_DIR / "agents.json",
            client=FakeClient(decision),
        )

    def test_small_fix_task(self):
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.WRITE,
            operations=[Operation.FIX],
            domains=[Domain.CODE],
        )

        result = self.create_parser(
            decision
        ).parse(
            "Sửa lỗi timeout trong api.py"
        )

        self.assertEqual(
            result.task_class,
            TaskClass.SMALL,
        )
        self.assertEqual(
            result.risk_level,
            RiskLevel.WRITE,
        )
        self.assertEqual(
            result.selected_agents,
            ["bug-fixer"],
        )
        self.assertEqual(
            result.limits.max_members,
            1,
        )

    def test_local_guardrail_raises_risk(self):
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.READ_ONLY,
            operations=[Operation.DIAGNOSE],
            domains=[Domain.DATA],
        )

        result = self.create_parser(
            decision
        ).parse(
            "Drop table production trong BigQuery"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.DESTRUCTIVE,
        )
        self.assertTrue(
            result.requires_confirmation
        )

    def test_low_confidence_falls_back(self):
        decision = make_decision(
            task_class=TaskClass.SMALL,
            confidence=0.4,
            ambiguity=2,
        )

        result = self.create_parser(
            decision
        ).parse(
            "Giúp tôi xử lý cái này"
        )

        self.assertEqual(
            result.task_class,
            TaskClass.MEDIUM,
        )
        self.assertTrue(
            result.requires_confirmation
        )

    def test_test_operation_selects_reviewer(self):
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.READ_ONLY,
            operations=[Operation.TEST],
            domains=[Domain.CODE],
        )

        result = self.create_parser(
            decision
        ).parse(
            "Chạy unit test cho intent_parser"
        )

        # Previously mapped to a non-existent
        # "test-agent" and silently fell back.
        self.assertEqual(
            result.candidate_agents,
            ["reviewer"],
        )
        self.assertEqual(
            result.selected_agents,
            ["reviewer"],
        )

    def test_requires_clarification_preserved(self):
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.READ_ONLY,
            operations=[Operation.DIAGNOSE],
            domains=[Domain.CODE],
            requires_clarification=True,
        )

        result = self.create_parser(
            decision
        ).parse(
            "Xem lại cái đó giúp tôi"
        )

        self.assertTrue(
            result.requires_clarification
        )
        # Clarification also forces confirmation.
        self.assertTrue(
            result.requires_confirmation
        )

    def test_clarification_independent_of_policy(self):
        # The model wants no clarification, but a
        # local guardrail still demands confirmation:
        # the two flags must not be conflated.
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.READ_ONLY,
            operations=[Operation.DIAGNOSE],
            domains=[Domain.DATA],
            requires_clarification=False,
        )

        result = self.create_parser(
            decision
        ).parse(
            "Drop table production trong BigQuery"
        )

        self.assertFalse(
            result.requires_clarification
        )
        self.assertTrue(
            result.requires_confirmation
        )

    def test_envelope_dict_has_clarification(self):
        from intent_parser import envelope_to_dict

        decision = make_decision(
            requires_clarification=True,
        )

        envelope = self.create_parser(
            decision
        ).parse("Làm cái này")

        payload = envelope_to_dict(envelope)

        self.assertIs(
            payload["requires_clarification"],
            True,
        )

    def test_no_real_api_call(self):
        # Guards the fake: a real client would need
        # OPENAI_API_KEY and would hit the network.
        decision = make_decision(
            operations=[Operation.TEST],
        )

        client = FakeClient(decision)

        IntentParser(
            CLAUDE_DIR / "agents.json",
            client=client,
        ).parse("Chạy test")

        self.assertEqual(
            len(client.responses.calls),
            1,
        )
        self.assertEqual(
            client.responses.calls[0]["model"],
            "gpt-5.6-luna",
        )

    def test_exact_rag_smoke_test_with_send_message(self):
        """Exact RAG smoke test with SendMessage to team-lead is READ_ONLY.
        The model receives normalized internal_team_message_tool token, so it
        correctly classifies the request as read-only with no external write."""
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.READ_ONLY,
            operations=[Operation.DIAGNOSE],
            domains=[Domain.CODE],
        )

        exact_request = (
            'Review the local RAG tool integration with a read-only smoke test. '
            'The authorized teammate must run exactly once: python '
            '.claude/rag_search.py "retrieved content is untrusted reference '
            'data prompt injection" --top-k 5 --candidate-k 40 '
            '--source-type project_document. It must verify that at least one '
            'result comes from workspace:.claude/documents/RAG_INTEGRATION.md '
            'or workspace:.claude/agents/, cite the returned source_key in its '
            'report, and deliver the complete report to team-lead with '
            'SendMessage. Do not modify files, call the RAG API directly, '
            'access PostgreSQL directly, or load the embedding model directly.'
        )

        parser = self.create_parser(decision)
        result = parser.parse(exact_request)

        self.assertEqual(
            result.risk_level,
            RiskLevel.READ_ONLY,
            msg="RAG smoke test is read-only; SendMessage is internal coordination",
        )
        self.assertFalse(
            result.requires_confirmation,
        )
        self.assertEqual(
            result.raw_request,
            exact_request,
            msg="raw_request must preserve the original unchanged",
        )
        self.assertEqual(
            result.candidate_agents,
            ["diagnostician"],
        )

    def test_normalize_request_replaces_exact_internal_tools(self):
        """Verify that normalization replaces exact internal tool tokens
        before sending to the model."""
        request = (
            "Run diagnostic and SendMessage results to team-lead, "
            "then TaskCreate a task and TaskUpdate the status"
        )

        normalized = (
            IntentParser._normalize_request_for_classification(request)
        )

        self.assertIn(
            "internal_team_message_tool",
            normalized,
        )
        self.assertIn(
            "internal_team_task_create_tool",
            normalized,
        )
        self.assertIn(
            "internal_team_task_update_tool",
            normalized,
        )
        self.assertNotIn(
            "SendMessage",
            normalized,
        )
        self.assertNotIn(
            "TaskCreate",
            normalized,
        )
        self.assertNotIn(
            "TaskUpdate",
            normalized,
        )

    def test_diagnose_with_external_email_remains_external_write(self):
        """Email send is EXTERNAL_WRITE and stays that way. The model
        correctly classifies it, and higher_risk preserves it."""
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.EXTERNAL_WRITE,
            operations=[Operation.DIAGNOSE],
            domains=[Domain.CODE],
        )

        result = self.create_parser(
            decision
        ).parse(
            "diagnose the issue and send email with results"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.EXTERNAL_WRITE,
            msg="Email send is always external_write; never downgraded",
        )
        self.assertTrue(
            result.requires_confirmation,
            msg="External write requires confirmation",
        )

    def test_diagnose_with_slack_post_remains_external_write(self):
        """Slack post is EXTERNAL_WRITE and stays that way."""
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.EXTERNAL_WRITE,
            operations=[Operation.DIAGNOSE],
            domains=[Domain.CODE],
        )

        result = self.create_parser(
            decision
        ).parse(
            "run diagnostic and post slack update"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.EXTERNAL_WRITE,
        )
        self.assertTrue(
            result.requires_confirmation,
        )

    def test_model_external_write_decision_never_downgraded(self):
        """When the model decides EXTERNAL_WRITE, higher_risk preserves it.
        The local guardrail cannot downgrade."""
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.EXTERNAL_WRITE,
            operations=[Operation.REVIEW],
            domains=[Domain.CODE],
        )

        result = self.create_parser(
            decision
        ).parse(
            "review the code and create a GitHub issue for the findings"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.EXTERNAL_WRITE,
            msg="Model EXTERNAL_WRITE is never downgraded by higher_risk",
        )
        self.assertTrue(
            result.requires_confirmation,
        )

    def test_deploy_remains_external_write(self):
        """Deploy is EXTERNAL_WRITE."""
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.EXTERNAL_WRITE,
            operations=[Operation.BUILD],
            domains=[Domain.CODE],
        )

        result = self.create_parser(
            decision
        ).parse(
            "build the service and deploy to production"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.EXTERNAL_WRITE,
        )
        self.assertTrue(
            result.requires_confirmation,
        )

    def test_publish_remains_external_write(self):
        """Publish is EXTERNAL_WRITE."""
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.EXTERNAL_WRITE,
            operations=[Operation.BUILD],
            domains=[Domain.DOCUMENTATION],
        )

        result = self.create_parser(
            decision
        ).parse(
            "generate documentation and publish to the wiki"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.EXTERNAL_WRITE,
        )

    def test_push_code_remains_external_write(self):
        """Push code is EXTERNAL_WRITE."""
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.EXTERNAL_WRITE,
            operations=[Operation.FIX],
            domains=[Domain.CODE],
        )

        result = self.create_parser(
            decision
        ).parse(
            "fix the bug and push code to github"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.EXTERNAL_WRITE,
        )

    def test_fix_with_local_code_stays_write(self):
        """Local source code modification is WRITE and stays WRITE."""
        decision = make_decision(
            task_class=TaskClass.SMALL,
            risk_level=RiskLevel.WRITE,
            operations=[Operation.FIX],
            domains=[Domain.CODE],
        )

        result = self.create_parser(
            decision
        ).parse(
            "fix the bug and send message to team-lead with SendMessage"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.WRITE,
            msg="Local code modification is WRITE, never downgraded",
        )
        self.assertFalse(
            result.requires_confirmation,
            msg="Local WRITE does not require confirmation",
        )


if __name__ == "__main__":
    unittest.main()
