"""CP12H.3: Merchant Direct EXECUTE reachable end to end.

User intent -> intent gate (real parser, fake model client) -> policy
dispatch -> teammate execute request -> trusted runtime handoff ->
team-state execution evidence -> TeammateIdle terminal gate -> release.

No test may construct a runtime-database repository. The Merchant Create
path runs against the configured test database only, and is skipped when
that database is not configured.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from io import StringIO
from pathlib import Path

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant.write_commands import MerchantWriteCommands
from claude.clients.merchant.repository import MerchantRepository
from claude.hooks import (
    intent_envelope_bridge,
    intent_gate,
    merchant_direct_handoff,
    policy_gate,
    runtime_state,
    team_lifecycle,
    team_result_hook,
)
from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_FAILED,
    HANDOFF_STATE_KEY,
    HANDOFF_SUCCESS,
    MERCHANT_EXECUTE_REQUEST_MARKER,
)
from claude.hooks.tmux_result_receipt import load_pending_result
from claude.hooks import harness_team_identity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_DIR = PROJECT_ROOT / ".claude" / "system"

sys.path.insert(0, str(SYSTEM_DIR))

from intent_parser import (  # noqa: E402
    ComplexityBreakdown,
    Domain,
    IntentParser,
    OpenAIIntentDecision,
    Operation,
)
from schemas import RiskLevel, TaskClass  # noqa: E402


LEAD = "cp12h3-lead"
PANE = "cp12h3-pane"

# The tmux pane the harness recorded for merchant-manager. Every other
# pane session runs in a different tmux pane.
PANE_TMUX = "%7"
# The psmux server that owns the teammate pane and the harness lead process.
# Unit tests replace only the OS evidence (harness_team_identity's
# _os_pane_server); the harness record and TMUX_PANE checks stay real.
LEAD_PID = 4242
PANE_SERVER = 7000
TMUX_BY_PANE = {PANE: PANE_TMUX}
TEAMMATE = "merchant-manager"
PROJECT_ID = "00000000-0000-0000-0000-000000000001"

UPDATE_ARGV = [
    "project", "update", PROJECT_ID,
    "--status", "IN_PROGRESS",
    "--expected-version", "3",
]


# -------------------------------------------------------------------
# Harness
# -------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, decision):
        self.status = "completed"
        self.output_parsed = decision


class _FakeResponses:
    def __init__(self, decision):
        self.decision = decision

    def parse(self, **kwargs):
        return _FakeResponse(self.decision)


class _FakeClient:
    def __init__(self, decision):
        self.responses = _FakeResponses(decision)


def _model_decision(operations, risk=RiskLevel.READ_ONLY):
    """A model decision the deterministic guardrails must correct."""
    return OpenAIIntentDecision(
        task_class=TaskClass.SMALL,
        risk_level=risk,
        confidence=0.95,
        score_breakdown=ComplexityBreakdown(
            scope=0, domains=0, dependencies=0,
            verification=0, ambiguity=0,
        ),
        operations=operations,
        domains=[Domain.MERCHANT],
        reasons=["fake model decision"],
        requires_clarification=False,
    )


def _parser(operations=(), risk=RiskLevel.READ_ONLY):
    return IntentParser(
        PROJECT_ROOT / ".claude" / "agents.json",
        client=_FakeClient(_model_decision(list(operations), risk)),
    )


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(
        runtime_state.STATE_DIR_ENV_VAR, str(tmp_path / "run_state")
    )
    monkeypatch.setenv("CLAUDE_TEAM_STATE_DIR", str(tmp_path / "team"))
    monkeypatch.setenv(
        "CLAUDE_PENDING_TEAM_RESULT_DIR", str(tmp_path / "pending")
    )
    monkeypatch.setenv("CLAUDE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv(
        intent_envelope_bridge.ENVELOPE_DIR_ENV_VAR,
        str(tmp_path / "envelopes"),
    )

    # The harness-written team config for this lead (see
    # harness_team_identity): merchant-manager runs in tmux pane %7.
    teams = tmp_path / "harness_teams"
    write_harness_team(teams, PANE_TMUX)
    monkeypatch.setenv(harness_team_identity.TEAMS_DIR_ENV_VAR, str(teams))
    monkeypatch.setattr(
        harness_team_identity,
        "_os_pane_server",
        lambda tmux_pane, lead_pid: (
            PANE_SERVER if lead_pid == LEAD_PID else None
        ),
        raising=False,
    )

    # Item 10: no test may even construct a non-test repository.
    original_init = MerchantRepository.__init__

    def guarded_init(self, *args, role="app", **kwargs):
        if role != "test":
            raise AssertionError(
                f"test attempted a {role!r} Merchant repository"
            )
        original_init(self, *args, role=role, **kwargs)

    monkeypatch.setattr(MerchantRepository, "__init__", guarded_init)


@pytest.fixture
def fake_runtime_handler(monkeypatch):
    """Non-Create runtime writes reach this in-memory handler only.

    The handler models one evidenced transaction: a commit records the
    attempt's claim, a raise commits nothing. ``resolve_attempt`` reads that
    model; ``fence_blocked`` models a fence that cannot be placed (an
    in-flight transaction or an unreachable database), and
    ``commit_then_raise`` a commit whose acknowledgement is lost.
    """
    calls = []
    behaviour = {
        "raise": None,
        "fence_blocked": False,
        "commit_then_raise": None,
        "no_evidence": False,
    }
    evidence = {}

    def scope_write_commands(database, repository, identity):
        def handler(payload):
            if behaviour["raise"] is not None:
                raise behaviour["raise"]
            calls.append(payload)
            if not behaviour["no_evidence"]:
                evidence[identity.operation_key] = (
                    identity.execution_attempt_id
                )
            if behaviour["commit_then_raise"] is not None:
                raise behaviour["commit_then_raise"]
            return {"status": "committed"}

        return MerchantWriteCommands({"project update": handler})

    def resolve_attempt(repository, identity, *, fence):
        committed = evidence.get(identity.operation_key)

        if committed == identity.execution_attempt_id:
            return "COMMITTED"

        if committed is None and fence and not behaviour["fence_blocked"]:
            evidence[identity.operation_key] = "REVOKED"
            return "NOT_COMMITTED"

        return "UNCERTAIN"

    monkeypatch.setattr(
        merchant_direct_handoff,
        "_target_repository",
        lambda target: object(),
    )
    monkeypatch.setattr(
        merchant_direct_handoff,
        "_scope_write_commands",
        scope_write_commands,
    )
    monkeypatch.setattr(
        "claude.clients.merchant.attempt_evidence.resolve_attempt",
        resolve_attempt,
    )
    monkeypatch.setattr(
        "claude.hooks.merchant_reserved_execution.repository_for_target",
        lambda database: object(),
    )
    # Runtime Direct EXECUTE ships disabled; these lifecycle tests reach
    # only the in-memory handler above.
    monkeypatch.setattr(
        merchant_direct_handoff,
        "RUNTIME_DIRECT_EXECUTE_ENABLED",
        True,
        raising=False,
    )

    return calls, behaviour


def submit(request, *, argv=None, confirmed=True, operations=(), target=None):
    prefix = "/solve --confirm" if confirmed else "/solve"
    scope = (
        f" --merchant-scope {json.dumps(argv)}"
        if argv is not None
        else ""
    )

    if target is not None:
        scope = f" --merchant-target {target}{scope}"

    return intent_gate.run(
        {
            "hook_event_name": "UserPromptExpansion",
            "session_id": LEAD,
            "prompt": f"{prefix}{scope} {request}",
        },
        parser_factory=lambda: _parser(operations),
        env={},
    )


def dispatch(prompt="Perform the user's Merchant request."):
    with runtime_state.locked_state(LEAD) as state:
        assert state is not None
        return policy_gate.apply_call(
            state,
            "Agent",
            {
                "subagent_type": TEAMMATE,
                "name": TEAMMATE,
                "prompt": prompt,
            },
            session_id=LEAD,
        )


def write_harness_team(teams_dir, tmux_pane):
    team = teams_dir / "session-cp12h3"
    team.mkdir(parents=True, exist_ok=True)
    (team / "config.json").write_text(
        json.dumps(
            {
                "leadSessionId": LEAD,
                "leadProcess": {
                    "pid": LEAD_PID,
                    "pidSpace": socket.gethostname(),
                },
                "members": [
                    {
                        "name": TEAMMATE,
                        "agentType": TEAMMATE,
                        "backendType": "tmux",
                        "tmuxPaneId": tmux_pane,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def run_hook(payload, *, tmux=None):
    """Run the hook as the payload pane's own subprocess would."""

    pane = tmux if tmux is not None else TMUX_BY_PANE.get(
        payload.get("session_id"), "%99"
    )
    original = sys.stdin
    original_pane = os.environ.get("TMUX_PANE")
    try:
        sys.stdin = StringIO(json.dumps(payload))
        os.environ["TMUX_PANE"] = pane
        return team_result_hook.main()
    finally:
        sys.stdin = original
        if original_pane is None:
            os.environ.pop("TMUX_PANE", None)
        else:
            os.environ["TMUX_PANE"] = original_pane


def send(message, *, pane=PANE, tool_use_id="send", tmux=None):
    return run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane,
            "agent_type": TEAMMATE,
            "tool_name": "SendMessage",
            "tool_use_id": tool_use_id,
            "tool_input": {"recipient": "team-lead", "message": message},
        },
        tmux=tmux,
    )


def execute_request(
    argv,
    *,
    pane=PANE,
    operation="merchant_execute",
    tmux=None,
    target="runtime",
):
    return send(
        MERCHANT_EXECUTE_REQUEST_MARKER
        + "\n"
        + json.dumps(
            {
                "contract_version": 1,
                "operation": operation,
                "database_target": target,
                "arguments": list(argv),
            }
        ),
        pane=pane,
        tool_use_id="execute-request",
        tmux=tmux,
    )


def report(outcome, *, pane=PANE, tmux=None, **fields):
    result = {
        "contract_version": 1,
        "outcome": outcome,
        "operation": "merchant_execute",
        "database_target": "runtime",
        "proposal_emitted": False,
        **fields,
    }
    return send(
        "TEAM_RESULT_JSON:\n" + json.dumps(result), pane=pane, tmux=tmux
    )


def idle(pane=PANE, *, tmux=None):
    return run_hook(
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane,
            "agent_type": TEAMMATE,
            "teammate_name": TEAMMATE,
        },
        tmux=tmux,
    )


def record():
    return team_lifecycle.load_team_state(LEAD)["teammates"][TEAMMATE]


def run_state():
    return runtime_state.load_state(LEAD)


# -------------------------------------------------------------------
# 1-2. Intent -> merchant_execute authorization -> exact binding
# -------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_text, model_operations",
    [
        ("Create merchant CP12H3 with code CP12H3X", []),
        ("Create merchant CP12H3 with code CP12H3X", [Operation.MERCHANT_READ]),
        (f"Update merchant project {PROJECT_ID} to IN_PROGRESS", []),
    ],
)
def test_write_intent_authorizes_merchant_execute_only(
    request_text, model_operations
):
    envelope = _parser(model_operations).parse(request_text)

    assert envelope.operations == ["merchant_execute"]
    assert envelope.selected_agents == [TEAMMATE]
    assert envelope.risk_level == RiskLevel.EXTERNAL_WRITE
    assert envelope.requires_confirmation is True


def test_preview_request_never_carries_write_authority():
    envelope = _parser().parse(
        "Prepare a proposal only to create merchant CGV"
    )

    assert envelope.operations == ["merchant_read"]
    assert envelope.risk_level == RiskLevel.READ_ONLY


def test_scoped_dispatch_binds_exact_teammate_and_scope():
    result = submit(
        f"Update merchant project {PROJECT_ID} to IN_PROGRESS",
        argv=UPDATE_ARGV,
    )
    assert "hookSpecificOutput" in result

    state = run_state()
    assert state["operations"] == ["merchant_execute"]
    assert state["selected_agents"] == [TEAMMATE]
    assert state["merchant_scope"]["argv"] == UPDATE_ARGV
    assert "merchant_confirmation" not in state

    assert dispatch() is None

    state = run_state()
    assert state["merchant_dispatch_spent"] is True
    assert state["merchant_dispatch"]["operation"] == "merchant_execute"

    current = record()
    assert current["status"] == "RUNNING"
    assert current["authorized_operations"] == ["merchant_execute"]
    assert current["authorized_selected_agents"] == [TEAMMATE]
    assert current["current_run_id"] == state["run_id"]

    # One scope authorizes exactly one dispatch.
    assert dispatch() is not None


def test_scope_cannot_be_combined_with_unconfirmed_request():
    result = submit("Update project", argv=UPDATE_ARGV, confirmed=False)

    assert "hookSpecificOutput" not in result
    assert run_state() is None


# -------------------------------------------------------------------
# 4-5. Scoped write -> trusted evidence -> report -> IDLE_REUSABLE
# -------------------------------------------------------------------


def test_scoped_update_executes_once_and_releases(fake_runtime_handler):
    calls, _ = fake_runtime_handler

    submit(
        f"Update merchant project {PROJECT_ID} to IN_PROGRESS",
        argv=UPDATE_ARGV,
    )
    assert dispatch() is None

    assert execute_request(UPDATE_ARGV) == 0

    assert len(calls) == 1
    assert calls[0]["project_id"] == PROJECT_ID
    assert run_state()[HANDOFF_STATE_KEY]["status"] == HANDOFF_SUCCESS

    execution = record()["direct_scope_execution"]
    assert execution["status"] == "SUCCEEDED"
    assert execution["command"] == "project update"
    assert record()["trusted_pane_session_id"] == PANE

    # Item 8: a duplicate request never executes again.
    assert execute_request(UPDATE_ARGV) == 0
    assert len(calls) == 1

    assert report("EXECUTE_SUCCESS", command="project update") == 0
    assert record()["status"] == "RUNNING"

    assert idle() == 0

    current = record()
    assert current["status"] == "IDLE_REUSABLE"
    assert current["report_source"] == "sendmessage"
    assert "direct_scope_execution" not in current
    assert [
        item["status"]
        for item in current["completed_scope_execution_history"]
    ] == ["SUCCEEDED"]
    assert load_pending_result(PANE) is None

    # Repeated idle is a no-op.
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"


def test_scoped_write_cannot_be_released_as_no_write(fake_runtime_handler):
    calls, _ = fake_runtime_handler

    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None
    assert execute_request(UPDATE_ARGV) == 0
    assert len(calls) == 1

    # A misleading no-write report is rejected: the committed execution
    # evidence decides, and no no-write marker is created.
    assert report("BLOCKED") == 0
    assert idle() == 2
    assert record()["status"] == "RUNNING"
    assert "direct_no_write_terminal" not in record()

    assert report("EXECUTE_SUCCESS", command="project update") == 0
    assert idle() == 0

    current = record()
    assert current["status"] == "IDLE_REUSABLE"
    assert "direct_no_write_terminal" not in current
    assert current["completed_scope_execution_history"][0]["status"] == (
        "SUCCEEDED"
    )


@pytest.mark.parametrize("failure", ["handler", "unclassified", "uncertain"])
def test_failed_scoped_write_is_terminal_and_never_retried(
    fake_runtime_handler, monkeypatch, failure
):
    calls, behaviour = fake_runtime_handler

    if failure == "handler":
        # Nothing committed and the fence was placed: verifiably failed.
        behaviour["raise"] = ValueError("expected_version mismatch")
        expected = "FAILED"
    elif failure == "unclassified":
        # The fence cannot be placed: never inferred as rolled back.
        behaviour["raise"] = RuntimeError("database rejected the write")
        behaviour["fence_blocked"] = True
        expected = "UNCERTAIN"
    else:
        behaviour["fence_blocked"] = True

        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt("interrupted after authorization")

        monkeypatch.setattr(
            "claude.system.merchant_runtime_handoff."
            "invoke_authorized_scope_apply",
            interrupted,
        )
        expected = "UNCERTAIN"

    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    if failure == "uncertain":
        with pytest.raises(KeyboardInterrupt):
            execute_request(UPDATE_ARGV)
    else:
        assert execute_request(UPDATE_ARGV) == 0
        assert run_state()[HANDOFF_STATE_KEY]["status"] == HANDOFF_FAILED

    assert record()["direct_scope_execution"]["status"] == expected

    # The spent attempt is never retried.
    assert execute_request(UPDATE_ARGV) == 0
    assert calls == []

    assert report(
        "EXECUTE_FAILED" if expected == "FAILED" else "EXECUTE_UNCERTAIN",
        command="project update",
    ) == 0

    # Item 9: bounded, no loop.
    assert idle() == 0
    current = record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"] == f"DIRECT_EXECUTION_{expected}"
    assert current["current_task_id"] is None

    # The execution record is kept and blocks reassignment.
    assert current["direct_scope_execution"]["status"] == expected
    assert team_lifecycle.mark_teammate_running(
        LEAD, TEAMMATE, "run-next", "task-next",
        operations=["merchant_execute"], selected_agents=[TEAMMATE],
    ) is False

    assert idle() == 0
    assert record()["status"] == "FAILED"


# -------------------------------------------------------------------
# 8. Duplicate, stale and cross-pane/cross-task events
# -------------------------------------------------------------------


def test_other_pane_cannot_execute_or_settle(fake_runtime_handler):
    calls, _ = fake_runtime_handler

    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    # First use binds the executing pane.
    assert execute_request(UPDATE_ARGV) == 0
    assert record()["trusted_pane_session_id"] == PANE

    # Another pane can neither execute nor settle this task.
    assert execute_request(UPDATE_ARGV, pane="intruder-pane") == 0
    assert len(calls) == 1

    assert report("EXECUTE_SUCCESS", pane="intruder-pane",
                  command="project update") == 0
    # CP12H.4C: a foreign pane is ignored without feedback (no loop).
    assert idle("intruder-pane") == 0
    assert record()["status"] == "RUNNING"


def test_changed_arguments_spend_scope_without_writing(fake_runtime_handler):
    calls, _ = fake_runtime_handler

    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    changed = [*UPDATE_ARGV[:-1], "4"]
    assert execute_request(changed) == 0

    assert calls == []
    assert "direct_scope_execution" not in record()
    assert run_state().get(HANDOFF_STATE_KEY) is None

    # The exact scope still executes once.
    assert execute_request(UPDATE_ARGV) == 0
    assert len(calls) == 1


def test_legacy_execute_request_shape_is_rejected(fake_runtime_handler):
    calls, _ = fake_runtime_handler

    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    assert execute_request(UPDATE_ARGV, operation="merchant_apply") == 0
    assert send(
        "MERCHANT_APPLY_HANDOFF_REQUEST_JSON:\n"
        + json.dumps({"arguments": UPDATE_ARGV})
    ) == 0

    assert calls == []
    assert "direct_scope_execution" not in record()


def test_previous_task_evidence_cannot_settle_new_task(fake_runtime_handler):
    calls, _ = fake_runtime_handler

    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None
    assert execute_request(UPDATE_ARGV) == 0
    assert report("EXECUTE_SUCCESS", command="project update") == 0
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"

    # Reuse the teammate for a new task with no new evidence.
    assert team_lifecycle.mark_teammate_running(
        LEAD, TEAMMATE, "run-next", "task-next",
        operations=["merchant_execute"], selected_agents=[TEAMMATE],
    )

    assert team_lifecycle.mark_bound_report_received(
        LEAD, TEAMMATE, "run-next", "task-next", "sendmessage"
    ) is False

    # The earlier task's delivered report does not match the new task.
    assert idle() == 2
    assert record()["status"] == "RUNNING"
    assert len(calls) == 1


# -------------------------------------------------------------------
# 3, 6. Unscoped request: completeness clarification without a write
# -------------------------------------------------------------------


def _completeness(pane=PANE):
    result = {
        "success": True,
        "mode": "COMPLETENESS",
        "command": "merchant create",
        "complete": False,
        "missing_fields": ["code"],
        "missing_one_of": [],
        "clarification": {
            "outcome": "REQUIRES_CLARIFICATION",
            "missing_fields": ["code"],
            "missing_one_of": [],
            "question": "Please provide code.",
        },
    }
    assert run_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": pane,
            "agent_type": TEAMMATE,
            "tool_name": "Bash",
            "tool_use_id": "completeness",
            "tool_response": {"stdout": json.dumps(result), "stderr": ""},
        }
    ) == 0


def test_unscoped_execute_clarifies_without_write(fake_runtime_handler):
    calls, _ = fake_runtime_handler

    result = submit("Create merchant CGV")
    assert "hookSpecificOutput" in result
    assert run_state()["operations"] == ["merchant_execute"]
    assert run_state().get("merchant_scope") is None

    assert dispatch() is None
    assert run_state().get("merchant_dispatch") is None

    # No user scope: an execute request can never reach the runtime.
    assert execute_request(UPDATE_ARGV) == 0
    assert calls == []
    assert run_state().get(HANDOFF_STATE_KEY) is None

    _completeness()

    assert report(
        "REQUIRES_CLARIFICATION",
        missing_fields=["code"],
        missing_one_of=[],
        question="Please provide code.",
    ) == 0

    assert idle() == 0

    current = record()
    assert current["status"] == "IDLE_REUSABLE"
    assert "direct_no_write_terminal" not in current
    assert "direct_writes" not in current
    assert "direct_scope_execution" not in current


def test_unscoped_assignment_cannot_carry_cli_syntax():
    submit("Create merchant CGV")

    decision = dispatch(
        "Run merchant create --code CGV --name CGV for the user."
    )

    assert decision is not None
    assert "semantic-only" in json.dumps(decision)
    assert team_lifecycle.load_team_state(LEAD) is None


# -------------------------------------------------------------------
# 7, 9. Legacy operations rejected; stale tasks terminate, no loops
# -------------------------------------------------------------------


def test_legacy_confirmation_flag_is_rejected():
    result = intent_gate.run(
        {
            "hook_event_name": "UserPromptExpansion",
            "session_id": LEAD,
            "prompt": "/solve --merchant-confirmation legacy-token apply it",
        },
        parser_factory=lambda: _parser(),
        env={},
    )

    assert result.get("decision") == "block"
    assert run_state() is None


@pytest.mark.parametrize("operation", ["merchant_propose", "merchant_apply"])
def test_legacy_operation_cannot_be_dispatched_or_started(operation):
    state = runtime_state.new_state(
        request="stale legacy request",
        task_class="small_task",
        risk_level="external_write",
        selected_agents=[TEAMMATE],
        limits={"max_members": 1, "max_total_tool_calls": 10},
        confirmed=True,
        operations=[operation],
        run_id="legacy-run",
    )
    runtime_state.save_state(LEAD, state)

    assert dispatch() is not None
    assert team_lifecycle.load_team_state(LEAD) is None or (
        record().get("status") != "RUNNING"
    )

    team_lifecycle.allocate_teammate(LEAD, TEAMMATE, TEAMMATE)
    assert team_lifecycle.mark_teammate_running(
        LEAD, TEAMMATE, "legacy-run", "legacy-task",
        operations=[operation], selected_agents=[TEAMMATE],
    ) is False


def _install_stale_legacy_task(operation):
    """Simulate a task persisted before CP12H.3 removed the workflow."""
    team_lifecycle.allocate_teammate(LEAD, TEAMMATE, TEAMMATE)

    with team_lifecycle.locked_team_state(LEAD) as state:
        state["teammates"][TEAMMATE].update(
            status="RUNNING",
            current_run_id="stale-run",
            current_task_id="stale-task",
            authorized_operations=[operation],
            authorized_selected_agents=[TEAMMATE],
            result_received=False,
            report_source=None,
        )


@pytest.mark.parametrize("operation", ["merchant_propose", "merchant_apply"])
@pytest.mark.parametrize("delivered", [True, False])
def test_stale_legacy_task_terminates_once_without_loop(
    operation, delivered
):
    _install_stale_legacy_task(operation)

    if delivered:
        assert send(
            "TEAM_RESULT_JSON:\n"
            + json.dumps(
                {
                    "contract_version": 1,
                    "outcome": "PROPOSAL_READY",
                    "operation": operation,
                    "database_target": "runtime",
                    "proposal_emitted": True,
                }
            )
        ) == 0

    # First idle ends the task: no write, never successful.
    assert idle() == 0

    current = record()
    assert current["status"] == "FAILED"
    assert current["failure_reason"] == "LEGACY_MERCHANT_OPERATION_REMOVED"
    assert current["current_run_id"] is None
    assert current["authorized_operations"] == []
    assert current.get("result_received") is False
    assert load_pending_result(PANE) is None

    # Repeated idle events never request another turn.
    for _ in range(3):
        assert idle() == 0

    assert record()["status"] == "FAILED"


def test_stale_legacy_task_with_write_evidence_stays_fail_closed():
    _install_stale_legacy_task("merchant_apply")

    with team_lifecycle.locked_team_state(LEAD) as state:
        state["teammates"][TEAMMATE]["direct_writes"] = {"w": {}}

    assert idle() == 2
    assert record()["status"] == "RUNNING"
    assert record()["direct_writes"] == {"w": {}}


# -------------------------------------------------------------------
# 4-5. Merchant Create: reserved executor on the test database
# -------------------------------------------------------------------


TEST_DB_CONFIGURED = (
    os.environ.get("MERCHANT_TEST_DB_NAME") == "coding_agent_merchant_test"
    and bool(os.environ.get("MERCHANT_TEST_PASSWORD"))
)


def _cleanup_create(merchant_id, operation_key, code=None):
    repo = MerchantRepository(role="test")

    with repo.connection() as conn:
        with conn.transaction():
            # A failed assertion can leave merchant_id unknown; the unique
            # test code still finds the row.
            if merchant_id is None and code is not None:
                row = conn.execute(
                    "SELECT id FROM merchant_ops.merchants WHERE code = %s",
                    (code,),
                ).fetchone()
                merchant_id = str(row["id"]) if row else None

            conn.execute(
                "DELETE FROM merchant_ops.merchant_execution_claims "
                "WHERE operation_key = %s",
                (operation_key,),
            )
            conn.execute(
                "DELETE FROM merchant_ops.merchant_execution_ledger "
                "WHERE operation_key = %s",
                (operation_key,),
            )

            if merchant_id is not None:
                mid = uuid.UUID(merchant_id)
                conn.execute(
                    "DELETE FROM merchant_ops.project_events "
                    "WHERE merchant_id = %s AND entity_type = 'MERCHANT'",
                    (mid,),
                )
                conn.execute(
                    "DELETE FROM merchant_ops.merchants WHERE id = %s",
                    (mid,),
                )


@pytest.mark.skipif(
    not TEST_DB_CONFIGURED,
    reason="Merchant test database not configured",
)
def test_scoped_merchant_create_commits_and_releases():
    code = "E2E" + uuid.uuid4().hex[:12].upper()
    argv = ["merchant", "create", "--code", code, "--name", "CP12H3 E2E"]

    # The user selects the test target; nothing is patched.
    submit(
        f"Create merchant CP12H3 E2E with code {code}",
        argv=argv,
        target="test",
    )
    assert run_state()["operations"] == ["merchant_execute"]
    assert dispatch() is None

    operation_key = None
    merchant_id = None

    try:
        assert execute_request(argv, target="test") == 0

        writes = record()["direct_writes"]
        assert len(writes) == 1
        (write,) = writes.values()
        operation_key = write["operation_key"]

        # Committed evidence is verified right after execution, so the
        # teammate's report can be checked against it.
        assert write["status"] == "VERIFIED"
        assert write["database"] == "test"
        assert record()["direct_completion_receipt"]["writes"]
        assert run_state()[HANDOFF_STATE_KEY]["status"] == HANDOFF_SUCCESS

        # Duplicate execute requests never reach PostgreSQL again.
        assert execute_request(argv, target="test") == 0
        assert len(record()["direct_writes"]) == 1

        assert (
            report(
                "EXECUTE_SUCCESS",
                command="merchant create",
                database_target="test",
            )
            == 0
        )
        assert idle() == 0

        current = record()
        assert current["status"] == "IDLE_REUSABLE"
        assert "direct_writes" not in current

        (receipt,) = current["completed_direct_write_history"]
        (verified,) = receipt["writes"].values()
        merchant_id = verified["merchant_id"]

        assert verified["operation_key"] == operation_key
        assert verified["claim_generation"] == 1
        assert verified["database"] == "test"

        repo = MerchantRepository(role="test")
        with repo.connection(read_only=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT code FROM merchant_ops.merchants WHERE id = %s",
                    (uuid.UUID(merchant_id),),
                )
                row = cur.fetchone()

        assert row is not None
        assert row["code"] == code

        assert idle() == 0
        assert record()["status"] == "IDLE_REUSABLE"
    finally:
        if operation_key is not None:
            _cleanup_create(merchant_id, operation_key, code)
