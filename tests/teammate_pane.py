"""Test helper: what the PostToolUse(Agent) backend hook does after a spawn.

Only the operating-system pane lookup is replaced; the lifecycle check that
records the verified pane is the real one.
"""

from claude.hooks import harness_team_identity
from claude.hooks.team_lifecycle import verify_spawned_teammate_backend

PANE = {"server": 4242, "pane": "%7", "pane_pid": 4343}


def verify_spawn(monkeypatch, session_id, teammate, run_id, pane=PANE):
    monkeypatch.setattr(
        harness_team_identity,
        "teammate_pane_identity",
        lambda *_: dict(pane) if pane else None,
    )
    return verify_spawned_teammate_backend(session_id, teammate, run_id)
