from __future__ import annotations

import json
import time

import pytest

from claude.hooks import (
    tmux_step_resolution
    as receipts,
)


MERCHANT_A = (
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
)

MERCHANT_B = (
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
)

PROJECT_A = (
    "11111111-1111-4111-8111-111111111111"
)

PROJECT_B = (
    "22222222-2222-4222-8222-222222222222"
)

STEP_A = (
    "33333333-3333-4333-8333-333333333333"
)

STEP_B = (
    "44444444-4444-4444-8444-444444444444"
)

TEMPLATE_A = (
    "55555555-5555-4555-8555-555555555555"
)

TEMPLATE_B = (
    "66666666-6666-4666-8666-666666666666"
)


@pytest.fixture(
    autouse=True
)
def isolated_receipt_dir(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        receipts.STEP_RESOLUTION_DIR_ENV,
        str(
            tmp_path
        ),
    )


def _candidate(
    step_id: str,
    *,
    project_id: str = PROJECT_A,
    template_step_id: str = TEMPLATE_A,
    branch_key: str | None = "uat_branch",
    step_name: str = "Run UAT test",
    status: str = "READY",
    sequence_number: int = 20,
    version: int = 1,
):
    return {
        "step_id": step_id,
        "project_id": project_id,
        "template_step_id": (
            template_step_id
        ),
        "branch_key": branch_key,
        "step_name": step_name,
        "step_type": (
            "PARALLEL_BRANCH"
        ),
        "status": status,
        "sequence_number": (
            sequence_number
        ),
        "version": version,
        "condition_key": None,
        "is_optional": False,
    }


def _resolved():
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": "Run UAT test",
        "project_id": PROJECT_A,
        "status": "RESOLVED",
        "match_kind": "STEP_NAME",
        "resolved": True,
        "step_id": STEP_A,
        "template_step_id": TEMPLATE_A,
        "branch_key": "uat_branch",
        "step_name": "Run UAT test",
        "step_type": "PARALLEL_BRANCH",
        "step_status": "READY",
        "sequence_number": 20,
        "version": 1,
        "condition_key": None,
        "is_optional": False,
        "candidates": [
            _candidate(
                STEP_A
            )
        ],
    }


def _ambiguous():
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": "Review",
        "project_id": PROJECT_A,
        "status": "AMBIGUOUS",
        "match_kind": "STEP_NAME",
        "resolved": False,
        "step_id": None,
        "template_step_id": None,
        "branch_key": None,
        "step_name": None,
        "step_type": None,
        "step_status": None,
        "sequence_number": None,
        "version": None,
        "condition_key": None,
        "is_optional": None,
        "candidates": [
            _candidate(
                STEP_A,
                branch_key=(
                    "uat_branch"
                ),
                step_name="Review",
                sequence_number=10,
            ),
            _candidate(
                STEP_B,
                template_step_id=TEMPLATE_B,
                branch_key=(
                    "production_branch"
                ),
                step_name="Review",
                sequence_number=20,
            ),
        ],
    }


def _not_found():
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": "Unknown Step",
        "project_id": PROJECT_A,
        "status": "NOT_FOUND",
        "match_kind": "NONE",
        "resolved": False,
        "step_id": None,
        "template_step_id": None,
        "branch_key": None,
        "step_name": None,
        "step_type": None,
        "step_status": None,
        "sequence_number": None,
        "version": None,
        "condition_key": None,
        "is_optional": None,
        "candidates": [],
    }


def _stage(
    resolution=None,
    *,
    merchant_id: str = MERCHANT_A,
    project_id: str = PROJECT_A,
    pane_session_id: str = "pane-1",
):
    return (
        receipts
        .stage_pending_step_resolution(
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id="lead-1",
            teammate_name=(
                "merchant-manager"
            ),
            run_id="run-1",
            task_id="task-1",
            merchant_id=(
                merchant_id
            ),
            project_id=(
                project_id
            ),
            tool_use_id="tool-1",
            resolution=(
                _resolved()
                if resolution is None
                else resolution
            ),
        )
    )


def test_valid_resolved_is_accepted():
    assert (
        receipts
        .validate_step_resolution_result(
            _resolved()
        )
        == _resolved()
    )


def test_valid_ambiguous_is_accepted():
    assert (
        receipts
        .validate_step_resolution_result(
            _ambiguous()
        )
        == _ambiguous()
    )


def test_valid_not_found_is_accepted():
    assert (
        receipts
        .validate_step_resolution_result(
            _not_found()
        )
        == _not_found()
    )


def test_stage_and_load_roundtrip():
    assert _stage() is True

    payload = (
        receipts
        .load_pending_step_resolution(
            "pane-1"
        )
    )

    assert payload is not None

    assert (
        payload[
            "pane_session_id"
        ]
        == "pane-1"
    )

    assert (
        payload[
            "owner_session_id"
        ]
        == "lead-1"
    )

    assert (
        payload[
            "teammate_name"
        ]
        == "merchant-manager"
    )

    assert (
        payload["run_id"]
        == "run-1"
    )

    assert (
        payload["task_id"]
        == "task-1"
    )

    assert (
        payload[
            "merchant_id"
        ]
        == MERCHANT_A
    )

    assert (
        payload[
            "project_id"
        ]
        == PROJECT_A
    )

    assert (
        payload[
            "tool_use_id"
        ]
        == "tool-1"
    )

    assert (
        payload["resolution"]
        == _resolved()
    )


def test_exact_binding_matches():
    assert _stage() is True

    payload = (
        receipts
        .load_pending_step_resolution(
            "pane-1"
        )
    )

    assert (
        receipts
        .pending_step_resolution_matches(
            payload,
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name=(
                "merchant-manager"
            ),
            run_id="run-1",
            task_id="task-1",
            merchant_id=MERCHANT_A,
            project_id=PROJECT_A,
        )
    )


@pytest.mark.parametrize(
    (
        "field",
        "value",
    ),
    [
        (
            "pane_session_id",
            "pane-2",
        ),
        (
            "owner_session_id",
            "lead-2",
        ),
        (
            "teammate_name",
            "other-agent",
        ),
        (
            "run_id",
            "run-2",
        ),
        (
            "task_id",
            "task-2",
        ),
        (
            "merchant_id",
            MERCHANT_B,
        ),
        (
            "project_id",
            PROJECT_B,
        ),
    ],
)
def test_wrong_binding_is_rejected(
    field,
    value,
):
    assert _stage() is True

    payload = (
        receipts
        .load_pending_step_resolution(
            "pane-1"
        )
    )

    kwargs = {
        "pane_session_id": (
            "pane-1"
        ),
        "owner_session_id": (
            "lead-1"
        ),
        "teammate_name": (
            "merchant-manager"
        ),
        "run_id": "run-1",
        "task_id": "task-1",
        "merchant_id": MERCHANT_A,
        "project_id": PROJECT_A,
    }

    kwargs[field] = value

    assert not (
        receipts
        .pending_step_resolution_matches(
            payload,
            **kwargs,
        )
    )


def test_stage_rejects_project_mismatch():
    assert (
        _stage(
            _resolved(),
            project_id=PROJECT_B,
        )
        is False
    )


def test_candidate_from_other_project_is_rejected():
    resolution = (
        _ambiguous()
    )

    resolution[
        "candidates"
    ][1][
        "project_id"
    ] = PROJECT_B

    assert (
        receipts
        .validate_step_resolution_result(
            resolution
        )
        is None
    )

    assert (
        _stage(
            resolution
        )
        is False
    )


def test_template_step_id_cannot_replace_step_id():
    resolution = (
        _resolved()
    )

    resolution[
        "step_id"
    ] = TEMPLATE_A

    assert (
        receipts
        .validate_step_resolution_result(
            resolution
        )
        is None
    )


def test_resolved_candidate_must_match_top_level_step():
    resolution = (
        _resolved()
    )

    resolution[
        "candidates"
    ][0][
        "step_id"
    ] = STEP_B

    assert (
        receipts
        .validate_step_resolution_result(
            resolution
        )
        is None
    )


def test_resolved_candidate_branch_must_match_top_level():
    resolution = (
        _resolved()
    )

    resolution[
        "candidates"
    ][0][
        "branch_key"
    ] = "production_branch"

    assert (
        receipts
        .validate_step_resolution_result(
            resolution
        )
        is None
    )


def test_ambiguous_candidates_must_use_workflow_order():
    resolution = (
        _ambiguous()
    )

    resolution[
        "candidates"
    ] = list(
        reversed(
            resolution[
                "candidates"
            ]
        )
    )

    assert (
        receipts
        .validate_step_resolution_result(
            resolution
        )
        is None
    )


def test_duplicate_candidate_step_ids_are_rejected():
    resolution = (
        _ambiguous()
    )

    resolution[
        "candidates"
    ][1][
        "step_id"
    ] = STEP_A

    assert (
        receipts
        .validate_step_resolution_result(
            resolution
        )
        is None
    )


def test_clear_removes_receipt():
    assert _stage() is True

    assert (
        receipts
        .clear_pending_step_resolution(
            "pane-1"
        )
        is True
    )

    assert (
        receipts
        .load_pending_step_resolution(
            "pane-1"
        )
        is None
    )


def test_expired_receipt_returns_none():
    assert _stage() is True

    path = (
        receipts
        .pending_step_resolution_path(
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
        - receipts
        .STEP_RESOLUTION_TTL_SECONDS
        - 1
    )

    path.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    assert (
        receipts
        .load_pending_step_resolution(
            "pane-1"
        )
        is None
    )


def test_malformed_step_uuid_is_rejected():
    resolution = (
        _resolved()
    )

    resolution[
        "step_id"
    ] = "not-a-uuid"

    assert (
        receipts
        .validate_step_resolution_result(
            resolution
        )
        is None
    )


def test_malformed_template_step_uuid_is_rejected():
    resolution = (
        _resolved()
    )

    resolution[
        "template_step_id"
    ] = "not-a-uuid"

    assert (
        receipts
        .validate_step_resolution_result(
            resolution
        )
        is None
    )


def test_receipt_alias_uses_same_exact_matcher():
    assert (
        receipts
        .step_resolution_receipt_matches
        is receipts
        .pending_step_resolution_matches
    )