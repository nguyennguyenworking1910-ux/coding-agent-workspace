"""CP12H.NL3A: natural-language Project understanding and preview outcome delivery.

Live 2026-11-04 (lead 49f7c713, teammate dd6e8672): the preview of

    "Tạo Project mở rạp Beta NL3 Confirmation Test cho Merchant Beta Cinemas
     trên database test, không cần Purchase Requisition"

returned NEEDS_CLARIFICATION: the Merchant phrase kept its role label
("Merchant Beta Cinemas"), so nothing resolved and the title could not be
built; "Purchase Requisition" was not a procurement noun. The teammate's
honest NEEDS_CLARIFICATION report was then blocked because it said the
outcome was "not READY_FOR_CONFIRMATION", and the gate told it to relabel the
verified result as PREVIEW_DELIVERY_FAILED.

No database: the NL1 read-only fake reader with the live test-DB catalog.
"""

from __future__ import annotations

import json

import pytest

from claude.agents.tools.merchant.project_nl import interpret_project_request
from claude.agents.tools.merchant.project_preview import (
    BLOCKED,
    NEEDS_CLARIFICATION,
    READY,
)
from claude.hooks import merchant_preview_delivery
from claude.hooks.merchant_preview_delivery import PREVIEW_DELIVERY_FAILED
from tests.merchant.test_nl1_project_preview import BETA, LOTTE, merchant
from tests.merchant.test_nl2e_p1_p2_p4 import (  # noqa: F401  (fixtures)
    LiveReader,
    PREVIEW_TEST,
    delivery,
    deny,
    isolated,
    post_bash,
    preview,
    report,
)

LIVE_NL3 = (
    "Tạo Project mở rạp Beta NL3 Confirmation Test cho Merchant Beta Cinemas "
    "trên database test, không cần Purchase Requisition"
)
PARTNER = "44444444-4444-4444-8444-444444444444"


def ready(text, reader=None):
    result = preview(text, reader)
    assert result["outcome"] == READY, result["clarifications"] + result["conflicts"]
    return result


# ------------------------------------------------------------- exact live request


def test_exact_live_request_is_ready_for_confirmation():
    result = ready(LIVE_NL3)
    op = result["requested_operation"]

    assert result["merchant"]["code"] == "NL2_LIVE_BETA"
    assert result["merchant"]["merchant_id"] == BETA
    assert result["merchant"]["match_kind"] == "NAME"  # "Beta Cinemas" is the name
    assert op["merchant_confirmation_required"] is False
    assert op["title"] == "Beta NL3 Confirmation Test"
    assert op["project_type"] == "OPENING_NEW_CINEMA"
    assert op["workflow_variant"] == "OPENING_NEW_CINEMA_STANDARD"
    assert op["requires_procurement"] is False
    assert op["database_target"] == "test"
    # A preview never authorizes anything.
    assert op["status"] == "NOT_AUTHORIZED"
    assert result["authorization"] is None
    assert result["executable"] is False


# ------------------------------------------------------- Merchant role labels


@pytest.mark.parametrize(
    "text",
    [
        LIVE_NL3,
        "Tạo dự án mở rạp Beta Nguyễn Văn Cừ cho đối tác Beta Cinemas, không cần mua sắm",
        "Tạo dự án mở rạp Beta Nguyễn Văn Cừ của Beta Cinemas, không cần mua sắm",
        "Tạo dự án mở rạp Beta Nguyễn Văn Cừ cho merchant Beta Cinemas, không cần PR",
        "Create a cinema opening project for Beta NL3 Confirmation Test under "
        "merchant Beta Cinemas without Purchase Requisition",
        "Create a cinema opening project for Beta Nguyễn Văn Cừ under partner "
        "Beta Cinemas, no procurement",
    ],
)
def test_role_label_before_the_merchant_name_is_not_part_of_it(text):
    result = ready(text)

    assert result["merchant"]["code"] == "NL2_LIVE_BETA"
    assert result["merchant"]["matched_text"] == "Beta Cinemas"
    assert result["requested_operation"]["merchant_confirmation_required"] is False


def test_a_merchant_whose_name_starts_with_a_label_word_keeps_it():
    reader = LiveReader(merchants=[
        merchant(BETA, "NL2_LIVE_BETA", "Beta Cinemas"),
        merchant(PARTNER, "PARTNER_CINEMAS", "Partner Cinemas"),
    ])

    result = ready(
        "Tạo dự án mở rạp Partner Quận 1 cho Partner Cinemas, không cần mua sắm",
        reader,
    )

    assert result["merchant"]["code"] == "PARTNER_CINEMAS"
    assert result["merchant"]["matched_text"] == "Partner Cinemas"


def test_a_label_alone_names_no_merchant():
    result = preview("Tạo dự án mở rạp Galaxy Quận 7 cho Merchant, không cần mua sắm")

    assert result["outcome"] == NEEDS_CLARIFICATION
    assert result["requested_operation"] is None


# ------------------------------------------------------------ title and site


@pytest.mark.parametrize(
    "text,title",
    [
        (LIVE_NL3, "Beta NL3 Confirmation Test"),
        ("Tạo dự án mở rạp Beta Nguyễn Văn Cừ, không cần mua sắm", "Beta Nguyễn Văn Cừ"),
        ("Create a cinema opening project for Beta NL3 Confirmation Test, no procurement",
         "Beta NL3 Confirmation Test"),
        ("Tạo project mở rạp Nguyễn Văn Cừ cho Beta Cinemas, không cần PR",
         "Beta Cinemas Nguyễn Văn Cừ"),
    ],
)
def test_title_comes_from_the_site_and_keeps_unicode(text, title):
    op = ready(text)["requested_operation"]

    assert op["title"] == title
    assert title in op["argv"]
    assert title in op["confirmation_command"]


def test_missing_site_asks_for_the_title_instead_of_inventing_one():
    result = preview("Tạo project mở rạp cho Merchant Beta Cinemas, không cần mua sắm")

    assert result["outcome"] == NEEDS_CLARIFICATION
    assert result["fields"]["title"] is None
    assert any("Project name" in question for question in result["clarifications"])
    assert result["requested_operation"] is None


def test_candidate_merchant_still_needs_the_users_confirmation():
    # "Beta" alone only partially matches "Beta Cinemas".
    op = ready("Tạo dự án mở rạp Beta Nguyễn Văn Cừ, không cần mua sắm")["requested_operation"]

    assert op["merchant_match_kind"] == "CANDIDATE"
    assert op["merchant_confirmation_required"] is True


def test_ambiguous_merchant_is_still_refused():
    reader = LiveReader(merchants=[
        merchant(BETA, "NL2_LIVE_BETA", "Beta Cinemas"),
        merchant(LOTTE, "BETA_MEDIA", "Beta Media"),
    ])

    result = preview("Tạo dự án mở rạp Beta Nguyễn Văn Cừ, không cần mua sắm", reader)

    assert result["outcome"] in {NEEDS_CLARIFICATION, BLOCKED}
    assert result["requested_operation"] is None


# ------------------------------------------------------------- procurement


@pytest.mark.parametrize(
    "phrase",
    [
        "không cần Purchase Requisition",
        "không cần PR",
        "bỏ bước xin PR",
        "bỏ qua bước Purchase Requisition",
        "không cần mua sắm",
        "without Purchase Requisition",
        "no purchase request",
    ],
)
def test_no_purchase_requisition_means_no_procurement(phrase):
    text = f"Tạo dự án mở rạp Beta Nguyễn Văn Cừ cho Beta Cinemas, {phrase}"

    assert interpret_project_request(text).requires_procurement is False


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("cần Purchase Requisition", True),
        ("cần mua sắm", True),
        # Purchase Order and Payment Request are not procurement (steps 10-11).
        ("không cần Purchase Order", None),
        ("không cần Payment Request", None),
        ("bộ phận kế toán xử lý Payment Request", None),
    ],
)
def test_purchase_order_and_payment_request_are_not_procurement(phrase, expected):
    text = f"Tạo dự án mở rạp Beta Nguyễn Văn Cừ cho Beta Cinemas, {phrase}"

    assert interpret_project_request(text).requires_procurement is expected


def test_no_pr_skips_only_steps_6_and_7():
    steps = {s["sequence"]: s for s in ready(LIVE_NL3)["initial_steps"]}

    assert {s["name"] for n, s in steps.items() if n in (6, 7)} == {
        "Create Purchase Request", "Record Purchase Request number"}
    assert steps[6]["initial_status"] == steps[7]["initial_status"] == "SKIPPED"
    assert steps[10]["name"] == "Create Purchase Order"
    assert steps[11]["name"] == "Create Payment Request"
    assert steps[10]["initial_status"] == steps[11]["initial_status"] == "PENDING"
    assert len(steps) == 22


# ------------------------------------------------- preview outcome delivery


LIVE_CLARIFICATION_REPORT = (
    "Merchant read report. Operation: merchant_read (Project preview). Database "
    "target: test. Outcome: NEEDS_CLARIFICATION (executable: false). No "
    "MERCHANT_PREVIEW_OPERATION_JSON is emitted, because requested_operation is "
    "null and the outcome is not READY_FOR_CONFIRMATION. No confirmation command "
    "exists. Questions: Which existing Merchant is this Project for?"
)


@pytest.fixture
def clarification(delivery):
    result = preview("Tạo dự án mở rạp Galaxy Quận 7 cho Merchant, không cần mua sắm")
    assert result["outcome"] == NEEDS_CLARIFICATION
    assert merchant_preview_delivery.record_preview_evidence(
        post_bash(PREVIEW_TEST, json.dumps(result, ensure_ascii=False, indent=2))
    )


def decide(body):
    payload = report()
    payload["tool_input"]["message"] = body
    return merchant_preview_delivery.preview_delivery_decision(payload, deny)


def reason_of(decision):
    return decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_verified_clarification_report_is_delivered_as_is(clarification):
    assert decide(LIVE_CLARIFICATION_REPORT) is None


def test_verified_clarification_is_not_a_delivery_failure(clarification):
    decision = decide(f"{PREVIEW_DELIVERY_FAILED}: the outcome is NEEDS_CLARIFICATION.")

    assert decision is not None
    assert "NEEDS_CLARIFICATION" in reason_of(decision)
    assert f"begin it with `{PREVIEW_DELIVERY_FAILED}:`" not in reason_of(decision)


@pytest.mark.parametrize(
    "body",
    [
        "Preview returned READY_FOR_CONFIRMATION for Beta Cinemas.",
        'Type: /solve --confirm --merchant-target test --merchant-scope ["project","create"] x',
        'MERCHANT_PREVIEW_OPERATION_JSON:\n{"argv":["project","create"]}',
    ],
)
def test_verified_clarification_still_cannot_carry_an_operation(clarification, body):
    decision = decide(body)

    assert decision is not None
    assert f"begin it with `{PREVIEW_DELIVERY_FAILED}:`" not in reason_of(decision)
