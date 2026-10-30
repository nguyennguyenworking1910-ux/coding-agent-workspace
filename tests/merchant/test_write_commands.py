"""Tests for deterministic Merchant write proposal binding."""

from __future__ import annotations

import uuid

import pytest

from claude.agents.tools.merchant.cli_contract import (
    MerchantCliContractError,
    ProposalHashError,
    build_proposal,
    RuntimeWriteDeniedError,
    issue_runtime_apply_authorization,
    proposal_hash,
    verify_proposal_hash,
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
            "operation": "merchant_execute",
            "subagent_type": "merchant-manager",
            "teammate_name": "merchant-manager",
            "confirmation_hash": confirmation[
                "confirmation_hash"
            ],
        },
        execution_guard=lambda: None,
    )


def test_historical_proposal_builder_never_calls_mutation_handler():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"merchant create": handler}
    )
    payload = {
        "code": "BETA",
        "name": "Beta Media",
        "region_code": "VN",
    }

    prepared = materialize_write_payload(
        "merchant create",
        "test",
        payload,
    )
    result = build_proposal(
        "merchant create",
        "test",
        prepared,
    ).to_dict()

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


def test_historical_contact_ids_are_stable_and_pii_free():
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

    prepared_first = materialize_write_payload(
        "contact import",
        "test",
        payload,
    )
    prepared_second = materialize_write_payload(
        "contact import",
        "test",
        payload,
    )

    first = build_proposal(
        "contact import",
        "test",
        prepared_first,
    ).to_dict()
    second = build_proposal(
        "contact import",
        "test",
        prepared_second,
    ).to_dict()

    contact = first["payload"]["contacts"][0]

    assert first["proposal_hash"] == second["proposal_hash"]
    assert contact["name"] == "[REDACTED]"
    assert contact["email"] == "[REDACTED]"
    assert PRIVATE_NAME not in repr(first)
    assert PRIVATE_EMAIL not in repr(first)
    assert uuid.UUID(contact["contact_id"])
    assert handler.calls == []


def test_direct_execute_invokes_handler_once():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"project update": handler}
    )
    payload = {
        "project_id": MERCHANT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 1,
    }

    result = commands.execute(
        "project update",
        "test",
        payload,
    )

    assert result["success"] is True
    assert result["mode"] == "EXECUTE"
    assert result["result"] == {"status": "committed"}
    assert handler.calls == [payload]


def test_historical_hash_detects_changed_payload():
    original = {
        "project_id": MERCHANT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 1,
    }
    digest = proposal_hash("project update", "test", original)

    with pytest.raises(ProposalHashError):
        verify_proposal_hash(
            digest,
            "project update",
            "test",
            {**original, "status": "BLOCKED"},
        )


def test_historical_hash_binds_database_and_command():
    payload = {
        "project_id": MERCHANT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 1,
    }
    digest = proposal_hash("project update", "test", payload)

    with pytest.raises(ProposalHashError):
        verify_proposal_hash(
            digest, "project update", "runtime", payload
        )

    with pytest.raises(ProposalHashError):
        verify_proposal_hash(
            digest, "step update", "test", payload
        )


def test_runtime_create_rejects_missing_authorization():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"merchant create": handler}
    )

    with pytest.raises(PermissionError, match="durable reservation"):
        commands.execute(
            "merchant create",
            "runtime",
            {"code": "BETA", "name": "Beta Media"},
        )

    assert handler.calls == []


def test_runtime_create_rejects_generic_execution_even_with_capability():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"merchant create": handler}
    )
    payload = {
        "code": "BETA",
        "name": "Beta Media",
    }

    prepared = materialize_write_payload(
        "merchant create",
        "runtime",
        payload,
    )
    proposal = build_proposal(
        "merchant create",
        "runtime",
        prepared,
    ).to_dict()
    authorization = _runtime_authorization(proposal)

    with pytest.raises(PermissionError, match="durable reservation"):
        commands.execute(
            "merchant create",
            "runtime",
            payload,
            runtime_authorization=authorization,
        )

    assert handler.calls == []
    assert authorization.consumed is False


def test_sensitive_execute_result_is_redacted():
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

    result = commands.execute(
        "integration identifier-set",
        "test",
        payload,
    )

    assert result["success"] is True
    assert result["mode"] == "EXECUTE"
    assert len(handler.calls) == 1
    assert PRIVATE_IDENTIFIER not in repr(result)
    assert result["result"]["identifier_value"] == "[REDACTED]"
    assert result["result"]["value"] == "[REDACTED]"


def test_direct_execute_rejects_missing_handler():
    commands = MerchantWriteCommands({})
    payload = {
        "project_id": MERCHANT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 1,
    }

    with pytest.raises(WriteCommandNotConfiguredError):
        commands.execute(
            "project update",
            "test",
            payload,
        )


@pytest.mark.parametrize(
    "contacts",
    (None, {}, ["not-an-object"]),
)
def test_invalid_contact_payload_rejected_before_execute(contacts):
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"contact import": handler}
    )

    with pytest.raises(MerchantCliContractError):
        commands.execute(
            "contact import",
            "test",
            {
                "merchant_id": MERCHANT_ID,
                "expected_version": 1,
                "contacts": contacts,
            },
        )

    assert handler.calls == []


# Regression tests: Merchant activation preflight and binding


class RecordingPreflight:
    """Records calls to activation preflight for testing."""

    def __init__(self):
        self.calls = []

    def __call__(self, payload):
        self.calls.append(payload)
        expected_count = payload.get("expected_count", 1)
        merchant_ids = payload.get("merchant_ids", [])

        merchants = []
        for i in range(expected_count):
            merchant_id = merchant_ids[i] if i < len(merchant_ids) else f"00000000-0000-0000-0000-{i:012d}"
            merchants.append({
                "merchant_id": merchant_id,
                "code": f"TEST{i}",
                "account_status": "ONBOARDING",
                "version": 1 + i,
            })

        merchants_sorted = sorted(merchants, key=lambda m: m["merchant_id"])

        return {
            "merchants": merchants_sorted,
            "manifest_sha256": "abc123",
        }


def test_merchant_activate_all_execute_runs_preflight_before_handler():
    """Direct activation runs preflight once before mutation."""
    events = []

    def preflight(payload):
        events.append("preflight")
        return RecordingPreflight()(payload)

    def handler(payload):
        events.append("handler")
        return {"status": "committed"}

    commands = MerchantWriteCommands({
        "merchant activate-all": handler,
    })
    commands.register_preflight_validator(
        "merchant activate-all",
        preflight,
    )

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
        ],
        "expected_count": 1,
        "reason": "test activation",
    }

    result = commands.execute(
        "merchant activate-all",
        "test",
        payload,
    )

    assert result["success"] is True
    assert result["mode"] == "EXECUTE"
    assert events == ["preflight", "handler"]


def test_activate_all_execute_calls_handler_once_after_preflight():
    events = []
    preflight = RecordingPreflight()

    def tracked_preflight(payload):
        events.append("preflight")
        return preflight(payload)

    def handler(payload):
        events.append("handler")
        return {"status": "committed"}

    commands = MerchantWriteCommands(
        {"merchant activate-all": handler}
    )
    commands.register_preflight_validator(
        "merchant activate-all", tracked_preflight
    )

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "expected_count": 2,
        "reason": "batch activation",
    }

    result = commands.execute(
        "merchant activate-all", "test", payload
    )

    assert result["success"] is True
    assert result["mode"] == "EXECUTE"
    assert result["result"] == {"status": "committed"}
    assert events == ["preflight", "handler"]
    assert len(preflight.calls) == 1


def test_merchant_activate_all_execute_contains_sorted_manifest():
    handler = RecordingHandler()
    preflight = RecordingPreflight()
    commands = MerchantWriteCommands(
        {"merchant activate-all": handler}
    )
    commands.register_preflight_validator(
        "merchant activate-all", preflight
    )

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000002",
            "00000000-0000-0000-0000-000000000001",
        ],
        "expected_count": 2,
        "reason": "sorted manifest test",
    }

    result = commands.execute(
        "merchant activate-all", "test", payload
    )

    assert result["success"] is True
    assert len(preflight.calls) == 1
    assert len(handler.calls) == 1

    manifest = handler.calls[0]["manifest"]
    assert isinstance(manifest, list)
    assert len(manifest) == 2

    ids = [entry["merchant_id"] for entry in manifest]
    assert ids == sorted(ids)
    assert set(ids) == set(payload["merchant_ids"])


def test_activate_all_changed_merchant_changes_manifest_binding():
    original = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "expected_count": 2,
        "reason": "original",
    }
    changed = {
        **original,
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000003",
        ],
    }

    preflight = RecordingPreflight()
    first_preflight = preflight(original)
    second_preflight = preflight(changed)

    first = materialize_write_payload(
        "merchant activate-all",
        "test",
        original,
        preflight_result=first_preflight,
    )
    second = materialize_write_payload(
        "merchant activate-all",
        "test",
        changed,
        preflight_result=second_preflight,
    )

    first_ids = {
        row["merchant_id"] for row in first["manifest"]
    }
    second_ids = {
        row["merchant_id"] for row in second["manifest"]
    }

    assert first_ids == set(original["merchant_ids"])
    assert second_ids == set(changed["merchant_ids"])
    assert first_ids != second_ids

    original_hash = proposal_hash(
        "merchant activate-all", "test", first
    )
    changed_hash = proposal_hash(
        "merchant activate-all", "test", second
    )

    assert original_hash != changed_hash

    with pytest.raises(ProposalHashError):
        verify_proposal_hash(
            original_hash,
            "merchant activate-all",
            "test",
            second,
        )


def test_activate_all_changed_version_changes_manifest_binding():
    merchant_id = "00000000-0000-0000-0000-000000000001"
    payload = {
        "merchant_ids": [merchant_id],
        "expected_count": 1,
        "reason": "version binding test",
    }

    original_preflight = {
        "merchants": [{
            "merchant_id": merchant_id,
            "code": "TEST0",
            "account_status": "ONBOARDING",
            "version": 1,
        }]
    }
    changed_preflight = {
        "merchants": [{
            "merchant_id": merchant_id,
            "code": "TEST0",
            "account_status": "ONBOARDING",
            "version": 2,
        }]
    }

    first = materialize_write_payload(
        "merchant activate-all",
        "test",
        payload,
        preflight_result=original_preflight,
    )
    second = materialize_write_payload(
        "merchant activate-all",
        "test",
        payload,
        preflight_result=changed_preflight,
    )

    assert first["manifest"][0]["version"] == 1
    assert second["manifest"][0]["version"] == 2

    original_hash = proposal_hash(
        "merchant activate-all", "test", first
    )
    changed_hash = proposal_hash(
        "merchant activate-all", "test", second
    )

    assert original_hash != changed_hash

    with pytest.raises(ProposalHashError):
        verify_proposal_hash(
            original_hash,
            "merchant activate-all",
            "test",
            second,
        )


def test_activate_all_execute_preserves_exact_preflight_manifest():
    """Handler receives the exact manifest produced by preflight."""
    handler = RecordingHandler()
    preflight = RecordingPreflight()

    observed = []

    def tracked_preflight(payload):
        result = preflight(payload)
        observed.append(result)
        return result

    commands = MerchantWriteCommands(
        {"merchant activate-all": handler}
    )
    commands.register_preflight_validator(
        "merchant activate-all", tracked_preflight
    )

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "expected_count": 2,
        "reason": "manifest consistency test",
    }

    result = commands.execute(
        "merchant activate-all", "test", payload
    )

    assert result["success"] is True
    assert result["mode"] == "EXECUTE"
    assert len(preflight.calls) == 1
    assert len(observed) == 1
    assert len(handler.calls) == 1

    received = handler.calls[0]
    expected_manifest = observed[0]["merchants"]

    assert received["manifest"] == expected_manifest
    assert len(received["manifest"]) == payload["expected_count"]

    actual_ids = {
        row["merchant_id"]
        for row in received["manifest"]
    }
    assert actual_ids == set(payload["merchant_ids"])



def test_merchant_activate_all_execute_manifest_has_required_fields():
    handler = RecordingHandler()
    preflight = RecordingPreflight()
    commands = MerchantWriteCommands(
        {"merchant activate-all": handler}
    )
    commands.register_preflight_validator(
        "merchant activate-all", preflight
    )

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
        ],
        "expected_count": 1,
        "reason": "field validation test",
    }

    result = commands.execute(
        "merchant activate-all", "test", payload
    )

    assert result["success"] is True
    assert len(handler.calls) == 1

    manifest = handler.calls[0]["manifest"]
    assert len(manifest) == 1

    required = {
        "merchant_id", "code", "account_status", "version"
    }
    for entry in manifest:
        assert set(entry) == required
        assert entry["merchant_id"] in payload["merchant_ids"]


def test_merchant_activate_all_execute_manifest_count_matches():
    handler = RecordingHandler()
    preflight = RecordingPreflight()
    commands = MerchantWriteCommands(
        {"merchant activate-all": handler}
    )
    commands.register_preflight_validator(
        "merchant activate-all", preflight
    )

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "expected_count": 2,
        "reason": "count matching test",
    }

    result = commands.execute(
        "merchant activate-all", "test", payload
    )

    assert result["success"] is True
    assert len(preflight.calls) == 1
    assert len(handler.calls) == 1

    prepared = handler.calls[0]
    manifest = prepared["manifest"]
    assert len(manifest) == prepared["expected_count"]
    assert prepared["expected_count"] == payload["expected_count"]
    assert len(manifest) == len(payload["merchant_ids"])


def test_activate_all_execute_returns_handler_event_ids():
    handler = RecordingHandler(
        {"event_ids": ["event-1", "event-2"]}
    )
    preflight = RecordingPreflight()

    commands = MerchantWriteCommands(
        {"merchant activate-all": handler}
    )
    commands.register_preflight_validator(
        "merchant activate-all", preflight
    )

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "expected_count": 2,
        "reason": "atomicity test",
    }

    result = commands.execute(
        "merchant activate-all", "test", payload
    )

    assert result["success"] is True
    assert result["mode"] == "EXECUTE"
    assert len(preflight.calls) == 1
    assert len(handler.calls) == 1
    assert result["result"]["event_ids"] == [
        "event-1", "event-2"
    ]
    assert len(handler.calls[0]["manifest"]) == 2
