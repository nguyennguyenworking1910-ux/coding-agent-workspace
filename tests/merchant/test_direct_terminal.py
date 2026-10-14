import pytest

from claude.hooks.merchant_direct_terminal import (
    decide_direct_terminal,
)


def result(outcome="EXECUTE_SUCCESS"):
    return {
        "operation": "merchant_execute",
        "database_target": "runtime",
        "command": "merchant create",
        "outcome": outcome,
    }


def evidence():
    return {
        "owner_session_id": "session-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
        "command": "merchant create",
        "database": "runtime",
        "mode": "EXECUTE",
        "success": True,
        "verified": True,
    }


def decide(task_result, proof):
    return decide_direct_terminal(
        task_result,
        proof,
        owner_session_id="session-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
    )


def test_success_with_matching_evidence():
    assert decide(result(), evidence()) == (
        True, "MATCHED_EXECUTION_EVIDENCE"
    )


def test_success_without_evidence_is_rejected():
    assert decide(result(), None)[0] is False


def test_unverified_evidence_is_rejected():
    proof = evidence()
    proof["verified"] = False
    assert decide(result(), proof)[0] is False


@pytest.mark.parametrize("field,value", [
    ("owner_session_id", "wrong-session"),
    ("teammate_name", "wrong-agent"),
    ("run_id", "wrong-run"),
    ("task_id", "wrong-task"),
    ("command", "project create"),
    ("database", "test"),
    ("mode", "APPLY"),
    ("success", False),
])
def test_mismatched_evidence_rejected(field, value):
    proof = evidence()
    proof[field] = value
    assert decide(result(), proof)[0] is False


def test_failed_execution_matches_failure_evidence():
    proof = evidence()
    proof["success"] = False

    assert decide(
        result("EXECUTE_FAILED"), proof
    )[0] is True


@pytest.mark.parametrize("outcome", ["FAILED", "BLOCKED"])
def test_terminal_without_success_claim(outcome):
    assert decide(result(outcome), None)[0] is True


def test_unknown_outcome_rejected():
    assert decide(result("UNKNOWN"), None)[0] is False
