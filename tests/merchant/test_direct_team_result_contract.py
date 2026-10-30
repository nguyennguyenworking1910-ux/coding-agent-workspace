import json

import pytest

from claude.hooks.team_result_contract import (
    task_result_candidate_from_message,
)


def message(**overrides):
    payload = {
        "contract_version": 1,
        "operation": "merchant_execute",
        "database_target": "runtime",
        "outcome": "EXECUTE_SUCCESS",
        "proposal_emitted": False,
        "command": "merchant create",
    }
    payload.update(overrides)
    return "TEAM_RESULT_JSON:" + json.dumps(payload)


def test_execute_success_parses():
    result = task_result_candidate_from_message(message())
    assert result is not None
    assert result["outcome"] == "EXECUTE_SUCCESS"


def test_execute_failure_parses():
    result = task_result_candidate_from_message(
        message(outcome="EXECUTE_FAILED")
    )
    assert result is not None
    assert result["outcome"] == "EXECUTE_FAILED"


@pytest.mark.parametrize("changes", [
    # "test" is an approved declared target since CP12H.5B; whether it is
    # the run's trusted target is checked where trusted state is available.
    {"database_target": "production"},
    {"operation": "merchant_apply"},
    {"proposal_emitted": True},
    {"command": ""},
    {"command": 123},
    {"confirmation_hash": "a" * 64},
    {"proposal_hash": "a" * 64},
])
def test_invalid_direct_result_rejected(changes):
    assert task_result_candidate_from_message(
        message(**changes)
    ) is None


def test_proposal_payload_cannot_follow_direct_result():
    text = (
        message()
        + "\nMERCHANT_PROPOSAL_RESULT_JSON:"
        + json.dumps({"proposal_hash": "a" * 64})
    )
    assert task_result_candidate_from_message(text) is None
