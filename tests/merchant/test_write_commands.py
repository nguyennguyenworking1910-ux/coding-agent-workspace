"""Tests for deterministic Merchant write proposal binding."""

from __future__ import annotations

import uuid

import pytest

from claude.agents.tools.merchant.cli_contract import (
    MerchantCliContractError,
    ProposalHashError,
    RuntimeWriteDeniedError,
    issue_runtime_apply_authorization,
    proposal_hash,
)
from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
    WriteCommandNotConfiguredError,
    materialize_write_payload,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PRIVATE_NAME = "Private Contact"
PRIVATE_EMAIL = "private@example.com"
PRIVATE_IDENTIFIER = "private-product-id"


class RecordingHandler:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"status": "committed"}

    def __call__(self, payload):
        self.calls.append(payload)
        return self.result


def _runtime_authorization(proposal):
    confirmation = proposal["confirmation"]
    return issue_runtime_apply_authorization(
        confirmation,
        {
            "operation": "merchant_apply",
            "subagent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
            "confirmation_hash": confirmation[
                "confirmation_hash"
            ],
        },
    )


def test_propose_never_calls_mutation_handler():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"merchant create": handler}
    )

    result = commands.propose(
        "merchant create",
        "test",
        {
            "code": "BETA",
            "name": "Beta Media",
            "region_code": "VN",
        },
    )

    assert result["success"] is True
    assert result["mode"] == "PROPOSE"
    assert result["requires_confirmation"] is True
    assert uuid.UUID(result["payload"]["merchant_id"])
    assert len(result["proposal_hash"]) == 64
    assert handler.calls == []


def test_generated_id_and_hash_are_deterministic():
    payload = {
        "merchant_id": MERCHANT_ID,
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "MEDIA_TOP_UP_NEW_DOCUMENT",
        "requires_procurement": True,
    }
    first = materialize_write_payload(
        "project create",
        "test",
        payload,
    )
    second = materialize_write_payload(
        " PROJECT   CREATE ",
        " TEST ",
        dict(reversed(tuple(payload.items()))),
    )

    assert first == second
    assert uuid.UUID(first["project_id"])
    assert proposal_hash(
        "project create",
        "test",
        first,
    ) == proposal_hash(
        "project create",
        "test",
        second,
    )


def test_explicit_id_is_preserved_and_bound():
    explicit_id = "00000000-0000-0000-0000-000000000002"
    prepared = materialize_write_payload(
        "document revision-create",
        "test",
        {
            "revision_id": explicit_id,
            "project_id": MERCHANT_ID,
            "document_type": "MERCHANT_AGREEMENT",
            "content_hash": "private-hash",
        },
    )

    assert prepared["revision_id"] == explicit_id


def test_contact_ids_are_stable_and_output_is_pii_free():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"contact import": handler}
    )
    payload = {
        "merchant_id": MERCHANT_ID,
        "expected_version": 1,
        "contacts": [
            {
                "name": PRIVATE_NAME,
                "email": PRIVATE_EMAIL,
                "is_primary": True,
            }
        ],
    }

    first = commands.propose(
        "contact import",
        "test",
        payload,
    )
    second = commands.propose(
        "contact import",
        "test",
        payload,
    )

    contact = first["payload"]["contacts"][0]
    assert first["proposal_hash"] == second["proposal_hash"]
    assert contact["name"] == "[REDACTED]"
    assert contact["email"] == "[REDACTED]"
    assert PRIVATE_NAME not in repr(first)
    assert PRIVATE_EMAIL not in repr(first)
    assert uuid.UUID(contact["contact_id"])
    assert handler.calls == []


def test_matching_apply_invokes_handler_once():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"project update": handler}
    )
    payload = {
        "project_id": MERCHANT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 1,
    }
    proposal = commands.propose(
        "project update",
        "test",
        payload,
    )

    result = commands.apply(
        "project update",
        "test",
        payload,
        proposal_hash=proposal["proposal_hash"],
    )

    assert result["success"] is True
    assert result["mode"] == "APPLY"
    assert result["result"] == {"status": "committed"}
    assert handler.calls == [payload]


def test_changed_apply_payload_never_calls_handler():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"project update": handler}
    )
    original = {
        "project_id": MERCHANT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 1,
    }
    proposal = commands.propose(
        "project update",
        "test",
        original,
    )

    with pytest.raises(ProposalHashError):
        commands.apply(
            "project update",
            "test",
            {**original, "status": "BLOCKED"},
            proposal_hash=proposal["proposal_hash"],
        )

    assert handler.calls == []


def test_hash_is_bound_to_database_and_command():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {
            "project update": handler,
            "step update": handler,
        }
    )
    payload = {
        "project_id": MERCHANT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 1,
    }
    proposal = commands.propose(
        "project update",
        "test",
        payload,
    )

    with pytest.raises(ProposalHashError):
        commands.apply(
            "step update",
            "test",
            payload,
            proposal_hash=proposal["proposal_hash"],
        )

    assert handler.calls == []


def test_runtime_authority_is_checked_before_handler():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"merchant create": handler}
    )
    payload = {
        "code": "BETA",
        "name": "Beta Media",
    }
    proposal = commands.propose(
        "merchant create",
        "runtime",
        payload,
    )

    with pytest.raises(RuntimeWriteDeniedError):
        commands.apply(
            "merchant create",
            "runtime",
            payload,
            proposal_hash=proposal["proposal_hash"],
        )

    assert handler.calls == []


def test_trusted_runtime_capability_uses_exact_proposal():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"merchant create": handler}
    )
    payload = {
        "code": "BETA",
        "name": "Beta Media",
    }
    proposal = commands.propose(
        "merchant create",
        "runtime",
        payload,
    )

    result = commands.apply(
        "merchant create",
        "runtime",
        payload,
        proposal_hash=proposal["proposal_hash"],
        runtime_authorization=_runtime_authorization(
            proposal
        ),
    )

    assert result["database"] == "runtime"
    assert len(handler.calls) == 1


def test_sensitive_apply_result_is_redacted():
    handler = RecordingHandler(
        {
            "identifier_value": PRIVATE_IDENTIFIER,
            "value": PRIVATE_IDENTIFIER,
            "scope": "UAT",
        }
    )
    commands = MerchantWriteCommands(
        {"integration identifier-set": handler}
    )
    payload = {
        "merchant_id": MERCHANT_ID,
        "project_id": None,
        "type": "MASTER_MID",
        "value": PRIVATE_IDENTIFIER,
        "scope": "MASTER",
    }
    proposal = commands.propose(
        "integration identifier-set",
        "test",
        payload,
    )

    result = commands.apply(
        "integration identifier-set",
        "test",
        payload,
        proposal_hash=proposal["proposal_hash"],
    )

    assert PRIVATE_IDENTIFIER not in repr(result)
    assert result["result"]["identifier_value"] == "[REDACTED]"
    assert result["result"]["value"] == "[REDACTED]"


def test_missing_handler_fails_in_both_modes():
    commands = MerchantWriteCommands({})
    payload = {
        "project_id": MERCHANT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 1,
    }

    with pytest.raises(WriteCommandNotConfiguredError):
        commands.propose(
            "project update",
            "test",
            payload,
        )

    with pytest.raises(WriteCommandNotConfiguredError):
        commands.apply(
            "project update",
            "test",
            payload,
            proposal_hash="0" * 64,
        )


@pytest.mark.parametrize(
    "contacts",
    (None, {}, ["not-an-object"]),
)
def test_contact_payload_shape_fails_before_proposal(contacts):
    commands = MerchantWriteCommands(
        {"contact import": RecordingHandler()}
    )

    with pytest.raises(MerchantCliContractError):
        commands.propose(
            "contact import",
            "test",
            {
                "merchant_id": MERCHANT_ID,
                "expected_version": 1,
                "contacts": contacts,
            },
        )
