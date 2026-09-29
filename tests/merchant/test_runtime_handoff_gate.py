"""Checkpoint 12H.1-12H.4 runtime handoff gate tests."""
import json
from copy import deepcopy

from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_FAILED,
    HANDOFF_PENDING,
    HANDOFF_STATE_KEY,
    HANDOFF_SUCCESS,
    MERCHANT_APPLY_HANDOFF_MARKER,
    handoff_candidate_from_message,
    record_runtime_handoff_result,
    stage_runtime_handoff_attempt,
    bounded_runtime_apply_result,
    successful_runtime_handoff_matches,  
)
from claude.agents.tools.merchant.cli_contract import (
    build_confirmation_envelope,
)


OWNER_SESSION_ID = "lead-session"
RUN_ID = "run-12h"
TASK_ID = "run-12h:merchant-manager"
PROJECT_ID = (
    "00000000-0000-0000-0000-000000000001"
)


def _confirmation():
    return (
        build_confirmation_envelope(
            "project update",
            "runtime",
            {
                "project_id": (
                    PROJECT_ID
                ),
                "status": (
                    "IN_PROGRESS"
                ),
                "expected_version": 3,
            },
        )
        .to_dict()
    )


def _arguments(
    confirmation,
):
    return [
        "project",
        "update",
        PROJECT_ID,
        "--apply",
        "--proposal-hash",
        confirmation[
            "proposal_hash"
        ],
        "--status",
        "IN_PROGRESS",
        "--expected-version",
        "3",
    ]


def _candidate(
    confirmation,
):
    message = (
        MERCHANT_APPLY_HANDOFF_MARKER
        + "\n"
        + __import__(
            "json"
        ).dumps(
            {
                "contract_version": 1,
                "operation": (
                    "merchant_apply"
                ),
                "database_target": (
                    "runtime"
                ),
                "confirmation_hash": (
                    confirmation[
                        "confirmation_hash"
                    ]
                ),
                "arguments": (
                    _arguments(
                        confirmation
                    )
                ),
            }
        )
    )

    candidate = (
        handoff_candidate_from_message(
            message
        )
    )

    assert candidate is not None

    return candidate


def _state(
    confirmation,
):
    return {
        "run_id": RUN_ID,
        "operations": [
            "merchant_apply"
        ],
        "selected_agents": [
            "merchant-manager"
        ],
        "risk_level": (
            "external_write"
        ),
        "confirmed": True,
        "merchant_confirmation": (
            deepcopy(
                confirmation
            )
        ),
        "merchant_dispatch_spent": True,
        "merchant_dispatch": {
            "operation": (
                "merchant_apply"
            ),
            "subagent_type": (
                "merchant-manager"
            ),
            "teammate_name": (
                "merchant-manager"
            ),
            "confirmation_hash": (
                confirmation[
                    "confirmation_hash"
                ]
            ),
        },
    }


def _stage(
    state,
    candidate,
):
    return (
        stage_runtime_handoff_attempt(
            state,
            owner_session_id=(
                OWNER_SESSION_ID
            ),
            teammate_name=(
                "merchant-manager"
            ),
            run_id=(
                RUN_ID
            ),
            task_id=(
                TASK_ID
            ),
            candidate=(
                candidate
            ),
        )
    )


def test_exact_handoff_message_parses():
    confirmation = (
        _confirmation()
    )

    candidate = (
        _candidate(
            confirmation
        )
    )

    assert (
        candidate[
            "operation"
        ]
        == "merchant_apply"
    )

    assert (
        candidate[
            "database_target"
        ]
        == "runtime"
    )

    assert (
        candidate[
            "confirmation_hash"
        ]
        == confirmation[
            "confirmation_hash"
        ]
    )

    assert isinstance(
        candidate[
            "arguments"
        ],
        tuple,
    )


def test_parser_rejects_database_override():
    confirmation = (
        _confirmation()
    )

    import json

    message = (
        MERCHANT_APPLY_HANDOFF_MARKER
        + "\n"
        + json.dumps(
            {
                "contract_version": 1,
                "operation": (
                    "merchant_apply"
                ),
                "database_target": (
                    "runtime"
                ),
                "confirmation_hash": (
                    confirmation[
                        "confirmation_hash"
                    ]
                ),
                "arguments": [
                    "project",
                    "update",
                    PROJECT_ID,
                    "--database",
                    "test",
                    "--apply",
                    "--proposal-hash",
                    confirmation[
                        "proposal_hash"
                    ],
                ],
            }
        )
    )

    assert (
        handoff_candidate_from_message(
            message
        )
        is None
    )


def test_valid_state_stages_pending():
    confirmation = (
        _confirmation()
    )

    state = _state(
        confirmation
    )

    attempt, reason = _stage(
        state,
        _candidate(
            confirmation
        ),
    )

    assert reason == ""
    assert attempt is not None

    receipt = state[
        HANDOFF_STATE_KEY
    ]

    assert (
        receipt[
            "status"
        ]
        == HANDOFF_PENDING
    )

    assert (
        receipt[
            "run_id"
        ]
        == RUN_ID
    )

    assert (
        receipt[
            "task_id"
        ]
        == TASK_ID
    )


def test_wrong_confirmation_hash_is_rejected():
    confirmation = (
        _confirmation()
    )

    candidate = dict(
        _candidate(
            confirmation
        )
    )

    candidate[
        "confirmation_hash"
    ] = "0" * 64

    state = _state(
        confirmation
    )

    attempt, reason = _stage(
        state,
        candidate,
    )

    assert attempt is None
    assert "confirmation hash" in (
        reason
    )

    assert (
        HANDOFF_STATE_KEY
        not in state
    )


def test_wrong_operation_is_rejected():
    confirmation = (
        _confirmation()
    )

    state = _state(
        confirmation
    )

    state[
        "operations"
    ] = [
        "merchant_propose"
    ]

    attempt, reason = _stage(
        state,
        _candidate(
            confirmation
        ),
    )

    assert attempt is None
    assert "merchant_apply" in reason


def test_wrong_teammate_is_rejected():
    confirmation = (
        _confirmation()
    )

    state = _state(
        confirmation
    )

    attempt, reason = (
        stage_runtime_handoff_attempt(
            state,
            owner_session_id=(
                OWNER_SESSION_ID
            ),
            teammate_name=(
                "reviewer"
            ),
            run_id=(
                RUN_ID
            ),
            task_id=(
                TASK_ID
            ),
            candidate=(
                _candidate(
                    confirmation
                )
            ),
        )
    )

    assert attempt is None
    assert "merchant-manager" in (
        reason
    )


def test_missing_dispatch_spend_is_rejected():
    confirmation = (
        _confirmation()
    )

    state = _state(
        confirmation
    )

    state[
        "merchant_dispatch_spent"
    ] = False

    attempt, reason = _stage(
        state,
        _candidate(
            confirmation
        ),
    )

    assert attempt is None
    assert "Gate 7.3" in reason


def test_duplicate_pending_is_not_retryable():
    confirmation = (
        _confirmation()
    )

    state = _state(
        confirmation
    )

    candidate = _candidate(
        confirmation
    )

    first, first_reason = (
        _stage(
            state,
            candidate,
        )
    )

    assert first is not None
    assert first_reason == ""

    second, second_reason = (
        _stage(
            state,
            candidate,
        )
    )

    assert second is None
    assert "already PENDING" in (
        second_reason
    )


def test_success_is_not_retryable():
    confirmation = (
        _confirmation()
    )

    state = _state(
        confirmation
    )

    candidate = _candidate(
        confirmation
    )

    attempt, _ = _stage(
        state,
        candidate,
    )

    assert attempt is not None

    raw_runtime_result = json.dumps(
        {
            "contract_version": 1,
            "success": True,
            "mode": "APPLY",
            "command": (
                attempt.command
            ),
            "database": "runtime",
            "proposal_hash": (
                attempt.proposal_hash
            ),
            "result": {
                "status": "committed",
            },
        }
    )

    bounded = (
        bounded_runtime_apply_result(
            raw_runtime_result,
            attempt,
        )
    )

    assert bounded is not None

    assert (
        record_runtime_handoff_result(
            state,
            attempt,
            succeeded=True,
            exit_code=0,
            runtime_result=(
                bounded
            ),
        )
        is True
    )

    assert (
        state[
            HANDOFF_STATE_KEY
        ][
            "status"
        ]
        == HANDOFF_SUCCESS
    )

    retry, reason = _stage(
        state,
        candidate,
    )

    assert retry is None

    assert (
        "already SUCCESS"
        in reason
    )


def test_success_without_runtime_evidence_is_rejected():
    confirmation = (
        _confirmation()
    )

    state = _state(
        confirmation
    )

    attempt, reason = _stage(
        state,
        _candidate(
            confirmation
        ),
    )

    assert reason == ""
    assert attempt is not None

    assert (
        record_runtime_handoff_result(
            state,
            attempt,
            succeeded=True,
            exit_code=0,
            runtime_result=None,
        )
        is False
    )

    assert (
        state[
            HANDOFF_STATE_KEY
        ][
            "status"
        ]
        == HANDOFF_PENDING
    )


def test_failure_is_not_retryable():
    confirmation = (
        _confirmation()
    )

    state = _state(
        confirmation
    )

    candidate = _candidate(
        confirmation
    )

    attempt, _ = _stage(
        state,
        candidate,
    )

    assert attempt is not None

    assert (
        record_runtime_handoff_result(
            state,
            attempt,
            succeeded=False,
            exit_code=1,
        )
        is True
    )

    assert (
        state[
            HANDOFF_STATE_KEY
        ][
            "status"
        ]
        == HANDOFF_FAILED
    )

    retry, reason = _stage(
        state,
        candidate,
    )

    assert retry is None
    assert "already FAILED" in (
        reason
    )

def test_bounded_runtime_result_persists_hash_not_raw_result():
    confirmation = (
        _confirmation()
    )

    state = _state(
        confirmation
    )

    attempt, reason = _stage(
        state,
        _candidate(
            confirmation
        ),
    )

    assert reason == ""
    assert attempt is not None

    raw = json.dumps(
        {
            "contract_version": 1,
            "success": True,
            "mode": "APPLY",
            "command": (
                attempt.command
            ),
            "database": "runtime",
            "proposal_hash": (
                attempt.proposal_hash
            ),
            "result": {
                "project_id": (
                    PROJECT_ID
                ),
                "status": (
                    "IN_PROGRESS"
                ),
            },
        }
    )

    bounded = (
        bounded_runtime_apply_result(
            raw,
            attempt,
        )
    )

    assert bounded is not None

    assert (
        "result_sha256"
        in bounded
    )

    assert (
        "project_id"
        not in bounded
    )

    assert (
        record_runtime_handoff_result(
            state,
            attempt,
            succeeded=True,
            exit_code=0,
            runtime_result=(
                bounded
            ),
        )
        is True
    )

    receipt = state[
        HANDOFF_STATE_KEY
    ]

    assert (
        receipt[
            "status"
        ]
        == HANDOFF_SUCCESS
    )

    assert (
        "runtime_result"
        in receipt
    )

    assert (
        "project_id"
        not in json.dumps(
            receipt[
                "runtime_result"
            ]
        )
    )