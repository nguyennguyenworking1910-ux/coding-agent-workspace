"""Checkpoint 7.1 Merchant intent classification and routing tests."""

import sys

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_DIR = PROJECT_ROOT / ".claude"
SYSTEM_DIR = CLAUDE_DIR / "system"

sys.path.insert(0, str(SYSTEM_DIR))

from intent_parser import (  # noqa: E402
    INTENT_SYSTEM_PROMPT,
    ComplexityBreakdown,
    Domain,
    IntentParser,
    IntentParserConfigError,
    OpenAIIntentDecision,
    Operation,
)
from schemas import RiskLevel, TaskClass  # noqa: E402


class FakeResponse:
    def __init__(self, decision):
        self.status = "completed"
        self.output_parsed = decision


class FakeResponses:
    def __init__(self, decision):
        self.decision = decision

    def parse(self, **_kwargs):
        return FakeResponse(self.decision)


class FakeClient:
    def __init__(self, decision):
        self.responses = FakeResponses(decision)


def _decision(
    *,
    operations,
    domains,
    risk_level=RiskLevel.READ_ONLY,
    task_class=TaskClass.SMALL,
):
    return OpenAIIntentDecision(
        task_class=task_class,
        risk_level=risk_level,
        confidence=0.98,
        score_breakdown=ComplexityBreakdown(
            scope=0,
            domains=0,
            dependencies=0,
            verification=0,
            ambiguity=0,
        ),
        operations=operations,
        domains=domains,
        reasons=["Fake Merchant decision"],
        requires_clarification=False,
    )


def _parse(request, decision):
    parser = IntentParser(
        CLAUDE_DIR / "agents.json",
        client=FakeClient(decision),
    )
    return parser.parse(request)


def _assert_exclusive_merchant_routing(result):
    assert result.candidate_agents == ["merchant-manager"]
    assert result.selected_agents == ["merchant-manager"]
    assert "merchant" in result.domains


def test_schema_exposes_three_merchant_operations_and_domain():
    assert Operation.MERCHANT_READ.value == "merchant_read"
    assert Operation.MERCHANT_PROPOSE.value == "merchant_propose"
    assert Operation.MERCHANT_APPLY.value == "merchant_apply"
    assert Domain.MERCHANT.value == "merchant"


def test_prompt_defines_merchant_modes_and_code_boundary():
    assert "merchant_read, merchant_propose, merchant_apply" in (
        INTENT_SYSTEM_PROMPT
    )
    assert "merchant_propose" in INTENT_SYSTEM_PROMPT
    assert "does not apply a change and is read_only" in (
        INTENT_SYSTEM_PROMPT
    )
    assert "Merchant source code" in INTENT_SYSTEM_PROMPT


def test_model_merchant_read_routes_only_to_merchant_manager():
    result = _parse(
        "List current Merchant projects",
        _decision(
            operations=[Operation.MERCHANT_READ],
            domains=[Domain.MERCHANT],
        ),
    )

    assert result.operations == ["merchant_read"]
    assert result.risk_level == RiskLevel.READ_ONLY
    assert result.requires_confirmation is False
    _assert_exclusive_merchant_routing(result)


def test_merchant_proposal_is_normalized_to_non_mutating_risk():
    result = _parse(
        "Prepare a Merchant project update proposal with --propose",
        _decision(
            operations=[Operation.BUILD],
            domains=[Domain.CODE],
            risk_level=RiskLevel.WRITE,
        ),
    )

    assert result.operations == ["merchant_propose"]
    assert result.risk_level == RiskLevel.READ_ONLY
    assert result.requires_confirmation is False
    _assert_exclusive_merchant_routing(result)


def test_merchant_apply_is_external_write_and_requires_confirmation():
    result = _parse(
        "Apply the prior Merchant proposal with --apply",
        _decision(
            operations=[Operation.MERCHANT_APPLY],
            domains=[Domain.MERCHANT],
        ),
    )

    assert result.operations == ["merchant_apply"]
    assert result.risk_level == RiskLevel.EXTERNAL_WRITE
    assert result.requires_confirmation is True
    _assert_exclusive_merchant_routing(result)


def test_highest_merchant_mode_wins_and_remains_exclusive():
    result = _parse(
        "Apply the approved Merchant proposal",
        _decision(
            operations=[
                Operation.BUILD,
                Operation.MERCHANT_READ,
                Operation.MERCHANT_PROPOSE,
                Operation.MERCHANT_APPLY,
            ],
            domains=[Domain.CODE, Domain.MERCHANT],
            task_class=TaskClass.COMPLEX,
        ),
    )

    assert result.operations == ["merchant_apply"]
    assert result.candidate_agents == ["merchant-manager"]
    assert result.selected_agents == ["merchant-manager"]


def test_local_guardrail_corrects_misclassified_english_read():
    result = _parse(
        "List Merchant projects with active blockers",
        _decision(
            operations=[Operation.DIAGNOSE],
            domains=[Domain.DATA],
        ),
    )

    assert result.operations == ["merchant_read"]
    _assert_exclusive_merchant_routing(result)


def test_local_guardrail_corrects_misclassified_vietnamese_read():
    result = _parse(
        "Liệt kê các dự án của đối tác đang bị chặn",
        _decision(
            operations=[Operation.SALES_QUERY],
            domains=[Domain.SALES],
        ),
    )

    assert result.operations == ["merchant_read"]
    _assert_exclusive_merchant_routing(result)


def test_unconfirmed_merchant_write_defaults_to_proposal():
    result = _parse(
        "Update the Merchant project payment period",
        _decision(
            operations=[Operation.BUILD],
            domains=[Domain.CODE],
            risk_level=RiskLevel.WRITE,
        ),
    )

    assert result.operations == ["merchant_propose"]
    assert result.risk_level == RiskLevel.READ_ONLY
    assert result.requires_confirmation is False
    _assert_exclusive_merchant_routing(result)


def test_vietnamese_merchant_write_defaults_to_proposal():
    result = _parse(
        "Đề xuất cập nhật trạng thái dự án của đối tác",
        _decision(
            operations=[Operation.REFACTOR],
            domains=[Domain.CODE],
            risk_level=RiskLevel.WRITE,
        ),
    )

    assert result.operations == ["merchant_propose"]
    assert result.risk_level == RiskLevel.READ_ONLY
    _assert_exclusive_merchant_routing(result)


def test_vietnamese_apply_is_detected_conservatively():
    result = _parse(
        "Xác nhận và áp dụng đề xuất của đối tác trước đó",
        _decision(
            operations=[Operation.MERCHANT_PROPOSE],
            domains=[Domain.MERCHANT],
        ),
    )

    assert result.operations == ["merchant_apply"]
    assert result.risk_level == RiskLevel.EXTERNAL_WRITE
    assert result.requires_confirmation is True
    _assert_exclusive_merchant_routing(result)


def test_external_side_effect_is_never_downgraded_for_merchant_read():
    result = _parse(
        "List Merchant projects and send email with the result",
        _decision(
            operations=[Operation.MERCHANT_READ],
            domains=[Domain.MERCHANT],
            risk_level=RiskLevel.EXTERNAL_WRITE,
        ),
    )

    assert result.risk_level == RiskLevel.EXTERNAL_WRITE
    assert result.requires_confirmation is True


def test_destructive_merchant_request_is_never_downgraded():
    result = _parse(
        "Apply the Merchant proposal and drop table production",
        _decision(
            operations=[Operation.MERCHANT_APPLY],
            domains=[Domain.MERCHANT],
        ),
    )

    assert result.risk_level == RiskLevel.DESTRUCTIVE
    assert result.requires_confirmation is True


def test_merchant_source_code_fix_stays_with_bug_fixer():
    result = _parse(
        "Fix the bug in the Merchant CLI source code",
        _decision(
            operations=[Operation.FIX],
            domains=[Domain.CODE],
            risk_level=RiskLevel.WRITE,
        ),
    )

    assert result.operations == ["fix"]
    assert result.domains == ["code"]
    assert result.selected_agents == ["bug-fixer"]


def test_vietnamese_merchant_source_code_fix_stays_with_bug_fixer():
    result = _parse(
        "Sửa lỗi mã nguồn của Merchant CLI parser",
        _decision(
            operations=[Operation.FIX],
            domains=[Domain.CODE],
            risk_level=RiskLevel.WRITE,
        ),
    )

    assert result.operations == ["fix"]
    assert result.selected_agents == ["bug-fixer"]


def test_merchant_domain_alone_never_falls_back_to_sales_agent():
    result = _parse(
        "Inspect the current operational records",
        _decision(
            operations=[Operation.DIAGNOSE],
            domains=[Domain.MERCHANT],
        ),
    )

    _assert_exclusive_merchant_routing(result)


def test_missing_merchant_manager_fails_closed_without_fallback():
    decision = _decision(
        operations=[Operation.MERCHANT_READ],
        domains=[Domain.MERCHANT],
    )
    parser = IntentParser(
        CLAUDE_DIR / "agents.json",
        client=FakeClient(decision),
    )
    parser.enabled_agents.remove("merchant-manager")

    try:
        parser.parse("List Merchant projects")
    except IntentParserConfigError as error:
        assert "requires the enabled merchant-manager" in str(error)
    else:  # pragma: no cover
        raise AssertionError(
            "Merchant routing must fail closed without merchant-manager"
        )
