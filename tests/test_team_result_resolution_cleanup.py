"""Lifecycle cleanup tests for Merchant resolution evidence."""

from __future__ import annotations

from contextlib import contextmanager

from claude.hooks import team_result_hook


def test_direct_merchant_release_clears_resolution(
    monkeypatch,
):
    cleared = []

    monkeypatch.setattr(
        team_result_hook,
        "load_team_state",
        lambda session_id: {
            "teammates": {},
        },
    )

    monkeypatch.setattr(
        team_result_hook,
        "release_reported_teammate_to_idle",
        lambda session_id, teammate_name: (
            True,
            "IDLE_REUSABLE",
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda session_id: (
            cleared.append(
                session_id
            )
            or True
        ),
    )

    feedback = (
        team_result_hook
        .handle_teammate_idle(
            None,
            {
                "teammate_name": (
                    "merchant-manager"
                ),
                "task_id": "task-1",
            },
            "pane-1",
        )
    )

    assert feedback == ""
    assert cleared == [
        "pane-1",
    ]


def test_other_teammate_release_does_not_clear_resolution(
    monkeypatch,
):
    cleared = []

    monkeypatch.setattr(
        team_result_hook,
        "load_team_state",
        lambda session_id: {
            "teammates": {},
        },
    )

    monkeypatch.setattr(
        team_result_hook,
        "release_reported_teammate_to_idle",
        lambda session_id, teammate_name: (
            True,
            "IDLE_REUSABLE",
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda session_id: (
            cleared.append(
                session_id
            )
            or True
        ),
    )

    feedback = (
        team_result_hook
        .handle_teammate_idle(
            None,
            {
                "teammate_name": "reviewer",
                "task_id": "task-1",
            },
            "pane-1",
        )
    )

    assert feedback == ""
    assert cleared == []


def test_failed_release_keeps_resolution(
    monkeypatch,
):
    cleared = []

    monkeypatch.setattr(
        team_result_hook,
        "load_team_state",
        lambda session_id: {
            "teammates": {},
        },
    )

    monkeypatch.setattr(
        team_result_hook,
        "release_reported_teammate_to_idle",
        lambda session_id, teammate_name: (
            False,
            "REPORT_RECEIVED",
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "find_unique_active_teammate_owner",
        lambda teammate_name: (
            "",
            None,
            "AMBIGUOUS",
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda session_id: (
            cleared.append(
                session_id
            )
            or True
        ),
    )

    feedback = (
        team_result_hook
        .handle_teammate_idle(
            None,
            {
                "teammate_name": (
                    "merchant-manager"
                ),
                "task_id": "task-1",
            },
            "pane-1",
        )
    )

    assert feedback
    assert cleared == []


def test_tmux_merchant_release_clears_resolution(
    monkeypatch,
):
    cleared = []
    result_cleared = []

    owner_record = {
        "current_run_id": "run-1",
        "current_task_id": "task-1",
        "authorized_operations": [
            "merchant_read",
        ],
        "authorized_selected_agents": [
            "merchant-manager",
        ],
    }

    monkeypatch.setattr(
        team_result_hook,
        "load_team_state",
        lambda session_id: None,
    )

    monkeypatch.setattr(
        team_result_hook,
        "find_unique_active_teammate_owner",
        lambda teammate_name: (
            "lead-1",
            owner_record,
            "FOUND",
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "load_pending_result",
        lambda session_id: {
            "owner_session_id": "lead-1",
            "teammate_name": (
                "merchant-manager"
            ),
            "run_id": "run-1",
            "task_id": "task-1",
        },
    )

    monkeypatch.setattr(
        team_result_hook,
        "mark_bound_report_received",
        lambda *args, **kwargs: True,
    )

    @contextmanager
    def fake_locked_state(
        session_id,
    ):
        yield None

    monkeypatch.setattr(
        team_result_hook,
        "locked_state",
        fake_locked_state,
    )

    monkeypatch.setattr(
        team_result_hook,
        "release_reported_teammate_to_idle",
        lambda session_id, teammate_name: (
            True,
            "IDLE_REUSABLE",
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda session_id: (
            cleared.append(
                session_id
            )
            or True
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_result",
        lambda session_id: (
            result_cleared.append(
                session_id
            )
            or True
        ),
    )

    feedback = (
        team_result_hook
        .handle_teammate_idle(
            None,
            {
                "teammate_name": (
                    "merchant-manager"
                ),
                "task_id": "task-1",
            },
            "pane-1",
        )
    )

    assert feedback == ""

    assert cleared == [
        "pane-1",
    ]

    assert result_cleared == [
        "pane-1",
    ]