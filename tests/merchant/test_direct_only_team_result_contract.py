import json

import pytest

from claude.hooks.team_result_contract import (
    task_result_candidate_from_message,
)


def encode(result, *, proposal=None):
    message = "TEAM_RESULT_JSON:\n" + json.dumps(result)
    if proposal is not None:
        message += (
            "\nMERCHANT_PROPOSAL_RESULT_JSON:\n"
            + json.dumps(proposal)
        )
    return message


@pytest.mark.parametrize(
    "outcome, operation, extra",
    [
        ("PROPOSAL_READY", "merchant_propose", {}),
        (
            "APPLY_SUCCESS",
            "merchant_apply",
            {"confirmation_hash": "a" * 64},
        ),
        (
            "APPLY_FAILED",
            "merchant_apply",
            {"confirmation_hash": "a" * 64},
        ),
    ],
)
def test_legacy_outcomes_are_rejected(
    outcome, operation, extra
):
    result = {
        "contract_version": 1,
        "outcome": outcome,
        "operation": operation,
        "database_target": "runtime",
        "proposal_emitted": outcome == "PROPOSAL_READY",
        **extra,
    }

    assert task_result_candidate_from_message(
        encode(result)
    ) is None


def test_legacy_proposal_delivery_block_is_rejected():
    result = {
        "contract_version": 1,
        "outcome": "PROPOSAL_READY",
        "operation": "merchant_propose",
        "database_target": "runtime",
        "proposal_emitted": True,
    }

    assert task_result_candidate_from_message(
        encode(result, proposal={"mode": "PROPOSE"})
    ) is None


def test_direct_execute_outcome_remains_valid():
    result = {
        "contract_version": 1,
        "outcome": "EXECUTE_SUCCESS",
        "operation": "merchant_execute",
        "database_target": "runtime",
        "proposal_emitted": False,
        "command": "merchant create",
    }

    assert task_result_candidate_from_message(
        encode(result)
    ) == result
