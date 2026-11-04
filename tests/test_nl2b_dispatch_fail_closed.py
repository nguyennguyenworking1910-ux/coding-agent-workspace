"""CP12H.NL2B: a dispatch whose lifecycle binding fails must fail closed.

Live finding (2026-11-01): ``os.replace`` of the team-state file was denied
by Windows (WinError 5) on every retry inside ``mark_teammate_running``. The
uncaught exception made ``policy_gate`` exit 1, which Claude Code treats as
non-blocking, so the teammate was spawned unbound and then looped forever in
TeammateIdle ("Result delivery is still incomplete").
"""

from __future__ import annotations

import json

import pytest

from claude.hooks import runtime_state, team_lifecycle
from tests.merchant import test_direct_execute_end_to_end as e2e
from tests.merchant.test_direct_execute_end_to_end import idle, isolated  # noqa: F401
from tests.test_hook_utf8_boundaries import env, prompt_bytes  # noqa: F401
from tests.test_hook_utf8_boundaries import run as run_hook_subprocess

import subprocess
import sys

from tests.test_hook_utf8_boundaries import ROOT

# policy_gate as Claude Code runs it, except that every team-state replace
# after the first one is denied, as Windows did live.
FAILING_BIND = r"""
import os, runpy, sys
root = os.environ["NL2A_ROOT"]
sys.path.insert(0, os.path.join(root, ".claude", "hooks"))
import team_lifecycle
real = team_lifecycle.replace_with_retry
calls = []
def denied_after_first(temporary, destination):
    calls.append(destination)
    if len(calls) > 1:
        raise PermissionError(13, "Access is denied", str(destination))
    return real(temporary, destination)
team_lifecycle.replace_with_retry = denied_after_first
runpy.run_path(os.path.join(root, ".claude", "hooks", "policy_gate.py"), run_name="__main__")
"""

READ_REQUEST = (
    "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, "
    "không cần mua sắm"
)
SCOPE = [
    "project", "create",
    "--merchant-id", "6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f",
    "--type", "OPENING_NEW_CINEMA",
    "--variant", "OPENING_NEW_CINEMA_STANDARD",
    "--title", "Beta Nguyễn Văn Cừ",
]


def agent_dispatch_bytes(session):
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "session_id": session,
            "tool_name": "Agent",
            "tool_input": {
                "description": "Merchant preview",
                "subagent_type": "merchant-manager",
                "name": "merchant-manager",
                "prompt": f"Perform the user's request: {READ_REQUEST}",
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def dispatch_with_failing_bind(environment, session):
    return subprocess.run(
        [sys.executable, "-c", FAILING_BIND],
        input=agent_dispatch_bytes(session),
        capture_output=True,
        env=environment,
        cwd=str(ROOT),
        timeout=120,
    )


def decision(completed):
    text = completed.stdout.decode("utf-8").strip()
    return json.loads(text)["hookSpecificOutput"]["permissionDecision"] if text else None


def test_read_dispatch_is_denied_when_its_binding_cannot_be_saved(env):
    assert run_hook_subprocess("intent_gate", prompt_bytes(READ_REQUEST), env).returncode == 0

    completed = dispatch_with_failing_bind(env, "nl2a-lead")

    assert decision(completed) == "deny", completed.stderr.decode("utf-8", "replace")[-800:]
    assert completed.returncode == 0


def test_write_dispatch_is_denied_and_records_no_receipt(env):
    prompt = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "nl2b-lead",
            "prompt": "/solve --confirm --merchant-target test --merchant-scope "
            + json.dumps(SCOPE, ensure_ascii=False)
            + " Create a cinema opening project for Beta Nguyễn Văn Cừ under Beta Cinemas.",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    assert run_hook_subprocess("intent_gate", prompt, env).returncode == 0
    state = runtime_state.load_state("nl2b-lead")
    assert state["operations"] == ["merchant_execute"]
    assert state["merchant_scope"]["argv"] == SCOPE

    completed = dispatch_with_failing_bind(env, "nl2b-lead")

    assert decision(completed) == "deny", completed.stderr.decode("utf-8", "replace")[-800:]
    state = runtime_state.load_state("nl2b-lead")
    assert state.get("merchant_dispatch") is None
    assert state.get("merchant_dispatch_spent") is not True


@pytest.mark.parametrize("module", (team_lifecycle, runtime_state))
def test_replace_survives_a_sharing_violation_longer_than_150ms(
    module, monkeypatch, tmp_path
):
    """The live denial outlasted 5 attempts (~150 ms of backoff)."""

    destination = tmp_path / "state.json"
    temporary = tmp_path / "state.json.tmp"
    destination.write_text("old", encoding="utf-8")
    temporary.write_text("new", encoding="utf-8")

    waited = []
    real_replace = module.os.replace
    failures = {"left": 7}

    def denied_for_a_while(src, dst):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError(13, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(module, "IS_WINDOWS", True)
    monkeypatch.setattr(module.os, "replace", denied_for_a_while)
    monkeypatch.setattr(module.time, "sleep", waited.append)

    module.replace_with_retry(temporary, destination)

    assert destination.read_text(encoding="utf-8") == "new"
    assert sum(module.REPLACE_RETRY_BACKOFF_SECONDS) >= 1.0


def test_unbound_created_teammate_does_not_loop_at_idle():
    """A dispatch that never bound leaves CREATED with no run or task."""

    decision_, name = team_lifecycle.allocate_teammate(
        e2e.LEAD, "merchant-manager", "merchant-manager"
    )
    assert decision_ == team_lifecycle.TeammateAllocationDecision.CREATE
    record = team_lifecycle.load_team_state(e2e.LEAD)["teammates"][name]
    assert record["status"] == "CREATED" and record["current_run_id"] is None

    assert idle() == 0
    assert idle() == 0

    record = team_lifecycle.load_team_state(e2e.LEAD)["teammates"][name]
    assert record["status"] == "IDLE_REUSABLE"
    assert record["authorized_operations"] == []
