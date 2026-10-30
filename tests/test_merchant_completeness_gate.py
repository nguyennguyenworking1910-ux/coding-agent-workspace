import pytest

from claude.hooks.merchant_completeness_gate import (
    validate_completeness_receipt_for_outcome,
)


def incomplete_receipt():
    return {
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "run-1:merchant-manager",
        "result": {
            "success": True,
            "mode": "COMPLETENESS",
            "command": (
                "document revision-create"
            ),
            "complete": False,
            "missing_fields": [
                "project_id",
                "document_type",
                "content_hash",
            ],
            "missing_one_of": [],
            "clarification": {
                "outcome": (
                    "REQUIRES_CLARIFICATION"
                ),
                "missing_fields": [
                    "project_id",
                    "document_type",
                    "content_hash",
                ],
                "missing_one_of": [],
                "question": (
                    "Please provide project_id, "
                    "document_type, and content_hash."
                ),
            },
        },
    }


def complete_receipt():
    return {
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "run-1:merchant-manager",
        "result": {
            "success": True,
            "mode": "COMPLETENESS",
            "command": "merchant create",
            "complete": True,
            "missing_fields": [],
            "missing_one_of": [],
            "clarification": None,
        },
    }


def clarification_outcome():
    return {
        "contract_version": 1,
        "outcome": "REQUIRES_CLARIFICATION",
        "operation": "merchant_execute",
        "database_target": "runtime",
        "proposal_emitted": False,
        "missing_fields": [
            "project_id",
            "document_type",
            "content_hash",
        ],
        "missing_one_of": [],
        "question": (
            "Please provide project_id, "
            "document_type, and content_hash."
        ),
    }


def test_exact_incomplete_receipt_accepts_clarification():
    decision = (
        validate_completeness_receipt_for_outcome(
            clarification_outcome(),
            incomplete_receipt(),
        )
    )

    assert decision.accepted is True
    assert decision.requires_receipt is True


def test_clarification_without_receipt_fails_closed():
    decision = (
        validate_completeness_receipt_for_outcome(
            clarification_outcome(),
            None,
        )
    )

    assert decision.accepted is False
    assert decision.requires_receipt is True


def test_clarification_question_must_match_exactly():
    outcome = clarification_outcome()
    outcome["question"] = (
        "Which project should I use?"
    )

    decision = (
        validate_completeness_receipt_for_outcome(
            outcome,
            incomplete_receipt(),
        )
    )

    assert decision.accepted is False


def test_clarification_missing_fields_must_match_exactly():
    outcome = clarification_outcome()

    outcome["missing_fields"] = [
        "project_id"
    ]

    decision = (
        validate_completeness_receipt_for_outcome(
            outcome,
            incomplete_receipt(),
        )
    )

    assert decision.accepted is False


@pytest.mark.parametrize(
    "outcome_name",
    ["PROPOSAL_READY", "EXECUTE_SUCCESS", "EXECUTE_FAILED"],
)
def test_execution_and_legacy_outcomes_are_not_completeness_outcomes(
    outcome_name,
):
    outcome = clarification_outcome()
    outcome["outcome"] = outcome_name

    decision = (
        validate_completeness_receipt_for_outcome(
            outcome,
            complete_receipt(),
        )
    )

    assert decision.accepted is False


@pytest.mark.parametrize(
    "operation",
    ["merchant_propose", "merchant_apply", "merchant_read", ""],
)
def test_non_direct_operation_is_rejected(operation):
    outcome = clarification_outcome()
    outcome["operation"] = operation

    decision = (
        validate_completeness_receipt_for_outcome(
            outcome,
            incomplete_receipt(),
        )
    )

    assert decision.accepted is False


def test_clarification_rejects_complete_receipt():
    decision = (
        validate_completeness_receipt_for_outcome(
            clarification_outcome(),
            complete_receipt(),
        )
    )

    assert decision.accepted is False


def test_action_semantics_clarification_does_not_require_receipt():
    outcome = {
        "contract_version": 1,
        "outcome": "REQUIRES_CLARIFICATION",
        "operation": "merchant_execute",
        "database_target": "runtime",
        "proposal_emitted": False,
        "missing_fields": [
            "action_semantics"
        ],
        "missing_one_of": [],
        "question": (
            "Which Merchant action should be performed?"
        ),
    }

    decision = (
        validate_completeness_receipt_for_outcome(
            outcome,
            None,
        )
    )

    assert decision.accepted is True
    assert decision.requires_receipt is False


def test_blocked_and_failed_do_not_require_receipt():
    for outcome_name in (
        "BLOCKED",
        "FAILED",
    ):
        outcome = {
            "contract_version": 1,
            "outcome": outcome_name,
            "operation": "merchant_execute",
            "database_target": "runtime",
            "proposal_emitted": False,
        }

        decision = (
            validate_completeness_receipt_for_outcome(
                outcome,
                None,
            )
        )

        assert decision.accepted is True
        assert decision.requires_receipt is False