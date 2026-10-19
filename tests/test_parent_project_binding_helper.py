"""Contract tests for shared parent Project receipt binding."""

from types import SimpleNamespace

import pytest

from claude.hooks import policy_gate


def test_parent_project_binding_forwards_exact_context(monkeypatch):
    receipt = {"resolution": {"query": "exact project"}}
    expected = SimpleNamespace(
        accepted=True,
        project_id="project-1",
    )
    observed = []

    def fake_binder(actual_receipt, **kwargs):
        observed.append((actual_receipt, kwargs))
        return expected

    monkeypatch.setattr(
        policy_gate,
        "bind_project_resolution_receipt",
        fake_binder,
    )

    result = policy_gate._bind_parent_project_receipt(
        receipt,
        pane_session_id="pane-1",
        owner_session_id="session-1",
        owner_run_id="run-1",
        owner_task_id="task-1",
        trusted_merchant_id="merchant-1",
        project_expected_query="exact project",
    )

    assert result is expected
    assert observed == [
        (
            receipt,
            {
                "pane_session_id": "pane-1",
                "owner_session_id": "session-1",
                "teammate_name": policy_gate.MERCHANT_MANAGER_AGENT,
                "run_id": "run-1",
                "task_id": "task-1",
                "trusted_merchant_id": "merchant-1",
                "expected_query": "exact project",
            },
        )
    ]


@pytest.mark.parametrize(
    "accepted,project_id",
    [
        (False, None),
        (True, None),
        (True, "project-1"),
    ],
)
def test_parent_project_binding_preserves_result(
    monkeypatch,
    accepted,
    project_id,
):
    expected = SimpleNamespace(
        accepted=accepted,
        project_id=project_id,
    )

    monkeypatch.setattr(
        policy_gate,
        "bind_project_resolution_receipt",
        lambda *args, **kwargs: expected,
    )

    result = policy_gate._bind_parent_project_receipt(
        {"resolution": {"query": "project"}},
        pane_session_id="pane-1",
        owner_session_id="session-1",
        owner_run_id="run-1",
        owner_task_id="task-1",
        trusted_merchant_id="merchant-1",
        project_expected_query="project",
    )

    assert result is expected
