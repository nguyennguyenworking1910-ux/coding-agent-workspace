"""CP12H.NL2C: /solve accepts only teammates running in their own psmux pane.

The PostToolUse(Agent) hook (teammate_backend_gate) verifies each spawn from
the harness team config (backendType tmux + tmuxPaneId) and the OS process
table (the pane is a child of the lead's nearest psmux server and is not the
lead's own pane). Reuse via SendMessage re-checks that the same pane process
still holds that pane id. Only the OS lookups are replaced here; the harness
record, lifecycle state, hooks and policy gate are real.
"""

from __future__ import annotations

import json
import socket
import sys
from io import StringIO
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "hooks"))

import policy_gate  # noqa: E402
import teammate_backend_gate  # noqa: E402
import team_result_hook  # noqa: E402
from runtime_state import (  # noqa: E402
    STATE_DIR_ENV_VAR,
    clear_state,
    new_state,
    save_state,
)
from team_lifecycle import (  # noqa: E402
    TEAM_STATE_DIR_ENV_VAR,
    allocate_teammate,
    load_team_state,
)

from claude.hooks import harness_team_identity  # noqa: E402

LEAD = "nl2c-lead"
LEAD_PID = 4242
SERVER = 7000
PANE = "%7"
PANE_PID = 7107
MM = "merchant-manager"
REVIEWER = "reviewer"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "run"))
    monkeypatch.setenv(TEAM_STATE_DIR_ENV_VAR, str(tmp_path / "team"))
    monkeypatch.setenv("CLAUDE_PENDING_TEAM_RESULT_DIR", str(tmp_path / "pending"))
    monkeypatch.setenv(harness_team_identity.TEAMS_DIR_ENV_VAR, str(tmp_path / "harness"))
    # The pane this lead's psmux server shows; tests change it per case.
    panes = {PANE: PANE_PID}
    monkeypatch.setattr(
        harness_team_identity,
        "_os_teammate_pane",
        lambda pane, lead_pid, *_: (
            (SERVER, panes[pane]) if lead_pid == LEAD_PID and pane in panes else None
        ),
    )
    return panes


def harness(tmp_path, name, *, backend="tmux", pane=PANE, lead_session=LEAD):
    team = tmp_path / "harness" / "session-nl2c"
    team.mkdir(parents=True, exist_ok=True)
    (team / "config.json").write_text(
        json.dumps(
            {
                "leadSessionId": lead_session,
                "leadProcess": {"pid": LEAD_PID, "pidSpace": socket.gethostname()},
                "members": [
                    {"name": "team-lead", "agentType": "team-lead",
                     "backendType": "in-process", "tmuxPaneId": "leader"},
                    {"name": name, "agentType": name,
                     "backendType": backend, "tmuxPaneId": pane},
                ],
            }
        ),
        encoding="utf-8",
    )


def run_state(name, run_id="run-1"):
    return new_state(
        request="Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test",
        task_class="small_task",
        risk_level="read_only",
        selected_agents=[name],
        limits={"max_members": 1, "max_tool_rounds": 2, "max_total_tool_calls": 20},
        confirmed=False,
        operations=["merchant_read"] if name == MM else None,
        run_id=run_id,
    )


def spawn(name, run_id="run-1"):
    """Lead dispatch through the real policy gate; returns the run state."""

    state = run_state(name, run_id)
    assert policy_gate.apply_call(
        state, "Agent", {"subagent_type": name, "name": name}, LEAD
    ) is None
    save_state(LEAD, state)
    return state


def run(module, payload):
    stdin, stdout, stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin, sys.stdout, sys.stderr = StringIO(json.dumps(payload)), StringIO(), StringIO()
    try:
        code = module.main()
        return code, sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout, sys.stderr = stdin, stdout, stderr


def backend_hook(name, response=None):
    code, out = run(
        teammate_backend_gate,
        {
            "hook_event_name": "PostToolUse",
            "session_id": LEAD,
            "tool_name": "Agent",
            "tool_input": {"subagent_type": name, "name": name},
            "tool_response": response
            if response is not None
            else {"status": "teammate_spawned", "tmux_pane_id": PANE, "is_splitpane": True},
        },
    )
    assert code == 0
    return json.loads(out) if out.strip() else None


def record(name):
    return load_team_state(LEAD)["teammates"][name]


def reuse(name, run_id):
    state = run_state(name, run_id)
    return policy_gate.apply_call(
        state, "SendMessage", {"to": name, "message": "New read-only work."}, LEAD
    )


def deliver_and_idle(name):
    assert run(team_result_hook, {
        "hook_event_name": "PostToolUse", "session_id": LEAD,
        "agent_id": f"agent-{name}", "agent_type": name, "tool_name": "SendMessage",
        "tool_input": {"recipient": "team-lead", "content": "Complete review"},
    })[0] == 0
    assert clear_state(LEAD)
    assert run(team_result_hook, {
        "hook_event_name": "TeammateIdle", "session_id": LEAD, "teammate_name": name,
    }) == (0, "")


# 1. Valid separate pane --------------------------------------------------


def test_teammate_in_its_own_verified_pane_is_accepted(tmp_path):
    harness(tmp_path, MM)
    spawn(MM)

    assert backend_hook(MM) is None
    assert record(MM)["status"] == "RUNNING"
    assert record(MM)["harness_pane"] == {"server": SERVER, "pane": PANE, "pane_pid": PANE_PID}
    assert record(MM)["authorized_operations"] == ["merchant_read"]


# 2. In-process teammate --------------------------------------------------


@pytest.mark.parametrize(
    "backend,pane,response,reason",
    [
        ("in-process", "in-process",
         {"status": "teammate_spawned", "is_splitpane": False}, "NOT_A_SPLIT_PANE"),
        ("in-process", "in-process", {"status": "teammate_spawned"},
         "TEAMMATE_BACKEND_UNVERIFIED"),
    ],
)
def test_in_process_teammate_is_rejected_and_cannot_deliver(
    tmp_path, backend, pane, response, reason
):
    harness(tmp_path, MM, backend=backend, pane=pane)
    spawn(MM)

    block = backend_hook(MM, response)

    assert block["decision"] == "block"
    assert reason in block["reason"] and "TaskStop" in block["reason"]
    assert record(MM)["status"] == "FAILED"
    assert record(MM)["failure_reason"] == reason
    assert record(MM)["current_task_id"] is None
    assert record(MM)["authorized_operations"] == []
    assert "harness_pane" not in record(MM)
    # Its idle events end quietly: no resend loop, no settlement.
    for _ in range(3):
        assert run(team_result_hook, {
            "hook_event_name": "TeammateIdle", "session_id": "pane-session",
            "teammate_name": MM,
        }) == (0, "")
    assert record(MM)["status"] == "FAILED"
    # And it is never reused.
    assert reuse(MM, "run-2") is not None


# 3. Forged pane metadata -------------------------------------------------


def test_forged_tmux_pane_env_and_reported_pane_do_not_verify(tmp_path, isolated, monkeypatch):
    harness(tmp_path, MM)
    spawn(MM)
    isolated.clear()  # the OS shows no such pane under the lead's server
    monkeypatch.setenv("TMUX_PANE", PANE)  # environment is never evidence

    block = backend_hook(MM)

    assert "TEAMMATE_BACKEND_UNVERIFIED" in block["reason"]
    assert record(MM)["status"] == "FAILED"


def test_tool_response_pane_must_match_the_harness_record(tmp_path):
    harness(tmp_path, MM)
    spawn(MM)

    block = backend_hook(
        MM, {"status": "teammate_spawned", "tmux_pane_id": "%9", "is_splitpane": True}
    )

    assert "PANE_MISMATCH" in block["reason"]
    assert record(MM)["status"] == "FAILED"


def test_harness_record_of_another_lead_does_not_verify(tmp_path):
    harness(tmp_path, MM, lead_session="someone-else")
    spawn(MM)

    assert "TEAMMATE_BACKEND_UNVERIFIED" in backend_hook(MM)["reason"]


# 4. Wrong psmux server (real OS logic, fake process table) ----------------


def _os(monkeypatch, table, panes):
    monkeypatch.setattr(harness_team_identity, "_process_table", lambda: table)
    monkeypatch.setattr(
        harness_team_identity, "_pane_pids",
        lambda pane: [pid for p, pid in panes if p == pane],
    )
    # Undo the fixture stub: exercise the real lookup.
    monkeypatch.setattr(harness_team_identity, "_os_teammate_pane", _REAL_OS_TEAMMATE_PANE)


# Captured at import, before any fixture replaces it.
_REAL_OS_TEAMMATE_PANE = harness_team_identity._os_teammate_pane


# Nested psmux servers: outer 100 -> inner 200 (the lead's). Lead claude 20
# runs in pane process 21 of server 200. Teammate pane processes: 31 (server
# 200, correct), 41 (outer server 100), 51 (server 300, another session).
TABLE = {
    100: (1, "tmux.exe"),
    200: (100, "tmux.exe"),
    300: (1, "psmux.exe"),
    21: (200, "pwsh.exe"),
    20: (21, "claude.exe"),
    31: (200, "pwsh.exe"),
    41: (100, "pwsh.exe"),
    51: (300, "pwsh.exe"),
}


@pytest.mark.parametrize(
    "panes,expected",
    [
        ([("%2", 31)], (200, 31)),          # own pane in the lead's server
        ([("%2", 41)], None),               # outer (nesting) server
        ([("%2", 51)], None),               # another psmux server
        ([("%2", 31), ("%2", 51)], (200, 31)),  # same id in two servers
        ([("%2", 31), ("%2", 32)], None),   # ambiguous within the server
    ],
)
def test_pane_must_belong_to_the_leads_nearest_server(monkeypatch, panes, expected):
    table = {**TABLE, 32: (200, "pwsh.exe")}
    _os(monkeypatch, table, panes)

    assert harness_team_identity._os_teammate_pane("%2", 20) == expected


def test_the_leads_own_pane_is_not_a_teammate_pane(monkeypatch):
    _os(monkeypatch, TABLE, [("%1", 21)])

    assert harness_team_identity._os_teammate_pane("%1", 20) is None


def test_lead_outside_any_psmux_server_never_verifies(monkeypatch):
    table = {20: (5, "explorer.exe"), 31: (200, "pwsh.exe"), 200: (1, "tmux.exe")}
    _os(monkeypatch, table, [("%2", 31)])

    assert harness_team_identity._os_teammate_pane("%2", 20) is None


# 5. Stale pane reuse -----------------------------------------------------


@pytest.mark.parametrize("pane_now", [None, 9999])  # closed, or id recycled
def test_stale_pane_is_not_reused(tmp_path, isolated, pane_now):
    harness(tmp_path, REVIEWER)
    spawn(REVIEWER)
    assert backend_hook(REVIEWER) is None
    deliver_and_idle(REVIEWER)
    assert record(REVIEWER)["status"] == "IDLE_REUSABLE"

    isolated.clear()
    if pane_now is not None:
        isolated[PANE] = pane_now

    decision = reuse(REVIEWER, "run-2")

    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "psmux pane" in decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert record(REVIEWER)["status"] == "IDLE_REUSABLE"


def test_teammate_never_verified_at_spawn_is_not_reused(tmp_path):
    harness(tmp_path, REVIEWER)
    spawn(REVIEWER)  # the backend hook never ran
    deliver_and_idle(REVIEWER)

    assert reuse(REVIEWER, "run-2") is not None
    assert record(REVIEWER)["status"] == "IDLE_REUSABLE"


# 6. Dispatch without trusted run binding ---------------------------------


def test_spawn_without_run_binding_is_rejected(tmp_path):
    harness(tmp_path, MM)
    save_state(LEAD, run_state(MM))
    # The gate was bypassed: an allocation exists but was never bound.
    allocate_teammate(LEAD, MM, MM)

    block = backend_hook(MM)

    assert "UNBOUND_DISPATCH" in block["reason"]
    assert record(MM)["status"] == "FAILED"
    assert "harness_pane" not in record(MM)


def test_spawn_with_no_lifecycle_record_is_rejected(tmp_path):
    harness(tmp_path, MM)
    save_state(LEAD, run_state(MM))

    assert "UNTRACKED_TEAMMATE" in backend_hook(MM)["reason"]


def test_agent_calls_outside_a_solve_run_are_ignored(tmp_path):
    harness(tmp_path, MM, backend="in-process", pane="in-process")

    assert backend_hook(MM) is None
    assert load_team_state(LEAD) is None


def test_backend_check_error_fails_closed(tmp_path, monkeypatch):
    harness(tmp_path, MM)
    spawn(MM)

    def broken(*_args, **_kwargs):
        raise OSError("state unavailable")

    monkeypatch.setattr(teammate_backend_gate, "verify_spawned_teammate_backend", broken)
    block = backend_hook(MM)

    assert block["decision"] == "block"
    assert "OSError" in block["reason"]


# 7. Return to IDLE_REUSABLE and verified reuse ---------------------------


def test_verified_teammate_returns_to_idle_and_is_reused_in_the_same_pane(tmp_path):
    harness(tmp_path, REVIEWER)
    spawn(REVIEWER)
    assert backend_hook(REVIEWER) is None

    deliver_and_idle(REVIEWER)

    after = record(REVIEWER)
    assert after["status"] == "IDLE_REUSABLE"
    assert after["harness_pane"]["pane_pid"] == PANE_PID
    # A second idle event is quiet and changes nothing.
    assert run(team_result_hook, {
        "hook_event_name": "TeammateIdle", "session_id": LEAD, "teammate_name": REVIEWER,
    }) == (0, "")
    assert record(REVIEWER)["status"] == "IDLE_REUSABLE"

    assert reuse(REVIEWER, "run-2") is None
    assert record(REVIEWER)["status"] == "RUNNING"
    assert record(REVIEWER)["current_run_id"] == "run-2"
