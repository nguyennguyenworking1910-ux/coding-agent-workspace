"""CP12H.MASTER-FINAL: Project start versus Project creation routing."""

from __future__ import annotations

import pytest

from claude.agents.tools.merchant.evidence_preview import build_evidence_preview
from claude.agents.tools.merchant.project_nl import (
    EVIDENCE_WRITE,
    MIXED,
    PROJECT_CREATE,
    interpret_project_request,
)
from tests.merchant.test_nl4d2_evidence_discovery import NAMED, EvidenceReader

TRUSTED = {"status": "TRUSTED", "operator_id": "0d5a0000-0000-4000-8000-0000000000c2"}
NAME = NAMED.split(" ", 1)[1]          # the Project name without the noun


def preview(text):
    return build_evidence_preview(text, EvidenceReader(), database_target="test", operator=TRUSTED)


@pytest.mark.parametrize("text", [
    f"Start project {NAME} on the test database",
    f"Start the project {NAME}",
    f"Begin project {NAME}",
    f"Kick off project {NAME}",
    f"Bắt đầu Project {NAME} trên database test",
    f"Khởi động dự án {NAME}",
])
def test_starting_an_existing_project_is_a_project_start_not_a_creation(text):
    interpretation = interpret_project_request(text)
    assert interpretation.kind == EVIDENCE_WRITE and interpretation.write_requested
    assert interpretation.project_phrase == NAME
    result = preview(text)
    assert result["operation_kind"] == "START_PROJECT"
    assert result["requested_operation"] is None or result["requested_operation"]["operation"] == "START_PROJECT"


@pytest.mark.parametrize("text", [
    "Create project mở rạp Beta Nguyễn Văn Cừ",
    "Tạo Project mở rạp Beta Nguyễn Văn Cừ",
    "Start a new cinema opening project for Beta Nguyễn Văn Cừ",
    "Start a new project for Beta Cinemas",
    "Tạo dự án mới cho Beta Cinemas",
])
def test_creating_a_project_stays_a_creation(text):
    assert interpret_project_request(text).kind == PROJECT_CREATE


@pytest.mark.parametrize("text", [
    f"Don't start project {NAME}",
    f"Không bắt đầu Project {NAME}",
])
def test_a_negated_start_requests_nothing(text):
    interpretation = interpret_project_request(text)
    assert not interpretation.write_requested


def test_starting_and_completing_in_one_request_is_mixed():
    assert interpret_project_request(
        f"Bắt đầu Project {NAME} rồi hoàn tất Project {NAME}").kind == MIXED


def test_an_unknown_project_to_start_asks_and_creates_nothing():
    result = preview("Start project Không Có Thật on the test database")
    assert result["outcome"] == "NEEDS_CLARIFICATION"
    assert result["requested_operation"] is None
