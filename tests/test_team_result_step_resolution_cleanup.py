from __future__ import annotations

from claude.hooks import (
    team_result_hook,
)


def test_release_cleanup_clears_entity_chain_child_first(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_step_resolution",
        lambda session_id: (
            calls.append(
                (
                    "step",
                    session_id,
                )
            )
            or True
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_project_resolution",
        lambda session_id: (
            calls.append(
                (
                    "project",
                    session_id,
                )
            )
            or True
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda session_id: (
            calls.append(
                (
                    "merchant",
                    session_id,
                )
            )
            or True
        ),
    )

    team_result_hook._clear_merchant_resolution_after_release(
        "pane-1",
        "merchant-manager",
    )

    assert calls == [
        (
            "step",
            "pane-1",
        ),
        (
            "project",
            "pane-1",
        ),
        (
            "merchant",
            "pane-1",
        ),
    ]


def test_release_cleanup_ignores_other_teammates(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_step_resolution",
        lambda session_id: (
            calls.append("step")
            or True
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_project_resolution",
        lambda session_id: (
            calls.append("project")
            or True
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda session_id: (
            calls.append("merchant")
            or True
        ),
    )

    team_result_hook._clear_merchant_resolution_after_release(
        "pane-1",
        "reviewer",
    )

    assert calls == []


def test_release_cleanup_requires_session_identity(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_step_resolution",
        lambda session_id: (
            calls.append("step")
            or True
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_project_resolution",
        lambda session_id: (
            calls.append("project")
            or True
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "clear_pending_merchant_resolution",
        lambda session_id: (
            calls.append("merchant")
            or True
        ),
    )

    team_result_hook._clear_merchant_resolution_after_release(
        "",
        "merchant-manager",
    )

    assert calls == []


def test_successful_idle_release_invokes_entity_cleanup(
    monkeypatch,
):
    cleanup_calls = []

    monkeypatch.setattr(
        team_result_hook,
        "load_team_state",
        lambda session_id: {},
    )

    monkeypatch.setattr(
        team_result_hook,
        "release_reported_teammate_to_idle",
        lambda session_id, teammate_name: (
            True,
            {},
        ),
    )

    monkeypatch.setattr(
        team_result_hook,
        "_clear_merchant_resolution_after_release",
        lambda session_id, teammate_name: (
            cleanup_calls.append(
                (
                    session_id,
                    teammate_name,
                )
            )
        ),
    )

    result = (
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

    assert result == ""

    assert cleanup_calls == [
        (
            "pane-1",
            "merchant-manager",
        )
    ]