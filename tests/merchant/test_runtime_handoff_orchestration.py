"""Checkpoint 12H.1-12H.4 controlled orchestration integration tests."""

from __future__ import annotations

import json
import sys

from io import StringIO

import pytest

from claude.agents.tools.merchant.cli_contract import (
    build_confirmation_envelope,
)
from claude.hooks import (
    team_result_hook,
)
from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_FAILED,
    HANDOFF_STATE_KEY,
    HANDOFF_SUCCESS,
    MERCHANT_APPLY_HANDOFF_MARKER,
    handoff_candidate_from_message,
)
from claude.hooks.runtime_state import (
    load_state,
    new_state,
    save_state,
)
from claude.hooks.team_lifecycle import (
    TeammateAllocationDecision,
    TeammateLifecycleStatus,
    allocate_teammate,
    get_teammate_status,
    locked_team_state,
    mark_teammate_running,
)

OWNER_SESSION_ID = (
    "gate-12h-owner"
)

PANE_SESSION_ID = (
    "gate-12h-pane"
)

RUN_ID = (
    "gate-12h-run"
)

TASK_ID = (
    f"{RUN_ID}:merchant-manager"
)

PROJECT_ID = (
    "00000000-0000-0000-0000-000000000001"
)

MERCHANT_ID = (
    "e9ad7d20-102d-52fd-aff0-f3295598802f"
)

PROPOSAL_HASH = (
    "da8b48dcf8bcfc7d41427cb4d5a605a4214f6b11c20e86199f5f9420dd8dbfd6"
)

CONFIRMATION_HASH = (
    "fb45ad432598a73902cf46f885db2a923fffbbfb63d6a5d17d1d71d06136496e"
)

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


def _setup_owner():
    confirmation = (
        _confirmation()
    )

    state = new_state(
        request=(
            "Apply exact Merchant project update"
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

    return confirmation


def _payload(
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
                    _arguments(
                        confirmation
                    )
                ),
            }
        )
    )

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
            "toolu-handoff"
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


def test_successful_handoff_runs_outside_owner_state_lock(
    isolated_state,
    monkeypatch,
    capsys,
):
    confirmation = (
        _setup_owner()
    )

    calls = []

    def fake_invoke(
        session_id,
        arguments,
    ):
        # Critical 12H.4 assertion:
        #
        # If team_result_hook still held the owner state lock here, this
        # nested load/lock path would fail or time out instead of observing
        # the already-persisted PENDING attempt.
        state = load_state(
            session_id
        )

        assert state is not None

        assert (
            state[
                HANDOFF_STATE_KEY
            ][
                "status"
            ]
            == "PENDING"
        )

        calls.append(
            (
                session_id,
                tuple(
                    arguments
                ),
            )
        )

        print(
            json.dumps(
                {
                    "contract_version": (
                        confirmation[
                            "contract_version"
                        ]
                    ),
                    "success": True,
                    "mode": "APPLY",
                    "command": (
                        confirmation[
                            "command"
                        ]
                    ),
                    "database": "runtime",
                    "proposal_hash": (
                        confirmation[
                            "proposal_hash"
                        ]
                    ),
                    "result": {
                        "status": (
                            "committed"
                        )
                    },
                }
            )
        )

        return 0

    monkeypatch.setattr(
        team_result_hook,
        "invoke_confirmed_merchant_session_apply",
        fake_invoke,
    )

    assert (
        _run_hook(
            monkeypatch,
            _payload(
                confirmation
            ),
        )
        == 0
    )

    assert len(calls) == 1

    assert (
        calls[0][0]
        == OWNER_SESSION_ID
    )

    state = load_state(
        OWNER_SESSION_ID
    )

    assert state is not None

    assert (
        state[
            HANDOFF_STATE_KEY
        ][
            "status"
        ]
        == HANDOFF_SUCCESS
    )

    # Handoff SendMessage is NON-TERMINAL.
    assert (
        state.get(
            "result_ledger",
            {}
        )
        == {}
    )

    assert (
        get_teammate_status(
            OWNER_SESSION_ID,
            "merchant-manager",
        )
        == TeammateLifecycleStatus.RUNNING.value
    )

    output = (
        capsys.readouterr()
        .out
        .strip()
    )

    document = json.loads(
        output
    )

    assert (
        document[
            "hookSpecificOutput"
        ][
            "hookEventName"
        ]
        == "PostToolUse"
    )

    assert (
        "succeeded"
        in document[
            "hookSpecificOutput"
        ][
            "additionalContext"
        ]
    )


def test_runtime_exception_records_failed_and_cannot_retry(
    isolated_state,
    monkeypatch,
):
    confirmation = (
        _setup_owner()
    )

    calls = []

    def failing_invoke(
        session_id,
        arguments,
    ):
        calls.append(
            (
                session_id,
                tuple(
                    arguments
                ),
            )
        )

        raise RuntimeError(
            "simulated runtime failure"
        )

    monkeypatch.setattr(
        team_result_hook,
        "invoke_confirmed_merchant_session_apply",
        failing_invoke,
    )

    payload = _payload(
        confirmation
    )

    assert (
        _run_hook(
            monkeypatch,
            payload,
        )
        == 0
    )

    assert len(calls) == 1

    state = load_state(
        OWNER_SESSION_ID
    )

    assert state is not None

    assert (
        state[
            HANDOFF_STATE_KEY
        ][
            "status"
        ]
        == HANDOFF_FAILED
    )

    # Same request cannot execute the runtime invocation twice.
    assert (
        _run_hook(
            monkeypatch,
            payload,
        )
        == 0
    )

    assert len(calls) == 1


def test_handoff_is_rejected_for_wrong_authenticated_sender(
    isolated_state,
    monkeypatch,
):
    confirmation = (
        _setup_owner()
    )

    calls = []

    monkeypatch.setattr(
        team_result_hook,
        "invoke_confirmed_merchant_session_apply",
        lambda *args, **kwargs: (
            calls.append(
                (
                    args,
                    kwargs,
                )
            )
            or 0
        ),
    )

    payload = _payload(
        confirmation
    )

    payload[
        "agent_type"
    ] = "reviewer"

    assert (
        _run_hook(
            monkeypatch,
            payload,
        )
        == 0
    )

    assert calls == []

    state = load_state(
        OWNER_SESSION_ID
    )

    assert state is not None

    assert (
        HANDOFF_STATE_KEY
        not in state
    )

def _bind_trusted_pane():
    with locked_team_state(
        OWNER_SESSION_ID
    ) as state:
        assert state is not None

        record = state[
            "teammates"
        ][
            "merchant-manager"
        ]

        record[
            "trusted_pane_session_id"
        ] = PANE_SESSION_ID

def test_reused_bound_pane_without_agent_id_can_handoff_once(
    isolated_state,
    monkeypatch,
):
    confirmation = (
        _setup_owner()
    )

    _bind_trusted_pane()

    calls = []

    def fake_invoke(
        session_id,
        arguments,
    ):
        calls.append(
            (
                session_id,
                tuple(
                    arguments
                ),
            )
        )

        print(
            json.dumps(
                {
                    "contract_version": (
                        confirmation[
                            "contract_version"
                        ]
                    ),
                    "success": True,
                    "mode": "APPLY",
                    "command": (
                        confirmation[
                            "command"
                        ]
                    ),
                    "database": "runtime",
                    "proposal_hash": (
                        confirmation[
                            "proposal_hash"
                        ]
                    ),
                    "result": {
                        "status": "committed",
                    },
                }
            )
        )

        return 0

    monkeypatch.setattr(
        team_result_hook,
        "invoke_confirmed_merchant_session_apply",
        fake_invoke,
    )

    payload = _payload(
        confirmation
    )

    # Reproduces the actual live reused-teammate PostToolUse shape.
    payload.pop(
        "agent_id"
    )

    assert (
        _run_hook(
            monkeypatch,
            payload,
        )
        == 0
    )

    assert len(
        calls
    ) == 1

    state = load_state(
        OWNER_SESSION_ID
    )

    assert state is not None

    assert (
        state[
            HANDOFF_STATE_KEY
        ][
            "status"
        ]
        == HANDOFF_SUCCESS
    )

    # Same handoff transmission can never execute again.
    assert (
        _run_hook(
            monkeypatch,
            payload,
        )
        == 0
    )

    assert len(
        calls
    ) == 1


def test_role_hint_without_agent_id_or_bound_pane_is_rejected(
    isolated_state,
    monkeypatch,
):
    confirmation = (
        _setup_owner()
    )

    calls = []

    monkeypatch.setattr(
        team_result_hook,
        "invoke_confirmed_merchant_session_apply",
        lambda *args, **kwargs: (
            calls.append(
                (
                    args,
                    kwargs,
                )
            )
            or 0
        ),
    )

    payload = _payload(
        confirmation
    )

    payload.pop(
        "agent_id"
    )

    assert (
        _run_hook(
            monkeypatch,
            payload,
        )
        == 0
    )

    assert calls == []

    state = load_state(
        OWNER_SESSION_ID
    )

    assert state is not None

    assert (
        HANDOFF_STATE_KEY
        not in state
    )

def test_wrong_pane_cannot_use_reused_teammate_authority(
    isolated_state,
    monkeypatch,
):
    confirmation = (
        _setup_owner()
    )

    _bind_trusted_pane()

    calls = []

    monkeypatch.setattr(
        team_result_hook,
        "invoke_confirmed_merchant_session_apply",
        lambda *args, **kwargs: (
            calls.append(
                (
                    args,
                    kwargs,
                )
            )
            or 0
        ),
    )

    payload = _payload(
        confirmation
    )

    payload.pop(
        "agent_id"
    )

    payload[
        "session_id"
    ] = "attacker-pane"

    assert (
        _run_hook(
            monkeypatch,
            payload,
        )
        == 0
    )

    assert calls == []

    state = load_state(
        OWNER_SESSION_ID
    )

    assert state is not None

    assert (
        HANDOFF_STATE_KEY
        not in state
    )

def test_project_create_canonical_handoff_message_parses():
    message = (
        MERCHANT_APPLY_HANDOFF_MARKER
        + "\n"
        + json.dumps({
            "contract_version": 1,
            "operation": "merchant_apply",
            "database_target": "runtime",
            "confirmation_hash": CONFIRMATION_HASH,
            "arguments": [
                "project",
                "create",
                "--merchant-id",
                MERCHANT_ID,
                "--type",
                "OPENING_NEW_CINEMA",
                "--variant",
                "OPENING_NEW_CINEMA_STANDARD",
                "--title",
                "Mở rạp mới AEON Beta Hải Dương",
                "--apply",
                "--proposal-hash",
                PROPOSAL_HASH,
            ],
        })
    )

    candidate = handoff_candidate_from_message(
        message
    )

    assert candidate is not None
    assert candidate["operation"] == "merchant_apply"
    assert candidate["database_target"] == "runtime"
    assert candidate["confirmation_hash"] == CONFIRMATION_HASH