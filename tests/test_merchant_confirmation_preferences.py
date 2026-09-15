"""Fail-closed persistence tests for local Merchant confirmation mode."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from io import StringIO
from pathlib import Path

import pytest

from claude.agents.tools.merchant.cli_contract import build_proposal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"

sys.path.insert(0, str(HOOKS_DIR))

import intent_gate  # noqa: E402
import merchant_confirmation_preferences as preferences  # noqa: E402


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_PROJECT_ID = "22222222-2222-4222-8222-222222222222"
STEP_ID = "33333333-3333-4333-8333-333333333333"
LOCAL_AUTO_ENV = {
    preferences.LOCAL_AUTO_ENV_VAR: "1",
    preferences.MERCHANT_HOST_ENV_VAR: "127.0.0.1",
    preferences.INTERACTIVE_ENV_VAR: "1",
}


def _proposal(command, payload):
    return {
        "success": True,
        **build_proposal(command, "runtime", payload).to_dict(),
    }


def _enable_and_capture(monkeypatch, tmp_path, command, payload):
    session_id = "session-1"
    monkeypatch.setenv(
        preferences.PREFERENCES_DIR_ENV_VAR,
        str(tmp_path),
    )
    message = preferences._enable_local_auto(
        session_id,
        LOCAL_AUTO_ENV,
    )
    assert preferences.MODE_LOCAL_AUTO in message

    outcome = preferences.capture_proposal_receipt(
        session_id,
        _proposal(command, payload),
    )
    assert outcome.accepted

    return session_id


@contextmanager
def _fail_when_persisting(document):
    """Model an atomic save failure after a caller mutates memory."""
    yield document
    raise PermissionError("simulated Windows replace failure")


def test_manual_toggle_handles_persistence_failure(monkeypatch):
    monkeypatch.setattr(
        preferences,
        "locked_preferences",
        lambda *args, **kwargs: _fail_when_persisting(
            preferences.new_preferences("session-1")
        ),
    )

    message = preferences._enable_manual("session-1")

    assert "could not be persisted" in message
    assert "nothing was dispatched" in message
    assert "simulated" not in message


def test_local_auto_toggle_handles_persistence_failure(monkeypatch):
    monkeypatch.setattr(
        preferences,
        "check_local_auto_prerequisites",
        lambda *args, **kwargs: preferences.PrerequisiteResult(True),
    )
    monkeypatch.setattr(
        preferences,
        "locked_preferences",
        lambda *args, **kwargs: _fail_when_persisting(
            preferences.new_preferences("session-1")
        ),
    )

    message = preferences._enable_local_auto("session-1", {})

    assert "could not be persisted" in message
    assert "remains in MANUAL mode" in message
    assert "nothing was dispatched" in message


def test_capture_receipt_handles_persistence_failure(monkeypatch):
    confirmation = {"confirmation_hash": "a" * 64}
    document = preferences.new_preferences("session-1")
    document["mode"] = preferences.MODE_LOCAL_AUTO

    monkeypatch.setattr(
        preferences,
        "validate_proposal_result",
        lambda result: confirmation,
    )
    monkeypatch.setattr(
        preferences,
        "_proposal_entity_binding",
        lambda result, validated: {
            "field": "project_id",
            "sha256": "c" * 64,
        },
    )
    monkeypatch.setattr(
        preferences,
        "locked_preferences",
        lambda *args, **kwargs: _fail_when_persisting(document),
    )

    outcome = preferences.capture_proposal_receipt(
        "session-1",
        {"success": True},
    )

    assert not outcome.accepted
    assert "could not be persisted" in outcome.reason


@pytest.mark.parametrize(
    ("operation", "receipt_state"),
    [
        (preferences.reserve_receipt, preferences.RECEIPT_AVAILABLE),
        (preferences.consume_receipt, preferences.RECEIPT_RESERVED),
    ],
)
def test_receipt_transition_handles_persistence_failure(
    monkeypatch,
    operation,
    receipt_state,
):
    confirmation = {"confirmation_hash": "b" * 64}
    document = preferences.new_preferences("session-1")
    document["mode"] = preferences.MODE_LOCAL_AUTO
    document["receipt"] = {
        "state": receipt_state,
        "confirmation": confirmation,
    }

    monkeypatch.setattr(
        preferences,
        "validate_confirmation_metadata",
        lambda value: value,
    )
    monkeypatch.setattr(
        preferences,
        "_validate_entity_binding",
        lambda value, command: {
            "field": "project_id",
            "sha256": "c" * 64,
        },
    )
    confirmation["command"] = "project update"
    monkeypatch.setattr(
        preferences,
        "locked_preferences",
        lambda *args, **kwargs: _fail_when_persisting(document),
    )

    outcome = operation("session-1", "b" * 64)

    assert not outcome.accepted
    assert "could not be persisted" in outcome.reason


def test_clear_preferences_deletes_document_under_lock(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(preferences.PREFERENCES_DIR_ENV_VAR, str(tmp_path))
    document_path = preferences.preferences_path("session-1")
    document_path.write_text("{}", encoding="utf-8")

    assert preferences.clear_preferences("session-1")
    assert not document_path.exists()


def test_clear_preferences_leaves_document_when_lock_fails(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(preferences.PREFERENCES_DIR_ENV_VAR, str(tmp_path))
    document_path = preferences.preferences_path("session-1")
    document_path.write_text("{}", encoding="utf-8")

    def fail_lock(*args, **kwargs):
        raise OSError("simulated lock failure")

    monkeypatch.setattr(preferences, "FileLock", fail_lock)

    assert not preferences.clear_preferences("session-1")
    assert document_path.exists()


def test_intent_hook_blocks_when_internal_persistence_crashes(
    monkeypatch,
    capsys,
):
    def fail_run(payload):
        raise PermissionError("secret local path")

    monkeypatch.setattr(intent_gate, "run", fail_run)
    monkeypatch.setattr(
        sys,
        "stdin",
        StringIO(
            json.dumps(
                {
                    "session_id": "session-1",
                    "prompt": "/solve test request",
                }
            )
        ),
    )

    assert intent_gate.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "block"
    assert "authorization state could not be persisted safely" in output[
        "reason"
    ]
    assert "secret local path" not in output["reason"]


@pytest.mark.parametrize(
    ("command", "payload", "request_text"),
    [
        (
            "project create",
            {
                "project_id": PROJECT_ID,
                "merchant_id": OTHER_PROJECT_ID,
                "project_type": "MEDIA_TOP_UP",
            },
            (
                "Apply project create with project_id "
                f"{PROJECT_ID} and expected_version null"
            ),
        ),
        (
            "project update",
            {
                "project_id": PROJECT_ID,
                "status": "IN_PROGRESS",
                "expected_version": 3,
            },
            f"Apply project update {PROJECT_ID} expected_version 3",
        ),
        (
            "step update",
            {
                "step_id": STEP_ID,
                "status": "IN_PROGRESS",
                "expected_version": 4,
            },
            (
                "Apply step update with step-id "
                f"{STEP_ID} expected-version 4"
            ),
        ),
    ],
)
def test_local_auto_requires_exact_primary_entity_binding(
    monkeypatch,
    tmp_path,
    command,
    payload,
    request_text,
):
    session_id = _enable_and_capture(
        monkeypatch,
        tmp_path,
        command,
        payload,
    )

    authorization = preferences.authorize_local_auto_apply(
        session_id,
        request_text,
        {
            "operations": [preferences.MERCHANT_APPLY_OPERATION],
            "selected_agents": [preferences.MERCHANT_MANAGER_AGENT],
            "risk_level": "external_write",
        },
        LOCAL_AUTO_ENV,
    )

    assert authorization.authorized


def test_wrong_primary_identifier_does_not_spend_receipt(
    monkeypatch,
    tmp_path,
):
    session_id = _enable_and_capture(
        monkeypatch,
        tmp_path,
        "project update",
        {
            "project_id": PROJECT_ID,
            "status": "IN_PROGRESS",
            "expected_version": 3,
        },
    )

    authorization = preferences.authorize_local_auto_apply(
        session_id,
        (
            "Apply project update with project_id "
            f"{OTHER_PROJECT_ID} expected_version 3"
        ),
        {
            "operations": [preferences.MERCHANT_APPLY_OPERATION],
            "selected_agents": [preferences.MERCHANT_MANAGER_AGENT],
            "risk_level": "external_write",
        },
        LOCAL_AUTO_ENV,
    )

    assert not authorization.authorized
    assert "primary identifier does not match" in authorization.reason
    assert preferences.receipt_state(session_id) == preferences.RECEIPT_AVAILABLE


def test_receipt_persists_only_hashed_primary_entity(
    monkeypatch,
    tmp_path,
):
    session_id = _enable_and_capture(
        monkeypatch,
        tmp_path,
        "step update",
        {
            "step_id": STEP_ID,
            "status": "IN_PROGRESS",
            "expected_version": 1,
        },
    )
    document = json.loads(
        preferences.preferences_path(session_id).read_text(
            encoding="utf-8"
        )
    )
    binding = document["receipt"]["entity_binding"]

    assert set(binding) == preferences.ENTITY_BINDING_FIELDS
    assert binding["field"] == "step_id"
    assert len(binding["sha256"]) == 64
    assert STEP_ID not in json.dumps(document)


def test_legacy_receipt_without_entity_binding_fails_closed(
    monkeypatch,
    tmp_path,
):
    session_id = _enable_and_capture(
        monkeypatch,
        tmp_path,
        "project update",
        {
            "project_id": PROJECT_ID,
            "status": "IN_PROGRESS",
            "expected_version": 2,
        },
    )
    document_path = preferences.preferences_path(session_id)
    document = json.loads(document_path.read_text(encoding="utf-8"))
    confirmation_hash = document["receipt"]["confirmation"][
        "confirmation_hash"
    ]
    del document["receipt"]["entity_binding"]
    document_path.write_text(json.dumps(document), encoding="utf-8")

    assert preferences.available_confirmation(session_id) is None
    outcome = preferences.reserve_receipt(
        session_id,
        confirmation_hash,
    )
    assert not outcome.accepted
    assert "primary-entity binding is malformed" in outcome.reason
    assert preferences.receipt_state(session_id) == preferences.RECEIPT_AVAILABLE
