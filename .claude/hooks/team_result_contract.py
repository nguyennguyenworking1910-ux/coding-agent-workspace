"""Pure structured task-result contract parsing.

This module validates machine-readable teammate outcomes only.
It performs no state mutation, lifecycle transition, Merchant apply,
or external side effect.
"""

from __future__ import annotations

import json
from typing import Any


TEAM_RESULT_MARKER = (
    "TEAM_RESULT_JSON:"
)

TEAM_RESULT_CONTRACT_VERSION = 1

MERCHANT_EXECUTE_SUCCESS_OUTCOME = "EXECUTE_SUCCESS"
MERCHANT_EXECUTE_FAILED_OUTCOME = "EXECUTE_FAILED"
MERCHANT_EXECUTE_UNCERTAIN_OUTCOME = "EXECUTE_UNCERTAIN"

MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES = {
    "REQUIRES_CLARIFICATION",
    "FAILED",
    "BLOCKED",
}


def task_result_candidate_from_message(
    message: str,
) -> dict[str, Any] | None:
    """Parse one strict structured teammate task outcome.

    This result describes what actually happened during the task.
    It is not authorization and never grants Merchant execution
    authority; committed PostgreSQL evidence does.
    """

    report = str(
        message
        or ""
    ).strip()

    if (
        report.count(
            TEAM_RESULT_MARKER
        )
        != 1
    ):
        return None

    _, encoded = (
        report.split(
            TEAM_RESULT_MARKER,
            1,
        )
    )

    encoded = encoded.strip()

    if not encoded:
        return None

    try:
        candidate, end = (
            json.JSONDecoder().raw_decode(
                encoded
            )
        )
    except json.JSONDecodeError:
        return None

    # Direct-only: reject trailing legacy proposal data.
    if encoded[end:].strip():
        return None

    if not isinstance(
        candidate,
        dict,
    ):
        return None

    if (
        candidate.get(
            "contract_version"
        )
        != TEAM_RESULT_CONTRACT_VERSION
    ):
        return None

    outcome = str(
        candidate.get(
            "outcome"
        )
        or ""
    ).strip()

    operation = str(
        candidate.get(
            "operation"
        )
        or ""
    ).strip()

    database_target = str(
        candidate.get(
            "database_target"
        )
        or ""
    ).strip()

    proposal_emitted = (
        candidate.get(
            "proposal_emitted"
        )
    )

    allowed_outcomes = {
        MERCHANT_EXECUTE_SUCCESS_OUTCOME,
        MERCHANT_EXECUTE_FAILED_OUTCOME,
        MERCHANT_EXECUTE_UNCERTAIN_OUTCOME,
        *MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES,
    }

    if outcome not in allowed_outcomes:
        return None

    if not (
        operation
        and database_target
    ):
        return None

    if not isinstance(
        proposal_emitted,
        bool,
    ):
        return None

    if proposal_emitted is not False:
        return None

    if outcome in {
        MERCHANT_EXECUTE_SUCCESS_OUTCOME,
        MERCHANT_EXECUTE_FAILED_OUTCOME,
        MERCHANT_EXECUTE_UNCERTAIN_OUTCOME,
    }:
        if (
            operation != "merchant_execute"
            or database_target not in {"runtime", "test"}
            or proposal_emitted is not False
        ):
            return None

        command = candidate.get("command")

        if not isinstance(command, str):
            return None

        if not command.strip() or len(command) > 128:
            return None

        if "confirmation_hash" in candidate:
            return None

        if "proposal_hash" in candidate:
            return None


    if (
        outcome
        == "REQUIRES_CLARIFICATION"
    ):
        missing_fields = (
            candidate.get(
                "missing_fields"
            )
        )

        missing_one_of = (
            candidate.get(
                "missing_one_of",
                [],
            )
        )

        question = str(
            candidate.get(
                "question"
            )
            or ""
        ).strip()

        if not isinstance(
            missing_fields,
            list,
        ):
            return None

        if not isinstance(
            missing_one_of,
            list,
        ):
            return None

        if any(
            not isinstance(
                field,
                str,
            )
            or not field.strip()
            for field in missing_fields
        ):
            return None

        for group in missing_one_of:
            if (
                not isinstance(
                    group,
                    list,
                )
                or not group
            ):
                return None

            if any(
                not isinstance(
                    field,
                    str,
                )
                or not field.strip()
                for field in group
            ):
                return None

        if not (
            missing_fields
            or missing_one_of
        ):
            return None

        if not question:
            return None

        candidate = dict(
            candidate
        )

        candidate[
            "missing_one_of"
        ] = missing_one_of

    return candidate
