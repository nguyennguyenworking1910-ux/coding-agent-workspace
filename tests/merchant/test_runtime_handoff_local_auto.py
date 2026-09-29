"""Checkpoint 12H.5 LOCAL_AUTO runtime-handoff integration tests."""

from __future__ import annotations

import json

import pytest

from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)
from claude.hooks.merchant_confirmation_preferences import (
    MODE_LOCAL_AUTO,
    RECEIPT_CONSUMED,
    RECEIPT_RESERVED,
    capture_proposal_receipt,
    locked_preferences,
    receipt_state,
    reserve_receipt,
)
from claude.hooks.runtime_state import (
    MERCHANT_CONFIRMATION_MODE_LOCAL_AUTO,
    load_state,
    new_state,
    save_state,
)
from claude.system.merchant_runtime_handoff import (
    MerchantRuntimeHandoffError,
    invoke_confirmed_merchant_session_apply,
)


SESSION_ID = "gate-12h-local-auto-session"

RUN_ID = "gate-12h-local-auto-run"

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


class RecordingHandler:
    def __init__(
        self,
    ):
        self.calls = []

    def __call__(
        self,
        payload,
    ):
        self.calls.append(
            payload
        )

        return {
            "status": "committed",
            "project_id": (
                payload[
                    "project_id"
                ]
            ),
        }


def _apply_arguments(
    proposal,
):
    return [
        "project",
        "update",
        PROJECT_ID,
        "--apply",
        "--proposal-hash",
        proposal[
            "proposal_hash"
        ],
        "--status",
        "IN_PROGRESS",
        "--expected-version",
        "3",
    ]


def test_local_auto_reserved_receipt_is_consumed_only_by_session_handoff(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setenv(
        "CLAUDE_RUNTIME_STATE_DIR",
        str(
            tmp_path
            / "runtime"
        ),
    )

    monkeypatch.setenv(
        "CLAUDE_MERCHANT_PREFERENCES_DIR",
        str(
            tmp_path
            / "merchant-confirmation"
        ),
    )

    handler = (
        RecordingHandler()
    )

    commands = (
        MerchantWriteCommands(
            {
                "project update": (
                    handler
                ),
            }
        )
    )

    proposal = (
        commands.propose(
            "project update",
            "runtime",
            PAYLOAD,
        )
    )

    confirmation = (
        proposal[
            "confirmation"
        ]
    )

    # ------------------------------------------------------------
    # LOCAL_AUTO preference exists for this exact session.
    # ------------------------------------------------------------

    with locked_preferences(
        SESSION_ID,
        create=True,
    ) as document:
        assert document is not None

        document[
            "mode"
        ] = MODE_LOCAL_AUTO

        document[
            "receipt"
        ] = None

    # ------------------------------------------------------------
    # Simulate exact proposal capture.
    #
    # This produces AVAILABLE.
    # ------------------------------------------------------------

    captured = (
        capture_proposal_receipt(
            SESSION_ID,
            proposal,
        )
    )

    assert (
        captured.accepted
        is True
    )

    # ------------------------------------------------------------
    # Gate 7.3 policy dispatch reservation.
    #
    # AVAILABLE → RESERVED
    # ------------------------------------------------------------

    reserved = (
        reserve_receipt(
            SESSION_ID,
            confirmation[
                "confirmation_hash"
            ],
        )
    )

    assert (
        reserved.accepted
        is True
    )

    assert (
        receipt_state(
            SESSION_ID
        )
        == RECEIPT_RESERVED
    )

    # ------------------------------------------------------------
    # Trusted merchant_apply owner run state.
    # ------------------------------------------------------------

    state = new_state(
        request=(
            "Apply the exact Merchant "
            "project update proposal"
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
            "max_tool_rounds": 1,
            "max_total_tool_calls": 6,
            "max_run_budget_usd": 1.0,
        },
        confirmed=True,
        merchant_confirmation=(
            confirmation
        ),
        merchant_confirmation_mode=(
            MERCHANT_CONFIRMATION_MODE_LOCAL_AUTO
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
        SESSION_ID,
        state,
    )

    # ------------------------------------------------------------
    # Gate 7.5 session-aware runtime handoff.
    #
    # This is the ONLY operation in this test that may consume the
    # LOCAL_AUTO proposal receipt.
    # ------------------------------------------------------------

    exit_code = (
        invoke_confirmed_merchant_session_apply(
            SESSION_ID,
            _apply_arguments(
                proposal
            ),
            write_command_factory=(
                lambda database: (
                    commands
                )
            ),
        )
    )

    captured_output = (
        capsys.readouterr()
    )

    assert exit_code == 0

    runtime_result = json.loads(
        captured_output.out
    )

    assert (
        runtime_result[
            "success"
        ]
        is True
    )

    assert (
        runtime_result[
            "mode"
        ]
        == "APPLY"
    )

    assert (
        runtime_result[
            "database"
        ]
        == "runtime"
    )

    # ------------------------------------------------------------
    # Critical Checkpoint 12H.5 assertion:
    #
    # RESERVED → CONSUMED only through the trusted session handoff.
    # ------------------------------------------------------------

    assert (
        receipt_state(
            SESSION_ID
        )
        == RECEIPT_CONSUMED
    )

    assert (
        handler.calls
        == [
            PAYLOAD
        ]
    )

    persisted = (
        load_state(
            SESSION_ID
        )
    )

    assert (
        persisted
        is not None
    )

    assert (
        persisted[
            "merchant_runtime_authorization_issued"
        ]
        is True
    )

    # ------------------------------------------------------------
    # The same persisted run can never issue a second runtime apply.
    # ------------------------------------------------------------

    with pytest.raises(
        MerchantRuntimeHandoffError,
        match="already issued",
    ):
        invoke_confirmed_merchant_session_apply(
            SESSION_ID,
            _apply_arguments(
                proposal
            ),
            write_command_factory=(
                lambda database: (
                    commands
                )
            ),
        )

    assert (
        handler.calls
        == [
            PAYLOAD
        ]
    )

    assert (
        receipt_state(
            SESSION_ID
        )
        == RECEIPT_CONSUMED
    )