

import json
import time

import pytest

from claude.hooks import (
    tmux_document_revision_resolution as receipts,
)


MERCHANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MERCHANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_A2 = "22222222-2222-4222-8222-222222222222"
PROJECT_B = "33333333-3333-4333-8333-333333333333"

REVISION_A1 = "41111111-1111-4111-8111-111111111111"
REVISION_A2 = "42222222-2222-4222-8222-222222222222"
REVISION_OTHER = "43333333-3333-4333-8333-333333333333"


@pytest.fixture(autouse=True)
def isolated_receipt_dir(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        receipts.DOCUMENT_REVISION_RESOLUTION_DIR_ENV,
        str(tmp_path),
    )


def _candidate(
    revision_id: str,
    *,
    project_id: str = PROJECT_A,
    merchant_id: str = MERCHANT_A,
    document_type: str = "CONTRACT",
    revision_number: int = 1,
    signed: bool = True,
    superseded_by=None,
):
    return {
        "revision_id": revision_id,
        "project_id": project_id,
        "merchant_id": merchant_id,
        "document_type": document_type,
        "revision_number": revision_number,
        "signed": signed,
        "superseded_by": superseded_by,
    }


def _project_resolved():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "CONTRACT#1",
        "scope": "PROJECT",
        "merchant_id": MERCHANT_A,
        "project_id": PROJECT_A,
        "status": "RESOLVED",
        "match_kind": "REVISION_KEY",
        "resolved": True,
        "revision_id": REVISION_A1,
        "source_project_id": PROJECT_A,
        "document_type": "CONTRACT",
        "revision_number": 1,
        "signed": True,
        "superseded_by": None,
        "candidates": [
            _candidate(
                REVISION_A1,
            ),
        ],
    }


def _merchant_resolved():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "MEDIA_APPENDIX#1",
        "scope": "MERCHANT",
        "merchant_id": MERCHANT_A,
        "project_id": None,
        "status": "RESOLVED",
        "match_kind": "REVISION_KEY",
        "resolved": True,
        "revision_id": REVISION_A2,
        "source_project_id": PROJECT_A2,
        "document_type": "MEDIA_APPENDIX",
        "revision_number": 1,
        "signed": False,
        "superseded_by": None,
        "candidates": [
            _candidate(
                REVISION_A2,
                project_id=PROJECT_A2,
                document_type="MEDIA_APPENDIX",
                revision_number=1,
                signed=False,
            ),
        ],
    }


def _merchant_ambiguous():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "CONTRACT",
        "scope": "MERCHANT",
        "merchant_id": MERCHANT_A,
        "project_id": None,
        "status": "AMBIGUOUS",
        "match_kind": "DOCUMENT_TYPE",
        "resolved": False,
        "revision_id": None,
        "source_project_id": None,
        "document_type": None,
        "revision_number": None,
        "signed": None,
        "superseded_by": None,
        "candidates": [
            _candidate(
                REVISION_A1,
                project_id=PROJECT_A,
                revision_number=1,
            ),
            _candidate(
                REVISION_A2,
                project_id=PROJECT_A2,
                revision_number=2,
            ),
        ],
    }


def _project_not_found():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "UNKNOWN#1",
        "scope": "PROJECT",
        "merchant_id": MERCHANT_A,
        "project_id": PROJECT_A,
        "status": "NOT_FOUND",
        "match_kind": "NONE",
        "resolved": False,
        "revision_id": None,
        "source_project_id": None,
        "document_type": None,
        "revision_number": None,
        "signed": None,
        "superseded_by": None,
        "candidates": [],
    }


def _stage_project(
    resolution=None,
    *,
    pane_session_id: str = "pane-1",
    merchant_id: str = MERCHANT_A,
    project_id: str = PROJECT_A,
):
    return (
        receipts.stage_pending_document_revision_resolution(
            pane_session_id=pane_session_id,
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            merchant_id=merchant_id,
            project_id=project_id,
            scope="PROJECT",
            tool_use_id="tool-1",
            resolution=(
                _project_resolved()
                if resolution is None
                else resolution
            ),
        )
    )


def _stage_merchant(
    resolution=None,
    *,
    pane_session_id: str = "pane-1",
    merchant_id: str = MERCHANT_A,
):
    return (
        receipts.stage_pending_document_revision_resolution(
            pane_session_id=pane_session_id,
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            merchant_id=merchant_id,
            project_id=None,
            scope="MERCHANT",
            tool_use_id="tool-1",
            resolution=(
                _merchant_resolved()
                if resolution is None
                else resolution
            ),
        )
    )


def test_valid_project_resolved_result_is_accepted():
    assert (
        receipts.validate_document_revision_resolution_result(
            _project_resolved()
        )
        == _project_resolved()
    )


def test_valid_merchant_resolved_result_is_accepted():
    assert (
        receipts.validate_document_revision_resolution_result(
            _merchant_resolved()
        )
        == _merchant_resolved()
    )


def test_valid_ambiguous_result_is_accepted():
    assert (
        receipts.validate_document_revision_resolution_result(
            _merchant_ambiguous()
        )
        == _merchant_ambiguous()
    )


def test_valid_not_found_result_is_accepted():
    assert (
        receipts.validate_document_revision_resolution_result(
            _project_not_found()
        )
        == _project_not_found()
    )


def test_project_stage_and_load_roundtrip():
    assert _stage_project() is True

    payload = (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
    )

    assert payload is not None
    assert payload["pane_session_id"] == "pane-1"
    assert payload["owner_session_id"] == "lead-1"
    assert payload["teammate_name"] == "merchant-manager"
    assert payload["run_id"] == "run-1"
    assert payload["task_id"] == "task-1"
    assert payload["merchant_id"] == MERCHANT_A
    assert payload["project_id"] == PROJECT_A
    assert payload["scope"] == "PROJECT"
    assert payload["tool_use_id"] == "tool-1"
    assert payload["resolution"] == _project_resolved()


def test_merchant_stage_and_load_roundtrip():
    assert _stage_merchant() is True

    payload = (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
    )

    assert payload is not None
    assert payload["merchant_id"] == MERCHANT_A
    assert payload["project_id"] is None
    assert payload["scope"] == "MERCHANT"
    assert payload["resolution"] == _merchant_resolved()


def test_project_exact_binding_matches():
    assert _stage_project() is True

    payload = (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
    )

    assert (
        receipts.pending_document_revision_resolution_matches(
            payload,
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            merchant_id=MERCHANT_A,
            project_id=PROJECT_A,
            scope="PROJECT",
        )
    )


def test_merchant_exact_binding_matches():
    assert _stage_merchant() is True

    payload = (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
    )

    assert (
        receipts.pending_document_revision_resolution_matches(
            payload,
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            merchant_id=MERCHANT_A,
            project_id=None,
            scope="MERCHANT",
        )
    )


@pytest.mark.parametrize(
    (
        "field",
        "value",
    ),
    (
        ("pane_session_id", "pane-2"),
        ("owner_session_id", "lead-2"),
        ("teammate_name", "reviewer"),
        ("run_id", "run-2"),
        ("task_id", "task-2"),
    ),
)
def test_wrong_text_binding_is_rejected(
    field,
    value,
):
    assert _stage_project() is True

    payload = (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
    )

    arguments = {
        "pane_session_id": "pane-1",
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
        "merchant_id": MERCHANT_A,
        "project_id": PROJECT_A,
        "scope": "PROJECT",
    }

    arguments[field] = value

    assert not (
        receipts.pending_document_revision_resolution_matches(
            payload,
            **arguments,
        )
    )


def test_wrong_merchant_binding_is_rejected():
    assert _stage_project() is True

    payload = (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
    )

    assert not (
        receipts.pending_document_revision_resolution_matches(
            payload,
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            merchant_id=MERCHANT_B,
            project_id=PROJECT_A,
            scope="PROJECT",
        )
    )


def test_wrong_project_binding_is_rejected():
    assert _stage_project() is True

    payload = (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
    )

    assert not (
        receipts.pending_document_revision_resolution_matches(
            payload,
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            merchant_id=MERCHANT_A,
            project_id=PROJECT_A2,
            scope="PROJECT",
        )
    )


def test_wrong_scope_binding_is_rejected():
    assert _stage_project() is True

    payload = (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
    )

    assert not (
        receipts.pending_document_revision_resolution_matches(
            payload,
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            merchant_id=MERCHANT_A,
            project_id=None,
            scope="MERCHANT",
        )
    )


def test_stage_rejects_resolution_merchant_mismatch():
    assert (
        _stage_project(
            _project_resolved(),
            merchant_id=MERCHANT_B,
        )
        is False
    )


def test_stage_rejects_resolution_project_mismatch():
    assert (
        _stage_project(
            _project_resolved(),
            project_id=PROJECT_A2,
        )
        is False
    )


def test_stage_rejects_resolution_scope_mismatch():
    assert (
        receipts.stage_pending_document_revision_resolution(
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            merchant_id=MERCHANT_A,
            project_id=None,
            scope="MERCHANT",
            tool_use_id="tool-1",
            resolution=_project_resolved(),
        )
        is False
    )


def test_merchant_scope_requires_null_project_id():
    resolution = _merchant_resolved()
    resolution["project_id"] = PROJECT_A

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_project_scope_requires_project_id():
    resolution = _project_resolved()
    resolution["project_id"] = None

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_project_scope_candidate_from_sibling_project_is_rejected():
    resolution = _project_resolved()
    resolution["source_project_id"] = PROJECT_A2
    resolution["candidates"][0]["project_id"] = PROJECT_A2

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_merchant_scope_candidate_from_sibling_project_is_accepted():
    assert (
        receipts.validate_document_revision_resolution_result(
            _merchant_resolved()
        )
        is not None
    )


def test_cross_merchant_candidate_is_rejected():
    resolution = _merchant_resolved()
    resolution["candidates"][0]["merchant_id"] = MERCHANT_B

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_resolved_candidate_must_match_top_level_revision():
    resolution = _project_resolved()
    resolution["candidates"][0]["revision_id"] = REVISION_A2

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_resolved_candidate_metadata_must_match_top_level():
    resolution = _project_resolved()
    resolution["candidates"][0]["signed"] = False

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_duplicate_revision_candidate_ids_are_rejected():
    resolution = _merchant_ambiguous()
    resolution["candidates"][1]["revision_id"] = REVISION_A1

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_malformed_revision_uuid_is_rejected():
    resolution = _project_resolved()
    resolution["revision_id"] = "not-a-uuid"

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_malformed_source_project_uuid_is_rejected():
    resolution = _project_resolved()
    resolution["source_project_id"] = "not-a-uuid"

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_invalid_revision_number_is_rejected():
    resolution = _project_resolved()
    resolution["revision_number"] = 0

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_signed_non_bool_is_rejected():
    resolution = _project_resolved()
    resolution["signed"] = "true"

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_malformed_superseded_by_is_rejected():
    resolution = _project_resolved()
    resolution["superseded_by"] = "not-a-uuid"
    resolution["candidates"][0]["superseded_by"] = "not-a-uuid"

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_ambiguous_candidates_must_be_deterministically_ordered():
    resolution = _merchant_ambiguous()
    resolution["candidates"] = list(
        reversed(
            resolution[
                "candidates"
            ]
        )
    )

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_ambiguous_requires_at_least_two_candidates():
    resolution = _merchant_ambiguous()
    resolution["candidates"] = [
        resolution["candidates"][0]
    ]

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_ambiguous_cannot_have_uuid_match_kind():
    resolution = _merchant_ambiguous()
    resolution["match_kind"] = "UUID"

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_not_found_requires_none_match_kind():
    resolution = _project_not_found()
    resolution["match_kind"] = "UUID"

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_not_found_must_have_empty_candidates():
    resolution = _project_not_found()
    resolution["candidates"] = [
        _candidate(
            REVISION_A1
        )
    ]

    assert (
        receipts.validate_document_revision_resolution_result(
            resolution
        )
        is None
    )


def test_expired_receipt_returns_none():
    assert _stage_project() is True

    path = (
        receipts.pending_document_revision_resolution_path(
            "pane-1"
        )
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    payload["created_at"] = (
        time.time()
        - receipts.DOCUMENT_REVISION_RESOLUTION_TTL_SECONDS
        - 1
    )

    path.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    assert (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
        is None
    )


def test_future_created_at_is_rejected():
    assert _stage_project() is True

    path = (
        receipts.pending_document_revision_resolution_path(
            "pane-1"
        )
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    payload["created_at"] = (
        time.time()
        + 60
    )

    path.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    assert (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
        is None
    )


def test_clear_removes_receipt():
    assert _stage_project() is True

    assert (
        receipts.clear_pending_document_revision_resolution(
            "pane-1"
        )
        is True
    )

    assert (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
        is None
    )


def test_separate_panes_are_isolated():
    assert (
        _stage_project(
            pane_session_id="pane-1"
        )
        is True
    )

    assert (
        _stage_merchant(
            pane_session_id="pane-2"
        )
        is True
    )

    first = (
        receipts.load_pending_document_revision_resolution(
            "pane-1"
        )
    )

    second = (
        receipts.load_pending_document_revision_resolution(
            "pane-2"
        )
    )

    assert first is not None
    assert second is not None

    assert first["scope"] == "PROJECT"
    assert second["scope"] == "MERCHANT"

    assert (
        receipts.pending_document_revision_resolution_path(
            "pane-1"
        )
        != receipts.pending_document_revision_resolution_path(
            "pane-2"
        )
    )


def test_receipt_alias_uses_same_exact_matcher():
    assert (
        receipts.document_revision_resolution_receipt_matches
        is receipts.pending_document_revision_resolution_matches
    )
