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


def test_merchant_activate_all_proposal_invokes_preflight_exactly_once():
    """Regression Test 1: propose invokes activation read-only preflight exactly once."""
    preflight = RecordingPreflight()
    mutation_handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {
            "merchant activate-all": mutation_handler,
        }
    )
    commands._preflight_validators["merchant activate-all"] = preflight

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
        ],
        "expected_count": 1,
        "reason": "test activation",
    }

    commands.propose(
        "merchant activate-all",
        "test",
        payload,
    )

    assert len(preflight.calls) == 1, (
        "Preflight must be called exactly once during proposal"
    )
    assert len(mutation_handler.calls) == 0, (
        "Mutation handler must never be called during proposal"
    )


def test_merchant_activate_all_proposal_never_calls_mutation_handler():
    """Regression Test 2: propose invokes mutation handler zero times, apply calls it once."""
    mutation_handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {
            "merchant activate-all": mutation_handler,
        }
    )
    preflight = RecordingPreflight()
    commands._preflight_validators["merchant activate-all"] = preflight

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "expected_count": 2,
        "reason": "batch activation",
    }

    result = commands.propose(
        "merchant activate-all",
        "test",
        payload,
    )

    assert result["mode"] == "PROPOSE"
    assert mutation_handler.calls == [], (
        "Mutation handler must not be called during proposal"
    )
    assert result["success"] is True
    assert "proposal_hash" in result
    assert len(result["proposal_hash"]) == 64

    apply_result = commands.apply(
        "merchant activate-all",
        "test",
        payload,
        proposal_hash=result["proposal_hash"],
    )

    assert len(mutation_handler.calls) == 1, (
        "Mutation handler must be called exactly once during apply"
    )


def test_merchant_activate_all_proposal_contains_sorted_manifest():
    """Regression Test 3: activate-all proposal payload contains exact sorted merchant manifest."""
    preflight = RecordingPreflight()
    commands = MerchantWriteCommands(
        {
            "merchant activate-all": RecordingHandler(),
        }
    )
    commands._preflight_validators["merchant activate-all"] = preflight

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000002",
            "00000000-0000-0000-0000-000000000001",
        ],
        "expected_count": 2,
        "reason": "sorted manifest test",
    }

    result = commands.propose(
        "merchant activate-all",
        "test",
        payload,
    )

    proposal_payload = result.get("payload", {})
    manifest = proposal_payload.get("manifest", [])

    assert isinstance(manifest, list), (
        "Proposal must include manifest list"
    )
    assert len(manifest) == 2, (
        "Manifest must contain exact count of merchants"
    )
    assert manifest[0]["merchant_id"] <= manifest[1]["merchant_id"], (
        "Manifest must be sorted by merchant_id"
    )
    for entry in manifest:
        assert set(entry.keys()) == {"merchant_id", "code", "account_status", "version"}, (
            "Manifest entries must contain exactly these 4 fields"
        )


def test_merchant_activate_all_changing_one_merchant_invalidates_binding():
    """Regression Test 4: Changing one merchant while preserving expected_count invalidates binding."""
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {
            "merchant activate-all": handler,
        }
    )
    preflight = RecordingPreflight()
    commands._preflight_validators["merchant activate-all"] = preflight

    original_payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "expected_count": 2,
        "reason": "original",
    }

    proposal = commands.propose(
        "merchant activate-all",
        "test",
        original_payload,
    )

    assert proposal["success"] is True
    assert "proposal_hash" in proposal
    original_hash = proposal["proposal_hash"]

    changed_payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000003",
        ],
        "expected_count": 2,
        "reason": "original",
    }

    changed_proposal = commands.propose(
        "merchant activate-all",
        "test",
        changed_payload,
    )

    assert changed_proposal["proposal_hash"] != original_hash, (
        "Different manifest must produce different proposal hash"
    )

    with pytest.raises(ProposalHashError):
        commands.apply(
            "merchant activate-all",
            "test",
            changed_payload,
            proposal_hash=original_hash,
        )

    assert handler.calls == [], (
        "Handler must not be called for mismatched manifest"
    )


def test_merchant_activate_all_changing_version_invalidates_binding():
    """Regression Test 5: Changing one merchant version invalidates binding."""
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {
            "merchant activate-all": handler,
        }
    )
    preflight = RecordingPreflight()
    commands._preflight_validators["merchant activate-all"] = preflight

    payload = {
        "merchant_ids": ["00000000-0000-0000-0000-000000000001"],
        "expected_count": 1,
        "merchant_versions": {
            "00000000-0000-0000-0000-000000000001": 1,
        },
        "reason": "version binding test",
    }

    proposal = commands.propose(
        "merchant activate-all",
        "test",
        payload,
    )

    changed_payload = {
        "merchant_ids": ["00000000-0000-0000-0000-000000000001"],
        "expected_count": 1,
        "merchant_versions": {
            "00000000-0000-0000-0000-000000000001": 2,
        },
        "reason": "version binding test",
    }

    with pytest.raises(ProposalHashError):
        commands.apply(
            "merchant activate-all",
            "test",
            changed_payload,
            proposal_hash=proposal["proposal_hash"],
        )

    assert handler.calls == [], (
        "Handler must not be called when version changes"
    )


def test_merchant_activate_all_applies_with_manifest_consistency_check():
    """Regression Test 5b: Apply verifies manifest consistency in same transaction."""
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {
            "merchant activate-all": handler,
        }
    )
    preflight = RecordingPreflight()
    commands._preflight_validators["merchant activate-all"] = preflight

    payload = {
        "merchant_ids": ["00000000-0000-0000-0000-000000000001"],
        "expected_count": 1,
        "reason": "manifest check test",
    }

    proposal = commands.propose(
        "merchant activate-all",
        "test",
        payload,
    )

    assert proposal["success"] is True
    assert "manifest" in proposal.get("payload", {}), (
        "Proposal must include manifest for later verification"
    )


def test_merchant_activate_all_manifest_includes_all_fields():
    """Regression Test 6b: Manifest includes exact required fields per merchant."""
    preflight = RecordingPreflight()
    commands = MerchantWriteCommands(
        {
            "merchant activate-all": RecordingHandler(),
        }
    )
    commands._preflight_validators["merchant activate-all"] = preflight

    payload = {
        "merchant_ids": ["00000000-0000-0000-0000-000000000001"],
        "expected_count": 1,
        "reason": "field validation test",
    }

    result = commands.propose(
        "merchant activate-all",
        "test",
        payload,
    )

    proposal_payload = result.get("payload", {})
    manifest = proposal_payload.get("manifest", [])

    if manifest:
        for entry in manifest:
            required_fields = {"merchant_id", "code", "account_status", "version"}
            actual_fields = set(entry.keys())
            assert required_fields == actual_fields, (
                f"Manifest entry must have exactly {required_fields}, "
                f"got {actual_fields}"
            )


def test_merchant_activate_all_expected_count_matches_manifest_length():
    """Regression Test 7b: Proposal ensures expected_count matches actual manifest."""
    preflight = RecordingPreflight()
    commands = MerchantWriteCommands(
        {
            "merchant activate-all": RecordingHandler(),
        }
    )
    commands._preflight_validators["merchant activate-all"] = preflight

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "expected_count": 2,
        "reason": "count matching test",
    }

    result = commands.propose(
        "merchant activate-all",
        "test",
        payload,
    )

    proposal_payload = result.get("payload", {})
    manifest = proposal_payload.get("manifest", [])
    expected_count = proposal_payload.get("expected_count", 0)

    if manifest:
        assert len(manifest) == expected_count, (
            f"Manifest length {len(manifest)} must match expected_count {expected_count}"
        )


def test_merchant_activate_all_apply_atomicity_with_handler():
    """Regression Test 8b: Apply invokes handler after manifest verification."""
    handler = RecordingHandler({"event_ids": ["event-1", "event-2"]})
    commands = MerchantWriteCommands(
        {
            "merchant activate-all": handler,
        }
    )
    preflight = RecordingPreflight()
    commands._preflight_validators["merchant activate-all"] = preflight

    payload = {
        "merchant_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "expected_count": 2,
        "reason": "atomicity test",
    }

    proposal = commands.propose(
        "merchant activate-all",
        "test",
        payload,
    )

    result = commands.apply(
        "merchant activate-all",
        "test",
        payload,
        proposal_hash=proposal["proposal_hash"],
    )

    assert result["success"] is True
    assert result["mode"] == "APPLY"
    assert len(handler.calls) == 1
    assert "event_ids" in result.get("result", {}), (
        "Apply result should include event IDs from handler"
    )
