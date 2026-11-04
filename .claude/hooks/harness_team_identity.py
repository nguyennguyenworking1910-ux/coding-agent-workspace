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

psmux respawned panes: Claude Code starts a teammate with ``split-window --
cat`` and then ``respawn-pane -k -t %N -- <claude ...>``. psmux 3.3.7 then
reports an empty ``#{pane_pid}`` for that pane for its whole life, so the pane
id can no longer be mapped to a process. Only for a pane listed with an empty
pid, the pane process is instead the unique direct child of the server whose
command line (psmux wraps it as ``powershell -NoLogo -Command "<cmd>"``)
carries the harness-recorded ``--agent-id`` and the lead's
``--parent-session-id``. The command line is read from the OS, not from any
hook payload; the same server, ancestry and uniqueness checks still apply.

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

_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9_.-]*")
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def harness_teams_dir() -> Path:
    override = os.environ.get(TEAMS_DIR_ENV_VAR)
    return Path(override) if override else Path.home() / ".claude" / "teams"


def current_tmux_pane() -> str:
    """The tmux pane of this hook process, inherited from its pane."""

    return str(os.environ.get("TMUX_PANE") or "").strip()


def harness_member(
    owner_session_id: Any,
    teammate_name: str,
) -> tuple[str, int, str] | None:
    """Return (tmuxPaneId, lead pid, agentId) the harness recorded, if unique.

    ``agentId`` is ``""`` when the harness did not record a usable one; the
    respawned-pane fallback is then unavailable.
    """

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

    agent_id = member.get("agentId")

    if not isinstance(agent_id, str) or _AGENT_ID.fullmatch(agent_id) is None:
        agent_id = ""

    return pane, lead_pid, agent_id


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


def _command_line(pid: int) -> str | None:
    """The OS command line of ``pid``; None if unreadable."""

    if sys.platform != "win32":
        try:
            raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
        except OSError:
            return None
        return raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32")
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    query = ntdll.NtQueryInformationProcess
    query.restype = ctypes.c_long
    query.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    )
    # PROCESS_QUERY_LIMITED_INFORMATION; ProcessCommandLineInformation (60)
    # returns a UNICODE_STRING followed by its buffer.
    handle = kernel32.OpenProcess(0x1000, False, pid)

    if not handle:
        return None

    try:
        size = wintypes.ULONG(0)
        query(handle, 60, None, 0, ctypes.byref(size))
        if not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if query(handle, 60, buffer, size, ctypes.byref(size)) != 0:
            return None
        length = ctypes.c_ushort.from_buffer(buffer).value
        address = ctypes.c_void_p.from_buffer(
            buffer, ctypes.sizeof(ctypes.c_void_p)
        ).value
        return ctypes.wstring_at(address, length // 2) if address else ""
    finally:
        kernel32.CloseHandle(handle)


def _flag_value(flag: str, value: str) -> "re.Pattern[str]":
    quote = "['\"]?"
    return re.compile(
        rf"(?:^|\s){re.escape(flag)}[ =]{quote}{re.escape(value)}{quote}(?=[\s'\"]|$)"
    )


def _respawned_pane_roots(
    server: int,
    table: dict[int, tuple[int, str]],
    agent_id: str,
    owner_session_id: str,
) -> list[int]:
    """Direct children of ``server`` launched for this teammate of this lead.

    Fallback for a psmux pane whose ``pane_pid`` is no longer reported
    (see the module docstring). Callers require exactly one result.
    """

    if (
        _AGENT_ID.fullmatch(agent_id or "") is None
        or _SESSION_ID.fullmatch(owner_session_id or "") is None
    ):
        return []

    agent = _flag_value("--agent-id", agent_id)
    owner = _flag_value("--parent-session-id", owner_session_id)
    roots = []

    for pid, (parent, _) in table.items():
        if parent != server:
            continue
        command = _command_line(pid) or ""
        if agent.search(command) and owner.search(command):
            roots.append(pid)

    return roots


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


def _pane_pid_unreported(tmux_pane: str) -> bool:
    """True if the server lists ``tmux_pane`` only with an empty pane_pid."""

    try:
        done = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_id}\t#{pane_pid}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    if done.returncode != 0:
        return False

    rows = [line.strip().partition("\t") for line in done.stdout.splitlines()]
    listed = [pid for pane, _, pid in rows if pane == tmux_pane]

    return bool(listed) and not any(listed)


def own_pane_server(
    tmux_pane: str,
    agent_id: str = "",
    owner_session_id: str = "",
) -> tuple[int, dict[int, tuple[int, str]]] | None:
    """(server pid, process table) for this process's own pane.

    Returns the pid of the tmux/psmux server that owns ``tmux_pane`` only if
    exactly one listed pane with that id is an ancestor of this process.
    Also returns the process table snapshot used, so the lead check sees
    the same snapshot.
    """

    table = _process_table()
    ancestors = process_ancestors(os.getpid(), table)
    listed = _pane_pids(tmux_pane)
    matches = [pid for pid in listed if pid in ancestors]

    if not listed and agent_id and _pane_pid_unreported(tmux_pane):
        # psmux respawned pane: this process's pane root is its nearest
        # ancestor whose parent is a server; it must be that server's only
        # child launched for this teammate of this lead.
        root = next(
            (
                pid
                for pid in ancestors[1:]
                if table.get(table[pid][0], (0, ""))[1] in _SERVER_EXECUTABLES
            ),
            None,
        )
        if root is not None and _respawned_pane_roots(
            table[root][0], table, agent_id, owner_session_id
        ) == [root]:
            matches = [root]

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

    server = _os_pane_server(
        actual, recorded[1], recorded[2], str(owner_session_id or "").strip()
    )

    return None if server is None else f"{server}:{actual}"


def _os_pane_server(
    tmux_pane: str,
    lead_pid: int,
    agent_id: str = "",
    owner_session_id: str = "",
) -> int | None:
    """Server pid owning this process's pane, if it also hosts the lead.

    The only operating-system evidence; unit tests replace this seam.
    """

    located = own_pane_server(tmux_pane, agent_id, owner_session_id)

    if located is None:
        return None

    server, table = located

    return server if server == _nearest_server(lead_pid, table) else None


def _nearest_server(pid: int, table: dict[int, tuple[int, str]]) -> int | None:
    # psmux spawns new servers from existing ones, so servers nest in the
    # process tree. A process's server is its NEAREST server ancestor; any
    # outer server is a different psmux session.
    return next(
        (
            ancestor
            for ancestor in process_ancestors(pid, table)[1:]
            if table[ancestor][1] in _SERVER_EXECUTABLES
        ),
        None,
    )


def teammate_pane_identity(
    owner_session_id: Any,
    teammate_name: str,
) -> dict[str, Any] | None:
    """The spawned teammate's own pane, verified from the lead's side.

    Used at dispatch and reuse time, where the checking process is the lead's
    hook, not the teammate. Returns ``{"server", "pane", "pane_pid"}`` only if
    the harness recorded a tmux backend and pane for this teammate, and the
    operating system shows exactly one pane with that id whose process is a
    child of the lead's nearest psmux server and is not the lead's own pane.
    An in-process teammate (``backendType: in-process``) never verifies.
    """

    recorded = harness_member(owner_session_id, teammate_name)

    if recorded is None:
        return None

    located = _os_teammate_pane(
        recorded[0], recorded[1], recorded[2], str(owner_session_id or "").strip()
    )

    if located is None:
        return None

    server, pane_pid = located

    return {"server": server, "pane": recorded[0], "pane_pid": pane_pid}


def _os_teammate_pane(
    tmux_pane: str,
    lead_pid: int,
    agent_id: str = "",
    owner_session_id: str = "",
) -> tuple[int, int] | None:
    """(server pid, pane pid) of a teammate pane in the lead's server.

    The operating-system seam for teammate_pane_identity; tests replace it.
    """

    table = _process_table()
    lead_server = _nearest_server(lead_pid, table)

    if lead_server is None:
        return None

    lead_chain = process_ancestors(lead_pid, table)
    candidates = _pane_pids(tmux_pane)

    if not candidates and agent_id and _pane_pid_unreported(tmux_pane):
        candidates = _respawned_pane_roots(
            lead_server, table, agent_id, owner_session_id
        )

    matches = [
        pid
        for pid in candidates
        if table.get(pid, (0, ""))[0] == lead_server and pid not in lead_chain
    ]

    return (lead_server, matches[0]) if len(matches) == 1 else None
