"""Direct Scope authenticated orchestration without database access."""

import io
import json
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from claude.hooks import runtime_state
from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_STATE_KEY,
    HANDOFF_SUCCESS,
    handoff_candidate_from_message,
    stage_runtime_handoff_attempt,
)
from claude.hooks.merchant_runtime_orchestration import (
    MerchantRuntimeDependencies,
    prepare_merchant_runtime_handoff,
)
from claude.hooks.team_result_dispatcher import (
    DispatcherDependencies,
    main,
)
from claude.system.merchant_runtime_handoff import (
    validate_direct_scope,
)

from tests.merchant.test_direct_scope_end_to_end import (
    ARGV,
    SESSION_ID,
    submit,
    dispatch,
)


@pytest.fixture
def prepared_owner(tmp_path, monkeypatch):
    monkeypatch.setenv(
        runtime_state.STATE_DIR_ENV_VAR,
        str(tmp_path / "runtime"),
    )

    # Reuse existing intent test's envelope isolation.
    from claude.hooks import intent_envelope_bridge

    monkeypatch.setenv(
        intent_envelope_bridge.ENVELOPE_DIR_ENV_VAR,
        str(tmp_path / "envelopes"),
    )

    submit()
    dispatch()

    state = runtime_state.load_state(SESSION_ID)
    assert state is not None

    return state


def test_authenticated_direct_scope_post_tool_use(prepared_owner):
    state = prepared_owner
    run_id = state["run_id"]
    task_id = "checkpoint-3d-authenticated-task"

    scope = validate_direct_scope(ARGV)

    handoff_message = (
        "MERCHANT_APPLY_HANDOFF_REQUEST_JSON:\n"
        + json.dumps({
            "contract_version": 1,
            "operation": "merchant_apply",
            "database_target": "runtime",
            "confirmation_hash": scope["confirmation_hash"],
            "arguments": ARGV,
        })
    )

    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "trusted-merchant-pane",
        "agent_type": "merchant-manager",
        "tool_name": "SendMessage",
        "tool_input": {
            "recipient": "team-lead",
            "message": handoff_message,
            "task_id": task_id,
        },
    }

    owner_record = {
        "current_run_id": run_id,
        "current_task_id": task_id,
        "authorized_operations": ["merchant_apply"],
        "authorized_selected_agents": ["merchant-manager"],
    }

    def owner_lookup(name):
        assert name == "merchant-manager"
        return SESSION_ID, owner_record, "FOUND"

    def pane_matches(
        owner, agent, pane, run, task, **kwargs
    ):
        return (
            owner == SESSION_ID
            and agent == "merchant-manager"
            and pane == "trusted-merchant-pane"
            and run == run_id
            and task == task_id
            and kwargs.get("required_operation") == "merchant_apply",
            "PANE_MISMATCH",
        )

    runtime_deps = {
        field.name: Mock()
        for field in fields(MerchantRuntimeDependencies)
    }

    runtime_deps.update(
        MERCHANT_MANAGER_AGENT="merchant-manager",
        MERCHANT_PROPOSE_OPERATION="merchant_propose",
        _coalesced_text=lambda obj, *keys: next(
            (
                str(obj[key])
                for key in keys
                if obj.get(key) is not None
            ),
            "",
        ),
        contains_handoff_marker=lambda message: (
            "MERCHANT_APPLY_HANDOFF_REQUEST_JSON:"
            in message
        ),
        find_unique_active_teammate_owner=owner_lookup,
        handoff_candidate_from_message=handoff_candidate_from_message,
        locked_state=runtime_state.locked_state,
        send_message_body=lambda obj: obj.get("message", ""),
        stage_runtime_handoff_attempt=stage_runtime_handoff_attempt,
        trusted_post_tool_sender=lambda obj: (
            "merchant-manager"
            if obj.get("session_id") == "trusted-merchant-pane"
            else None
        ),
        trusted_teammate_pane_session_matches=pane_matches,
    )

    dependencies = MerchantRuntimeDependencies(
        **runtime_deps
    )

    preparer = lambda event: prepare_merchant_runtime_handoff(
        event,
        dependencies=dependencies,
    )

    direct_calls = []
    legacy_calls = []
    receipts = []
    contexts = []

    def direct_handler(owner, arguments):
        direct_calls.append((owner, tuple(arguments)))
        print(json.dumps({"success": True}))
        return 0

    def legacy_handler(owner, arguments):
        legacy_calls.append((owner, tuple(arguments)))
        raise AssertionError("Legacy handler must not execute")

    def record_receipt(owner_state, attempt, **kwargs):
        receipts.append(kwargs)
        assert owner_state[HANDOFF_STATE_KEY]["status"] == "PENDING"

        if kwargs["succeeded"]:
            owner_state[HANDOFF_STATE_KEY]["status"] = HANDOFF_SUCCESS

        return True

    dispatcher_deps = {
        field.name: Mock()
        for field in fields(DispatcherDependencies)
    }

    dispatcher_deps.update(
        HOOK_EVENT_NAMES={"PostToolUse"},
        MerchantRuntimeHandoffStageError=type(
            "FakeStageError", (Exception,), {}
        ),
        bounded_runtime_apply_failure=lambda output: "FAKE_ERROR",
        bounded_runtime_apply_result=lambda output, attempt: (
            {"success": True}
            if json.loads(output).get("success") is True
            else None
        ),
        emit_post_tool_context=contexts.append,
        handle_merchant_proposal_receipt=Mock(),
        handle_post_tool_use=Mock(),
        handle_teammate_idle=Mock(),
        invoke_confirmed_merchant_session_apply=legacy_handler,
        invoke_authorized_scope_apply=direct_handler,
        io=io,
        json=json,
        locked_state=runtime_state.locked_state,
        prepare_merchant_runtime_handoff=preparer,
        record_runtime_handoff_result=record_receipt,
        redirect_stderr=redirect_stderr,
        redirect_stdout=redirect_stdout,
        sys=SimpleNamespace(
            stdin=io.StringIO(json.dumps(payload))
        ),
    )

    exit_code = main(
        dependencies=DispatcherDependencies(**dispatcher_deps)
    )

    assert exit_code == 0
    assert direct_calls == [(SESSION_ID, tuple(ARGV))]
    assert legacy_calls == []
    assert len(receipts) == 1
    assert receipts[0]["succeeded"] is True

    persisted = runtime_state.load_state(SESSION_ID)

    assert persisted[HANDOFF_STATE_KEY]["status"] == HANDOFF_SUCCESS

    # Replaying the exact same message must not execute again.
    replay = preparer(payload)
    assert replay[0] is True
    assert replay[1] is None
    assert replay[2]

    # Forged sender cannot stage a new handoff.
    forged = dict(payload)
    forged["session_id"] = "untrusted-pane"
    recognized, attempt, reason = preparer(forged)

    assert recognized is True
    assert attempt is None
    assert reason
    assert len(direct_calls) == 1
