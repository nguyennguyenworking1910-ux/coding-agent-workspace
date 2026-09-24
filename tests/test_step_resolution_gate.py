"""Tests for trusted Step resolver receipt consumption."""

from __future__ import annotations

from copy import deepcopy

from claude.hooks.step_resolution_gate import (
    BOUND,
    REJECTED,
    REQUIRES_CLARIFICATION,
    bind_step_resolution_receipt,
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


def candidate(
    step_id: str,
    *,
    template_step_id: str = TEMPLATE_A,
    branch_key: str | None = "uat_branch",
    step_name: str = "Run UAT test",
    sequence_number: int = 20,
):
    return {
        "step_id": step_id,
        "project_id": PROJECT_A,
        "template_step_id": (
            template_step_id
        ),
        "branch_key": branch_key,
        "step_name": step_name,
        "step_type": (
            "PARALLEL_BRANCH"
        ),
        "status": "READY",
        "sequence_number": (
            sequence_number
        ),
        "version": 1,
        "condition_key": None,
        "is_optional": False,
    }


def resolved_step():
    return {
        "success": True,
        "mode": "STEP_RESOLUTION",
        "query": "Run UAT test",
        "project_id": PROJECT_A,
        "status": "RESOLVED",
        "match_kind": "STEP_NAME",
        "resolved": True,
        "step_id": STEP_A,
        "template_step_id": (
            TEMPLATE_A
        ),
        "branch_key": "uat_branch",
        "step_name": "Run UAT test",
        "step_type": (
            "PARALLEL_BRANCH"
        ),
        "step_status": "READY",
        "sequence_number": 20,
        "version": 1,
        "condition_key": None,
        "is_optional": False,
        "candidates": [
            candidate(
                STEP_A
            )
        ],
    }


def ambiguous_step():
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
            candidate(
                STEP_A,
                step_name="Review",
                sequence_number=10,
            ),
            candidate(
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


def not_found_step():
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
        "run_id": "run-1",
        "task_id": "task-1",
        "merchant_id": (
            MERCHANT_A
        ),
        "project_id": (
            PROJECT_A
        ),
        "tool_use_id": (
            "tool-1"
        ),
        "resolution": (
            resolved_step()
            if resolution is None
            else resolution
        ),
        "created_at": 1.0,
    }


def bind(
    value,
    *,
    query="Run UAT test",
    merchant_id=MERCHANT_A,
    project_id=PROJECT_A,
    pane_session_id="pane-1",
    owner_session_id="lead-1",
    teammate_name="merchant-manager",
    run_id="run-1",
    task_id="task-1",
):
    return bind_step_resolution_receipt(
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
        trusted_project_id=(
            project_id
        ),
        expected_query=query,
    )


def test_exact_resolved_receipt_binds_step():
    decision = bind(
        receipt()
    )

    assert decision.accepted is True
    assert decision.outcome == BOUND

    assert decision.merchant_id == (
        MERCHANT_A
    )

    assert decision.project_id == (
        PROJECT_A
    )

    assert decision.step_id == (
        STEP_A
    )

    assert (
        decision.template_step_id
        == TEMPLATE_A
    )

    assert (
        decision.branch_key
        == "uat_branch"
    )

    assert (
        decision.step_name
        == "Run UAT test"
    )

    assert (
        decision.step_status
        == "READY"
    )

    assert (
        decision.sequence_number
        == 20
    )

    assert decision.version == 1

    assert (
        decision.match_kind
        == "STEP_NAME"
    )

    assert decision.question is None


def test_wrong_pane_is_rejected():
    decision = bind(
        receipt(),
        pane_session_id=(
            "pane-wrong"
        ),
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_wrong_owner_is_rejected():
    decision = bind(
        receipt(),
        owner_session_id=(
            "lead-wrong"
        ),
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_wrong_teammate_is_rejected():
    decision = bind(
        receipt(),
        teammate_name="reviewer",
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_wrong_run_is_rejected():
    decision = bind(
        receipt(),
        run_id="run-wrong",
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_wrong_task_is_rejected():
    decision = bind(
        receipt(),
        task_id="task-wrong",
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_wrong_merchant_is_rejected():
    decision = bind(
        receipt(),
        merchant_id=MERCHANT_B,
    )

    assert decision.accepted is False

    assert (
        decision.outcome
        == REJECTED
    )


def test_wrong_project_is_rejected():
    decision = bind(
        receipt(),
        project_id=PROJECT_B,
    )

    assert decision.accepted is False

    assert (
        decision.outcome
        == REJECTED
    )


def test_missing_receipt_is_rejected():
    decision = bind(
        None
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_empty_query_is_rejected():
    decision = bind(
        receipt(),
        query="",
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_query_mismatch_is_rejected():
    decision = bind(
        receipt(),
        query="Run Production test",
    )

    assert (
        decision.outcome
        == REJECTED
    )

    assert decision.question is None


def test_malformed_step_resolution_is_rejected():
    value = receipt()

    value[
        "resolution"
    ] = deepcopy(
        resolved_step()
    )

    value[
        "resolution"
    ][
        "step_id"
    ] = "not-a-uuid"

    decision = bind(
        value
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_cross_project_resolution_is_rejected():
    value = receipt()

    value[
        "resolution"
    ] = deepcopy(
        resolved_step()
    )

    value[
        "resolution"
    ][
        "project_id"
    ] = PROJECT_B

    value[
        "resolution"
    ][
        "candidates"
    ][0][
        "project_id"
    ] = PROJECT_B

    decision = bind(
        value
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_cross_project_candidate_is_rejected():
    value = receipt(
        ambiguous_step()
    )

    value[
        "resolution"
    ][
        "candidates"
    ][1][
        "project_id"
    ] = PROJECT_B

    decision = bind(
        value,
        query="Review",
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_receipt_merchant_binding_is_authoritative():
    value = receipt()

    value[
        "merchant_id"
    ] = MERCHANT_B

    decision = bind(
        value
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_receipt_project_binding_is_authoritative():
    value = receipt()

    value[
        "project_id"
    ] = PROJECT_B

    decision = bind(
        value
    )

    assert (
        decision.outcome
        == REJECTED
    )


def test_nfkc_equivalent_query_is_accepted():
    resolution = (
        resolved_step()
    )

    resolution[
        "query"
    ] = (
        "Ｒｕｎ UAT test"
    )

    value = receipt(
        resolution
    )

    decision = bind(
        value,
        query="Run UAT test",
    )

    assert decision.accepted is True

    assert (
        decision.outcome
        == BOUND
    )

    assert (
        decision.step_id
        == STEP_A
    )


def test_ambiguous_requires_clarification():
    decision = bind(
        receipt(
            ambiguous_step()
        ),
        query="Review",
    )

    assert decision.accepted is False

    assert (
        decision.outcome
        == REQUIRES_CLARIFICATION
    )

    assert (
        decision.merchant_id
        == MERCHANT_A
    )

    assert (
        decision.project_id
        == PROJECT_A
    )

    assert decision.step_id is None

    assert len(
        decision.candidates
    ) == 2


def test_ambiguous_question_is_deterministic():
    decision = bind(
        receipt(
            ambiguous_step()
        ),
        query="Review",
    )

    assert decision.question == (
        'Multiple workflow steps match '
        '"Review" for project '
        f"{PROJECT_A}: "
        '"Review" '
        f"[uat_branch, sequence 10] ({STEP_A}), "
        '"Review" '
        f"[production_branch, sequence 20] ({STEP_B}). "
        "Please specify one Step by exact UUID."
    )


def test_not_found_requires_clarification():
    decision = bind(
        receipt(
            not_found_step()
        ),
        query="Unknown Step",
    )

    assert decision.accepted is False

    assert (
        decision.outcome
        == REQUIRES_CLARIFICATION
    )

    assert (
        decision.merchant_id
        == MERCHANT_A
    )

    assert (
        decision.project_id
        == PROJECT_A
    )

    assert decision.step_id is None
    assert decision.candidates == ()

    assert (
        decision.match_kind
        == "NONE"
    )


def test_not_found_question_is_deterministic():
    decision = bind(
        receipt(
            not_found_step()
        ),
        query="Unknown Step",
    )

    assert decision.question == (
        'No workflow step matched '
        '"Unknown Step" for project '
        f"{PROJECT_A}. "
        "Please provide an exact Step UUID "
        "or full Step name."
    )


def test_candidate_metadata_is_preserved():
    decision = bind(
        receipt()
    )

    step = (
        decision.candidates[
            0
        ]
    )

    assert step.step_id == (
        STEP_A
    )

    assert (
        step.project_id
        == PROJECT_A
    )

    assert (
        step.template_step_id
        == TEMPLATE_A
    )

    assert (
        step.branch_key
        == "uat_branch"
    )

    assert (
        step.step_name
        == "Run UAT test"
    )

    assert (
        step.step_type
        == "PARALLEL_BRANCH"
    )

    assert (
        step.status
        == "READY"
    )

    assert (
        step.sequence_number
        == 20
    )

    assert step.version == 1
    assert step.is_optional is False