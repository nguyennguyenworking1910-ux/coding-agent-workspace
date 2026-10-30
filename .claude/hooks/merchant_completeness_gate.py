from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from .tmux_merchant_completeness import (
        validate_completeness_result,
    )
except ImportError:
    from tmux_merchant_completeness import (  # type: ignore
        validate_completeness_result,
    )


MERCHANT_EXECUTE_OPERATION = "merchant_execute"

REQUIRES_CLARIFICATION = "REQUIRES_CLARIFICATION"
BLOCKED = "BLOCKED"
FAILED = "FAILED"

ACTION_SEMANTICS_FIELD = "action_semantics"


@dataclass(frozen=True)
class CompletenessGateDecision:
    accepted: bool
    requires_receipt: bool
    reason: str


def validate_completeness_receipt_for_outcome(
    outcome: dict[str, Any],
    receipt: dict[str, Any] | None,
) -> CompletenessGateDecision:
    """Bind one no-write Merchant outcome to exact completeness evidence.

    Completeness evidence never authorizes a write. Execution outcomes
    are verified from committed PostgreSQL evidence instead.
    """

    if not isinstance(outcome, dict):
        return _reject(
            "Merchant task outcome must be an object"
        )

    if (
        str(
            outcome.get("operation")
            or ""
        ).strip()
        != MERCHANT_EXECUTE_OPERATION
    ):
        return _reject(
            "Completeness gate applies only to merchant_execute"
        )

    outcome_name = str(
        outcome.get("outcome")
        or ""
    ).strip()

    if outcome_name in {
        BLOCKED,
        FAILED,
    }:
        return CompletenessGateDecision(
            accepted=True,
            requires_receipt=False,
            reason=(
                "Blocked and failed outcomes do not require "
                "completeness evidence"
            ),
        )

    if outcome_name == REQUIRES_CLARIFICATION:
        if _is_action_semantics_clarification(
            outcome
        ):
            if receipt is not None:
                return _reject(
                    "Pre-command action-semantics clarification "
                    "must not claim completeness evidence"
                )

            return CompletenessGateDecision(
                accepted=True,
                requires_receipt=False,
                reason=(
                    "Normalized write command was not yet "
                    "uniquely resolved"
                ),
            )

        result = _receipt_result(
            receipt
        )

        if result is None:
            return _reject(
                "REQUIRES_CLARIFICATION requires an exact "
                "incomplete completeness receipt",
                requires_receipt=True,
            )

        if result.get("complete") is not False:
            return _reject(
                "Clarification cannot use a complete=true receipt",
                requires_receipt=True,
            )

        clarification = result.get(
            "clarification"
        )

        if not isinstance(
            clarification,
            dict,
        ):
            return _reject(
                "Incomplete completeness receipt has no "
                "clarification object",
                requires_receipt=True,
            )

        expected_missing_fields = (
            clarification.get(
                "missing_fields"
            )
        )

        expected_missing_one_of = (
            clarification.get(
                "missing_one_of"
            )
        )

        expected_question = (
            clarification.get(
                "question"
            )
        )

        if (
            outcome.get(
                "missing_fields"
            )
            != expected_missing_fields
        ):
            return _reject(
                "TEAM_RESULT_JSON missing_fields does not match "
                "the exact completeness receipt",
                requires_receipt=True,
            )

        if (
            outcome.get(
                "missing_one_of"
            )
            != expected_missing_one_of
        ):
            return _reject(
                "TEAM_RESULT_JSON missing_one_of does not match "
                "the exact completeness receipt",
                requires_receipt=True,
            )

        if (
            outcome.get(
                "question"
            )
            != expected_question
        ):
            return _reject(
                "TEAM_RESULT_JSON question does not match the "
                "exact CLI-emitted clarification question",
                requires_receipt=True,
            )

        return CompletenessGateDecision(
            accepted=True,
            requires_receipt=True,
            reason=(
                "Clarification exactly matches incomplete "
                "completeness receipt"
            ),
        )

    return _reject(
        f"Unsupported no-write Merchant outcome: {outcome_name}"
    )


def _receipt_result(
    receipt: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(
        receipt,
        dict,
    ):
        return None

    result = receipt.get(
        "result"
    )

    validated = (
        validate_completeness_result(
            result
        )
    )

    if validated is None:
        return None

    return validated


def _is_action_semantics_clarification(
    outcome: dict[str, Any],
) -> bool:
    return (
        outcome.get(
            "missing_fields"
        )
        == [
            ACTION_SEMANTICS_FIELD
        ]
        and outcome.get(
            "missing_one_of"
        )
        == []
        and isinstance(
            outcome.get(
                "question"
            ),
            str,
        )
        and bool(
            outcome[
                "question"
            ].strip()
        )
    )


def _reject(
    reason: str,
    *,
    requires_receipt: bool = False,
) -> CompletenessGateDecision:
    return CompletenessGateDecision(
        accepted=False,
        requires_receipt=requires_receipt,
        reason=reason,
    )