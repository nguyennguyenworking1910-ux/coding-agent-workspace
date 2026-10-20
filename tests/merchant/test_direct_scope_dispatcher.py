"""Dispatcher selects the runtime handler using owner state only."""

import io
import json
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from claude.hooks.team_result_dispatcher import (
    DispatcherDependencies,
    main,
)


@pytest.mark.parametrize("direct_mode", [True, False])
def test_dispatcher_invokes_unified_handler_for_both_scenarios(direct_mode):
    session_id = "isolated-dispatcher-session"
    argv = (
        "project",
        "update",
        "00000000-0000-0000-0000-000000000001",
        "--status",
        "IN_PROGRESS",
        "--expected-version",
        "3",
    )

    attempt = SimpleNamespace(
        owner_session_id=session_id,
        arguments=argv,
        run_id="isolated-run",
        task_id="isolated-task",
    )

    owner_state = {
        "merchant_scope": {"argv": list(argv)}
        if direct_mode else None,
    }

    calls = []
    receipts = []
    contexts = []

    @contextmanager
    def locked_state(owner):
        assert owner == session_id
        calls.append("lock")
        try:
            yield owner_state
        finally:
            calls.append("unlock")

    def direct_apply(owner, arguments):
        assert owner == session_id
        assert tuple(arguments) == argv
        assert calls == []
        calls.append("direct")
        print(json.dumps({"success": True}))
        return 0

    def legacy_apply(owner, arguments):
        assert owner == session_id
        assert tuple(arguments) == argv
        assert calls == []
        calls.append("legacy")
        print(json.dumps({"success": True}))
        return 0

    def prepare(payload):
        assert payload["hook_event_name"] == "PostToolUse"
        return True, attempt, ""

    def record(state, handoff, **kwargs):
        assert state is owner_state
        assert handoff is attempt
        receipts.append(kwargs)
        return True

    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": "SendMessage",
    }

    dependencies = {
        field.name: Mock()
        for field in fields(DispatcherDependencies)
    }

    dependencies.update(
        HOOK_EVENT_NAMES={"PostToolUse"},
        MerchantRuntimeHandoffStageError=type(
            "FakeHandoffStageError",
            (Exception,),
            {},
        ),
        bounded_runtime_apply_failure=lambda stderr: (
            "FAKE_RUNTIME_FAILURE"
        ),
        bounded_runtime_apply_result=lambda stdout, handoff: (
            {"success": True}
            if json.loads(stdout).get("success") is True
            else None
        ),
        emit_post_tool_context=contexts.append,
        handle_merchant_proposal_receipt=Mock(),
        handle_post_tool_use=Mock(),
        handle_teammate_idle=Mock(),


        invoke_trusted_merchant_session_apply=(direct_apply if direct_mode else legacy_apply),
        io=io,
        json=json,
        locked_state=locked_state,
        prepare_merchant_runtime_handoff=prepare,
        record_runtime_handoff_result=record,
        redirect_stderr=redirect_stderr,
        redirect_stdout=redirect_stdout,
        sys=SimpleNamespace(
            stdin=io.StringIO(json.dumps(payload))
        ),
    )

    result = main(
        dependencies=DispatcherDependencies(**dependencies)
    )

    assert result == 0

    expected_handler = "direct" if direct_mode else "legacy"
    unexpected_handler = "legacy" if direct_mode else "direct"

    assert calls.count(expected_handler) == 1
    assert unexpected_handler not in calls

    assert len(receipts) == 1
    assert receipts[0]["succeeded"] is True
    assert receipts[0]["exit_code"] == 0

    assert contexts
