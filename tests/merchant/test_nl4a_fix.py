"""CP12H.NL4A-FIX: the two live parser bugs and their neighbours.

Live test 2: "... Bước nào đang bị phụ thuộc vào bước khác?" took
"vào bước khác" as the Merchant (the "thuộc" of "phụ thuộc" was read as
"belongs to"). Live test 3: "Liệt kê tất cả Project ... cho biết trạng thái
từng Project" became a single-Project status lookup because the status word
outranked the list operation. No database: the read-only fake from NL4A.
"""

from __future__ import annotations

import copy
import uuid

import pytest

from claude.agents.tools.merchant.project_nl import (
    PROJECT_CREATE,
    PROJECT_LIST,
    PROJECT_STATUS,
    STEP_UPDATE,
    interpret_project_request,
)
from claude.agents.tools.merchant.project_status import CLARIFY, LIST, STATUS
from tests.merchant.test_nl1_project_preview import BETA, LOTTE, merchant
from tests.merchant.test_nl4a_project_status import (  # noqa: F401  (fixtures)
    LEAD,
    P_DONE,
    P_LOTTE,
    P_NL3,
    P_NVC,
    ExecuteParser,
    StatusReader,
    edge,
    intent_gate,
    isolated,
    runtime_state,
    status,
    step,
    summary,
)

LIVE_2 = (
    "Các bước đang chờ của Project Beta NL3 Confirmation Test trên database test là gì? "
    "Bước nào đang bị phụ thuộc vào bước khác?"
)
LIVE_3 = (
    "Liệt kê tất cả Project của Merchant Beta Cinemas trên database test "
    "và cho biết trạng thái từng Project"
)
SAO = "bbbbbbbb-0000-4000-8000-0000000000aa"
P_SAO = "aaaaaaaa-0000-4000-8000-000000000010"
P_NL3_LOTTE = "aaaaaaaa-0000-4000-8000-000000000011"


def project(project_id, title, merchant_id, code, name):
    return dict(summary(project_id, title), merchant_id=merchant_id,
                merchant_code=code, merchant_name=name)


# ------------------------------------------------- live test 2: entity context


def test_live_2_exact_request_has_no_merchant_and_resolves_the_project():
    parsed = interpret_project_request(LIVE_2)
    assert parsed.kind == PROJECT_STATUS
    assert parsed.merchant_phrase is None
    assert parsed.project_phrase == "Beta NL3 Confirmation Test"

    result = status(LIVE_2)
    assert result["outcome"] == STATUS, result["clarifications"]
    assert result["project"]["project_id"] == P_NL3
    assert result["merchant"]["match_kind"] == "FROM_PROJECT"


@pytest.mark.parametrize(
    "text",
    [
        "Bước nào của Project Beta NL3 Confirmation Test đang phụ thuộc vào bước khác?",
        "Project Beta NL3 Confirmation Test có bước nào tùy thuộc vào bước khác?",
        "Bước nào của Project Beta NL3 Confirmation Test đang chờ kết quả của bước khác?",
        "Project Beta NL3 Confirmation Test bị vướng ở đâu, bước nào lệ thuộc bước khác?",
        "Which pending steps of project Beta NL3 Confirmation Test depend on other steps?",
        "Which steps of project Beta NL3 Confirmation Test are waiting on other steps?",
    ],
)
def test_dependency_wording_is_never_a_merchant(text):
    parsed = interpret_project_request(text)

    assert parsed.kind == PROJECT_STATUS
    assert parsed.merchant_phrase is None
    assert parsed.project_phrase == "Beta NL3 Confirmation Test"
    assert status(text)["project"]["project_id"] == P_NL3


@pytest.mark.parametrize(
    "text,phrase",
    [
        ("Project Beta NL3 Confirmation Test của Merchant Beta Cinemas có bước nào phụ thuộc vào bước khác?",
         "Merchant Beta Cinemas"),
        ("Project Beta NL3 Confirmation Test thuộc Beta Cinemas có bước nào phụ thuộc vào bước khác?",
         "Beta Cinemas"),
        ("Which steps of project Beta NL3 Confirmation Test of Beta Cinemas depend on other steps?",
         "Beta Cinemas"),
    ],
)
def test_real_merchant_phrases_are_still_recognised(text, phrase):
    parsed = interpret_project_request(text)

    assert parsed.merchant_phrase == phrase
    result = status(text)
    assert result["project"]["project_id"] == P_NL3
    assert result["merchant"]["code"] == "NL2_LIVE_BETA"
    assert result["merchant"]["match_kind"] != "FROM_PROJECT"


def test_merchant_name_containing_a_preposition_is_preserved():
    reader = StatusReader([project(P_SAO, "Sao Quận 1", SAO, "SAO", "Sao Vào Cinemas")])
    reader.merchants.append(merchant(SAO, "SAO", "Sao Vào Cinemas"))
    text = "Project Sao Quận 1 của Sao Vào Cinemas đang ở bước nào?"

    assert interpret_project_request(text).merchant_phrase == "Sao Vào Cinemas"
    result = status(text, reader)
    assert result["merchant"]["code"] == "SAO"
    assert result["project"]["project_id"] == P_SAO


def test_same_title_under_two_merchants_without_a_merchant_is_ambiguous():
    reader = StatusReader([
        summary(P_NL3, "Beta NL3 Confirmation Test"),
        summary(P_NL3_LOTTE, "Beta NL3 Confirmation Test", LOTTE),
    ])

    result = status(LIVE_2, reader)

    assert result["outcome"] == CLARIFY
    assert result["project"] is None
    assert {c["project_id"] for c in result["candidates"]} == {P_NL3, P_NL3_LOTTE}
    assert {c["merchant_code"] for c in result["candidates"]} == {"NL2_LIVE_BETA", "LOTTE"}


def test_same_title_is_resolved_once_the_merchant_is_named():
    reader = StatusReader([
        summary(P_NL3, "Beta NL3 Confirmation Test"),
        summary(P_NL3_LOTTE, "Beta NL3 Confirmation Test", LOTTE),
    ])

    result = status(
        "Project Beta NL3 Confirmation Test của Lotte Cinema có bước nào phụ thuộc vào bước khác?",
        reader,
    )

    assert result["project"]["project_id"] == P_NL3_LOTTE


def test_unique_partial_title_without_a_merchant_is_only_a_candidate():
    result = status("Project NL3 Confirmation đang ở bước nào?")

    assert result["outcome"] == CLARIFY
    assert result["project"] is None
    assert [c["project_id"] for c in result["candidates"]] == [P_NL3]
    assert "steps" not in result and "step_counts" not in result


def test_unique_partial_title_within_a_named_merchant_still_resolves():
    result = status("Project Nguyễn Văn Cừ của Lotte Cinema đang ở bước nào?")

    assert result["outcome"] == STATUS
    assert result["project"]["project_id"] == P_LOTTE


# ------------------------------------------------ live test 3: list precedence


def test_live_3_exact_request_lists_projects_with_their_status():
    parsed = interpret_project_request(LIVE_3)
    assert parsed.kind == PROJECT_LIST
    assert parsed.merchant_phrase == "Merchant Beta Cinemas"
    assert parsed.write_requested is False

    result = status(LIVE_3)
    assert result["outcome"] == LIST, result["clarifications"]
    assert result["merchant"]["code"] == "NL2_LIVE_BETA"
    assert result["status_filter"] is None
    by_id = {p["project_id"]: p["status"] for p in result["projects"]}
    assert by_id == {P_NVC: "IN_PROGRESS", P_NL3: "PLANNED", P_DONE: "COMPLETED"}


@pytest.mark.parametrize(
    "text",
    [
        "Liệt kê tất cả Project của Beta Cinemas và mỗi project đang ở bước nào",
        "Danh sách Project của Merchant Beta Cinemas kèm trạng thái",
        "Trạng thái các Project của Beta Cinemas",
        "Show all projects of Beta Cinemas with their status",
        "List projects for Merchant Beta Cinemas and the status of each",
        "List all projects of Beta Cinemas and which step each one is at",
    ],
)
def test_collection_requests_are_lists_whatever_fields_they_ask_for(text):
    parsed = interpret_project_request(text)

    assert parsed.kind == PROJECT_LIST
    result = status(text)
    assert result["outcome"] == LIST, result["clarifications"]
    assert {p["project_id"] for p in result["projects"]} == {P_NVC, P_NL3, P_DONE}
    assert all(p["status"] for p in result["projects"])


@pytest.mark.parametrize(
    "text,project_id",
    [
        ("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?", P_NVC),
        ("What is the status of project Beta NL3 Confirmation Test?", P_NL3),
        ("Show me the status of project Beta NL3 Confirmation Test", P_NL3),
        ("List the steps of project Beta NL3 Confirmation Test", P_NL3),
        # A list verb over one named Project's steps is that Project's status.
        ("Liệt kê các bước của Project Beta NL3 Confirmation Test", P_NL3),
        ("Liệt kê Project Beta Nguyễn Văn Cừ đang ở bước nào?", P_NVC),
        ("Các bước đang chờ của Project Beta NL3 Confirmation Test là gì?", P_NL3),
    ],
)
def test_single_project_status_requests_are_preserved(text, project_id):
    assert interpret_project_request(text).kind == PROJECT_STATUS
    result = status(text)
    assert result["outcome"] == STATUS, result["clarifications"]
    assert result["project"]["project_id"] == project_id


def test_list_without_a_merchant_asks_and_cho_biet_is_not_a_merchant():
    text = "Liệt kê tất cả Project và cho biết trạng thái"
    parsed = interpret_project_request(text)

    assert parsed.kind == PROJECT_LIST
    assert parsed.merchant_phrase is None
    result = status(text)
    assert result["outcome"] == CLARIFY
    assert "projects" not in result


def test_status_word_in_a_list_still_honours_a_status_filter():
    result = status("Liệt kê tất cả Project đã hoàn thành của Beta Cinemas và trạng thái từng Project")

    assert result["outcome"] == LIST
    assert [p["project_id"] for p in result["projects"]] == [P_DONE]


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Tạo project mở rạp Beta Nguyễn Văn Cừ cho Beta Cinemas", PROJECT_CREATE),
        ("Cập nhật bước Legal review của project Beta là xong", STEP_UPDATE),
        ("Hoàn thành bước Legal review của tất cả Project của Beta Cinemas", STEP_UPDATE),
    ],
)
def test_writes_keep_precedence_over_list_and_status(text, kind):
    parsed = interpret_project_request(text)

    assert parsed.kind == kind
    assert parsed.write_requested is True


@pytest.mark.parametrize("text", [LIVE_2, LIVE_3])
def test_live_requests_run_read_only_without_confirm(isolated, text):
    output = intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD, "prompt": f"/solve {text}"},
        parser_factory=ExecuteParser, env={},
    )

    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["operations"] == ["merchant_read"]
    assert run["risk_level"] == "read_only"
    assert run["merchant_read_target"] == "test"
    assert run.get("merchant_scope") is None


# ---------------------------------------------- workflow output: join ordering


def reversed_id(n):
    # Real step ids are uuid5 values: their order says nothing about sequence.
    return str(uuid.UUID(int=100 - n))


class JoinReader(StatusReader):
    """Step 4 joins 3 and 2; ids sort opposite to sequence, as live ones may."""

    def get_project_detail(self, project_id):
        detail = super().get_project_detail(project_id)
        steps = [
            step(1, "Draft or renew document", "COMPLETED"),
            step(2, "Legal review", "READY", "PARALLEL_BRANCH"),
            step(3, "Accounting review", "READY", "PARALLEL_BRANCH"),
            step(4, "Send reviewed revision to Partner", "PENDING"),
        ]
        for item in steps:
            item["id"] = reversed_id(item["sequence_number"])
        detail["steps"] = steps
        detail["dependencies"] = [
            dict(edge(a, b), from_step_id=reversed_id(a), to_step_id=reversed_id(b))
            for a, b in ((1, 2), (1, 3), (2, 4), (3, 4))
        ]
        return copy.deepcopy(detail)


def test_parallel_join_lists_every_unmet_predecessor_in_sequence_order():
    result = status("Project Beta Nguyễn Văn Cừ hiện tại đến bước nào?", JoinReader())

    assert [s["sequence"] for s in result["current_steps"]] == [2, 3]
    (waiting,) = result["waiting_steps"]
    assert waiting["sequence"] == 4
    assert [p["sequence"] for p in waiting["unmet_predecessors"]] == [2, 3]
