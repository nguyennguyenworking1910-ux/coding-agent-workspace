"""Checkpoint 12H.7 trusted Merchant apply terminal-result enforcement."""

from __future__ import annotations

import json

from io import StringIO

import pytest

from claude.agents.tools.merchant.cli_contract import (
    build_confirmation_envelope,
)
from claude.hooks import (
    team_result_hook,
)
from claude.hooks.merchant_runtime_handoff_gate import (
    MERCHANT_APPLY_HANDOFF_MARKER,
    bounded_runtime_apply_result,
    handoff_candidate_from_message,
    record_runtime_handoff_result,
    stage_runtime_handoff_attempt,
)
from claude.hooks.runtime_state import (
    load_state,
    locked_state,
    new_state,
    save_state,
)
from claude.hooks.team_lifecycle import (
    TeammateAllocationDecision,
    TeammateLifecycleStatus,
    allocate_teammate,
    get_teammate_status,
    mark_teammate_running,
)


OWNER_SESSION_ID = (
    "gate-12h-terminal-owner"
)

PANE_SESSION_ID = (
    "gate-12h-terminal-pane"
)

RUN_ID = (
    "gate-12h-terminal-run"
)

TASK_ID = (
    f"{RUN_ID}:merchant-manager"
)

PROJECT_ID = (
    "00000000-0000-0000-0000-000000000001"
)

PAYLOAD = {
    "project_id": PROJECT_ID,
    "status": "IN_PROGRESS",
    "expected_version": 3,
    "occurred_at": None,
    "triggered_by": None,
    "allow_reopen": False,
}


@pytest.fixture
def isolated_state(
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

    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(
            tmp_path
            / "team"
        ),
    )

    monkeypatch.setenv(
        "CLAUDE_PENDING_TEAM_RESULT_DIR",
        str(
            tmp_path
            / "pending-results"
        ),
    )


def _confirmation():
    return (
        build_confirmation_envelope(
            "project update",
            "runtime",
            PAYLOAD,
        )
        .to_dict()
    )


def _apply_arguments(
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


def _handoff_candidate(
    confirmation,
):
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
                "arguments": (
                    _apply_arguments(
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


def _setup_owner(
    *,
    trusted_handoff: str | None,
):
    """Create one exact merchant_apply run and optional Gate 7.4 evidence."""

    confirmation = (
        _confirmation()
    )

    state = new_state(
        request=(
            "Apply the exact confirmed "
            "Merchant project update"
        ),
        task_class=(
            "small_task"
        ),
        risk_level=(
            "external_write"
        ),
        selected_agents=[
            "merchant-manager"
        ],
        operations=[
            "merchant_apply"
        ],
        limits={
            "max_members": 1,
            "max_tool_rounds": 3,
            "max_total_tool_calls": 12,
            "max_run_budget_usd": 2.0,
        },
        confirmed=True,
        merchant_confirmation=(
            confirmation
        ),
        run_id=(
            RUN_ID
        ),
    )

    state[
        "merchant_dispatch_spent"
    ] = True

    state[
        "merchant_dispatch"
    ] = {
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
    }

    save_state(
        OWNER_SESSION_ID,
        state,
    )

    decision, name = (
        allocate_teammate(
            OWNER_SESSION_ID,
            "merchant-manager",
            "merchant-manager",
        )
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert (
        name
        == "merchant-manager"
    )

    assert (
        mark_teammate_running(
            OWNER_SESSION_ID,
            "merchant-manager",
            RUN_ID,
            TASK_ID,
            operations=[
                "merchant_apply"
            ],
            selected_agents=[
                "merchant-manager"
            ],
        )
        is True
    )

    if trusted_handoff is not None:
        with locked_state(
            OWNER_SESSION_ID
        ) as owner_state:
            assert owner_state is not None

            attempt, reason = (
                stage_runtime_handoff_attempt(
                    owner_state,
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
                        _handoff_candidate(
                            confirmation
                        )
                    ),
                )
            )

            assert reason == ""
            assert attempt is not None

            if (
                trusted_handoff
                == "SUCCESS"
            ):
                raw_runtime_result = (
                    json.dumps(
                        {
                            "contract_version": 1,
                            "success": True,
                            "mode": "APPLY",
                            "command": (
                                attempt.command
                            ),
                            "database": (
                                "runtime"
                            ),
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
                        owner_state,
                        attempt,
                        succeeded=True,
                        exit_code=0,
                        runtime_result=(
                            bounded
                        ),
                    )
                    is True
                )

            elif (
                trusted_handoff
                == "FAILED"
            ):
                assert (
                    record_runtime_handoff_result(
                        owner_state,
                        attempt,
                        succeeded=False,
                        exit_code=1,
                    )
                    is True
                )

            else:
                raise AssertionError(
                    "unsupported test handoff status"
                )

    return confirmation


def _terminal_message(
    confirmation,
    *,
    outcome: str,
    confirmation_hash: str | None = None,
):
    return (
        "TEAM_RESULT_JSON:\n"
        + json.dumps(
            {
                "contract_version": 1,
                "outcome": (
                    outcome
                ),
                "operation": (
                    "merchant_apply"
                ),
                "database_target": (
                    "runtime"
                ),
                "proposal_emitted": (
                    False
                ),
                "confirmation_hash": (
                    confirmation_hash
                    or confirmation[
                        "confirmation_hash"
                    ]
                ),
            }
        )
    )


def _post_tool_payload(
    message,
):
    return {
        "hook_event_name": (
            "PostToolUse"
        ),
        "session_id": (
            PANE_SESSION_ID
        ),
        "agent_id": (
            "merchant-manager-agent"
        ),
        "agent_type": (
            "merchant-manager"
        ),
        "tool_name": (
            "SendMessage"
        ),
        "tool_use_id": (
            "toolu-terminal-result"
        ),
        "tool_input": {
            "recipient": (
                "team-lead"
            ),
            "task_id": (
                TASK_ID
            ),
            "message": (
                message
            ),
        },
        "tool_response": {
            "success": True,
        },
    }


def _idle_payload():
    return {
        "hook_event_name": (
            "TeammateIdle"
        ),
        "session_id": (
            PANE_SESSION_ID
        ),
        "teammate_name": (
            "merchant-manager"
        ),
        "task_id": (
            TASK_ID
        ),
    }


def _run_hook(
    monkeypatch,
    payload,
):
    monkeypatch.setattr(
        team_result_hook.sys,
        "stdin",
        StringIO(
            json.dumps(
                payload
            )
        ),
    )

    return (
        team_result_hook.main()
    )


def test_fake_apply_success_without_gate_7_4_receipt_is_rejected(
    isolated_state,
    monkeypatch,
):
    confirmation = (
        _setup_owner(
            trusted_handoff=None,
        )
    )

    assert (
        _run_hook(
            monkeypatch,
            _post_tool_payload(
                _terminal_message(
                    confirmation,
                    outcome=(
                        "APPLY_SUCCESS"
                    ),
                )
            ),
        )
        == 0
    )

    # The terminal SendMessage itself remains staged, not accepted.
    assert (
        get_teammate_status(
            OWNER_SESSION_ID,
            "merchant-manager",
        )
        == TeammateLifecycleStatus.RUNNING.value
    )

    exit_code = (
        _run_hook(
            monkeypatch,
            _idle_payload(),
        )
    )

    assert exit_code == 2

    # Critical 12H.7 invariant:
    # model prose cannot release the teammate as a successful apply.
    assert (
        get_teammate_status(
            OWNER_SESSION_ID,
            "merchant-manager",
        )
        != TeammateLifecycleStatus.IDLE_REUSABLE.value
    )

    owner_state = (
        load_state(
            OWNER_SESSION_ID
        )
    )

    assert owner_state is not None

    assert (
        owner_state.get(
            "result_ledger",
            {}
        )
        == {}
    )


def test_apply_success_with_wrong_confirmation_hash_is_rejected(
    isolated_state,
    monkeypatch,
):
    confirmation = (
        _setup_owner(
            trusted_handoff="SUCCESS",
        )
    )

    wrong_hash = (
        "0" * 64
    )

    assert (
        wrong_hash
        != confirmation[
            "confirmation_hash"
        ]
    )

    assert (
        _run_hook(
            monkeypatch,
            _post_tool_payload(
                _terminal_message(
                    confirmation,
                    outcome=(
                        "APPLY_SUCCESS"
                    ),
                    confirmation_hash=(
                        wrong_hash
                    ),
                )
            ),
        )
        == 0
    )

    assert (
        _run_hook(
            monkeypatch,
            _idle_payload(),
        )
        == 2
    )

    assert (
        get_teammate_status(
            OWNER_SESSION_ID,
            "merchant-manager",
        )
        != TeammateLifecycleStatus.IDLE_REUSABLE.value
    )


def test_matching_trusted_apply_success_is_accepted_and_released(
    isolated_state,
    monkeypatch,
):
    confirmation = (
        _setup_owner(
            trusted_handoff="SUCCESS",
        )
    )

    assert (
        _run_hook(
            monkeypatch,
            _post_tool_payload(
                _terminal_message(
                    confirmation,
                    outcome=(
                        "APPLY_SUCCESS"
                    ),
                )
            ),
        )
        == 0
    )

    # Terminal result is not accepted merely at SendMessage time.
    assert (
        get_teammate_status(
            OWNER_SESSION_ID,
            "merchant-manager",
        )
        == TeammateLifecycleStatus.RUNNING.value
    )

    assert (
        _run_hook(
            monkeypatch,
            _idle_payload(),
        )
        == 0
    )

    assert (
        get_teammate_status(
            OWNER_SESSION_ID,
            "merchant-manager",
        )
        == TeammateLifecycleStatus.IDLE_REUSABLE.value
    )

    owner_state = (
        load_state(
            OWNER_SESSION_ID
        )
    )

    assert owner_state is not None

    ledger = owner_state.get(
        "result_ledger",
        {}
    )

    dedup_key = (
        f"{RUN_ID}:"
        f"{TASK_ID}:"
        "merchant-manager"
    )

    assert (
        dedup_key
        in ledger
    )

    assert (
        ledger[
            dedup_key
        ][
            "result_received"
        ]
        is True
    )


def test_matching_trusted_apply_failed_is_accepted_and_released(
    isolated_state,
    monkeypatch,
):
    confirmation = (
        _setup_owner(
            trusted_handoff="FAILED",
        )
    )

    assert (
        _run_hook(
            monkeypatch,
            _post_tool_payload(
                _terminal_message(
                    confirmation,
                    outcome=(
                        "APPLY_FAILED"
                    ),
                )
            ),
        )
        == 0
    )

    assert (
        _run_hook(
            monkeypatch,
            _idle_payload(),
        )
        == 0
    )

    assert (
        get_teammate_status(
            OWNER_SESSION_ID,
            "merchant-manager",
        )
        == TeammateLifecycleStatus.IDLE_REUSABLE.value
    )