"""Pure Merchant Direct Execute terminal reconciliation decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DIRECT_OUTCOMES = frozenset({
    "EXECUTE_SUCCESS",
    "EXECUTE_FAILED",
    "FAILED",
    "BLOCKED",
})


def decide_direct_terminal(
    task_result: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None,
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
) -> tuple[bool, str]:
    """Decide acceptance without mutating lifecycle or running writes."""

    if not isinstance(task_result, Mapping):
        return False, "INVALID_TASK_RESULT"

    if task_result.get("operation") != "merchant_execute":
        return False, "WRONG_OPERATION"

    if task_result.get("database_target") != "runtime":
        return False, "WRONG_DATABASE"

    outcome = task_result.get("outcome")

    if outcome not in DIRECT_OUTCOMES:
        return False, "INVALID_OUTCOME"

    if outcome in {"FAILED", "BLOCKED"}:
        return True, "TERMINAL_WITHOUT_SUCCESS_CLAIM"

    if not isinstance(evidence, Mapping):
        return False, "MISSING_EXECUTION_EVIDENCE"

    expected = {
        "owner_session_id": owner_session_id,
        "teammate_name": teammate_name,
        "run_id": run_id,
        "task_id": task_id,
        "command": task_result.get("command"),
    }

    if any(
        not isinstance(value, str) or not value.strip()
        for value in expected.values()
    ):
        return False, "INVALID_BINDING"

    if any(
        evidence.get(key) != value
        for key, value in expected.items()
    ):
        return False, "EVIDENCE_BINDING_MISMATCH"

    if evidence.get("database") != "runtime":
        return False, "EVIDENCE_DATABASE_MISMATCH"

    if evidence.get("mode") != "EXECUTE":
        return False, "EVIDENCE_MODE_MISMATCH"

    if evidence.get("verified") is not True:
        return False, "UNVERIFIED_EXECUTION"

    expected_success = outcome == "EXECUTE_SUCCESS"

    if evidence.get("success") is not expected_success:
        return False, "EVIDENCE_OUTCOME_MISMATCH"

    return True, "MATCHED_EXECUTION_EVIDENCE"
