from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"

if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(HOOKS_DIR),
    )

import cleanup_state
import intent_envelope_bridge
import intent_gate
import runtime_state


REQUEST = (
    "Review README.md and report exactly "
    "3 concise observations. Do not modify any file."
)

SESSION_ID = "r7-intent-idempotency"


def _envelope(
    request_id: str = "request-expansion-1",
) -> dict:
    return {
        "request_id": request_id,
        "task_class": "small_task",
        "risk_level": "read_only",
        "limits": {
            "max_members": 1,
            "max_tool_rounds": 1,
            "max_total_tool_calls": 6,
            "max_run_budget_usd": 1.0,
        },
        "selected_agents": [
            "reviewer",
        ],
        "requires_clarification": False,
        "requires_confirmation": False,
        "raw_request": REQUEST,
        "operations": [],
        "reasons": [
            "read-only review",
        ],
    }


class FakeParser:
    def __init__(
        self,
        calls: list[str],
        request_id: str = "request-expansion-1",
    ) -> None:
        self.calls = calls
        self.request_id = request_id

    def parse(
        self,
        request: str,
    ) -> dict:
        self.calls.append(
            request
        )
        return _envelope(
            self.request_id
        )


@pytest.fixture()
def isolated_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    runtime_dir = (
        tmp_path
        / "runtime"
    )

    envelope_dir = (
        tmp_path
        / "intent-envelopes"
    )

    monkeypatch.setenv(
        runtime_state.STATE_DIR_ENV_VAR,
        str(runtime_dir),
    )

    monkeypatch.setenv(
        intent_envelope_bridge.ENVELOPE_DIR_ENV_VAR,
        str(envelope_dir),
    )

    yield

    runtime_state.clear_state(
        SESSION_ID
    )

    intent_envelope_bridge.clear_intent_envelope(
        SESSION_ID
    )


def _payload(
    event: str,
    request: str = REQUEST,
) -> dict:
    return {
        "hook_event_name": event,
        "session_id": SESSION_ID,
        "prompt": (
            f"/solve {request}"
        ),
    }


def test_expansion_classifies_and_persists_once(
    isolated_runtime,
):
    calls: list[str] = []

    output = intent_gate.run(
        _payload(
            "UserPromptExpansion"
        ),
        parser_factory=lambda: FakeParser(
            calls
        ),
        env={},
    )

    assert calls == [
        REQUEST,
    ]

    assert (
        output[
            "hookSpecificOutput"
        ][
            "hookEventName"
        ]
        == "UserPromptExpansion"
    )

    assert (
        "additionalContext"
        not in output[
            "hookSpecificOutput"
        ]
    )

    state = runtime_state.load_state(
        SESSION_ID
    )

    envelope = (
        intent_envelope_bridge
        .load_intent_envelope(
            SESSION_ID
        )
    )

    assert state is not None
    assert envelope is not None

    assert state["request"] == REQUEST
    assert state["run_id"]

    assert (
        envelope["request_id"]
        == "request-expansion-1"
    )

    assert (
        envelope["raw_request"]
        == REQUEST
    )


def test_submit_exact_expansion_request_is_silent_and_does_not_reclassify(
    isolated_runtime,
):
    expansion_calls: list[str] = []

    intent_gate.run(
        _payload(
            "UserPromptExpansion"
        ),
        parser_factory=lambda: FakeParser(
            expansion_calls
        ),
        env={},
    )

    before_state = (
        runtime_state.load_state(
            SESSION_ID
        )
    )

    before_envelope = (
        intent_envelope_bridge
        .load_intent_envelope(
            SESSION_ID
        )
    )

    submit_calls: list[str] = []

    output = intent_gate.run(
        _payload(
            "UserPromptSubmit"
        ),
        parser_factory=lambda: FakeParser(
            submit_calls,
            request_id="request-submit-2",
        ),
        env={},
    )

    after_state = (
        runtime_state.load_state(
            SESSION_ID
        )
    )

    after_envelope = (
        intent_envelope_bridge
        .load_intent_envelope(
            SESSION_ID
        )
    )

    assert output == {}

    assert submit_calls == []

    assert after_state == before_state
    assert after_envelope == before_envelope

    assert (
        after_envelope[
            "request_id"
        ]
        == "request-expansion-1"
    )


def test_submit_does_not_emit_second_intent_envelope_context(
    isolated_runtime,
):
    intent_gate.run(
        _payload(
            "UserPromptExpansion"
        ),
        parser_factory=lambda: FakeParser(
            []
        ),
        env={},
    )

    output = intent_gate.run(
        _payload(
            "UserPromptSubmit"
        ),
        parser_factory=lambda: FakeParser(
            []
        ),
        env={},
    )

    encoded = json.dumps(
        output,
        ensure_ascii=False,
    )

    assert (
        "INTENT_ENVELOPE_JSON"
        not in encoded
    )


def test_stale_envelope_without_matching_run_state_is_not_reused(
    isolated_runtime,
):
    intent_envelope_bridge.save_intent_envelope(
        SESSION_ID,
        _envelope(
            "stale-request-id"
        ),
    )

    calls: list[str] = []

    output = intent_gate.run(
        _payload(
            "UserPromptSubmit"
        ),
        parser_factory=lambda: FakeParser(
            calls,
            request_id="fresh-request-id",
        ),
        env={},
    )

    assert calls == [
        REQUEST,
    ]

    hook_output = output[
        "hookSpecificOutput"
    ]

    assert (
        hook_output[
            "hookEventName"
        ]
        == "UserPromptSubmit"
    )

    assert (
        "INTENT_ENVELOPE_JSON"
        in hook_output[
            "additionalContext"
        ]
    )

    envelope = (
        intent_envelope_bridge
        .load_intent_envelope(
            SESSION_ID
        )
    )

    assert envelope is not None

    assert (
        envelope["request_id"]
        == "fresh-request-id"
    )


def test_stop_clears_run_state_and_intent_envelope(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
):
    intent_gate.run(
        _payload(
            "UserPromptExpansion"
        ),
        parser_factory=lambda: FakeParser(
            []
        ),
        env={},
    )

    assert (
        runtime_state.load_state(
            SESSION_ID
        )
        is not None
    )

    assert (
        intent_envelope_bridge
        .load_intent_envelope(
            SESSION_ID
        )
        is not None
    )

    monkeypatch.setattr(
        cleanup_state,
        "active_teammate_owns_run",
        lambda *_args, **_kwargs: False,
    )

    monkeypatch.setattr(
        sys,
        "stdin",
        type(
            "FakeStdin",
            (),
            {
                "read": lambda self: json.dumps(
                    {
                        "session_id": SESSION_ID,
                        "hook_event_name": "Stop",
                    }
                ),
            },
        )(),
    )

    assert (
        cleanup_state.main()
        == 0
    )

    assert (
        runtime_state.load_state(
            SESSION_ID
        )
        is None
    )

    assert (
        intent_envelope_bridge
        .load_intent_envelope(
            SESSION_ID
        )
        is None
    )


def test_session_end_clears_intent_envelope(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
):
    intent_gate.run(
        _payload(
            "UserPromptExpansion"
        ),
        parser_factory=lambda: FakeParser(
            []
        ),
        env={},
    )

    monkeypatch.setattr(
        cleanup_state,
        "clear_team_state",
        lambda _session_id: True,
    )

    monkeypatch.setattr(
        cleanup_state,
        "load_team_state",
        lambda _session_id: None,
    )

    monkeypatch.setattr(
        cleanup_state,
        "clear_preferences",
        lambda _session_id: True,
    )

    monkeypatch.setattr(
        cleanup_state,
        "load_preferences",
        lambda _session_id: None,
    )

    monkeypatch.setattr(
        sys,
        "stdin",
        type(
            "FakeStdin",
            (),
            {
                "read": lambda self: json.dumps(
                    {
                        "session_id": SESSION_ID,
                        "hook_event_name": "SessionEnd",
                    }
                ),
            },
        )(),
    )

    assert (
        cleanup_state.main()
        == 0
    )

    assert (
        runtime_state.load_state(
            SESSION_ID
        )
        is None
    )

    assert (
        intent_envelope_bridge
        .load_intent_envelope(
            SESSION_ID
        )
        is None
    )
