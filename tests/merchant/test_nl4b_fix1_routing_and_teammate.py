"""CP12H.NL4B-FIX1: the two live NL4B failures.

1. "/solve Đánh dấu bước Legal Review của Project Beta Nguyễn Văn Cừ là hoàn
   thành trên database test" was blocked for --confirm. Replaying it through
   the real parser showed the model sometimes classifying it as
   ``operations ['fix'], domains ['data'], selected ['bug-fixer']``. With no
   "merchant" word or Project type, no deterministic guardrail claimed it, so
   the read-only downgrade (merchant-manager only) never applied. Fix: an
   explicit update of a named Project's step is a local Merchant operation.

2. A reused merchant-manager pane kept the definition it was started with,
   from before ``step preview`` existed. Fix: a definition fingerprint is
   recorded at allocation; a stale (or unfingerprinted) idle teammate is shown
   as STALE_DEFINITION and its reuse is refused.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

SYSTEM_DIR = Path(__file__).resolve().parents[2] / ".claude" / "system"
sys.path.insert(0, str(SYSTEM_DIR))

from intent_parser import Domain, IntentParser, Operation  # noqa: E402
from schemas import RiskLevel  # noqa: E402

from tests.merchant.test_merchant_intent_routing import (  # noqa: E402
    CLAUDE_DIR,
    FakeClient,
    _decision,
)
from tests.merchant.test_nl2e_p1_p2_p4 import (  # noqa: E402,F401  (fixtures)
    LEAD,
    intent_gate,
    isolated,
    runtime_state,
)

LIVE_1 = "Đánh dấu bước Legal Review của Project Beta Nguyễn Văn Cừ là hoàn thành trên database test"
LIVE_2 = "Cập nhật bước 1 của Project Beta NL3 Confirmation Test thành đang thực hiện trên database test"
PARAPHRASES = [
    LIVE_1,
    LIVE_2,
    "Hoàn thành bước Legal Review của Project Beta Nguyễn Văn Cừ trên database test",
    "Chuyển bước 2 của dự án Beta Nguyễn Văn Cừ sang đang thực hiện",
    "Mark step 3 of project Beta Nguyễn Văn Cừ as completed on the test database",
    "Mark the Legal Review step of project Beta Nguyễn Văn Cừ as done",
    "Start step 1 of project Beta NL3 Confirmation Test",
]
# The live misclassification, replayed from the real model's output.
BUG_FIXER = _decision(operations=[Operation.FIX], domains=[Domain.DATA],
                      risk_level=RiskLevel.EXTERNAL_WRITE)


def parse(text, decision=BUG_FIXER):
    return IntentParser(CLAUDE_DIR / "agents.json", client=FakeClient(decision)).parse(text)


class Misclassifying:
    """The real parser, fed the model's bug-fixer classification."""

    def parse(self, request):
        return parse(request)


def submit(text):
    return intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD, "prompt": f"/solve {text}"},
        parser_factory=Misclassifying, env={},
    )


# ------------------------------------------------------------------ routing


@pytest.mark.parametrize("text", PARAPHRASES)
def test_step_update_is_merchant_owned_whatever_the_model_says(text):
    envelope = parse(text)

    assert envelope.operations == ["merchant_execute"]
    assert envelope.selected_agents == ["merchant-manager"]


@pytest.mark.parametrize(
    "text,target", [(LIVE_1, "test"), (LIVE_2, "test"), (PARAPHRASES[4], "test"),
                    (PARAPHRASES[6], "runtime")],
)
def test_live_step_updates_run_as_read_only_previews_without_confirm(isolated, text, target):
    output = submit(text)

    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["operations"] == ["merchant_read"] and run["risk_level"] == "read_only"
    assert run["selected_agents"] == ["merchant-manager"]
    assert run["merchant_read_target"] == target
    assert run.get("merchant_scope") is None


def test_negated_step_update_is_a_read():
    assert parse("Đừng đánh dấu bước 2 của Project Beta Nguyễn Văn Cừ là hoàn thành").operations == [
        "merchant_read"
    ]


@pytest.mark.parametrize(
    "text",
    [
        # "Mark the deploy step as done" (no Project) moved in FIX2B: every
        # recognized Step update runs as the read-only preview, which asks.
        "Fix the step update code in project_nl.py",     # code work
        "Tạo merchant Beta Cinemas mã BETA2",           # Merchant create
        "Tạo merchant Beta và project mở rạp Beta Nguyễn Văn Cừ",  # mixed
    ],
)
def test_other_writes_still_need_confirmation(isolated, text):
    assert submit(text).get("decision") == "block"
    assert runtime_state.load_state(LEAD) is None


# ------------------------------------------------------- teammate definition


def test_fingerprint_is_recorded_at_allocation_and_checked():
    from claude.hooks import team_lifecycle as lifecycle

    record = lifecycle.init_teammate_record("merchant-manager", "merchant-manager")

    assert record["definition_sha256"] == lifecycle.agent_definition_fingerprint("merchant-manager")
    assert lifecycle.teammate_definition_current(record) is True
    assert lifecycle.teammate_definition_current(dict(record, definition_sha256="0" * 64)) is False
    assert lifecycle.teammate_definition_current({"role": "merchant-manager"}) is False  # pre-fix
    assert lifecycle.agent_definition_fingerprint("../CLAUDE") is None


def test_snapshot_shows_a_stale_idle_teammate_as_not_reusable(monkeypatch):
    from claude.hooks import team_lifecycle as lifecycle

    current = dict(lifecycle.init_teammate_record("merchant-manager", "merchant-manager"),
                   status="IDLE_REUSABLE")
    for record, expected in ((current, "IDLE_REUSABLE"),
                             (dict(current, definition_sha256=None), "STALE_DEFINITION"),
                             (dict(current, status="RUNNING", definition_sha256=None), "RUNNING")):
        monkeypatch.setattr(intent_gate, "load_team_state",
                            lambda _s, r=record: {"teammates": {"merchant-manager": r}})
        snapshot = intent_gate.build_team_state_snapshot(LEAD, ["merchant-manager"])
        assert snapshot["merchant-manager"]["status"] == expected


@pytest.mark.parametrize("stale", ["changed", "unfingerprinted"])
def test_reuse_of_a_stale_teammate_is_refused_and_nothing_is_reserved(monkeypatch, stale):
    from tests.test_teammate_reuse_dispatch import (
        controlled_state,
        policy_gate,
        run_result_hook,
    )
    from tests.teammate_pane import verify_spawn
    import team_lifecycle  # the hook-path module policy_gate imports
    from runtime_state import STATE_DIR_ENV_VAR, clear_state, save_state

    with tempfile.TemporaryDirectory() as run_dir, tempfile.TemporaryDirectory() as team_dir:
        monkeypatch.setenv(STATE_DIR_ENV_VAR, run_dir)
        monkeypatch.setenv(team_lifecycle.TEAM_STATE_DIR_ENV_VAR, team_dir)
        session = "stale-session"

        first = controlled_state("run-1")
        assert policy_gate.apply_call(first, "Agent", {"subagent_type": "reviewer", "name": "reviewer"}, session) is None
        assert verify_spawn(monkeypatch, session, "reviewer", "run-1") == (True, "VERIFIED")
        save_state(session, first)
        run_result_hook({"hook_event_name": "PostToolUse", "session_id": session,
                         "agent_id": "agent-reviewer-1", "agent_type": "reviewer",
                         "tool_name": "SendMessage",
                         "tool_input": {"recipient": "team-lead", "content": "Done"}})
        clear_state(session)
        run_result_hook({"hook_event_name": "TeammateIdle", "session_id": session,
                         "teammate_name": "reviewer"})
        idle = team_lifecycle.TeammateLifecycleStatus.IDLE_REUSABLE.value
        assert team_lifecycle.get_teammate_status(session, "reviewer") == idle

        if stale == "changed":  # the definition file was edited after spawn
            monkeypatch.setattr(team_lifecycle, "agent_definition_fingerprint", lambda role: "1" * 64)
        else:                   # a teammate spawned before fingerprints existed
            with team_lifecycle.locked_team_state(session) as state:
                state["teammates"]["reviewer"].pop("definition_sha256")

        second = controlled_state("run-2")
        decision = policy_gate.apply_call(
            second, "SendMessage", {"recipient": "reviewer", "content": "Review CLAUDE.md"}, session
        )

        reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
        assert "older definition" in reason
        assert team_lifecycle.get_teammate_status(session, "reviewer") == idle  # not reserved
        assert not second.get("members_used")
