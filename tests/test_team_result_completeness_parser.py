import json

from claude.hooks.team_result_hook import (
    task_result_candidate_from_message,
)


def _message(
    result,
):
    return (
        "TEAM_RESULT_JSON:\n"
        + json.dumps(
            result
        )
    )


def _base_clarification():
    return {
        "contract_version": 1,
        "outcome": (
            "REQUIRES_CLARIFICATION"
        ),
        "operation": "merchant_propose",
        "database_target": "runtime",
        "proposal_emitted": False,
        "missing_fields": [
            "project_id"
        ],
        "missing_one_of": [],
        "question": (
            "Please provide project_id."
        ),
    }


def test_parser_accepts_direct_missing_fields():
    result = (
        _base_clarification()
    )

    parsed = (
        task_result_candidate_from_message(
            _message(
                result
            )
        )
    )

    assert parsed == result


def test_parser_accepts_missing_one_of_only():
    result = {
        "contract_version": 1,
        "outcome": (
            "REQUIRES_CLARIFICATION"
        ),
        "operation": "merchant_propose",
        "database_target": "runtime",
        "proposal_emitted": False,
        "missing_fields": [],
        "missing_one_of": [
            [
                "status",
                "external_id",
            ]
        ],
        "question": (
            "Please provide at least one "
            "of status and external_id."
        ),
    }

    parsed = (
        task_result_candidate_from_message(
            _message(
                result
            )
        )
    )

    assert parsed == result


def test_parser_rejects_empty_clarification_evidence():
    result = (
        _base_clarification()
    )

    result[
        "missing_fields"
    ] = []

    result[
        "missing_one_of"
    ] = []

    assert (
        task_result_candidate_from_message(
            _message(
                result
            )
        )
        is None
    )


def test_parser_rejects_malformed_missing_one_of():
    result = (
        _base_clarification()
    )

    result[
        "missing_fields"
    ] = []

    result[
        "missing_one_of"
    ] = [
        []
    ]

    assert (
        task_result_candidate_from_message(
            _message(
                result
            )
        )
        is None
    )


def test_parser_normalizes_legacy_missing_one_of():
    result = (
        _base_clarification()
    )

    result.pop(
        "missing_one_of"
    )

    parsed = (
        task_result_candidate_from_message(
            _message(
                result
            )
        )
    )

    assert parsed is not None

    assert (
        parsed[
            "missing_one_of"
        ]
        == []
    )