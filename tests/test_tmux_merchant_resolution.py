"""Tests for exact transient Merchant resolution receipts."""

from __future__ import annotations

import json
import time

import pytest

from claude.hooks.tmux_merchant_resolution import (
    MAX_RESOLUTION_AGE_SECONDS,
    PENDING_MERCHANT_RESOLUTION_DIR_ENV_VAR,
    clear_pending_merchant_resolution,
    load_pending_merchant_resolution,
    pending_merchant_resolution_matches,
    pending_merchant_resolution_path,
    stage_pending_merchant_resolution,
    validate_merchant_resolution_result,
)


CGV_ID = (
    "2da7ab08-1eda-5ca2-b28e-f94f3e1be0d0"
)

BETA_ID = (
    "a6949851-958d-51df-95b8-07cdf8065291"
)

BETA_PHU_MY_ID = (
    "5b4c9bc1-bad3-5b03-9bdc-604f5adb3f26"
)


@pytest.fixture(
    autouse=True
)
def isolated_resolution_store(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        PENDING_MERCHANT_RESOLUTION_DIR_ENV_VAR,
        str(
            tmp_path
            / "pending-resolution"
        ),
    )


def resolved_cgv():
    return {
        "candidates": [
            {
                "code": "CGV",
                "merchant_id": CGV_ID,
                "name": "CGV",
            }
        ],
        "code": "CGV",
        "match_kind": "CODE",
        "merchant_id": CGV_ID,
        "mode": "RESOLUTION",
        "name": "CGV",
        "query": "CGV",
        "resolved": True,
        "status": "RESOLVED",
        "success": True,
    }


def ambiguous_beta():
    return {
        "candidates": [
            {
                "code": "BETA_CINEMA",
                "merchant_id": BETA_ID,
                "name": "BETA CINEMA",
            },
            {
                "code": "BETA_PHU_MY",
                "merchant_id": BETA_PHU_MY_ID,
                "name": "BETA PHÚ MỸ",
            },
        ],
        "code": None,
        "match_kind": "CANDIDATE",
        "merchant_id": None,
        "mode": "RESOLUTION",
        "name": None,
        "query": "BETA",
        "resolved": False,
        "status": "AMBIGUOUS",
        "success": True,
    }


def unknown_uuid():
    return {
        "candidates": [],
        "code": None,
        "match_kind": "UUID",
        "merchant_id": None,
        "mode": "RESOLUTION",
        "name": None,
        "query": (
            "00000000-0000-0000-"
            "0000-000000000999"
        ),
        "resolved": False,
        "status": "NOT_FOUND",
        "success": True,
    }


def test_valid_resolved_result_is_accepted():
    result = resolved_cgv()

    assert (
        validate_merchant_resolution_result(
            result
        )
        == result
    )


def test_valid_ambiguous_result_is_accepted():
    result = ambiguous_beta()

    assert (
        validate_merchant_resolution_result(
            result
        )
        == result
    )


def test_valid_not_found_uuid_is_accepted():
    result = unknown_uuid()

    assert (
        validate_merchant_resolution_result(
            result
        )
        == result
    )


@pytest.mark.parametrize(
    "mutation",
    (
        {
            "resolved": False,
        },
        {
            "merchant_id": None,
        },
        {
            "match_kind": "NONE",
        },
        {
            "candidates": [],
        },
    ),
)
def test_inconsistent_resolved_result_is_rejected(
    mutation,
):
    result = {
        **resolved_cgv(),
        **mutation,
    }

    assert (
        validate_merchant_resolution_result(
            result
        )
        is None
    )


def test_stage_and_load_preserve_exact_resolution():
    resolution = resolved_cgv()

    assert stage_pending_merchant_resolution(
        pane_session_id="pane-1",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        tool_use_id="tool-1",
        resolution=resolution,
    )

    receipt = (
        load_pending_merchant_resolution(
            "pane-1"
        )
    )

    assert receipt is not None

    assert (
        receipt[
            "resolution"
        ]
        == resolution
    )

    assert (
        receipt[
            "tool_use_id"
        ]
        == "tool-1"
    )


def test_receipt_matches_exact_owner_run_task():
    assert stage_pending_merchant_resolution(
        pane_session_id="pane-2",
        owner_session_id="lead-2",
        teammate_name="merchant-manager",
        run_id="run-2",
        task_id="task-2",
        resolution=resolved_cgv(),
    )

    receipt = (
        load_pending_merchant_resolution(
            "pane-2"
        )
    )

    assert receipt is not None

    assert pending_merchant_resolution_matches(
        receipt,
        owner_session_id="lead-2",
        teammate_name="merchant-manager",
        run_id="run-2",
        task_id="task-2",
    )

    assert not pending_merchant_resolution_matches(
        receipt,
        owner_session_id="lead-2",
        teammate_name="merchant-manager",
        run_id="run-CHANGED",
        task_id="task-2",
    )


def test_invalid_resolution_is_not_staged():
    invalid = {
        **resolved_cgv(),
        "merchant_id": None,
    }

    assert not stage_pending_merchant_resolution(
        pane_session_id="pane-3",
        owner_session_id="lead-3",
        teammate_name="merchant-manager",
        run_id="run-3",
        task_id="task-3",
        resolution=invalid,
    )

    assert (
        load_pending_merchant_resolution(
            "pane-3"
        )
        is None
    )


def test_expired_receipt_is_rejected():
    assert stage_pending_merchant_resolution(
        pane_session_id="pane-4",
        owner_session_id="lead-4",
        teammate_name="merchant-manager",
        run_id="run-4",
        task_id="task-4",
        resolution=resolved_cgv(),
    )

    path = (
        pending_merchant_resolution_path(
            "pane-4"
        )
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    payload[
        "created_at"
    ] = (
        time.time()
        - MAX_RESOLUTION_AGE_SECONDS
        - 1
    )

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert (
        load_pending_merchant_resolution(
            "pane-4"
        )
        is None
    )


def test_clear_removes_receipt():
    assert stage_pending_merchant_resolution(
        pane_session_id="pane-5",
        owner_session_id="lead-5",
        teammate_name="merchant-manager",
        run_id="run-5",
        task_id="task-5",
        resolution=resolved_cgv(),
    )

    assert clear_pending_merchant_resolution(
        "pane-5"
    )

    assert (
        load_pending_merchant_resolution(
            "pane-5"
        )
        is None
    )