"""Identify a teammate pane from harness-written team configuration.

Hook payloads from tmux teammate panes carry no authenticated identity:
``agent_id`` is empty and ``agent_type``/``session_id`` are self-declared.
The Claude Code harness, however, records each spawned teammate's tmux pane
(``members[].tmuxPaneId``) and the lead's process (``leadProcess.pid`` in the
``pidSpace`` host) in ``~/.claude/teams/<team>/config.json``.

A pane id alone is not an identity: psmux runs one server per session and
every server numbers its panes from ``%1``, so ``%1`` exists once per
session. ``TMUX_PANE`` and ``$TMUX`` are inherited environment strings any
same-user process can set. A pane is therefore verified from the operating
system process tree, not from the environment:

1. ``TMUX_PANE`` equals the harness ``tmuxPaneId`` for this teammate;
2. the pane's own server reports that pane's ``pane_pid`` (session-qualified
   lookup, the returned pane id must match), and that process is an ancestor
   of this hook process;
3. the parent of ``pane_pid`` is a tmux/psmux server process, and that same
   server is the nearest server ancestor of the harness-recorded lead
   process (psmux servers nest, so "any ancestor" would accept an outer
   server's panes).

The verified identity is the server-qualified pane ``"<server_pid>:%N"``.

Threat model: this rejects panes in other psmux sessions or servers, panes
that are not the teammate's, and payloads replayed from elsewhere. It is not
cryptographic: a same-user process that runs inside the teammate's own pane
(for example via ``send-keys``) or that replaces the ``tmux`` executable on
PATH can still impersonate it. merchant-manager cannot do either because its
shell is limited to the allowlisted scripts, and the write APIs still require
the user's one-use scope. When identity cannot be established, the caller
must fail closed.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any


TEAMS_DIR_ENV_VAR = "CLAUDE_HARNESS_TEAMS_DIR"

_TMUX_PANE = re.compile(r"%[0-9]+")

# Executables that own panes. A pane process's parent must be one of them.
_SERVER_EXECUTABLES = frozenset({"tmux", "tmux.exe", "psmux", "psmux.exe"})

_MAX_ANCESTRY = 64


def harness_teams_dir() -> Path:
    override = os.environ.get(TEAMS_DIR_ENV_VAR)
    return Path(override) if override else Path.home() / ".claude" / "teams"


def current_tmux_pane() -> str:
    """The tmux pane of this hook process, inherited from its pane."""

    return str(os.environ.get("TMUX_PANE") or "").strip()


def harness_member(
    owner_session_id: Any,
    teammate_name: str,
) -> tuple[str, int] | None:
    """Return (tmuxPaneId, lead pid) the harness recorded, if unique."""

    owner = str(owner_session_id or "").strip()

    if not owner or not teammate_name:
        return None

    teams = []

    for path in harness_teams_dir().glob("*/config.json"):
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        if isinstance(config, dict) and config.get("leadSessionId") == owner:
            teams.append(config)

    if len(teams) != 1:
        return None

    lead = teams[0].get("leadProcess")

    if not isinstance(lead, dict):
        return None

    lead_pid = lead.get("pid")

    if (
        isinstance(lead_pid, bool)
        or not isinstance(lead_pid, int)
        or lead_pid <= 0
        or str(lead.get("pidSpace") or "").lower()
        != socket.gethostname().lower()
    ):
        return None

    members = [
        member
        for member in teams[0].get("members") or []
        if isinstance(member, dict) and member.get("name") == teammate_name
    ]

    if len(members) != 1:
        return None

    member = members[0]
    pane = member.get("tmuxPaneId")

    if (
        member.get("agentType") != teammate_name
        or member.get("backendType") != "tmux"
        or not isinstance(pane, str)
        or _TMUX_PANE.fullmatch(pane) is None
    ):
        return None

    return pane, lead_pid


def _process_table() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, lowercase executable name); empty if unknown."""

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)

        if snapshot in (None, wintypes.HANDLE(-1).value):
            return {}

        table = {}
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)

        try:
            more = kernel32.Process32First(snapshot, ctypes.byref(entry))
            while more:
                table[int(entry.th32ProcessID)] = (
                    int(entry.th32ParentProcessID),
                    entry.szExeFile.decode("utf-8", "replace").lower(),
                )
                more = kernel32.Process32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)

        return table

    table = {}

    for proc in Path("/proc").glob("[0-9]*"):
        try:
            stat = (proc / "stat").read_text()
            name = stat[stat.index("(") + 1 : stat.rindex(")")]
            parent = int(stat[stat.rindex(")") + 2 :].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        table[int(proc.name)] = (parent, name.lower())

    return table


def process_ancestors(pid: int, table: dict[int, tuple[int, str]]) -> list[int]:
    """``pid`` and its ancestors, nearest first."""

    chain = []

    while pid in table and pid not in chain and len(chain) < _MAX_ANCESTRY:
        chain.append(pid)
        pid = table[pid][0]

    return chain


def _pane_pids(tmux_pane: str) -> list[int]:
    """pane_pid of every listed pane whose id equals ``tmux_pane``.

    psmux resolves a bare ``-t %N`` against its default session rather than
    the caller's ``$TMUX``, so panes are listed across all sessions and the
    caller decides by process ancestry which one it actually runs in.
    """

    try:
        done = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_id}\t#{pane_pid}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    if done.returncode != 0:
        return []

    pids = []

    for line in done.stdout.splitlines():
        pane, _, pid = line.strip().partition("\t")
        if pane == tmux_pane and pid.isdigit():
            pids.append(int(pid))

    return pids


def own_pane_server(
    tmux_pane: str,
) -> tuple[int, dict[int, tuple[int, str]]] | None:
    """(server pid, process table) for this process's own pane.

    Returns the pid of the tmux/psmux server that owns ``tmux_pane`` only if
    exactly one listed pane with that id is an ancestor of this process.
    Also returns the process table snapshot used, so the lead check sees
    the same snapshot.
    """

    table = _process_table()
    ancestors = process_ancestors(os.getpid(), table)
    matches = [pid for pid in _pane_pids(tmux_pane) if pid in ancestors]

    if len(matches) != 1:
        return None

    pane_pid = matches[0]

    server = table[pane_pid][0]

    if table.get(server, (0, ""))[1] not in _SERVER_EXECUTABLES:
        return None

    return server, table


def verified_teammate_pane(
    owner_session_id: Any,
    teammate_name: str,
) -> str | None:
    """Return ``"<server_pid>:%N"`` only if this process is in the teammate's pane.

    The pane must be the harness-recorded pane, in the same tmux/psmux
    server as the harness-recorded lead process.
    """

    recorded = harness_member(owner_session_id, teammate_name)
    actual = current_tmux_pane()

    if recorded is None or actual != recorded[0]:
        return None

    server = _os_pane_server(actual, recorded[1])

    return None if server is None else f"{server}:{actual}"


def _os_pane_server(tmux_pane: str, lead_pid: int) -> int | None:
    """Server pid owning this process's pane, if it also hosts the lead.

    The only operating-system evidence; unit tests replace this seam.
    """

    located = own_pane_server(tmux_pane)

    if located is None:
        return None

    server, table = located

    # psmux spawns new servers from existing ones, so servers nest in the
    # process tree. The lead's server is its NEAREST server ancestor; any
    # outer server is a different psmux session.
    lead_server = next(
        (
            pid
            for pid in process_ancestors(lead_pid, table)[1:]
            if table[pid][1] in _SERVER_EXECUTABLES
        ),
        None,
    )

    return server if server == lead_server else None
