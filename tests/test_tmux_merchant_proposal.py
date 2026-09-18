from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"

if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(HOOKS_DIR),
    )

import tmux_merchant_proposal as proposal_store


@pytest.fixture
def isolated_store(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        proposal_store
        .PENDING_MERCHANT_PROPOSAL_DIR_ENV_VAR,
        str(tmp_path),
    )

    return tmp_path


def valid_proposal():
    return {
        "success": True,
        "mode": "PROPOSE",
        "database": "runtime",
        "command": "project create",
        "confirmation_token": "temporary-token",
    }


def test_stage_load_match_and_clear(
    isolated_store,
):
    assert (
        proposal_store
        .stage_pending_merchant_proposal(
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            tool_use_id="tool-1",
            proposal=valid_proposal(),
        )
    )

    loaded = (
        proposal_store
        .load_pending_merchant_proposal(
            "pane-1"
        )
    )

    assert loaded is not None

    assert (
        loaded["proposal"][
            "confirmation_token"
        ]
        == "temporary-token"
    )

    assert (
        proposal_store
        .pending_merchant_proposal_matches(
            loaded,
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
        )
    )

    assert (
        proposal_store
        .clear_pending_merchant_proposal(
            "pane-1"
        )
    )

    assert (
        proposal_store
        .load_pending_merchant_proposal(
            "pane-1"
        )
        is None
    )


def test_stale_binding_does_not_match(
    isolated_store,
):
    assert (
        proposal_store
        .stage_pending_merchant_proposal(
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-old",
            task_id="task-old",
            proposal=valid_proposal(),
        )
    )

    loaded = (
        proposal_store
        .load_pending_merchant_proposal(
            "pane-1"
        )
    )

    assert loaded is not None

    assert not (
        proposal_store
        .pending_merchant_proposal_matches(
            loaded,
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-new",
            task_id="task-new",
        )
    )


def test_invalid_proposal_is_not_staged(
    isolated_store,
):
    invalid = valid_proposal()
    invalid[
        "confirmation_token"
    ] = ""

    assert not (
        proposal_store
        .stage_pending_merchant_proposal(
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            proposal=invalid,
        )
    )


def test_missing_binding_is_not_staged(
    isolated_store,
):
    assert not (
        proposal_store
        .stage_pending_merchant_proposal(
            pane_session_id="pane-1",
            owner_session_id="",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            proposal=valid_proposal(),
        )
    )


def test_expired_proposal_is_rejected(
    isolated_store,
):
    assert (
        proposal_store
        .stage_pending_merchant_proposal(
            pane_session_id="pane-1",
            owner_session_id="lead-1",
            teammate_name="merchant-manager",
            run_id="run-1",
            task_id="task-1",
            proposal=valid_proposal(),
        )
    )

    path = (
        proposal_store
        .pending_merchant_proposal_path(
            "pane-1"
        )
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    payload["created_at"] = (
        time.time()
        - proposal_store.MAX_PROPOSAL_AGE_SECONDS
        - 1
    )

    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    assert (
        proposal_store
        .load_pending_merchant_proposal(
            "pane-1"
        )
        is None
    )
