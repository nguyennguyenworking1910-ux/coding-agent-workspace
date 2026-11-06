"""CP12H.NL4B-FIX2B: UserPromptSubmit routing of incomplete Step updates.

Live failure: "/solve Đánh dấu bước Legal Review hoàn thành trên database test"
was blocked as external_write needing --confirm. Replaying the real parser
showed the model routing it to ``bug-fixer``/``fix`` (2 of 3 runs) or to
merchant-manager with ``requires_clarification`` (1 of 3). The FIX1 local
guardrail claimed a Step update only when it named a Project, so neither
outcome reached the read-only downgrade.

Every test drives the real ``intent_gate.run`` UserPromptSubmit entry point
with the real ``IntentParser``; only the model's answer is replayed.
"""

from __future__ import annotations

import pytest

from claude.agents.tools.merchant.project_nl import (
    MIXED,
    PROJECT_STATUS,
    STEP_UPDATE,
    interpret_project_request,
)
from claude.agents.tools.merchant.step_preview import CLARIFY
from tests.merchant.test_nl4b_fix1_routing_and_teammate import (  # noqa: F401 (fixtures)
    BUG_FIXER,
    LEAD,
    intent_gate,
    isolated,
    parse,
    runtime_state,
)
from tests.merchant.test_nl4b_step_preview import preview
from tests.merchant.test_merchant_intent_routing import _decision
from intent_parser import Domain, Operation  # noqa: E402
from schemas import RiskLevel  # noqa: E402

LIVE = "Đánh dấu bước Legal Review hoàn thành trên database test"
SHORT = "Đánh dấu bước Legal Review hoàn thành"
FULL = "Đánh dấu bước Legal Review của Project Beta Nguyễn Văn Cừ là hoàn thành"

# The two live model answers, replayed.
MERCHANT_CLARIFY = _decision(
    operations=[Operation.MERCHANT_EXECUTE], domains=[Domain.MERCHANT, Domain.DATA],
    risk_level=RiskLevel.EXTERNAL_WRITE,
).model_copy(update={"requires_clarification": True})
# The worst case for a mixed request: the model claims it is Merchant only.
MERCHANT_ONLY = _decision(
    operations=[Operation.MERCHANT_EXECUTE], domains=[Domain.MERCHANT],
    risk_level=RiskLevel.EXTERNAL_WRITE,
)


def submit(text, decision=BUG_FIXER, confirm=False):
    class Replayed:
        def parse(self, request):
            return parse(request, decision)

    flag = "--confirm " if confirm else ""
    return intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD, "prompt": f"/solve {flag}{text}"},
        parser_factory=Replayed, env={},
    )


def assert_read_only_preview(output, target):
    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["operations"] == ["merchant_read"] and run["risk_level"] == "read_only"
    assert run["selected_agents"] == ["merchant-manager"]
    assert run["merchant_read_target"] == target
    assert run.get("merchant_scope") is None
    envelope = intent_gate.load_intent_envelope(LEAD)
    assert envelope["requires_confirmation"] is False
    assert envelope["requires_clarification"] is False
    assert "merchant_scope" not in envelope
    return run


# ------------------------------------------------------------ live prompt


@pytest.mark.parametrize("decision", [BUG_FIXER, MERCHANT_CLARIFY], ids=["bug-fixer", "clarify"])
def test_exact_live_prompt_runs_as_read_only_preview(isolated, decision):
    run = assert_read_only_preview(submit(LIVE, decision), "test")
    assert run["confirmed"] is False


@pytest.mark.parametrize(
    "text,target",
    [
        (SHORT, "runtime"),                                      # missing Project
        (FULL, "runtime"),                                       # complete
        ("Đánh dấu bước hoàn thành cho Project Beta", "runtime"),  # missing Step
        ("Cập nhật bước Legal Review trên database test", "test"),  # missing status
        ("Mark the Legal Review step as completed", "runtime"),
        ("Mark step Legal Review done on the test database", "test"),
        ("Hoàn thành bước Legal Review", "runtime"),
        ("Mark the deploy step as done", "runtime"),               # was a FIX1 block
    ],
)
@pytest.mark.parametrize("decision", [BUG_FIXER, MERCHANT_CLARIFY], ids=["bug-fixer", "clarify"])
def test_incomplete_step_updates_reach_the_preview(isolated, text, target, decision):
    assert_read_only_preview(submit(text, decision), target)


def test_confirm_flag_grants_no_write_to_a_step_update(isolated):
    run = assert_read_only_preview(submit(LIVE, confirm=True), "test")
    assert run["confirmed"] is True and run["operations"] == ["merchant_read"]


def test_no_pending_confirmation_or_write_path_is_touched(isolated, monkeypatch):
    from claude.hooks import merchant_pending_confirmation as pending
    from claude.system import merchant_runtime_handoff as handoff

    def forbidden(*_a, **_k):
        raise AssertionError("write path reached")

    monkeypatch.setattr(handoff, "invoke_authorized_scope_apply", forbidden)
    monkeypatch.setattr(pending, "record_pending", forbidden)
    assert_read_only_preview(submit(LIVE), "test")
    assert pending.load_records(LEAD) == []


# ------------------------------------------- parser/preview consistency


def test_short_and_full_forms_agree():
    short, full = interpret_project_request(SHORT), interpret_project_request(FULL)

    for result in (short, full):
        assert result.kind == STEP_UPDATE
        assert (result.step_reference, result.target_status) == ("Legal Review", "COMPLETED")
    assert short.project_phrase is None
    assert full.project_phrase == "Beta Nguyễn Văn Cừ"
    assert parse(SHORT).operations == parse(FULL).operations == ["merchant_execute"]


def test_short_form_preview_asks_for_the_project():
    result = preview(SHORT)

    assert result["outcome"] == CLARIFY
    assert result["missing"] == ["project"]


def test_missing_step_is_not_read_from_the_verb():
    result = interpret_project_request("Đánh dấu bước hoàn thành cho Project Beta")

    assert result.step_reference is None and result.target_status == "COMPLETED"
    assert "step" in preview("Đánh dấu bước hoàn thành cho Project Beta")["missing"]
    # English "the X step" still reads the name before the noun.
    assert interpret_project_request("Mark the Legal Review step as done").step_reference == "Legal Review"


# ------------------------------------------------- what must not downgrade


@pytest.mark.parametrize(
    "text",
    [
        f"{SHORT} và lên lịch họp ngày mai",
        f"{SHORT} rồi xóa merchant Beta",
        f"{SHORT} và sửa lỗi trong step_preview.py",
        "Tạo project mở rạp Beta Nguyễn Văn Cừ và đánh dấu bước Legal Review hoàn thành",
        "Mark the Legal Review step as completed and then delete merchant Beta",
    ],
)
@pytest.mark.parametrize("decision", [BUG_FIXER, MERCHANT_ONLY], ids=["bug-fixer", "merchant"])
def test_mixed_requests_keep_external_write(isolated, text, decision):
    assert interpret_project_request(text).kind == MIXED
    output = submit(text, decision)

    assert output.get("decision") == "block"
    assert "confirmation" in output["reason"]
    assert runtime_state.load_state(LEAD) is None


@pytest.mark.parametrize(
    "text",
    ["Bước Legal Review đã hoàn thành chưa?", "Is the Legal Review step completed?",
     "Đã đánh dấu bước Legal Review hoàn thành chưa?"],
)
def test_status_questions_are_not_updates(text):
    result = interpret_project_request(text)

    assert result.kind == PROJECT_STATUS and result.write_requested is False


def test_status_question_routed_to_merchant_stays_read_only(isolated):
    read = _decision(operations=[Operation.MERCHANT_READ], domains=[Domain.MERCHANT])
    assert_read_only_preview(submit("Bước Legal Review đã hoàn thành chưa?", read), "runtime")


def test_project_create_is_still_only_a_preview(isolated):
    assert_read_only_preview(submit("Tạo project mở rạp Beta Nguyễn Văn Cừ", MERCHANT_ONLY), "runtime")


@pytest.mark.parametrize(
    "text",
    ["Set step Legal Review to in progress",  # not recognized: fails closed
     "Fix the step preview parser so Legal Review marks completed",
     "Tạo merchant Beta Cinemas mã BETA2"],
)
def test_unrecognized_or_other_writes_still_need_confirmation(isolated, text):
    assert submit(text).get("decision") == "block"
    assert runtime_state.load_state(LEAD) is None


def test_scheduled_step_update_prompt_is_denied():
    from claude.hooks.merchant_pending_confirmation import scheduled_prompt_denial

    for tool in ("CronCreate", "ScheduleWakeup", "RemoteTrigger"):
        assert scheduled_prompt_denial(tool, {"prompt": f"/solve {LIVE}"})


def test_explicit_scope_still_requires_confirm(isolated):
    output = submit("--merchant-target test --merchant-scope [step update --project-id x] " + SHORT)

    assert output.get("decision") == "block"
    assert runtime_state.load_state(LEAD) is None
