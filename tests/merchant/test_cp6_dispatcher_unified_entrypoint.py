"""CP6.5B: production dispatcher calls exactly one trusted entrypoint."""

import io
import json
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import Mock

from claude.hooks.team_result_dispatcher import DispatcherDependencies, main


def test_dispatcher_uses_unified_trusted_entrypoint_only():
    owner = "cp6-unified-owner"
    argv = ("project", "update", "00000000-0000-0000-0000-000000000001",
            "--status", "IN_PROGRESS", "--expected-version", "3")
    attempt = SimpleNamespace(owner_session_id=owner, arguments=argv,
                              run_id="run", task_id="task")
    calls = []
    receipts = []

    def trusted_apply(session_id, arguments):
        assert session_id == owner
        assert tuple(arguments) == argv
        calls.append("trusted")
        print(json.dumps({"success": True}))
        return 0

    def forbidden(*args, **kwargs):
        raise AssertionError("Dispatcher called legacy apply dependency")

    @contextmanager
    def result_lock(session_id):
        assert session_id == owner
        yield {}

    deps = {field.name: Mock() for field in fields(DispatcherDependencies)}
    deps.update(
        HOOK_EVENT_NAMES={"PostToolUse"},
        MerchantRuntimeHandoffStageError=type("FakeStageError", (Exception,), {}),
        bounded_runtime_apply_failure=lambda _: "failure",
        bounded_runtime_apply_result=lambda output, _: (
            {"success": True} if json.loads(output).get("success") else None
        ),
        emit_post_tool_context=Mock(),
        handle_merchant_proposal_receipt=Mock(),
        handle_post_tool_use=Mock(),
        handle_teammate_idle=Mock(),

        invoke_trusted_merchant_session_apply=trusted_apply,
        io=io, json=json,
        locked_state=result_lock,
        prepare_merchant_runtime_handoff=lambda _: (True, attempt, ""),
        record_runtime_handoff_result=lambda *args, **kwargs: (
            receipts.append(kwargs) or True
        ),
        redirect_stderr=redirect_stderr,
        redirect_stdout=redirect_stdout,
        sys=SimpleNamespace(stdin=io.StringIO(json.dumps({
            "hook_event_name": "PostToolUse", "session_id": owner,
            "tool_name": "SendMessage"
        }))),
    )
    assert main(dependencies=DispatcherDependencies(**deps)) == 0
    assert calls == ["trusted"]
    assert len(receipts) == 1
    assert receipts[0]["succeeded"] is True
