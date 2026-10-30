"""CP12H.4D: trusted deterministic completeness is required before a write.

The evidence is computed by trusted code from the exact user-scope payload,
never accepted from the teammate, persisted with the staged request and
re-verified where authority is spent. It binds command, payload hash, run
and task. In-memory handlers only.
"""

from __future__ import annotations

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant.cli_contract import build_confirmation_envelope
from claude.agents.tools.merchant.write_commands import MerchantWriteCommands
from claude.hooks import merchant_direct_handoff
from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_STATE_KEY,
    stage_runtime_handoff_attempt,
)
from claude.hooks.runtime_state import locked_state
from claude.system import merchant_runtime_handoff

from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD,
    PROJECT_ID,
    TEAMMATE,
    UPDATE_ARGV,
    dispatch,
    execute_request,
    fake_runtime_handler,
    isolated,
    record,
    run_state,
    submit,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000005"

BLANK_REASON_ARGV = [
    "merchant", "activate",
    "--merchant-id", MERCHANT_ID,
    "--expected-version", "1",
    "--reason", "  ",
]


def _authority_spent():
    return run_state().get("merchant_runtime_authorization_issued") is True


def _scoped_update():
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None
    # Bind the verified pane; staging rejects these arguments.
    execute_request(["project", "list"])


def _stage():
    current = record()

    with locked_state(LEAD) as state:
        attempt, reason = stage_runtime_handoff_attempt(
            state,
            owner_session_id=LEAD,
            teammate_name=TEAMMATE,
            run_id=current["current_run_id"],
            task_id=current["current_task_id"],
            candidate={
                "arguments": tuple(UPDATE_ARGV),
                "database_target": "runtime",
            },
        )

    assert attempt is not None, reason
    return attempt


def _tamper_evidence(change):
    with locked_state(LEAD) as state:
        change(state[HANDOFF_STATE_KEY])


# -------------------------------------------------------------------
# Incomplete scopes never become write authority
# -------------------------------------------------------------------


def test_blank_required_field_scope_is_rejected():
    with pytest.raises(
        merchant_runtime_handoff.MerchantRuntimeHandoffError,
        match="incomplete",
    ):
        merchant_runtime_handoff.validate_direct_scope(BLANK_REASON_ARGV)


def test_incomplete_persisted_scope_never_writes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        merchant_cli,
        "build_write_commands",
        lambda database: MerchantWriteCommands(
            {"merchant activate": lambda p: calls.append(p) or {"ok": 1}}
        ),
    )

    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    # A persisted scope that is internally consistent (integrity hash and
    # dispatch receipt match) but incomplete, as if the user typed it.
    args = merchant_cli.build_argument_parser().parse_args(
        ["--database", "runtime", *BLANK_REASON_ARGV]
    )
    payload = merchant_cli.build_write_payload(args, "merchant activate")
    envelope = build_confirmation_envelope(
        "merchant activate", "runtime", payload
    )

    with locked_state(LEAD) as state:
        state["merchant_scope"].update(
            argv=list(BLANK_REASON_ARGV),
            command="merchant activate",
            scope_hash=merchant_runtime_handoff._direct_scope_hash(
                BLANK_REASON_ARGV, "runtime"
            ),
        )
        state["merchant_dispatch"]["confirmation_hash"] = (
            envelope.confirmation_hash
        )

    assert execute_request(BLANK_REASON_ARGV) == 0

    assert calls == []
    assert not _authority_spent()
    assert run_state().get(HANDOFF_STATE_KEY) is None


def test_staged_request_carries_trusted_completeness_evidence(
    fake_runtime_handler,
):
    _scoped_update()
    _stage()

    evidence = run_state()[HANDOFF_STATE_KEY]["completeness"]
    current = record()

    assert evidence["complete"] is True
    assert evidence["command"] == "project update"
    assert evidence["run_id"] == current["current_run_id"]
    assert evidence["task_id"] == current["current_task_id"]
    assert len(evidence["payload_sha256"]) == 64


def test_exact_completeness_evidence_allows_one_write(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    _scoped_update()

    attempt = _stage()
    assert merchant_direct_handoff.invoke_direct_merchant_execute(attempt) == 0
    assert len(calls) == 1


@pytest.mark.parametrize(
    "case, change",
    [
        ("missing", lambda handoff: handoff.pop("completeness")),
        ("stale-task", lambda handoff: handoff["completeness"].update(
            task_id="task-previous")),
        ("stale-run", lambda handoff: handoff["completeness"].update(
            run_id="run-previous")),
        ("incomplete", lambda handoff: handoff["completeness"].update(
            complete=False)),
        ("other-command", lambda handoff: handoff["completeness"].update(
            command="merchant activate")),
        ("other-payload", lambda handoff: handoff["completeness"].update(
            payload_sha256="0" * 64)),
    ],
)
def test_bad_completeness_evidence_blocks_spend_and_write(
    fake_runtime_handler,
    case,
    change,
):
    calls, _ = fake_runtime_handler
    _scoped_update()

    attempt = _stage()
    _tamper_evidence(change)

    with pytest.raises(Exception):
        merchant_direct_handoff.invoke_direct_merchant_execute(attempt)

    assert calls == []
    assert not _authority_spent()


def test_intent_gate_rejects_incomplete_user_scope():
    result = submit(
        f"Activate merchant {MERCHANT_ID}", argv=BLANK_REASON_ARGV
    )

    assert "hookSpecificOutput" not in (result or {})
    state = run_state()
    assert state is None or state.get("merchant_scope") is None
