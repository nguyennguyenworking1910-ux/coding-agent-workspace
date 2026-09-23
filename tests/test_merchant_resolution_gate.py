"""Tests for trusted Merchant resolver receipt consumption."""

from __future__ import annotations

from copy import deepcopy

from claude.hooks.merchant_resolution_gate import (
    BOUND,
    REJECTED,
    REQUIRES_CLARIFICATION,
    bind_merchant_resolution_receipt,
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


def not_found():
    return {
        "candidates": [],
        "code": None,
        "match_kind": "NONE",
        "merchant_id": None,
        "mode": "RESOLUTION",
        "name": None,
        "query": "UNKNOWN",
        "resolved": False,
        "status": "NOT_FOUND",
        "success": True,
    }


def receipt(
    resolution=None,
):
    return {
        "pane_session_id": "pane-1",
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
        "tool_use_id": "tool-1",
        "resolution": (
            resolved_cgv()
            if resolution is None
            else resolution
        ),
        "created_at": 1.0,
    }


def bind(
    value,
    *,
    query="CGV",
    pane_session_id="pane-1",
    owner_session_id="lead-1",
    teammate_name="merchant-manager",
    run_id="run-1",
    task_id="task-1",
):
    return bind_merchant_resolution_receipt(
        value,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        expected_query=query,
    )


def test_exact_resolved_receipt_binds_merchant():
    decision = bind(
        receipt()
    )

    assert decision.accepted is True
    assert decision.outcome == BOUND
    assert decision.query == "CGV"
    assert decision.merchant_id == CGV_ID
    assert decision.code == "CGV"
    assert decision.name == "CGV"
    assert decision.match_kind == "CODE"
    assert decision.question is None


def test_wrong_pane_is_rejected():
    decision = bind(
        receipt(),
        pane_session_id="pane-wrong",
    )

    assert decision.accepted is False
    assert decision.outcome == REJECTED


def test_wrong_owner_is_rejected():
    decision = bind(
        receipt(),
        owner_session_id="lead-wrong",
    )

    assert decision.outcome == REJECTED
    assert decision.merchant_id is None


def test_wrong_run_is_rejected():
    decision = bind(
        receipt(),
        run_id="run-wrong",
    )

    assert decision.outcome == REJECTED


def test_wrong_task_is_rejected():
    decision = bind(
        receipt(),
        task_id="task-wrong",
    )

    assert decision.outcome == REJECTED


def test_wrong_teammate_is_rejected():
    decision = bind(
        receipt(),
        teammate_name="reviewer",
    )

    assert decision.outcome == REJECTED


def test_query_mismatch_is_rejected():
    decision = bind(
        receipt(),
        query="LOTTE",
    )

    assert decision.outcome == REJECTED
    assert decision.question is None


def test_malformed_resolution_is_rejected():
    value = receipt()

    value[
        "resolution"
    ] = deepcopy(
        resolved_cgv()
    )

    value[
        "resolution"
    ][
        "merchant_id"
    ] = None

    decision = bind(
        value
    )

    assert decision.outcome == REJECTED


def test_ambiguous_resolution_requires_exact_clarification():
    decision = bind(
        receipt(
            ambiguous_beta()
        ),
        query="BETA",
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REQUIRES_CLARIFICATION
    )

    assert decision.merchant_id is None

    assert [
        candidate.code
        for candidate in decision.candidates
    ] == [
        "BETA_CINEMA",
        "BETA_PHU_MY",
    ]

    assert decision.question == (
        'Multiple merchants match "BETA": '
        "BETA_CINEMA, BETA_PHU_MY. "
        "Please specify one merchant by exact code or UUID."
    )


def test_not_found_requires_exact_clarification():
    decision = bind(
        receipt(
            not_found()
        ),
        query="UNKNOWN",
    )

    assert decision.accepted is False

    assert decision.outcome == (
        REQUIRES_CLARIFICATION
    )

    assert decision.candidates == ()

    assert decision.question == (
        'No merchant matched "UNKNOWN". '
        "Please provide an exact merchant code, name, or UUID."
    )


def test_nfkc_equivalent_query_is_accepted():
    resolution = resolved_cgv()

    resolution[
        "query"
    ] = "ＣＧＶ"

    value = receipt(
        resolution
    )

    decision = bind(
        value,
        query="CGV",
    )

    assert decision.accepted is True
    assert decision.merchant_id == CGV_ID