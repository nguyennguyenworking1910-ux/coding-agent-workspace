from __future__ import annotations

import json
import time

import pytest

from claude.hooks import tmux_project_resolution as receipts


MERCHANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MERCHANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def isolated_receipt_dir(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        receipts.PROJECT_RESOLUTION_DIR_ENV,
        str(tmp_path),
    )


def _candidate(
    project_id: str,
    *,
    merchant_id: str = MERCHANT_A,
    title: str = "CGV Media Top Up 2026",
    status: str = "PLANNED",
    version: int = 1,
):
    return {
        "project_id": project_id,
        "merchant_id": merchant_id,
        "title": title,
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "status": status,
        "version": version,
    }


def _resolved():
    return {
        "success": True,
        "mode": "PROJECT_RESOLUTION",
        "query": "CGV Media Top Up 2026",
        "merchant_id": MERCHANT_A,
        "status": "RESOLVED",
        "match_kind": "TITLE",
        "resolved": True,
        "project_id": PROJECT_A,
        "title": "CGV Media Top Up 2026",
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "project_status": "PLANNED",
        "version": 1,
        "candidates": [
            _candidate(PROJECT_A),
        ],
    }


def _ambiguous():
    return {
        "success": True,
        "mode": "PROJECT_RESOLUTION",
        "query": "Media Top Up",
        "merchant_id": MERCHANT_A,
        "status": "AMBIGUOUS",
        "match_kind": "CANDIDATE",
        "resolved": False,
        "project_id": None,
        "title": None,
        "project_type": None,
        "workflow_variant": None,
        "project_status": None,
        "version": None,
        "candidates": [
            _candidate(PROJECT_A),
            _candidate(
                PROJECT_B,
                title="CGV Media Top Up 2027",
                status="IN_PROGRESS",
                version=2,
            ),
        ],
    }


def _not_found():
    return {
        "success": True,
        "mode": "PROJECT_RESOLUTION",
        "query": "Unknown Project",
        "merchant_id": MERCHANT_A,
        "status": "NOT_FOUND",
        "match_kind": "NONE",
        "resolved": False,
        "project_id": None,
        "title": None,
        "project_type": None,
        "workflow_variant": None,
        "project_status": None,
        "version": None,
        "candidates": [],
    }


def _stage(
    resolution=None,
    *,
    merchant_id: str = MERCHANT_A,
    pane_session_id: str = "pane-1",
):
    return receipts.stage_pending_project_resolution(
        pane_session_id=pane_session_id,
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        merchant_id=merchant_id,
        tool_use_id="tool-1",
        resolution=(
            _resolved()
            if resolution is None
            else resolution
        ),
    )


def test_valid_resolved_result_is_accepted():
    assert (
        receipts.validate_project_resolution_result(
            _resolved()
        )
        == _resolved()
    )


def test_valid_ambiguous_result_is_accepted():
    assert (
        receipts.validate_project_resolution_result(
            _ambiguous()
        )
        == _ambiguous()
    )


def test_valid_not_found_result_is_accepted():
    assert (
        receipts.validate_project_resolution_result(
            _not_found()
        )
        == _not_found()
    )


def test_stage_and_load_roundtrip():
    assert _stage() is True

    payload = receipts.load_pending_project_resolution(
        "pane-1"
    )

    assert payload is not None
    assert payload["pane_session_id"] == "pane-1"
    assert payload["owner_session_id"] == "lead-1"
    assert payload["teammate_name"] == "merchant-manager"
    assert payload["run_id"] == "run-1"
    assert payload["task_id"] == "task-1"
    assert payload["merchant_id"] == MERCHANT_A
    assert payload["tool_use_id"] == "tool-1"
    assert payload["resolution"] == _resolved()


def test_exact_binding_matches():
    assert _stage() is True

    payload = receipts.load_pending_project_resolution(
        "pane-1"
    )

    assert receipts.pending_project_resolution_matches(
        payload,
        pane_session_id="pane-1",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        merchant_id=MERCHANT_A,
    )


def test_wrong_pane_is_rejected():
    assert _stage() is True

    payload = receipts.load_pending_project_resolution(
        "pane-1"
    )

    assert not receipts.pending_project_resolution_matches(
        payload,
        pane_session_id="pane-2",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        merchant_id=MERCHANT_A,
    )


def test_wrong_owner_is_rejected():
    assert _stage() is True

    payload = receipts.load_pending_project_resolution(
        "pane-1"
    )

    assert not receipts.pending_project_resolution_matches(
        payload,
        pane_session_id="pane-1",
        owner_session_id="lead-2",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        merchant_id=MERCHANT_A,
    )


def test_wrong_run_or_task_is_rejected():
    assert _stage() is True

    payload = receipts.load_pending_project_resolution(
        "pane-1"
    )

    assert not receipts.pending_project_resolution_matches(
        payload,
        pane_session_id="pane-1",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-2",
        task_id="task-1",
        merchant_id=MERCHANT_A,
    )

    assert not receipts.pending_project_resolution_matches(
        payload,
        pane_session_id="pane-1",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-2",
        merchant_id=MERCHANT_A,
    )


def test_wrong_merchant_binding_is_rejected():
    assert _stage() is True

    payload = receipts.load_pending_project_resolution(
        "pane-1"
    )

    assert not receipts.pending_project_resolution_matches(
        payload,
        pane_session_id="pane-1",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        merchant_id=MERCHANT_B,
    )


def test_stage_rejects_resolution_merchant_mismatch():
    assert (
        _stage(
            _resolved(),
            merchant_id=MERCHANT_B,
        )
        is False
    )


def test_cross_merchant_candidate_is_rejected():
    resolution = _ambiguous()
    resolution["candidates"][1][
        "merchant_id"
    ] = MERCHANT_B

    assert (
        receipts.validate_project_resolution_result(
            resolution
        )
        is None
    )

    assert _stage(resolution) is False


def test_clear_removes_receipt():
    assert _stage() is True

    assert (
        receipts.clear_pending_project_resolution(
            "pane-1"
        )
        is True
    )

    assert (
        receipts.load_pending_project_resolution(
            "pane-1"
        )
        is None
    )


def test_expired_receipt_returns_none():
    assert _stage() is True

    path = receipts.pending_project_resolution_path(
        "pane-1"
    )

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )
    payload["created_at"] = (
        time.time()
        - receipts.PROJECT_RESOLUTION_TTL_SECONDS
        - 1
    )
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    assert (
        receipts.load_pending_project_resolution(
            "pane-1"
        )
        is None
    )


def test_malformed_project_uuid_is_rejected():
    resolution = _resolved()
    resolution["project_id"] = "not-a-uuid"

    assert (
        receipts.validate_project_resolution_result(
            resolution
        )
        is None
    )


def test_resolved_candidate_must_match_top_level_project():
    resolution = _resolved()
    resolution["candidates"][0][
        "project_id"
    ] = PROJECT_B

    assert (
        receipts.validate_project_resolution_result(
            resolution
        )
        is None
    )


def test_ambiguous_candidates_must_be_deterministically_ordered():
    resolution = _ambiguous()
    resolution["candidates"] = list(
        reversed(resolution["candidates"])
    )

    assert (
        receipts.validate_project_resolution_result(
            resolution
        )
        is None
    )


def test_receipt_alias_uses_same_exact_matcher():
    assert (
        receipts.project_resolution_receipt_matches
        is receipts.pending_project_resolution_matches
    )