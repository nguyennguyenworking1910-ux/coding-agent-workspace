"""Regression coverage for the Checkpoint 12H Gate 7.4 handoff contract."""

from __future__ import annotations

import json

import pytest

from claude.agents.tools.merchant.cli_contract import (
    build_confirmation_envelope,
)
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
)
from claude.hooks.runtime_state import (
    clear_state,
    load_state,
    new_state,
    save_state,
)


OWNER_SESSION_ID = "gate-7-4-session"
RUN_ID = "gate-7-4-run"
TASK_ID = "gate-7-4-run:merchant-manager"

PROJECT_ID = (
    "00000000-0000-0000-0000-000000000001"
)


def _confirmation():
    return (
        build_confirmation_envelope(
            "project update",
            "runtime",
            {
                "project_id": PROJECT_ID,
                "status": "IN_PROGRESS",
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


def _message(
    confirmation,
    *,
    arguments=None,
):
    if arguments is None:
        arguments = _arguments(
            confirmation
        )

    return (
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
                "arguments": arguments,
            }
        )
    )


def _candidate(
    confirmation,
):
    candidate = (
        handoff_candidate_from_message(
            _message(
                confirmation
            )
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
        "merchant_dispatch_spent": True,
        "merchant_confirmation": (
            dict(
                confirmation
            )
        ),
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
            run_id=RUN_ID,
            task_id=TASK_ID,
            candidate=candidate,
        )
    )


class TestHandoffRequestExtraction:
    """Strict wire-format validation."""

    def test_exact_request_parses(
        self,
    ):
        confirmation = (
            _confirmation()
        )

        result = (
            handoff_candidate_from_message(
                _message(
                    confirmation
                )
            )
        )

        assert result is not None

        assert (
            result[
                "contract_version"
            ]
            == 1
        )

        assert (
            result[
                "operation"
            ]
            == "merchant_apply"
        )

        assert (
            result[
                "database_target"
            ]
            == "runtime"
        )

    def test_missing_marker_rejected(
        self,
    ):
        assert (
            handoff_candidate_from_message(
                "No handoff request here"
            )
            is None
        )

    def test_duplicate_marker_rejected(
        self,
    ):
        confirmation = (
            _confirmation()
        )

        one = _message(
            confirmation
        )

        message = (
            one
            + "\n"
            + one
        )

        assert (
            handoff_candidate_from_message(
                message
            )
            is None
        )

    def test_malformed_json_rejected(
        self,
    ):
        message = (
            MERCHANT_APPLY_HANDOFF_MARKER
            + "\n"
            + "{this is not valid json}"
        )

        assert (
            handoff_candidate_from_message(
                message
            )
            is None
        )

    def test_prose_before_marker_rejected(
        self,
    ):
        confirmation = (
            _confirmation()
        )

        message = (
            "Prose before authority message.\n"
            + _message(
                confirmation
            )
        )

        assert (
            handoff_candidate_from_message(
                message
            )
            is None
        )


class TestHandoffArgumentValidation:
    """Untrusted argument-vector validation."""

    def test_empty_arguments_rejected(
        self,
    ):
        confirmation = (
            _confirmation()
        )

        assert (
            handoff_candidate_from_message(
                _message(
                    confirmation,
                    arguments=[],
                )
            )
            is None
        )

    def test_password_override_rejected(
        self,
    ):
        confirmation = (
            _confirmation()
        )

        arguments = (
            _arguments(
                confirmation
            )
            + [
                "--password",
                "not-allowed",
            ]
        )

        assert (
            handoff_candidate_from_message(
                _message(
                    confirmation,
                    arguments=arguments,
                )
            )
            is None
        )

    def test_database_override_rejected(
        self,
    ):
        confirmation = (
            _confirmation()
        )

        arguments = (
            _arguments(
                confirmation
            )
            + [
                "--database",
                "test",
            ]
        )

        assert (
            handoff_candidate_from_message(
                _message(
                    confirmation,
                    arguments=arguments,
                )
            )
            is None
        )


class TestHandoffStateBinding:
    """Trusted-state validation and at-most-once behavior."""

    def test_valid_request_stages_pending(
        self,
    ):
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
            state[
                HANDOFF_STATE_KEY
            ][
                "status"
            ]
            == HANDOFF_PENDING
        )

    def test_missing_dispatch_rejected(
        self,
    ):
        confirmation = (
            _confirmation()
        )

        state = _state(
            confirmation
        )

        state.pop(
            "merchant_dispatch"
        )

        attempt, reason = _stage(
            state,
            _candidate(
                confirmation
            ),
        )

        assert attempt is None

        assert (
            "dispatch receipt"
            in reason
        )

    def test_missing_confirmation_rejected(
        self,
    ):
        confirmation = (
            _confirmation()
        )

        state = _state(
            confirmation
        )

        state.pop(
            "merchant_confirmation"
        )

        attempt, reason = _stage(
            state,
            _candidate(
                confirmation
            ),
        )

        assert attempt is None

        assert (
            "confirmation"
            in reason.lower()
        )

    def test_wrong_confirmation_hash_rejected(
        self,
    ):
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

        assert (
            "confirmation hash"
            in reason
        )

    def test_duplicate_pending_rejected(
        self,
    ):
        confirmation = (
            _confirmation()
        )

        state = _state(
            confirmation
        )

        candidate = _candidate(
            confirmation
        )

        first, _ = _stage(
            state,
            candidate,
        )

        assert first is not None

        second, reason = _stage(
            state,
            candidate,
        )

        assert second is None

        assert (
            "already PENDING"
            in reason
        )

    def test_success_is_non_retryable(
        self,
    ):
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

    def test_failure_is_non_retryable(
        self,
    ):
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

        assert (
            "already FAILED"
            in reason
        )


class TestHandoffCleanup:
    """Handoff evidence disappears with normal run-state cleanup."""

    def test_run_cleanup_removes_handoff_state(
        self,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setenv(
            "CLAUDE_RUNTIME_STATE_DIR",
            str(
                tmp_path
                / "runtime"
            ),
        )

        confirmation = (
            _confirmation()
        )

        state = new_state(
            request="test",
            task_class="small_task",
            risk_level="external_write",
            selected_agents=[
                "merchant-manager"
            ],
            operations=[
                "merchant_apply"
            ],
            limits={
                "max_members": 1,
                "max_total_tool_calls": 10,
            },
            confirmed=True,
            merchant_confirmation=(
                confirmation
            ),
            run_id=RUN_ID,
        )

        state[
            HANDOFF_STATE_KEY
        ] = {
            "contract_version": 1,
            "status": (
                HANDOFF_SUCCESS
            ),
            "owner_session_id": (
                OWNER_SESSION_ID
            ),
            "run_id": RUN_ID,
            "task_id": TASK_ID,
            "teammate_name": (
                "merchant-manager"
            ),
            "confirmation_hash": (
                confirmation[
                    "confirmation_hash"
                ]
            ),
            "arguments_hash": (
                "0" * 64
            ),
        }

        save_state(
            OWNER_SESSION_ID,
            state,
        )

        assert (
            load_state(
                OWNER_SESSION_ID
            )
            is not None
        )

        assert (
            clear_state(
                OWNER_SESSION_ID
            )
            is True
        )

        assert (
            load_state(
                OWNER_SESSION_ID
            )
            is None
        )