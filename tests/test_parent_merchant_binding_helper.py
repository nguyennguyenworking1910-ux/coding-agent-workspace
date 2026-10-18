"""Contract tests for shared parent Merchant receipt binding."""

from types import SimpleNamespace

import pytest

from claude.hooks import policy_gate


def test_parent_binding_forwards_exact_trusted_context(monkeypatch):
    receipt = {"resolution": {"query": "exact merchant"}}
    expected = SimpleNamespace(
        accepted=True,
        outcome="BOUND",
        merchant_id="merchant-1",
    )
    observed = []

    def fake_binder(actual_receipt, **kwargs):
        observed.append((actual_receipt, kwargs))
        return expected

    monkeypatch.setattr(
        policy_gate,
        "bind_merchant_resolution_receipt",
        fake_binder,
    )

    result = policy_gate._bind_parent_merchant_receipt(
        receipt,
        pane_session_id="pane-session-1",
        owner_session_id="owner-session-1",
        owner_run_id="run-1",
        owner_task_id="task-1",
        merchant_expected_query="exact merchant",
    )

    assert result is expected
    assert observed == [
        (
            receipt,
            {
                "pane_session_id": "pane-session-1",
                "owner_session_id": "owner-session-1",
                "teammate_name": policy_gate.MERCHANT_MANAGER_AGENT,
                "run_id": "run-1",
                "task_id": "task-1",
                "expected_query": "exact merchant",
            },
        )
    ]


@pytest.mark.parametrize(
    "accepted,outcome,merchant_id",
    [
        (False, "REJECTED", None),
        (True, "REJECTED", None),
        (True, "BOUND", None),
    ],
)
def test_parent_binding_preserves_rejected_results(
    monkeypatch,
    accepted,
    outcome,
    merchant_id,
):
    expected = SimpleNamespace(
        accepted=accepted,
        outcome=outcome,
        merchant_id=merchant_id,
    )

    monkeypatch.setattr(
        policy_gate,
        "bind_merchant_resolution_receipt",
        lambda *args, **kwargs: expected,
    )

    result = policy_gate._bind_parent_merchant_receipt(
        {"resolution": {"query": "merchant"}},
        pane_session_id="pane-1",
        owner_session_id="session-1",
        owner_run_id="run-1",
        owner_task_id="task-1",
        merchant_expected_query="merchant",
    )

    assert result is expected
