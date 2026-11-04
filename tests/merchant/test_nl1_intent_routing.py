"""CP12H.NL1: /solve intent routing for natural-language Project requests."""

import pytest

from tests.merchant.test_merchant_intent_routing import (
    Domain,
    Operation,
    RiskLevel,
    _assert_exclusive_merchant_routing,
    _decision,
    _parse,
)


CREATE = (
    "Tạo project mở rạp Beta Nguyễn Văn Cừ.",
    "Tạo dự án khai trương rạp Nguyễn Văn Cừ cho Beta.",
    "Create a new cinema opening project for Beta Nguyễn Văn Cừ.",
    "Create a project to open Beta Nguyễn Văn Cừ cinema",
)
NON_WRITE = (
    "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ",
    "Preview a cinema opening project for Beta Nguyễn Văn Cừ",
    "Không tạo project, chỉ xem trước dự án mở rạp Beta Nguyễn Văn Cừ",
    "Do not create the cinema opening project for Beta Nguyễn Văn Cừ",
    "Should we create a cinema opening project for Beta Nguyễn Văn Cừ?",
)


@pytest.mark.parametrize("request_text", CREATE)
@pytest.mark.parametrize(
    "model",
    (
        (Operation.MERCHANT_READ, Domain.MERCHANT, RiskLevel.READ_ONLY),
        (Operation.BUILD, Domain.CODE, RiskLevel.WRITE),
    ),
)
def test_project_creation_routes_to_merchant_execute_with_confirmation(
    request_text, model
):
    operation, domain, risk = model
    result = _parse(
        request_text,
        _decision(operations=[operation], domains=[domain], risk_level=risk),
    )

    assert result.operations == ["merchant_execute"]
    assert result.risk_level == RiskLevel.EXTERNAL_WRITE
    assert result.requires_confirmation is True
    _assert_exclusive_merchant_routing(result)


@pytest.mark.parametrize("request_text", NON_WRITE)
def test_preview_negated_and_exploratory_project_requests_stay_reads(
    request_text,
):
    result = _parse(
        request_text,
        _decision(
            operations=[Operation.MERCHANT_EXECUTE],
            domains=[Domain.MERCHANT],
            risk_level=RiskLevel.EXTERNAL_WRITE,
        ),
    )

    assert result.operations == ["merchant_read"]
    _assert_exclusive_merchant_routing(result)


@pytest.mark.parametrize("request_text", NON_WRITE[:3])
def test_explicit_preview_needs_no_confirmation(request_text):
    result = _parse(
        request_text,
        _decision(
            operations=[Operation.MERCHANT_EXECUTE],
            domains=[Domain.MERCHANT],
            risk_level=RiskLevel.EXTERNAL_WRITE,
        ),
    )

    assert result.risk_level == RiskLevel.READ_ONLY
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "request_text",
    (
        "Create a new project for the calculator app",
        "Fix the integration tests for the intent parser",
        "Tạo project mới cho ứng dụng todo",
    ),
)
def test_generic_project_or_integration_code_work_is_not_merchant(request_text):
    result = _parse(
        request_text,
        _decision(
            operations=[Operation.BUILD],
            domains=[Domain.CODE],
            risk_level=RiskLevel.WRITE,
        ),
    )

    assert "merchant_execute" not in result.operations
    assert "merchant_read" not in result.operations
    assert "merchant-manager" not in result.selected_agents
