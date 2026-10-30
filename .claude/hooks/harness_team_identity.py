"""Identify a teammate pane from harness-written team configuration.

Hook payloads from tmux teammate panes carry no authenticated identity:
``agent_id`` is empty and ``agent_type``/``session_id`` are self-declared.
The Claude Code harness, however, records each spawned teammate's tmux pane
(``members[].tmuxPaneId``) in ``~/.claude/teams/<team>/config.json``, and
tmux sets ``TMUX_PANE`` for every process in a pane, including the hook
subprocess the pane's Claude process spawns.

A pane is verified as a teammate only when its inherited ``TMUX_PANE``
equals the pane the harness recorded for that teammate in the owner's team.

Threat model: this distinguishes a teammate's own pane from other panes and
from payloads replayed elsewhere. It is not cryptographic. A same-user
process that deliberately sets ``TMUX_PANE`` while invoking a hook script by
hand can still impersonate the pane; merchant-manager cannot do so because
its shell is limited to the allowlisted scripts, and the write APIs still
require the user's one-use scope. When identity cannot be established, the
caller must fail closed.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


TEAMS_DIR_ENV_VAR = "CLAUDE_HARNESS_TEAMS_DIR"

_TMUX_PANE = re.compile(r"%[0-9]+")


def harness_teams_dir() -> Path:
    override = os.environ.get(TEAMS_DIR_ENV_VAR)
    return Path(override) if override else Path.home() / ".claude" / "teams"


def current_tmux_pane() -> str:
    """The tmux pane of this hook process, inherited from its pane."""

    return str(os.environ.get("TMUX_PANE") or "").strip()


def harness_member_pane(owner_session_id: Any, teammate_name: str) -> str | None:
    """Return the tmux pane the harness recorded for this teammate, if unique."""

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

    return pane


def verified_teammate_pane(owner_session_id: Any, teammate_name: str) -> str | None:
    """Return this process's tmux pane only if it is the teammate's pane."""

    expected = harness_member_pane(owner_session_id, teammate_name)
    actual = current_tmux_pane()

    if expected is None or actual != expected:
        return None

    return expected
