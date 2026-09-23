"""Tests for trusted Project resolver receipt consumption."""

from __future__ import annotations

from copy import deepcopy

from claude.hooks.project_resolution_gate import (
    BOUND,
    REJECTED,
    REQUIRES_CLARIFICATION,
    bind_project_resolution_receipt,
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


def candidate(
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


def resolved_project():
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
            candidate(
                PROJECT_A
            ),
        ],
    }


def ambiguous_project():
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
            candidate(
                PROJECT_A,
                title=(
                    "CGV Media Top Up 2026"
                ),
                status="PLANNED",
                version=1,
            ),
            candidate(
                PROJECT_B,
                title=(
                    "CGV Media Top Up 2027"
                ),
                status="IN_PROGRESS",
                version=2,
            ),
        ],
    }


def not_found_project():
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


def receipt(
    resolution=None,
):
    return {
        "pane_session_id": (
            "pane-1"
        ),
        "owner_session_id": (
            "lead-1"
        ),
        "teammate_name": (
            "merchant-manager"
        ),
        "run_id": (
            "run-1"
        ),
        "task_id": (
            "task-1"
        ),
        "merchant_id": (
            MERCHANT_A
        ),
        "tool_use_id": (
            "tool-1"
        ),
        "resolution": (
            resolved_project()
            if resolution is None
            else resolution
        ),
        "created_at": 1.0,
    }


def bind(
    value,
    *,
    query="CGV Media Top Up 2026",
    merchant_id=MERCHANT_A,
    pane_session_id="pane-1",
    owner_session_id="lead-1",
    teammate_name="merchant-manager",
    run_id="run-1",
    task_id="task-1",
):
    return bind_project_resolution_receipt(
        value,
        pane_session_id=(
            pane_session_id
        ),
        owner_session_id=(
            owner_session_id
        ),
        teammate_name=(
            teammate_name
        ),
        run_id=run_id,
        task_id=task_id,
        trusted_merchant_id=(
            merchant_id
        ),
        expected_query=query,
    )


def test_exact_resolved_receipt_binds_project():
    decision = bind(
        receipt()
    )

    assert decision.accepted is True

    assert decision.outcome == (
        BOUND
    )

    assert decision.query == (
        "CGV Media Top Up 2026"
    )

    assert decision.merchant_id == (
        MERCHANT_A
    )

    assert decision.project_id == (
        PROJECT_A
    )

    assert decision.title == (
        "CGV Media Top Up 2026"
    )

    assert decision.project_type == (
        "MEDIA_TOP_UP"
    )

    assert decision.workflow_variant == (
        "STANDARD"
    )

    assert decision.project_status == (
        "PLANNED"
    )

    assert decision.version == 1

    assert decision.match_kind == (
        "TITLE"
    )

    assert decision.question is None

    assert len(
        decision.candidates
    ) == 1

    assert (
        decision.candidates[0].project_id
        == PROJECT_A
    )


def test_wrong_pane_is_rejected():
    decision = bind(
        receipt(),
        pane_session_id="pane-wrong",
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REJECTED
    )

    assert decision.project_id is None


def test_wrong_owner_is_rejected():
    decision = bind(
        receipt(),
        owner_session_id="lead-wrong",
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REJECTED
    )


def test_wrong_run_is_rejected():
    decision = bind(
        receipt(),
        run_id="run-wrong",
    )

    assert decision.outcome == (
        REJECTED
    )


def test_wrong_task_is_rejected():
    decision = bind(
        receipt(),
        task_id="task-wrong",
    )

    assert decision.outcome == (
        REJECTED
    )


def test_wrong_teammate_is_rejected():
    decision = bind(
        receipt(),
        teammate_name="reviewer",
    )

    assert decision.outcome == (
        REJECTED
    )


def test_wrong_trusted_merchant_is_rejected():
    decision = bind(
        receipt(),
        merchant_id=MERCHANT_B,
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REJECTED
    )

    assert decision.project_id is None


def test_query_mismatch_is_rejected():
    decision = bind(
        receipt(),
        query=(
            "CGV Media Top Up 2027"
        ),
    )

    assert decision.outcome == (
        REJECTED
    )

    assert decision.question is None


def test_missing_receipt_is_rejected():
    decision = bind(
        None
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REJECTED
    )


def test_empty_expected_query_is_rejected():
    decision = bind(
        receipt(),
        query="",
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REJECTED
    )


def test_invalid_trusted_merchant_id_is_rejected():
    decision = bind(
        receipt(),
        merchant_id="not-a-uuid",
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REJECTED
    )


def test_malformed_resolution_is_rejected():
    value = receipt()

    value[
        "resolution"
    ] = deepcopy(
        resolved_project()
    )

    value[
        "resolution"
    ][
        "project_id"
    ] = "not-a-uuid"

    decision = bind(
        value
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REJECTED
    )


def test_resolution_merchant_mismatch_is_rejected():
    value = receipt()

    value[
        "resolution"
    ] = deepcopy(
        resolved_project()
    )

    value[
        "resolution"
    ][
        "merchant_id"
    ] = MERCHANT_B

    value[
        "resolution"
    ][
        "candidates"
    ][0][
        "merchant_id"
    ] = MERCHANT_B

    decision = bind(
        value
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REJECTED
    )


def test_cross_merchant_candidate_is_rejected():
    value = receipt(
        ambiguous_project()
    )

    value[
        "resolution"
    ][
        "candidates"
    ][1][
        "merchant_id"
    ] = MERCHANT_B

    decision = bind(
        value,
        query="Media Top Up",
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REJECTED
    )


def test_ambiguous_resolution_requires_clarification():
    decision = bind(
        receipt(
            ambiguous_project()
        ),
        query="Media Top Up",
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REQUIRES_CLARIFICATION
    )

    assert decision.merchant_id == (
        MERCHANT_A
    )

    assert decision.project_id is None

    assert decision.title is None

    assert decision.match_kind == (
        "CANDIDATE"
    )

    assert [
        item.project_id
        for item in decision.candidates
    ] == [
        PROJECT_A,
        PROJECT_B,
    ]


def test_ambiguous_question_is_deterministic():
    decision = bind(
        receipt(
            ambiguous_project()
        ),
        query="Media Top Up",
    )

    assert decision.question == (
        'Multiple projects match "Media Top Up" '
        f"for merchant {MERCHANT_A}: "
        f'"CGV Media Top Up 2026" ({PROJECT_A}), '
        f'"CGV Media Top Up 2027" ({PROJECT_B}). '
        "Please specify one project by exact UUID "
        "or full title."
    )


def test_not_found_requires_clarification():
    decision = bind(
        receipt(
            not_found_project()
        ),
        query="Unknown Project",
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REQUIRES_CLARIFICATION
    )

    assert decision.merchant_id == (
        MERCHANT_A
    )

    assert decision.project_id is None

    assert decision.candidates == ()

    assert decision.match_kind == (
        "NONE"
    )


def test_not_found_question_is_deterministic():
    decision = bind(
        receipt(
            not_found_project()
        ),
        query="Unknown Project",
    )

    assert decision.question == (
        'No project matched "Unknown Project" '
        f"for merchant {MERCHANT_A}. "
        "Please provide an exact project UUID "
        "or full project title."
    )


def test_nfkc_equivalent_query_is_accepted():
    resolution = resolved_project()

    resolution[
        "query"
    ] = (
        "ＣＧＶ Media Top Up 2026"
    )

    value = receipt(
        resolution
    )

    decision = bind(
        value,
        query=(
            "CGV Media Top Up 2026"
        ),
    )

    assert decision.accepted is True

    assert decision.outcome == (
        BOUND
    )

    assert decision.project_id == (
        PROJECT_A
    )


def test_resolved_candidate_metadata_is_preserved():
    decision = bind(
        receipt()
    )

    project = (
        decision.candidates[0]
    )

    assert project.project_id == (
        PROJECT_A
    )

    assert project.merchant_id == (
        MERCHANT_A
    )

    assert project.title == (
        "CGV Media Top Up 2026"
    )

    assert project.project_type == (
        "MEDIA_TOP_UP"
    )

    assert project.workflow_variant == (
        "STANDARD"
    )

    assert project.status == (
        "PLANNED"
    )

    assert project.version == 1