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


if __name__ == "__main__":
    unittest.main()