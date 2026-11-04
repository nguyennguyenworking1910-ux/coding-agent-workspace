"""CP12H.NL2C-FIX: verify teammates in psmux panes started by respawn-pane.

Claude Code launches a teammate with ``split-window -- cat`` followed by
``respawn-pane -k -t %N -- <claude --agent-id ... --parent-session-id ...>``.
psmux 3.3.7 then reports an empty ``#{pane_pid}`` for that pane, so the
NL2C lookup found no process and rejected every real teammate
(TEAMMATE_BACKEND_UNVERIFIED). The fallback maps such a pane to the unique
direct child of the lead's server whose OS command line carries the
harness-recorded agent id and the lead's session id.

Only the OS evidence is replaced (process table, pane listing, command
lines); the harness record, lifecycle state, hooks and policy gate are real.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from io import StringIO
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "hooks"))

import policy_gate  # noqa: E402
import teammate_backend_gate  # noqa: E402
from runtime_state import STATE_DIR_ENV_VAR, new_state, save_state  # noqa: E402
from team_lifecycle import (  # noqa: E402
    TEAM_STATE_DIR_ENV_VAR,
    load_team_state,
    reused_teammate_pane_matches,
)

from claude.hooks import harness_team_identity as hti  # noqa: E402

LEAD = "556b81a8-dff7-499c-997e-590fd906ba22"
LEAD_PID = 20
MM = "merchant-manager"
AGENT_ID = "merchant-manager@session-556b81a8"
PANE = "%12"

# Captured at import, before the fixture replaces the seam.
_REAL_COMMAND_LINE = hti._command_line

# Nested psmux servers: outer 100 -> lead's server 200; 300 is another
# session. Lead claude 20 runs in pane root 21 of server 200. The teammate's
# respawn wrapper is 31 (server 200) with its claude child 32.
TABLE = {
    100: (1, "tmux.exe"),
    200: (100, "tmux.exe"),
    300: (1, "tmux.exe"),
    21: (200, "powershell.exe"),
    20: (21, "claude.exe"),
    31: (200, "powershell.exe"),
    32: (31, "claude.exe"),
}


def wrapper(agent=AGENT_ID, lead=LEAD):
    # The form psmux gives a respawned pane's root process (live-observed).
    return (
        'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoLogo '
        f'-Command "cd C:\\ws && claude.exe --agent-id {agent} --agent-name {MM} '
        f'--team-name session-556b81a8 --agent-color blue --parent-session-id {lead} '
        f'--agent-type {MM} --model haiku"'
    )


@pytest.fixture(autouse=True)
def os_view(tmp_path, monkeypatch):
    """Mutable fake OS: process table, pane listing, command lines."""

    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "run"))
    monkeypatch.setenv(TEAM_STATE_DIR_ENV_VAR, str(tmp_path / "team"))
    monkeypatch.setenv("CLAUDE_PENDING_TEAM_RESULT_DIR", str(tmp_path / "pending"))
    monkeypatch.setenv(hti.TEAMS_DIR_ENV_VAR, str(tmp_path / "harness"))

    view = {
        "table": dict(TABLE),
        "listed": {PANE: None},  # None = listed with an empty pane_pid
        "cmd": {31: wrapper(), 32: wrapper(), 21: "powershell.exe"},
        "unreported_calls": 0,
    }

    def pane_pids(pane):
        pid = view["listed"].get(pane)
        return [pid] if isinstance(pid, int) else []

    def unreported(pane):
        view["unreported_calls"] += 1
        return pane in view["listed"] and view["listed"][pane] is None

    monkeypatch.setattr(hti, "_process_table", lambda: view["table"])
    monkeypatch.setattr(hti, "_pane_pids", pane_pids)
    monkeypatch.setattr(hti, "_pane_pid_unreported", unreported)
    monkeypatch.setattr(hti, "_command_line", lambda pid: view["cmd"].get(pid))
    write_harness(tmp_path)
    return view


def write_harness(tmp_path, *, agent_id=AGENT_ID):
    team = tmp_path / "harness" / "session-556b81a8"
    team.mkdir(parents=True, exist_ok=True)
    member = {"name": MM, "agentType": MM, "backendType": "tmux", "tmuxPaneId": PANE}
    if agent_id is not None:
        member["agentId"] = agent_id
    (team / "config.json").write_text(
        json.dumps({
            "name": "session-556b81a8",
            "leadSessionId": LEAD,
            "leadProcess": {"pid": LEAD_PID, "pidSpace": socket.gethostname()},
            "members": [
                {"name": "team-lead", "agentType": "team-lead",
                 "backendType": "in-process", "tmuxPaneId": "leader"},
                member,
            ],
        }),
        encoding="utf-8",
    )


def spawn():
    state = new_state(
        request="Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm",
        task_class="small_task",
        risk_level="read_only",
        selected_agents=[MM],
        limits={"max_members": 1, "max_tool_rounds": 1, "max_total_tool_calls": 10},
        confirmed=False,
        operations=["merchant_read"],
        run_id="run-1",
    )
    assert policy_gate.apply_call(
        state, "Agent", {"subagent_type": MM, "name": MM}, LEAD
    ) is None
    save_state(LEAD, state)


def backend_hook():
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": LEAD,
        "tool_name": "Agent",
        "tool_input": {"subagent_type": MM, "name": MM},
        # The live spawn result of the failed run.
        "tool_response": {"status": "teammate_spawned", "tmux_pane_id": PANE,
                          "is_splitpane": True},
    }
    stdin, stdout, stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin, sys.stdout, sys.stderr = StringIO(json.dumps(payload)), StringIO(), StringIO()
    try:
        assert teammate_backend_gate.main() == 0
        out = sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout, sys.stderr = stdin, stdout, stderr
    return json.loads(out) if out.strip() else None


def record():
    return load_team_state(LEAD)["teammates"][MM]


def lead_side():
    return hti._os_teammate_pane(PANE, LEAD_PID, AGENT_ID, LEAD)


# 1. The live failure: respawned pane with an empty pane_pid ---------------


def test_respawned_teammate_pane_is_verified_at_spawn():
    spawn()

    assert backend_hook() is None
    assert record()["status"] == "RUNNING"
    assert record()["harness_pane"] == {"server": 200, "pane": PANE, "pane_pid": 31}


# 2. Startup: pane process not (yet) observable -----------------------------


def test_pane_process_not_observable_fails_closed_and_is_not_revived(os_view):
    del os_view["table"][31], os_view["table"][32]
    spawn()

    decision = backend_hook()

    assert "TEAMMATE_BACKEND_UNVERIFIED" in decision["reason"]
    assert record()["status"] == "FAILED"

    # The process appearing later does not revive the failed task or allow
    # reuse: the spawn was already rejected and no pane was recorded.
    os_view["table"].update({31: TABLE[31], 32: TABLE[32]})
    assert lead_side() == (200, 31)
    assert record()["status"] == "FAILED"
    assert reused_teammate_pane_matches(LEAD, MM) is False


def test_pane_never_listed_does_not_verify(os_view):
    os_view["listed"].clear()

    assert lead_side() is None


# 3. Wrong server / lead pane / ambiguity -----------------------------------


@pytest.mark.parametrize("server", [100, 300])  # outer nesting server, other session
def test_wrapper_under_another_psmux_server_is_rejected(os_view, server):
    os_view["table"][31] = (server, "powershell.exe")

    assert lead_side() is None


def test_leads_own_pane_is_never_the_teammate_pane(os_view):
    # Even if the lead's pane root carried the teammate's markers.
    del os_view["table"][31], os_view["table"][32]
    os_view["cmd"][21] = wrapper()

    assert lead_side() is None


def test_two_matching_wrappers_are_rejected(os_view):
    os_view["table"][33] = (200, "powershell.exe")
    os_view["cmd"][33] = wrapper()

    assert lead_side() is None


@pytest.mark.parametrize(
    "command",
    [
        wrapper(agent="reviewer@session-556b81a8"),          # other teammate
        wrapper(agent=AGENT_ID + "x"),                       # prefix only
        wrapper(lead="0be1b049-b14a-4220-aa13-df5e1013dbd1"),  # other lead
        wrapper().replace("--agent-id", "--agent-name"),     # wrong flag
        None,                                                # unreadable
    ],
)
def test_command_line_must_name_this_teammate_of_this_lead(os_view, command):
    os_view["cmd"][31] = command

    assert lead_side() is None


def test_reported_pane_pid_never_uses_the_fallback(os_view):
    # psmux reports a pid (here in another server): the strict NL2C check
    # alone decides, even though a matching wrapper exists.
    os_view["table"][51] = (300, "powershell.exe")
    os_view["listed"][PANE] = 51

    assert lead_side() is None
    assert os_view["unreported_calls"] == 0


def test_harness_record_without_agent_id_disables_the_fallback(tmp_path):
    write_harness(tmp_path, agent_id=None)
    spawn()

    assert "TEAMMATE_BACKEND_UNVERIFIED" in backend_hook()["reason"]


# 4. Stale pane reuse -----------------------------------------------------


def test_reuse_requires_the_same_wrapper_process(os_view):
    spawn()
    assert backend_hook() is None
    assert reused_teammate_pane_matches(LEAD, MM) is True

    # The teammate exited and something else was launched with the same
    # markers: new pid, so not the verified pane.
    del os_view["table"][31], os_view["table"][32]
    os_view["table"][34] = (200, "powershell.exe")
    os_view["cmd"][34] = wrapper()

    assert reused_teammate_pane_matches(LEAD, MM) is False


# 5. Teammate-side identity (Direct EXECUTE staging) ------------------------


@pytest.fixture
def in_teammate_pane(os_view, monkeypatch):
    os_view["table"][os.getpid()] = (32, "python.exe")
    monkeypatch.setenv("TMUX_PANE", PANE)
    return os_view


def test_hook_inside_respawned_teammate_pane_is_verified(in_teammate_pane):
    assert hti.verified_teammate_pane(LEAD, MM) == f"200:{PANE}"


def test_hook_in_a_non_matching_pane_is_not_verified(in_teammate_pane):
    in_teammate_pane["cmd"][31] = wrapper(agent="reviewer@session-556b81a8")

    assert hti.verified_teammate_pane(LEAD, MM) is None


def test_hook_pane_in_another_server_than_the_lead_is_not_verified(in_teammate_pane):
    in_teammate_pane["table"][31] = (300, "powershell.exe")

    assert hti.verified_teammate_pane(LEAD, MM) is None


# 6. Failure of the new OS evidence fails closed -----------------------------


def test_command_line_reader_crash_blocks_the_spawn(monkeypatch):
    def broken(_pid):
        raise OSError("access denied")

    monkeypatch.setattr(hti, "_command_line", broken)
    spawn()

    decision = backend_hook()

    assert decision["decision"] == "block"
    assert "backend check failed" in decision["reason"]


# 7. Real command-line reader (this OS) -------------------------------------


def test_command_line_reader_reads_this_process():
    command = _REAL_COMMAND_LINE(os.getpid())

    assert command and "pytest" in command
    assert _REAL_COMMAND_LINE(2**31 - 1) is None  # no such process
