"""CP12H.NL4B-FIX2: target status parsing, complete clarification, and
labelled dependency evidence for the read-only Step Update preview.

Live failure: "Đánh dấu bước Legal Review hoàn thành trên database test" lost
its target status (a bare state word after the step name, no "là"/"thành"
connector) and the preview asked only for the status, never for the missing
Project.
"""

from __future__ import annotations

import copy
import json

import pytest

from claude.agents.tools.merchant.project_nl import (
    PROJECT_STATUS,
    STEP_UPDATE,
    interpret_project_request,
)
from claude.agents.tools.merchant.step_preview import BLOCKED, CLARIFY
from tests.merchant.test_nl4b_step_preview import (
    NVC,
    P_NVC,
    STEPS,
    StepReader,
    preview,
    step,
)

LIVE = "Đánh dấu bước Legal Review hoàn thành trên database test"


# ------------------------------------------------- target status parsing


def test_exact_live_request_is_parsed():
    result = interpret_project_request(LIVE)

    assert result.kind == STEP_UPDATE
    assert (result.step_reference, result.target_status) == ("Legal Review", "COMPLETED")
    assert result.project_phrase is None and result.merchant_phrase is None


@pytest.mark.parametrize(
    "text",
    [
        "Đánh dấu bước Legal Review hoàn thành",
        "Đánh dấu Legal Review là hoàn thành",
        "Cập nhật bước Legal Review thành hoàn thành",
        "Mark Legal Review as completed",
        "Complete the Legal Review step",
        "Đánh dấu bước Legal Review đã hoàn thành",
    ],
)
def test_equivalent_update_requests_agree(text):
    result = interpret_project_request(text)

    assert result.kind == STEP_UPDATE, text
    assert (result.step_reference, result.target_status) == ("Legal Review", "COMPLETED")
    assert result.negated is False


@pytest.mark.parametrize(
    "text,project",
    [
        (f"Đánh dấu bước Legal Review của {NVC} hoàn thành", "Beta Nguyễn Văn Cừ"),
        (f"Mark Legal Review of {NVC} as completed", "Beta Nguyễn Văn Cừ"),
        (f"Đánh dấu bước Legal Review hoàn thành cho {NVC}", "Beta Nguyễn Văn Cừ"),
    ],
)
def test_bare_state_keeps_the_project_phrase(text, project):
    result = interpret_project_request(text)

    assert (result.step_reference, result.target_status) == ("Legal Review", "COMPLETED")
    assert result.project_phrase == project


def test_bare_in_progress_state_is_parsed():
    result = interpret_project_request(f"Cập nhật bước 2 của {NVC} đang thực hiện")
    assert (result.step_reference, result.target_status) == ("2", "IN_PROGRESS")


@pytest.mark.parametrize(
    "text",
    [
        "Legal Review đã hoàn thành chưa?",
        "Bước nào đã hoàn thành?",
        f"Bước Legal Review của {NVC} đã hoàn thành chưa trên database test?",
        "Đã đánh dấu bước Legal Review hoàn thành chưa?",
        "Did you mark the Legal Review step as completed?",
    ],
)
def test_status_questions_are_never_updates(text):
    result = interpret_project_request(text)

    assert result.kind != STEP_UPDATE, text
    assert result.write_requested is False


@pytest.mark.parametrize(
    "text",
    [
        "Đừng đánh dấu bước Legal Review hoàn thành",
        "Không đánh dấu Legal Review là hoàn thành",
        "Đánh dấu bước Legal Review không hoàn thành",
        "Do not mark Legal Review as completed",
        "Có nên đánh dấu bước Legal Review hoàn thành không?",
        "Có lẽ đánh dấu bước Legal Review hoàn thành",
        "Maybe mark Legal Review as completed",
    ],
)
def test_negated_or_uncertain_updates_fail_closed(text):
    result = interpret_project_request(text)
    assert result.write_requested is False, text

    previewed = preview(f"{text} của {NVC}")
    assert previewed["outcome"] == CLARIFY and previewed["step"] is None
    assert previewed["transition"] is None


@pytest.mark.parametrize(
    "text",
    [
        "Đánh dấu bước Legal Review hoàn thành đang thực hiện",  # two states
        "Mark project Beta Nguyễn Văn Cừ as completed",          # no step
    ],
)
def test_conflicting_or_stepless_requests_never_bind(text):
    result = interpret_project_request(text)
    assert result.target_status is None or result.step_reference is None


# ------------------------------------------------- clarification completeness


def test_live_request_asks_only_for_the_project():
    reader = StepReader()
    result = preview(LIVE, reader)

    assert result["outcome"] == CLARIFY
    assert result["query"]["step_reference"] == "Legal Review"
    assert result["query"]["target_status"] == "COMPLETED"
    assert result["missing"] == ["project"]
    assert len(result["clarifications"]) == 1
    assert "Project" in result["clarifications"][0]
    assert "status" not in result["clarifications"][0]
    # Never a guess: no Project, step or candidate was invented.
    assert result["project"] is None and result["step"] is None
    assert result["candidates"] == []


def test_missing_target_with_known_project():
    result = preview(f"Cập nhật bước 2 của {NVC}")

    assert result["outcome"] == CLARIFY and result["missing"] == ["target_status"]
    assert result["project"]["project_id"] == P_NVC
    assert result["step"] is None and result["transition"] is None


def test_missing_target_and_project():
    result = preview("Cập nhật bước Legal Review")

    assert result["outcome"] == CLARIFY
    assert result["missing"] == ["target_status", "project"]
    assert len(result["clarifications"]) == 2


def test_missing_step_with_known_project():
    result = preview(f"Đánh dấu {NVC} là hoàn thành")

    assert result["outcome"] == CLARIFY and "step" in result["missing"]
    assert result["step"] is None


def test_ambiguous_project_returns_grounded_candidates():
    result = preview("Đánh dấu bước Legal Review của Project Nguyễn Văn Cừ hoàn thành")

    assert result["outcome"] == CLARIFY and result["missing"] == ["project"]
    assert sorted(c["title"] for c in result["candidates"]) == [
        "Beta Nguyễn Văn Cừ", "Lotte Nguyễn Văn Cừ",
    ]
    assert result["project"] is None


def test_complete_request_has_nothing_missing():
    result = preview(f"Bắt đầu bước 2 của {NVC}")
    assert result["missing"] == [] and result["clarifications"] == []


# ------------------------------------------------- dependency evidence


def test_direct_and_transitive_dependencies_are_labelled():
    # The live shape: 1 READY; 2 and 3 wait on 1; 4 waits on 2 and 3.
    steps = [
        step(1, "Draft or renew document", "READY"),
        step(2, "Legal Review", "PENDING"),
        step(3, "Accounting Review", "PENDING"),
        step(4, "Send reviewed revision to Partner", "PENDING"),
    ] + [s for s in STEPS if s["sequence_number"] > 4]
    result = preview(f"Đánh dấu bước 4 của {NVC} hoàn thành", StepReader(steps=steps))

    assert result["outcome"] == BLOCKED
    assert result["unmet_dependency_scope"] == "DIRECT"
    assert [s["sequence"] for s in result["unmet_dependencies"]] == [2, 3]
    assert [s["sequence"] for s in result["unmet_transitive_dependencies"]] == [1, 2, 3]
    assert result["unmet_transitive_count"] == 3
    message = next(b["message"] for b in result["blocking"] if b["code"] == "UNMET_DEPENDENCIES")
    assert "2 Legal Review" in message and "3 Accounting Review" in message
    assert "1 Draft or renew document" in message  # the ancestor is named, not inferred


def test_met_dependencies_list_nothing():
    result = preview(f"Bắt đầu bước 2 của {NVC}")

    assert result["unmet_dependencies"] == [] and result["unmet_transitive_dependencies"] == []
    assert result["unmet_transitive_count"] == 0


# ------------------------------------------------- read-only guarantees


@pytest.mark.parametrize("text", [LIVE, f"Đánh dấu bước 4 của {NVC} hoàn thành",
                                  "Mark Legal Review as completed"])
def test_new_paths_stay_read_only_without_authorization(text):
    reader = StepReader()
    before = copy.deepcopy((reader.projects, reader.steps))
    result = preview(text, reader)

    assert result["read_only"] is True and result["executable"] is False
    assert result["confirmation_available"] is False and result["authorization"] is None
    dumped = json.dumps(result, default=str)
    for forbidden in ("argv", "confirmation_command", "--merchant-scope",
                      "requested_operation", "pending"):
        assert forbidden not in dumped
    assert (reader.projects, reader.steps) == before


def test_live_request_routes_as_a_read(isolated):  # noqa: F811
    from tests.merchant.test_nl2e_p1_p2_p4 import LEAD, intent_gate, runtime_state
    from tests.merchant.test_nl4a_project_status import ExecuteParser

    output = intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD, "prompt": f"/solve {LIVE}"},
        parser_factory=ExecuteParser, env={},
    )

    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["operations"] == ["merchant_read"] and run["risk_level"] == "read_only"
    assert run["merchant_read_target"] == "test"
    assert run.get("merchant_scope") is None


from tests.merchant.test_nl2e_p1_p2_p4 import isolated  # noqa: E402,F401  (fixture)
