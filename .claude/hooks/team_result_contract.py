"""Pure structured task-result contract parsing.

This module validates machine-readable teammate outcomes only.
It performs no state mutation, lifecycle transition, Merchant apply,
or external side effect.
"""

from __future__ import annotations

import json
from typing import Any


MERCHANT_PROPOSAL_RESULT_MARKER = (
    "MERCHANT_PROPOSAL_RESULT_JSON:"
)

TEAM_RESULT_MARKER = (
    "TEAM_RESULT_JSON:"
)

TEAM_RESULT_CONTRACT_VERSION = 1

MERCHANT_PROPOSAL_READY_OUTCOME = (
    "PROPOSAL_READY"
)

MERCHANT_APPLY_SUCCESS_OUTCOME = (
    "APPLY_SUCCESS"
)

MERCHANT_APPLY_FAILED_OUTCOME = (
    "APPLY_FAILED"
)

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
    It is not authorization and does not grant Merchant proposal
    or apply authority.
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

    trailing_content = (
        encoded[end:].strip()
    )

    has_proposal_delivery_block = False

    if trailing_content:
        if (
            trailing_content.count(
                MERCHANT_PROPOSAL_RESULT_MARKER
            )
            != 1
        ):
            return None

        if not trailing_content.startswith(
            MERCHANT_PROPOSAL_RESULT_MARKER
        ):
            return None

        _, proposal_encoded = (
            trailing_content.split(
                MERCHANT_PROPOSAL_RESULT_MARKER,
                1,
            )
        )

        proposal_encoded = (
            proposal_encoded.strip()
        )

        if not proposal_encoded:
            return None

        try:
            proposal_candidate, proposal_end = (
                json.JSONDecoder().raw_decode(
                    proposal_encoded
                )
            )
        except json.JSONDecodeError:
            return None

        if (
            proposal_encoded[
                proposal_end:
            ].strip()
        ):
            return None

        if not isinstance(
            proposal_candidate,
            dict,
        ):
            return None

        has_proposal_delivery_block = True

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
        MERCHANT_PROPOSAL_READY_OUTCOME,
        MERCHANT_APPLY_SUCCESS_OUTCOME,
        MERCHANT_APPLY_FAILED_OUTCOME,
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

    if (
        outcome
        == MERCHANT_PROPOSAL_READY_OUTCOME
    ):
        if proposal_emitted is not True:
            return None

    else:
        if proposal_emitted is not False:
            return None

        if has_proposal_delivery_block:
            return None

    if outcome in {
        MERCHANT_APPLY_SUCCESS_OUTCOME,
        MERCHANT_APPLY_FAILED_OUTCOME,
    }:
        if (
            operation
            != "merchant_apply"
            or database_target
            != "runtime"
            or proposal_emitted
            is not False
            or has_proposal_delivery_block
        ):
            return None

        confirmation_hash = (
            candidate.get(
                "confirmation_hash"
            )
        )

        if (
            not isinstance(
                confirmation_hash,
                str,
            )
            or len(
                confirmation_hash
            )
            != 64
            or any(
                character
                not in "0123456789abcdef"
                for character
                in confirmation_hash
            )
        ):
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
