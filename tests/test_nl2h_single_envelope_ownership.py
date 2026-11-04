"""CP12H.NL2H: one user prompt -> one authoritative intent envelope and run.

Real subprocesses run the registered entry points in Claude Code's order:
UserPromptSubmit (intent_gate.py), UserPromptExpansion (intent_gate.py), then
the /solve dynamic-context bridge (intent_envelope_bridge.py). psycopg is
replaced in every subprocess so any database access is recorded and refused.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# RED runs point this at a copy of the pre-fix hooks.
HOOKS_DIR = Path(os.environ.get("NL2H_HOOKS_DIR") or PROJECT_ROOT / ".claude" / "hooks")
INTENT_GATE = HOOKS_DIR / "intent_gate.py"
BRIDGE = HOOKS_DIR / "intent_envelope_bridge.py"

ARGV = [
    "project", "create",
    "--merchant-id", "6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f",
    "--type", "OPENING_NEW_CINEMA",
    "--variant", "OPENING_NEW_CINEMA_STANDARD",
    "--title", "Beta Nguyễn Văn Cừ",
    "--project-id", "30fffeaf-e6b5-5119-b078-52c934e1821e",
    "--expected-basis",
    "2f26fb44ec6b5265a2d912bc2fa43619be4d8a8afa0a09cdca9784ed29053ea5",
    "--merchant-code", "NL2_LIVE_BETA",
    "--no-requires-procurement",
]
REQUEST = (
    "Tạo Project mở rạp Beta Nguyễn Văn Cừ cho Merchant Beta Cinemas "
    "(NL2_LIVE_BETA) trên database test, không cần Purchase Requisition."
)
SCOPED_PROMPT = (
    "/solve --confirm --merchant-target test --merchant-scope "
    f"{json.dumps(ARGV, ensure_ascii=False)} {REQUEST}"
)
PREVIEW_REQUEST = (
    "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, "
    "không cần mua sắm"
)

# Runs a hook as __main__ with psycopg connections refused and recorded.
RUNNER = r"""
import os, runpy, sys
import psycopg

def _deny(*args, **kwargs):
    with open(os.environ["NL2H_DB_ATTEMPTS"], "a", encoding="utf-8") as f:
        f.write("connect\n")
    raise RuntimeError("database access during intent processing")

psycopg.connect = _deny
psycopg.Connection.connect = classmethod(lambda cls, *a, **k: _deny())
script = sys.argv[1]
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
"""


def _envelope(request: str, request_id: str, **extra) -> dict:
    scoped = request == REQUEST
    envelope = {
        "request_id": request_id,
        "raw_request": request,
        "task_class": "small_task",
        "risk_level": "external_write" if scoped else "read_only",
        "operations": ["merchant_execute" if scoped else "merchant_read"],
        "selected_agents": ["merchant-manager"],
        "candidate_agents": ["merchant-manager"],
        "limits": {
            "max_members": 1,
            "max_tool_rounds": 1,
            "max_total_tool_calls": 10,
            "max_run_budget_usd": 1.0,
        },
        "requires_clarification": False,
        "requires_confirmation": scoped,
        "reasons": ["nl2h"],
    }
    envelope.update(extra)
    return envelope


@pytest.fixture()
def runtime(tmp_path: Path) -> dict:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("CLAUDE_")
    }
    env.update(
        {
            "CLAUDE_PROJECT_DIR": str(PROJECT_ROOT),
            "CLAUDE_RUNTIME_STATE_DIR": str(tmp_path / "runtime"),
            "CLAUDE_TEAM_STATE_DIR": str(tmp_path / "team"),
            "CLAUDE_INTENT_ENVELOPE_DIR": str(tmp_path / "envelopes"),
            "NL2H_DB_ATTEMPTS": str(tmp_path / "db_attempts.log"),
            # A classification attempt without a pre-parsed envelope fails
            # instead of reaching the network.
            "OPENAI_API_KEY": "",
            "OPENAI_BASE_URL": "http://127.0.0.1:9",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return {"env": env, "dir": tmp_path}


def _run(runtime: dict, script: Path, *, stdin: str = "", **env) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", RUNNER, str(script)],
        input=stdin.encode("utf-8"),
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env={**runtime["env"], **env},
        timeout=120,
    )


def hook(runtime: dict, session: str, event: str, prompt: str, preparsed: dict | None) -> dict:
    extra = (
        {"CLAUDE_PREPARSED_INTENT_JSON": json.dumps(preparsed, ensure_ascii=False)}
        if preparsed is not None
        else {}
    )
    result = _run(
        runtime,
        INTENT_GATE,
        stdin=json.dumps(
            {"hook_event_name": event, "session_id": session, "prompt": prompt},
            ensure_ascii=False,
        ),
        **extra,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    out = result.stdout.decode("utf-8").strip()
    return json.loads(out) if out else {}


def bridge(runtime: dict, session: str) -> tuple[int, dict | None]:
    result = _run(runtime, BRIDGE, CLAUDE_CODE_SESSION_ID=session)
    if result.returncode != 0:
        return result.returncode, None
    text = result.stdout.decode("utf-8").replace("\r\n", "\n")
    body = text.split("INTENT_ENVELOPE_JSON\n```json\n", 1)[1].split("\n```", 1)[0]
    return 0, json.loads(body)


def submit_context_envelope(output: dict) -> dict:
    context = output["hookSpecificOutput"]["additionalContext"]
    body = context.split("```json\n", 1)[1].split("\n```", 1)[0]
    return json.loads(body)


def state_of(runtime: dict, session: str) -> dict | None:
    path = runtime["dir"] / "runtime" / f"{session}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def envelope_of(runtime: dict, session: str) -> dict | None:
    path = runtime["dir"] / "envelopes" / f"{session}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def edit_state(runtime: dict, session: str, mutate) -> None:
    path = runtime["dir"] / "runtime" / f"{session}.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    mutate(state)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def no_db_access(runtime: dict) -> bool:
    return not (runtime["dir"] / "db_attempts.log").exists()


# 1-4, 11: both entry points, one run, no reclassification, no database.
def test_submit_expansion_bridge_share_exactly_one_run(runtime):
    submit = hook(runtime, "s1", "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, "req-submit"))
    # If Expansion classified, it would adopt this different envelope.
    expansion = hook(runtime, "s1", "UserPromptExpansion", SCOPED_PROMPT, _envelope(REQUEST, "req-expansion"))
    code, rendered = bridge(runtime, "s1")

    from_submit = submit_context_envelope(submit)
    state = state_of(runtime, "s1")

    assert expansion == {}
    assert code == 0
    assert from_submit["request_id"] == rendered["request_id"] == "req-submit"
    assert from_submit["run_id"] == rendered["run_id"] == state["run_id"]
    assert rendered["merchant_scope"] == from_submit["merchant_scope"] == state["merchant_scope"]
    assert rendered["merchant_scope"]["argv"] == ARGV
    assert rendered["merchant_scope"]["database_target"] == "test"
    assert rendered["merchant_scope"]["run_id"] == state["run_id"]
    assert rendered["confirmed"] is True and state["confirmed"] is True
    assert state["intent_claim"]["consumed_at"] is not None
    assert no_db_access(runtime)


# 5: identical text submitted twice is two runs; a consumed claim is not reused.
def test_separate_submissions_are_separate_runs_and_claims_are_single_use(runtime):
    hook(runtime, "s2", "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, "req-1"))
    assert hook(runtime, "s2", "UserPromptExpansion", SCOPED_PROMPT, None) == {}
    first_run = state_of(runtime, "s2")["run_id"]

    replay = hook(runtime, "s2", "UserPromptExpansion", SCOPED_PROMPT, None)
    assert replay.get("decision") == "block"

    hook(runtime, "s2", "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, "req-2"))
    assert hook(runtime, "s2", "UserPromptExpansion", SCOPED_PROMPT, None) == {}
    code, rendered = bridge(runtime, "s2")

    second = state_of(runtime, "s2")
    assert code == 0
    assert second["run_id"] != first_run
    assert rendered["run_id"] == second["run_id"]
    assert rendered["request_id"] == "req-2"
    assert rendered["merchant_scope"]["scope_hash"] == second["merchant_scope"]["scope_hash"]
    assert rendered["merchant_scope"]["run_id"] == second["run_id"] != first_run


# 6: concurrent submissions never mix runs.
def test_concurrent_sessions_do_not_overwrite_each_other(runtime):
    sessions = [f"c{index}" for index in range(4)]

    def flow(session: str):
        hook(runtime, session, "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, f"req-{session}"))
        hook(runtime, session, "UserPromptExpansion", SCOPED_PROMPT, None)
        return bridge(runtime, session)

    with ThreadPoolExecutor(max_workers=len(sessions)) as pool:
        results = dict(zip(sessions, pool.map(flow, sessions)))

    run_ids = set()
    for session, (code, rendered) in results.items():
        assert code == 0
        assert rendered["request_id"] == f"req-{session}"
        assert rendered["run_id"] == state_of(runtime, session)["run_id"]
        run_ids.add(rendered["run_id"])
    assert len(run_ids) == len(sessions)


def test_concurrent_submits_in_one_session_never_render_a_mixed_run(runtime):
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(
            lambda rid: hook(runtime, "s6", "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, rid)),
            ["req-a", "req-b"],
        ))

    expansion = hook(runtime, "s6", "UserPromptExpansion", SCOPED_PROMPT, None)
    code, rendered = bridge(runtime, "s6")
    state = state_of(runtime, "s6")

    if expansion == {}:
        assert code == 0
        assert rendered["run_id"] == state["run_id"]
        assert rendered["request_id"] == state["intent_claim"]["request_id"]
    else:
        assert expansion["decision"] == "block"
        assert code != 0


# 7: a stale claim or stale consumption is refused.
def test_stale_claim_is_rejected(runtime):
    hook(runtime, "s7", "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, "req-7"))
    edit_state(runtime, "s7", lambda s: s["intent_claim"].update(issued_at=s["intent_claim"]["issued_at"] - 3600))

    assert hook(runtime, "s7", "UserPromptExpansion", SCOPED_PROMPT, None)["decision"] == "block"
    assert bridge(runtime, "s7")[0] != 0


def test_stale_consumption_is_not_rendered(runtime):
    hook(runtime, "s7b", "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, "req-7b"))
    assert hook(runtime, "s7b", "UserPromptExpansion", SCOPED_PROMPT, None) == {}
    edit_state(runtime, "s7b", lambda s: s["intent_claim"].update(consumed_at=s["intent_claim"]["consumed_at"] - 3600))

    assert bridge(runtime, "s7b")[0] != 0


# 8: an envelope that disagrees with the run (crash between writes, tamper).
@pytest.mark.parametrize("field", ["run_id", "request_id", "merchant_scope"])
def test_mismatched_envelope_is_rejected(runtime, field):
    hook(runtime, "s8", "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, "req-8"))
    path = runtime["dir"] / "envelopes" / "s8.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope[field] = (
        {**envelope["merchant_scope"], "run_id": "other-run"}
        if field == "merchant_scope"
        else "other"
    )
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")

    assert hook(runtime, "s8", "UserPromptExpansion", SCOPED_PROMPT, None)["decision"] == "block"
    assert bridge(runtime, "s8")[0] != 0


def test_expansion_of_a_different_prompt_cannot_consume_the_claim(runtime):
    hook(runtime, "s8b", "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, "req-8b"))
    changed = SCOPED_PROMPT.replace("NL2_LIVE_BETA\"", "OTHER_CODE\"")

    assert hook(runtime, "s8b", "UserPromptExpansion", changed, None)["decision"] == "block"
    assert state_of(runtime, "s8b")["intent_claim"]["consumed_at"] is None


# 9: a failed Submit leaves nothing an Expansion, bridge or dispatch can use.
def test_failed_submit_cannot_be_completed_by_expansion(runtime):
    # No pre-parsed envelope and no reachable parser: Submit fails closed.
    failed = hook(runtime, "s9", "UserPromptSubmit", SCOPED_PROMPT, None)
    assert failed["decision"] == "block"

    expansion = hook(runtime, "s9", "UserPromptExpansion", SCOPED_PROMPT, _envelope(REQUEST, "req-9"))
    assert expansion["decision"] == "block"
    assert state_of(runtime, "s9") is None
    assert envelope_of(runtime, "s9") is None
    assert bridge(runtime, "s9")[0] != 0


def test_failed_resubmit_revokes_the_previous_claim(runtime):
    hook(runtime, "s9b", "UserPromptSubmit", SCOPED_PROMPT, _envelope(REQUEST, "req-9b"))
    # A later identical submission fails before writing a new run.
    assert hook(runtime, "s9b", "UserPromptSubmit", SCOPED_PROMPT, None)["decision"] == "block"

    assert hook(runtime, "s9b", "UserPromptExpansion", SCOPED_PROMPT, None)["decision"] == "block"
    assert bridge(runtime, "s9b")[0] != 0


def test_expansion_without_any_submit_fails_closed(runtime):
    assert hook(runtime, "s9c", "UserPromptExpansion", SCOPED_PROMPT, _envelope(REQUEST, "req-9c"))["decision"] == "block"
    assert state_of(runtime, "s9c") is None


def test_preparsed_envelope_cannot_supply_run_identity_or_scope(runtime):
    forged = _envelope(
        PREVIEW_REQUEST,
        "req-forged",
        run_id="attacker-run",
        merchant_scope={"argv": ARGV, "database_target": "runtime", "run_id": "attacker-run"},
        merchant_database_target="runtime",
        confirmed=True,
    )
    hook(runtime, "s9d", "UserPromptSubmit", f"/solve {PREVIEW_REQUEST}", forged)

    state = state_of(runtime, "s9d")
    envelope = envelope_of(runtime, "s9d")
    assert state["run_id"] != "attacker-run" and envelope["run_id"] == state["run_id"]
    assert "merchant_scope" not in state and "merchant_scope" not in envelope
    assert envelope["confirmed"] is False
    assert envelope["merchant_database_target"] == "test"


# 10: the read-only preview path is unchanged apart from the shared run id.
def test_read_only_preview_flow_is_intact(runtime):
    prompt = f"/solve {PREVIEW_REQUEST}"
    submit = hook(runtime, "s10", "UserPromptSubmit", prompt, _envelope(PREVIEW_REQUEST, "req-10"))
    assert hook(runtime, "s10", "UserPromptExpansion", prompt, None) == {}
    code, rendered = bridge(runtime, "s10")

    state = state_of(runtime, "s10")
    assert code == 0
    assert submit_context_envelope(submit)["run_id"] == rendered["run_id"] == state["run_id"]
    assert rendered["operations"] == ["merchant_read"]
    assert rendered["merchant_database_target"] == "test"
    assert state["merchant_read_target"] == "test"
    assert "merchant_scope" not in state
    assert no_db_access(runtime)
