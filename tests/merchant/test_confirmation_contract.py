"""Checkpoint 7.2 exact, redacted Merchant confirmation contract tests."""

import base64
import json

import pytest

from claude.agents.tools.merchant.cli_contract import (
    CONFIRMATION_OPERATION,
    CONFIRMATION_VERSION,
    ConfirmationEnvelopeError,
    RuntimeWriteDeniedError,
    build_confirmation_envelope,
    build_proposal,
    parse_confirmation_token,
    proposal_payload_hash,
    require_apply_authorization,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
PRIVATE_NAME = "Private Merchant Name"
PRIVATE_EMAIL = "private@example.com"


def _project_payload(**changes):
    payload = {
        "project_id": PROJECT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 3,
        "contact_email": PRIVATE_EMAIL,
    }
    payload.update(changes)
    return payload


def _encode(payload):
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(canonical).decode(
        "ascii"
    ).rstrip("=")


def _decode(token):
    padding = "=" * (-len(token) % 4)
    return json.loads(
        base64.urlsafe_b64decode(token + padding).decode("utf-8")
    )


def test_proposal_emits_exact_confirmation_metadata_and_token():
    proposal = build_proposal(
        "project update",
        "runtime",
        _project_payload(),
    ).to_dict()
    confirmation = proposal["confirmation"]

    assert confirmation["contract_version"] == 1
    assert confirmation["confirmation_version"] == CONFIRMATION_VERSION
    assert confirmation["operation"] == CONFIRMATION_OPERATION
    assert confirmation["command"] == "project update"
    assert confirmation["database_target"] == "runtime"
    assert confirmation["expected_version"] == 3
    assert confirmation["proposal_hash"] == proposal["proposal_hash"]
    assert len(confirmation["payload_hash"]) == 64
    assert len(confirmation["confirmation_hash"]) == 64
    assert parse_confirmation_token(
        proposal["confirmation_token"]
    ).to_dict() == confirmation


def test_confirmation_contains_hashes_not_raw_or_redacted_payload():
    proposal = build_proposal(
        "merchant create",
        "runtime",
        {
            "code": "PRIVATE",
            "name": PRIVATE_NAME,
        },
    ).to_dict()
    confirmation_text = json.dumps(proposal["confirmation"])
    decoded_token = json.dumps(
        _decode(proposal["confirmation_token"])
    )

    assert "payload" not in proposal["confirmation"]
    assert PRIVATE_NAME not in confirmation_text
    assert PRIVATE_NAME not in decoded_token
    assert "[REDACTED]" not in decoded_token


def test_confirmation_token_is_deterministic_across_payload_key_order():
    first = build_proposal(
        "project update",
        "runtime",
        _project_payload(),
    ).to_dict()
    second = build_proposal(
        " PROJECT   UPDATE ",
        " RUNTIME ",
        dict(reversed(tuple(_project_payload().items()))),
    ).to_dict()

    assert first["confirmation_token"] == second["confirmation_token"]


def test_payload_hash_changes_with_exact_payload():
    baseline = proposal_payload_hash(_project_payload())

    assert baseline != proposal_payload_hash(
        _project_payload(status="BLOCKED")
    )
    assert baseline != proposal_payload_hash(
        _project_payload(expected_version=4)
    )


def test_confirmation_binds_command_target_payload_and_version():
    baseline = build_confirmation_envelope(
        "project update",
        "runtime",
        _project_payload(),
    )
    changed_command = build_confirmation_envelope(
        "step update",
        "runtime",
        _project_payload(),
    )
    changed_target = build_confirmation_envelope(
        "project update",
        "test",
        _project_payload(),
    )
    changed_payload = build_confirmation_envelope(
        "project update",
        "runtime",
        _project_payload(status="BLOCKED"),
    )
    changed_version = build_confirmation_envelope(
        "project update",
        "runtime",
        _project_payload(expected_version=4),
    )

    assert len(
        {
            baseline.confirmation_hash,
            changed_command.confirmation_hash,
            changed_target.confirmation_hash,
            changed_payload.confirmation_hash,
            changed_version.confirmation_hash,
        }
    ) == 5


def test_create_proposal_records_null_expected_version():
    confirmation = build_confirmation_envelope(
        "merchant create",
        "runtime",
        {
            "code": "SAFE",
            "name": "Safe Merchant",
        },
    )

    assert confirmation.expected_version is None
    assert parse_confirmation_token(
        confirmation.to_token()
    ).expected_version is None


@pytest.mark.parametrize("expected_version", (False, 0, -1, "3", 3.0))
def test_invalid_expected_version_is_rejected(expected_version):
    with pytest.raises(
        ConfirmationEnvelopeError,
        match="expected_version",
    ):
        build_confirmation_envelope(
            "project update",
            "runtime",
            _project_payload(expected_version=expected_version),
        )


@pytest.mark.parametrize(
    "token",
    (None, "", "not+urlsafe", "a" * 4097),
)
def test_malformed_confirmation_token_is_rejected(token):
    with pytest.raises(ConfirmationEnvelopeError):
        parse_confirmation_token(token)


def test_changed_confirmation_field_without_new_binding_is_rejected():
    confirmation = build_confirmation_envelope(
        "project update",
        "runtime",
        _project_payload(),
    )
    changed = _decode(confirmation.to_token())
    changed["command"] = "step update"

    with pytest.raises(
        ConfirmationEnvelopeError,
        match="binding does not match",
    ):
        parse_confirmation_token(_encode(changed))


def test_unexpected_confirmation_field_is_rejected():
    confirmation = build_confirmation_envelope(
        "project update",
        "runtime",
        _project_payload(),
    )
    changed = _decode(confirmation.to_token())
    changed["password"] = "must-not-be-accepted"

    with pytest.raises(
        ConfirmationEnvelopeError,
        match="incomplete or unexpected",
    ):
        parse_confirmation_token(_encode(changed))


def test_noncanonical_token_is_rejected():
    confirmation = build_confirmation_envelope(
        "project update",
        "runtime",
        _project_payload(),
    )
    payload = _decode(confirmation.to_token())
    noncanonical = base64.urlsafe_b64encode(
        json.dumps(payload, indent=2).encode("utf-8")
    ).decode("ascii").rstrip("=")

    with pytest.raises(
        ConfirmationEnvelopeError,
        match="not canonical",
    ):
        parse_confirmation_token(noncanonical)


def test_confirmation_token_does_not_unlock_runtime_apply():
    confirmation = build_confirmation_envelope(
        "merchant create",
        "runtime",
        {
            "code": "SAFE",
            "name": "Safe Merchant",
        },
    )

    assert parse_confirmation_token(confirmation.to_token())

    with pytest.raises(RuntimeWriteDeniedError):
        require_apply_authorization(
            "merchant create",
            "runtime",
        )
