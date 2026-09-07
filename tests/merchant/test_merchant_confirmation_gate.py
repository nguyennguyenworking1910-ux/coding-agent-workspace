"""Checkpoint 7.2 intent-hook tests for exact Merchant confirmation."""

import sys

from pathlib import Path

import pytest

from claude.agents.tools.merchant.cli_contract import (
    build_confirmation_envelope,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"
SOLVE_PATH = PROJECT_ROOT / ".claude" / "commands" / "solve.md"

sys.path.insert(0, str(HOOKS_DIR))

import intent_gate  # noqa: E402


REQUEST = "Apply the exact Merchant project update proposal"
PROJECT_ID = "00000000-0000-0000-0000-000000000001"


class FakeParser:
    def __init__(self, envelope):
        self.envelope = envelope
        self.requests = []

    def parse(self, request):
        self.requests.append(request)
        return self.envelope


def _envelope(
    request=REQUEST,
    *,
    operation="merchant_apply",
    risk_level="external_write",
    selected_agents=None,
):
    return {
        "request_id": "request-1",
        "raw_request": request,
        "task_class": "small_task",
        "risk_level": risk_level,
        "confidence": 0.99,
        "complexity_score": 1,
        "score_breakdown": {
            "scope": 1,
            "domains": 0,
            "dependencies": 0,
            "verification": 0,
            "ambiguity": 0,
        },
        "domains": ["merchant"],
        "operations": [operation],
        "candidate_agents": ["merchant-manager"],
        "selected_agents": (
            ["merchant-manager"]
            if selected_agents is None
            else selected_agents
        ),
        "limits": {
            "max_members": 1,
            "max_tool_rounds": 1,
            "max_total_tool_calls": 6,
            "max_run_budget_usd": 1.0,
        },
        "reasons": ["Merchant apply"],
        "requires_clarification": False,
        "requires_confirmation": True,
    }


def _confirmation(database="runtime"):
    return build_confirmation_envelope(
        "project update",
        database,
        {
            "project_id": PROJECT_ID,
            "status": "IN_PROGRESS",
            "expected_version": 3,
        },
    )


def _run(monkeypatch, prompt, envelope):
    states = []
    parser = FakeParser(envelope)
    monkeypatch.setattr(
        intent_gate,
        "save_state",
        lambda _session_id, state: states.append(state),
    )
    output = intent_gate.run(
        {
            "prompt": prompt,
            "session_id": "session-1",
        },
        parser_factory=lambda: parser,
        env={},
    )
    return output, states, parser


def test_parse_prompt_removes_confirmation_token_before_classification():
    token = _confirmation().to_token()
    parsed = intent_gate.parse_prompt(
        f"/solve --merchant-confirmation {token} {REQUEST}"
    )

    assert parsed == (
        "solve",
        False,
        token,
        REQUEST,
    )


def test_solve_documents_exact_confirmation_without_runtime_authority():
    content = SOLVE_PATH.read_text(encoding="utf-8")

    assert "For `merchant_apply`, the general `--confirm` flag is never" in (
        content
    )
    assert "exact `--merchant-confirmation` token" in content
    assert "raw proposal payload" in content
    assert "does not by itself\ngrant the Merchant CLI runtime-write" in (
        content
    )
    assert "runtime `--apply` remains fail-closed" in content


def test_merchant_manager_reports_cli_emitted_confirmation_token():
    content = (
        PROJECT_ROOT / ".claude" / "agents" / "merchant-manager.md"
    ).read_text(encoding="utf-8")

    assert "redacted `confirmation` metadata" in content
    assert "a `confirmation_token`" in content
    assert "Preserve the CLI-emitted token exactly" in content
    assert "not runtime permission or a credential" in content


def test_exact_runtime_confirmation_is_redacted_and_persisted(monkeypatch):
    confirmation = _confirmation()
    token = confirmation.to_token()
    output, states, parser = _run(
        monkeypatch,
        f"/solve --merchant-confirmation {token} {REQUEST}",
        _envelope(),
    )

    assert "hookSpecificOutput" in output
    assert parser.requests == [REQUEST]
    assert len(states) == 1
    assert states[0]["confirmed"] is True
    assert states[0]["merchant_confirmation"] == (
        confirmation.to_dict()
    )
    assert token not in repr(output)
    assert token not in repr(states)
    assert '"confirmed": true' in output["hookSpecificOutput"][
        "additionalContext"
    ]


def test_generic_confirm_cannot_authorize_merchant_apply(monkeypatch):
    output, states, _parser = _run(
        monkeypatch,
        f"/solve --confirm {REQUEST}",
        _envelope(),
    )

    assert output["decision"] == "block"
    assert "--confirm is not sufficient" in output["reason"]
    assert "--merchant-confirmation" in output["reason"]
    assert states == []


def test_missing_confirmation_token_blocks_merchant_apply(monkeypatch):
    output, states, _parser = _run(
        monkeypatch,
        f"/solve {REQUEST}",
        _envelope(),
    )

    assert output["decision"] == "block"
    assert "exact confirmation token" in output["reason"]
    assert states == []


def test_empty_confirmation_token_blocks_before_classification(monkeypatch):
    output, states, parser = _run(
        monkeypatch,
        "/solve --merchant-confirmation",
        _envelope(request=""),
    )

    assert output["decision"] == "block"
    assert "needs a request" in output["reason"]
    assert parser.requests == []
    assert states == []


def test_malformed_confirmation_never_echoes_token(monkeypatch):
    token = "malformed-token"
    output, states, _parser = _run(
        monkeypatch,
        f"/solve --merchant-confirmation {token} {REQUEST}",
        _envelope(),
    )

    assert output["decision"] == "block"
    assert "malformed or its binding does not match" in output["reason"]
    assert token not in output["reason"]
    assert states == []


def test_tampered_confirmation_blocks_without_state(monkeypatch):
    token = _confirmation().to_token()
    replacement = "A" if token[-1] != "A" else "B"
    tampered = token[:-1] + replacement
    output, states, _parser = _run(
        monkeypatch,
        f"/solve --merchant-confirmation {tampered} {REQUEST}",
        _envelope(),
    )

    assert output["decision"] == "block"
    assert states == []


def test_test_target_confirmation_cannot_authorize_operational_run(
    monkeypatch,
):
    token = _confirmation(database="test").to_token()
    output, states, _parser = _run(
        monkeypatch,
        f"/solve --merchant-confirmation {token} {REQUEST}",
        _envelope(),
    )

    assert output["decision"] == "block"
    assert "must target runtime" in output["reason"]
    assert states == []


def test_confirmation_cannot_authorize_non_apply_intent(monkeypatch):
    token = _confirmation().to_token()
    read_request = "List Merchant projects"
    output, states, _parser = _run(
        monkeypatch,
        f"/solve --merchant-confirmation {token} {read_request}",
        _envelope(
            request=read_request,
            operation="merchant_read",
            risk_level="read_only",
        ),
    )

    assert output["decision"] == "block"
    assert "only a merchant_apply intent" in output["reason"]
    assert states == []


def test_confirmation_requires_exclusive_merchant_manager(monkeypatch):
    token = _confirmation().to_token()
    output, states, _parser = _run(
        monkeypatch,
        f"/solve --merchant-confirmation {token} {REQUEST}",
        _envelope(selected_agents=["merchant-manager", "coder"]),
    )

    assert output["decision"] == "block"
    assert "exclusive merchant-manager" in output["reason"]
    assert states == []


def test_confirmation_requires_mutating_risk_envelope(monkeypatch):
    token = _confirmation().to_token()
    output, states, _parser = _run(
        monkeypatch,
        f"/solve --merchant-confirmation {token} {REQUEST}",
        _envelope(risk_level="read_only"),
    )

    assert output["decision"] == "block"
    assert "external_write or destructive" in output["reason"]
    assert states == []


@pytest.mark.parametrize(
    "prompt",
    (
        "/solve --confirm --merchant-confirmation token request",
        "/solve --merchant-confirmation token --confirm request",
    ),
)
def test_generic_and_merchant_confirmation_flags_cannot_be_combined(
    monkeypatch,
    prompt,
):
    output, states, parser = _run(
        monkeypatch,
        prompt,
        _envelope(request="request"),
    )

    assert output["decision"] == "block"
    assert "cannot be combined" in output["reason"]
    assert states == []
    assert parser.requests == []


def test_existing_generic_confirmation_still_works_for_non_merchant(
    monkeypatch,
):
    request = "Create the confirmed calendar event"
    envelope = _envelope(
        request=request,
        operation="schedule",
        selected_agents=["scheduler"],
    )
    envelope["domains"] = ["calendar"]
    envelope["candidate_agents"] = ["scheduler"]
    output, states, parser = _run(
        monkeypatch,
        f"/solve --confirm {request}",
        envelope,
    )

    assert "hookSpecificOutput" in output
    assert parser.requests == [request]
    assert states[0]["confirmed"] is True
    assert "merchant_confirmation" not in states[0]


def test_request_secrets_are_blocked_before_classification(monkeypatch):
    secret = "sk-1234567890123456"
    request = f"{REQUEST} using token {secret}"
    confirmation = _confirmation()
    output, states, parser = _run(
        monkeypatch,
        (
            "/solve --merchant-confirmation "
            f"{confirmation.to_token()} {request}"
        ),
        _envelope(request=request),
    )

    assert output["decision"] == "block"
    assert "must not contain credentials or secrets" in output["reason"]
    assert secret not in output["reason"]
    assert parser.requests == []
    assert states == []
