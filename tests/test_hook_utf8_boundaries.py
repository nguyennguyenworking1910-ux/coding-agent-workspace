"""CP12H.NL2A: hook subprocess byte boundaries on a cp1252 Windows default.

Every test starts a real Python subprocess and writes raw bytes to its
stdin, exactly as Claude Code does, with ``PYTHONIOENCODING=cp1252`` (the
Windows default observed live). Only non-I/O seams are stubbed: the OpenAI
call for the intent gate, and the OS pane-server lookup for team-result
delivery. Hook ``main()`` functions, their stdin reads and their stdout
writes are the real ones.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude.hooks import harness_team_identity, intent_envelope_bridge, intent_gate, runtime_state
from tests.merchant import test_direct_execute_end_to_end as e2e


ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".claude" / "hooks"
PYTHON = sys.executable

REQUEST = (
    "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, "
    "không cần mua sắm"
)
MIXED = "Preview a cinema opening project for Beta Nguyễn Văn Cừ trên database test"
ASCII = "Preview a cinema opening project for Beta Nguyen Van Cu"
TITLE = "Beta Nguyễn Văn Cừ"
MALFORMED = b'{"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "/solve Xem tr\xff\xfe"}'

# Runs one hook entry point in this subprocess. Argument 1 selects it.
BOOT = r"""
import os, runpy, sys
root = os.environ["NL2A_ROOT"]
sys.path.insert(0, root)
kind = sys.argv[1]
if kind == "intent_gate":
    sys.path.insert(0, os.path.join(root, ".claude", "system"))
    import intent_parser as ip
    decision = ip.OpenAIIntentDecision(
        task_class=ip.TaskClass.SMALL, risk_level=ip.RiskLevel.READ_ONLY,
        confidence=0.98,
        score_breakdown=ip.ComplexityBreakdown(
            scope=0, domains=0, dependencies=0, verification=0, ambiguity=0),
        operations=[ip.Operation.DIAGNOSE], domains=[ip.Domain.GENERAL],
        reasons=["stub model: no Merchant routing"], requires_clarification=False)
    class Response:
        status = "completed"
        output_parsed = decision
    class Client:
        class responses:
            @staticmethod
            def parse(**kwargs):
                return Response()
    ip.OpenAI = lambda *a, **k: Client()
    os.environ["OPENAI_API_KEY"] = "stub-not-used"
    runpy.run_path(os.path.join(root, ".claude", "hooks", "intent_gate.py"), run_name="__main__")
elif kind == "team_result_hook":
    from claude.hooks import harness_team_identity
    harness_team_identity._os_pane_server = (
        lambda tmux_pane, lead_pid, *_: 7000 if lead_pid == 4242 else None)
    from claude.hooks import team_result_hook
    raise SystemExit(team_result_hook.main())
else:
    runpy.run_path(os.path.join(root, ".claude", "hooks", kind + ".py"), run_name="__main__")
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    dirs = {
        runtime_state.STATE_DIR_ENV_VAR: tmp_path / "run_state",
        "CLAUDE_TEAM_STATE_DIR": tmp_path / "team",
        "CLAUDE_PENDING_TEAM_RESULT_DIR": tmp_path / "pending",
        "CLAUDE_RUNTIME_DIR": tmp_path / "runtime",
        intent_envelope_bridge.ENVELOPE_DIR_ENV_VAR: tmp_path / "envelopes",
        "CLAUDE_HARNESS_TEAMS_DIR": tmp_path / "harness_teams",
    }
    for name, path in dirs.items():
        monkeypatch.setenv(name, str(path))

    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONUTF8", "PYTHONIOENCODING", "CLAUDE_PREPARSED_INTENT_JSON"}
    }
    environment.update(
        {key: str(path) for key, path in dirs.items()},
        PYTHONIOENCODING="cp1252",
        PYTHONUTF8="0",
        NL2A_ROOT=str(ROOT),
    )
    return environment


def run(kind, data: bytes, environment, **extra):
    completed = subprocess.run(
        [PYTHON, "-c", BOOT, kind],
        input=data,
        capture_output=True,
        env={**environment, **extra},
        cwd=str(ROOT),
        timeout=120,
    )
    return completed


def prompt_bytes(request, session="nl2a-lead"):
    return json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session,
            "prompt": f"/solve {request}",
        },
        ensure_ascii=False,
    ).encode("utf-8")


def envelope_from(stdout: bytes):
    output = json.loads(stdout.decode("utf-8"))
    context = output["hookSpecificOutput"]["additionalContext"]
    block = context.split("INTENT_ENVELOPE_JSON\n```json\n", 1)[1].split("\n```", 1)[0]
    return json.loads(block)


# ----------------------------------------------------------- intent gate


@pytest.mark.parametrize("request_text", (REQUEST, MIXED, ASCII))
def test_intent_gate_preserves_the_exact_request(env, request_text):
    completed = run("intent_gate", prompt_bytes(request_text), env)

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    envelope = envelope_from(completed.stdout)
    assert envelope["raw_request"] == request_text
    assert envelope["operations"] == ["merchant_read"]
    assert envelope["selected_agents"] == ["merchant-manager"]
    assert envelope["requires_confirmation"] is False
    # Routed by the deterministic guardrail, not the (stubbed) model.
    assert any("local guardrail" in reason for reason in envelope["reasons"])

    state = runtime_state.load_state("nl2a-lead")
    assert state["request"] == request_text


def test_intent_gate_blocks_malformed_utf8_without_creating_a_run(env):
    completed = run("intent_gate", MALFORMED, env)

    output = json.loads(completed.stdout.decode("utf-8") or "{}")
    assert output.get("decision") == "block"
    assert runtime_state.load_state("s") is None


def test_envelope_bridge_prints_the_exact_request(env):
    assert run("intent_gate", prompt_bytes(REQUEST), env).returncode == 0
    # Real order (NL2H): Expansion consumes Submit's claim before the bridge.
    expansion = prompt_bytes(REQUEST).replace(
        b'"UserPromptSubmit"', b'"UserPromptExpansion"'
    )
    consumed = run("intent_gate", expansion, env)
    assert consumed.returncode == 0 and consumed.stdout.strip() == b""

    completed = run(
        "intent_envelope_bridge", b"", env, CLAUDE_CODE_SESSION_ID="nl2a-lead"
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    # Text-mode stdout ends lines with CRLF on Windows.
    text = completed.stdout.decode("utf-8").replace("\r\n", "\n")
    envelope = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert envelope["raw_request"] == REQUEST


# ----------------------------------------------------------- policy gate


def test_policy_gate_denies_malformed_utf8(env):
    data = (
        b'{"hook_event_name": "PreToolUse", "session_id": "s", '
        b'"tool_name": "Bash", "tool_input": {"command": "echo \xff"}}'
    )
    completed = run("policy_gate", data, env)

    output = json.loads(completed.stdout.decode("utf-8") or "{}")
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_policy_gate_accepts_a_unicode_merchant_preview_command(env):
    command = (
        # Runtime read: a --test-database read needs a trusted test-target
        # run (CP12H.NL2E P1), which this boundary test does not set up.
        "python .claude/agents/tools/merchant/agent_cli.py project preview "
        f'--request "{REQUEST}"'
    )
    data = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "pane",
            "agent_type": "merchant-manager",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        },
        ensure_ascii=False,
    ).encode("utf-8")

    completed = run("policy_gate", data, env)

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    decision = json.loads(completed.stdout.decode("utf-8") or "{}")
    assert decision.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"


# ------------------------------------------------- team-result delivery


@pytest.fixture
def scoped_lead(env, tmp_path, monkeypatch):
    """A confirmed runtime project-create scope whose title is Unicode."""

    e2e.write_harness_team(tmp_path / "harness_teams", e2e.PANE_TMUX)
    # The in-process dispatch below also runs the spawn backend check
    # (CP12H.NL2C); only its OS pane lookup is replaced, as in e2e.
    monkeypatch.setattr(
        harness_team_identity,
        "_os_teammate_pane",
        lambda pane, lead_pid, *_: (e2e.PANE_SERVER, e2e.PANE_PID_BASE + int(pane[1:])),
    )
    argv = [
        "project", "create",
        "--merchant-id", "6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f",
        "--type", "OPENING_NEW_CINEMA",
        "--variant", "OPENING_NEW_CINEMA_STANDARD",
        "--title", TITLE,
    ]
    e2e.submit(f"Create a cinema opening project for {TITLE}", argv=argv)
    assert runtime_state.load_state(e2e.LEAD)["merchant_scope"]["argv"] == argv
    assert e2e.dispatch() is None
    return argv


def execute_request_bytes(argv):
    message = e2e.MERCHANT_EXECUTE_REQUEST_MARKER + "\n" + json.dumps(
        {
            "contract_version": 1,
            "operation": "merchant_execute",
            "database_target": "runtime",
            "arguments": argv,
        },
        ensure_ascii=False,
    )
    return json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "session_id": e2e.PANE,
            "agent_type": e2e.TEAMMATE,
            "tool_name": "SendMessage",
            "tool_use_id": "execute-request",
            "tool_input": {"recipient": "team-lead", "message": message},
        },
        ensure_ascii=False,
    ).encode("utf-8")


def test_unicode_title_reaches_staging_unchanged(env, scoped_lead):
    completed = run(
        "team_result_hook",
        execute_request_bytes(scoped_lead),
        env,
        TMUX_PANE=e2e.PANE_TMUX,
    )

    state = runtime_state.load_state(e2e.LEAD)
    handoff = state.get(e2e.HANDOFF_STATE_KEY) or {}
    # The arguments matched the Unicode scope exactly, so the attempt
    # reached the target check, which refuses runtime before any spend.
    assert handoff.get("failure_type") == "PREFLIGHT:RUNTIME_EXECUTION_DISABLED", (
        handoff,
        completed.stderr.decode("utf-8", "replace"),
    )
    assert state.get("merchant_runtime_authorization_issued") is not True


def test_team_result_hook_fails_closed_on_malformed_utf8(env, scoped_lead):
    data = execute_request_bytes(scoped_lead).replace(
        TITLE.encode("utf-8"), b"Beta \xff\xfe"
    )
    before = runtime_state.load_state(e2e.LEAD)

    completed = run("team_result_hook", data, env, TMUX_PANE=e2e.PANE_TMUX)

    assert completed.returncode == 2
    after = runtime_state.load_state(e2e.LEAD)
    assert after.get(e2e.HANDOFF_STATE_KEY) == before.get(e2e.HANDOFF_STATE_KEY)
    assert after.get("merchant_runtime_authorization_issued") is not True


# ------------------------------------------------------ other entry points


def test_round_counter_fails_closed_on_malformed_utf8(env):
    data = b'{"hook_event_name": "PostToolBatch", "session_id": "s\xff"}'

    assert run("round_counter", data, env).returncode == 2


def test_cleanup_state_keeps_state_on_malformed_utf8(env):
    assert run("intent_gate", prompt_bytes(REQUEST, session="keep"), env).returncode == 0
    data = b'{"hook_event_name": "SessionEnd", "session_id": "keep\xff"}'

    completed = run("cleanup_state", data, env)

    assert completed.returncode == 0
    assert b"UTF-8" in completed.stderr
    assert runtime_state.load_state("keep") is not None
