"""CP12H.NL2F: cross-run Project confirmation and execute-message routing.

Live run 2026-11-03 (lead 44beb2f5): Run A previewed "Beta Nguyễn Văn Cừ" on
the test database; Run B was the user's exact ``/solve --confirm
--merchant-target test --merchant-scope [...]``. The teammate's
``MERCHANT_EXECUTE_REQUEST_JSON`` was denied at PreToolUse(SendMessage) by the
Project *preview* delivery gate ("no verified Project preview operation exists
for this task"), because that gate judged every merchant-manager message and
the request text matched its operation-text pattern (``["project","create"``).

The earlier end-to-end tests drove only the PostToolUse hook, so the
PreToolUse gate never saw an execute request. These tests send every message
through the real PreToolUse policy gate first, and only a message it allows
reaches the PostToolUse staging hook, exactly as the harness does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from io import StringIO

import pytest

from claude.hooks import merchant_direct_handoff, policy_gate
from claude.hooks.merchant_preview_delivery import (
    PREVIEW_DELIVERY_FAILED,
    PREVIEW_OPERATION_MARKER,
)
from claude.hooks.merchant_reserved_execution import DatabasePreflightError
from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_STATE_KEY,
    MERCHANT_EXECUTE_REQUEST_MARKER,
)
from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD,
    PANE,
    PANE_TMUX,
    PROJECT_ROOT,
    TEAMMATE,
    TEST_DB_CONFIGURED,
    dispatch,
    idle,
    isolated,
    record,
    run_hook,
    run_state,
    submit,
)
from tests.merchant.test_nl2e_p1_p2_p4 import operation as preview_operation

# The fake intent model only reconciles operations from the request text, so
# Run B names the Project it confirms (the live text was "Create the
# previewed Project", which the real model classified as merchant_execute).
RUN_B = "Create the previewed cinema opening project Beta Nguyễn Văn Cừ"
LIVE_A = "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm"


def argv_from_run_a():
    """Run A: the read-only preview's exact operation (NL1 fake reader)."""

    return preview_operation(LIVE_A)["argv"]


def execute_body(argv, target="test", operation="merchant_execute"):
    return MERCHANT_EXECUTE_REQUEST_MARKER + "\n" + json.dumps(
        {
            "contract_version": 1,
            "operation": operation,
            "database_target": target,
            "arguments": list(argv),
        },
        ensure_ascii=False,
    )


def pre_payload(message):
    return {
        "hook_event_name": "PreToolUse",
        "session_id": PANE,
        "agent_type": TEAMMATE,
        "tool_name": "SendMessage",
        "tool_input": {"to": "team-lead", "message": message},
    }


def pre(message, capsys):
    """The real PreToolUse policy gate; returns its denial reason or None."""

    capsys.readouterr()
    original = sys.stdin
    try:
        sys.stdin = StringIO(json.dumps(pre_payload(message), ensure_ascii=False))
        assert policy_gate.main() == 0
    finally:
        sys.stdin = original
    out = capsys.readouterr().out.strip()

    if not out:
        return None

    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    return decision["permissionDecisionReason"]


def deliver(message, capsys, tool_use_id="send"):
    """Harness order: PreToolUse; only an allowed call runs and reaches Post."""

    reason = pre(message, capsys)

    if reason is not None:
        return reason

    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": PANE,
            "agent_type": TEAMMATE,
            "tool_name": "SendMessage",
            "tool_use_id": tool_use_id,
            "tool_input": {"recipient": "team-lead", "message": message},
        }
    ) == 0
    return None


@pytest.fixture
def preflight_calls(monkeypatch):
    """The trusted test-target preflight, stopped before any database use."""

    calls = []

    def target_repository(target):
        calls.append(target)
        raise DatabasePreflightError("DATABASE_UNAVAILABLE")

    monkeypatch.setattr(merchant_direct_handoff, "_target_repository", target_repository)
    return calls


def run_b(argv):
    """Run B: the user's exact confirmed scope, a fresh work unit."""

    submit(RUN_B, argv=argv, target="test")
    assert run_state()["merchant_scope"]["argv"] == list(argv)
    assert run_state()["merchant_scope"]["database_target"] == "test"
    assert dispatch() is None
    assert "project_preview_evidence" not in record()


def authority_spent():
    return run_state().get("merchant_runtime_authorization_issued") is True


# ------------------------------------------------- 1-2. cross-run accepted


def test_cross_run_execute_request_passes_the_message_gate(capsys, preflight_calls):
    argv = argv_from_run_a()
    run_b(argv)

    assert pre(execute_body(argv), capsys) is None


def test_cross_run_request_reaches_the_trusted_preflight_without_preview_evidence(
    capsys, preflight_calls
):
    argv = argv_from_run_a()
    run_b(argv)

    assert deliver(execute_body(argv), capsys, "execute-request") is None

    # Staged against the persisted scope and handed to the trusted preflight,
    # which (here) refuses before any reservation or spend.
    assert preflight_calls == ["test"]
    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == (
        "PREFLIGHT:DATABASE_UNAVAILABLE"
    )
    assert not authority_spent()


# ------------------------------------------------- 3. authorization required


def test_execute_request_in_an_unscoped_run_is_refused(capsys):
    argv = argv_from_run_a()
    submit(LIVE_A, confirmed=False, operations=())
    assert run_state().get("merchant_scope") is None
    assert dispatch("operation: merchant_read\ndatabase_target: test\nPreview it.") is None

    reason = pre(execute_body(argv), capsys)

    assert reason is not None
    assert "--merchant-scope" in reason
    assert PREVIEW_DELIVERY_FAILED not in reason


# ------------------------------------------------- 4. read-only stays bound


def test_read_only_preview_block_still_needs_current_task_evidence(capsys):
    op = preview_operation(LIVE_A)
    submit(LIVE_A, confirmed=False, operations=())
    assert dispatch("operation: merchant_read\ndatabase_target: test\nPreview it.") is None

    reason = pre(
        "Preview ready.\n" + PREVIEW_OPERATION_MARKER + "\n"
        + json.dumps(op, ensure_ascii=False),
        capsys,
    )

    assert reason is not None
    assert "no verified Project preview operation" in reason


# ------------------------------------------------- 5-6. masquerade and mixing


@pytest.mark.parametrize(
    "body",
    [
        lambda argv: PREVIEW_OPERATION_MARKER + "\n" + json.dumps({"argv": argv}),
        lambda argv: f"{PREVIEW_DELIVERY_FAILED}: gate blocked.\nTEAM_RESULT_JSON:\n{{}}",
        lambda argv: "confirmation_command: /solve --confirm ...",
    ],
)
def test_scoped_run_messages_cannot_present_as_preview_results(capsys, body):
    argv = argv_from_run_a()
    run_b(argv)

    reason = pre(body(argv), capsys)

    assert reason is not None and "scoped merchant_execute run" in reason


def test_mixed_execute_and_preview_contracts_are_refused(capsys, preflight_calls):
    argv = argv_from_run_a()
    run_b(argv)
    body = execute_body(argv) + "\n" + PREVIEW_OPERATION_MARKER + "\n{}"

    reason = pre(body, capsys)

    assert reason is not None and "mixes" in reason
    assert preflight_calls == []


# ------------------------------------------------- 7. wrong run/task/target


def test_execute_request_from_a_stale_run_is_refused(capsys):
    argv = argv_from_run_a()
    run_b(argv)
    # The run state moves on (a new prompt) while the teammate's task is the
    # old one: the task's run can no longer be verified.
    submit(RUN_B, argv=argv, target="test")

    reason = pre(execute_body(argv), capsys)

    assert reason is not None
    assert PREVIEW_DELIVERY_FAILED not in reason


def test_wrong_database_target_is_rejected_at_staging_without_spend(
    capsys, preflight_calls
):
    argv = argv_from_run_a()
    run_b(argv)

    assert deliver(execute_body(argv, target="runtime"), capsys, "execute-request") is None

    assert preflight_calls == []
    assert not authority_spent()


# ------------------------------------------------- 10. malformed arguments


@pytest.mark.parametrize(
    "mutate",
    [
        lambda argv: argv[:2] + argv[4:6] + argv[2:4] + argv[6:],    # reordered
        lambda argv: argv[:-1],                                       # truncated
        lambda argv: [t.replace("Nguyễn Văn Cừ", "Nguyen Van Cu") for t in argv],
        lambda argv: [t.replace("NL2_LIVE_BETA", "LOTTE") for t in argv],
    ],
)
def test_changed_arguments_never_reach_the_preflight(capsys, preflight_calls, mutate):
    argv = argv_from_run_a()
    run_b(argv)

    assert deliver(execute_body(mutate(argv)), capsys, "execute-request") is None

    assert preflight_calls == []
    assert run_state().get(HANDOFF_STATE_KEY, {}).get("status") != "SUCCESS"


def test_malformed_execute_request_never_reaches_the_preflight(capsys, preflight_calls):
    argv = argv_from_run_a()
    run_b(argv)

    deliver(MERCHANT_EXECUTE_REQUEST_MARKER + "\n{not json", capsys, "execute-request")

    assert preflight_calls == []


# ------------------------------------------------- 11-12. delivery and retry


def test_blocked_send_message_cannot_release_the_teammate(capsys):
    argv = argv_from_run_a()
    run_b(argv)

    assert pre(execute_body(argv) + "\n" + PREVIEW_OPERATION_MARKER + "{}", capsys)

    # The blocked call never ran, so no report is in the ledger: the idle
    # hook keeps the teammate active instead of accepting RESULT_DELIVERED.
    assert idle() == 2
    assert record()["status"] != "IDLE_REUSABLE"


def test_a_refused_attempt_is_never_retried(capsys, preflight_calls):
    argv = argv_from_run_a()
    run_b(argv)

    deliver(execute_body(argv), capsys, "execute-request")
    deliver(execute_body(argv), capsys, "execute-request-2")

    assert preflight_calls == ["test"]


# ------------------------------------------------- 13. UTF-8


def test_unicode_title_survives_into_the_staged_request(capsys, preflight_calls):
    argv = argv_from_run_a()
    assert "Beta Nguyễn Văn Cừ" in argv
    run_b(argv)

    deliver(execute_body(argv), capsys, "execute-request")

    assert preflight_calls == ["test"]  # an altered title never stages


def test_real_policy_gate_subprocess_allows_the_cross_run_request():
    """The hook as the harness runs it: its own process, UTF-8 stdin."""

    argv = argv_from_run_a()
    run_b(argv)

    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / ".claude" / "hooks" / "policy_gate.py")],
        input=json.dumps(pre_payload(execute_body(argv)), ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env={**os.environ, "TMUX_PANE": PANE_TMUX, "PYTHONPATH": str(PROJECT_ROOT)},
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert completed.stdout.decode("utf-8").strip() == ""


def test_real_policy_gate_subprocess_still_refuses_an_unscoped_execute_request():
    argv = argv_from_run_a()
    submit(LIVE_A, confirmed=False, operations=())
    assert dispatch("operation: merchant_read\ndatabase_target: test\nPreview it.") is None

    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / ".claude" / "hooks" / "policy_gate.py")],
        input=json.dumps(pre_payload(execute_body(argv)), ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env={**os.environ, "TMUX_PANE": PANE_TMUX, "PYTHONPATH": str(PROJECT_ROOT)},
        timeout=60,
    )

    decision = json.loads(completed.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"


# ------------------------------------------------- 14. production disabled


def test_runtime_direct_execute_remains_disabled():
    assert merchant_direct_handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False


# ------------------------------------------------- Phase 5: argv completeness


def test_completeness_from_scope_argv_uses_the_trusted_translation():
    from claude.agents.tools.merchant.cli import scope_argv_payload
    from claude.agents.tools.merchant.completeness import validate_write_completeness

    argv = argv_from_run_a()
    payload = scope_argv_payload(argv, "project create")

    assert payload["workflow_variant"] == "OPENING_NEW_CINEMA_STANDARD"
    assert "variant" not in payload
    assert validate_write_completeness("project create", payload).complete

    with pytest.raises(ValueError):
        scope_argv_payload(argv, "merchant create")
