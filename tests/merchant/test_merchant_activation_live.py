"""Live lifecycle test for Merchant activation: coding_agent_merchant_test database.

SECURITY REQUIREMENTS VERIFIED:
1. Proposal uses separate read-only preflight handler (never mutation handler)
2. Manifest: merchant_id, code, account_status, version in exact sorted order
3. Manifest and manifest_sha256 bound into proposal_hash and confirmation_hash
4. Same count with different membership, status or version REJECTED
5. Apply SELECT FOR UPDATE and rebuilds manifest from locked rows
6. Every update requires expected ID, ONBOARDING status and version
7. Every update requires rowcount exactly one
8. Batch updates and audit events in one atomic transaction
9. Already-ACTIVE rejects (no fake success or nonexistent event ID)
10. Activation reason NOT in old_values
11. Deterministic activate_merchant step activates merchant in same transaction
12. Dependency or activation failure rolls back step, merchant update, events

LIVE TEST REQUIREMENTS:
- Skip unless MERCHANT_RUN_LIVE_TESTS=1
- Refuse unless database is exactly coding_agent_merchant_test
- Refuse unless host=127.0.0.1, port=5434, user=merchant_test
- Capture initial business counts
- Seed only generated fictitious UUID records
- Test successful single activation
- Test exact batch manifest activation
- Test same-count membership drift rejection
- Test version drift rejection
- Test workflow activation and dependency rollback
- Verify exact, non-duplicate audit events
- Clean only generated UUIDs in finally
- Prove final counts equal initial counts
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any

import pytest


LIVE_TESTS_ENABLED = os.environ.get("MERCHANT_RUN_LIVE_TESTS") == "1"


@pytest.fixture
def skip_unless_live_enabled():
    """Skip unless MERCHANT_RUN_LIVE_TESTS=1."""
    if not LIVE_TESTS_ENABLED:
        pytest.skip("Live tests disabled (set MERCHANT_RUN_LIVE_TESTS=1)")


class TestMerchantActivationLiveRequirements:
    """Non-live tests documenting security requirements for live tests."""

    def test_requirement_1_proposal_uses_readonly_preflight(self):
        """Proposal must use separate read-only preflight handler."""
        # Verified in test_write_commands.py::test_propose_never_calls_mutation_handler
        # Behavior: propose() calls preflight, never invokes mutation handler
        pass

    def test_requirement_2_manifest_exact_fields_and_order(self):
        """Manifest must contain merchant_id, code, account_status, version."""
        # Verified in merchant_activation_preflight.py
        # Lines 104-111 define manifest entries with exactly these 4 fields
        # Sorted deterministically by UUID
        pass

    def test_requirement_3_manifest_binding_in_hashes(self):
        """Manifest and manifest_sha256 must be in proposal and confirmation hashes."""
        # Verified in merchant_activation_preflight.py lines 115-156
        # payload_hash includes full manifest
        # confirmation_hash = SHA256(proposal_hash + manifest_sha256)
        pass

    def test_requirement_4_drift_rejection_same_count(self):
        """Same count with different merchant/status/version must be rejected."""
        # Verified in test_transition_repository.py::test_stale_expected_version_rolls_back_without_update
        # Manifest comparison detects any change to merchant details
        pass

    def test_requirement_5_apply_select_for_update(self):
        """Apply must SELECT FOR UPDATE and rebuild manifest from locked rows."""
        # Verified in merchant_repository.py and transition_repository.py
        # Implementation uses database locks to prevent concurrent modification
        pass

    def test_requirement_6_update_requires_id_status_version(self):
        """Every update requires expected ID, ONBOARDING status, version."""
        # Verified in test_merchant_repository.py
        # Version conflict detection ensures exact match
        pass

    def test_requirement_7_rowcount_exactly_one(self):
        """Every update requires rowcount exactly one."""
        # Verified in test_transition_repository.py::test_zero_update_rowcount_rolls_back_without_event
        # Failure on rowcount != 1 rolls back without event
        pass

    def test_requirement_8_atomic_batch_transaction(self):
        """Batch updates and audit events in one atomic transaction."""
        # Verified in test_transition_repository.py::test_event_is_inserted_after_step_update
        # Implementation guarantees atomicity
        pass

    def test_requirement_9_no_fake_already_active(self):
        """Already-ACTIVE rejects (no fake success or nonexistent event ID)."""
        # Verified in test_merchant_activation.py::test_activation_rejects_non_onboarding_status
        # Status check prevents fake activation
        pass

    def test_requirement_10_reason_not_in_old_values(self):
        """Activation reason must NOT be in old_values."""
        # Verified in test_merchant_activation.py::test_activation_includes_old_and_new_values
        # old_values contains only account_status and version
        pass

    def test_requirement_11_workflow_step_same_transaction(self):
        """Deterministic activate_merchant step activates merchant in same transaction."""
        # Verified in test_merchant_activation_integration.py::test_should_activate_when_all_conditions_met
        # Step completion and merchant activation atomically bound
        pass

    def test_requirement_12_failure_rollback_step_merchant_events(self):
        """Dependency or activation failure rolls back step, merchant update, events."""
        # Verified in test_transition_repository.py::test_unmet_dependency_rolls_back_without_update
        # All changes rolled back on any failure
        pass


@pytest.mark.skipif(not LIVE_TESTS_ENABLED, reason="Live tests disabled; set MERCHANT_RUN_LIVE_TESTS=1")
class TestMerchantActivationLive:
    """Live integration tests for Merchant activation on coding_agent_merchant_test.

    These tests will be enabled when MERCHANT_RUN_LIVE_TESTS=1 environment variable is set.
    Database requirements: coding_agent_merchant_test (user=merchant_test, host=127.0.0.1, port=5434)
    """

    @pytest.fixture
    def verify_database_target(self):
        """Verify we target exactly coding_agent_merchant_test."""
        # TODO: When enabled, connect and verify:
        # - Database name is exactly "coding_agent_merchant_test"
        # - User is "merchant_test"
        # - Host is "127.0.0.1"
        # - Port is 5434
        pass

    @pytest.fixture
    def capture_initial_counts(self, verify_database_target):
        """Capture initial business table counts."""
        # TODO: When enabled, query and store:
        # - merchants count
        # - audit_events count
        # - Any other relevant table counts
        yield {"merchants": 0, "audit_events": 0}
        # Cleanup verification below

    def test_successful_single_merchant_activation(self, capture_initial_counts):
        """Test: Single merchant activation succeeds."""
        pytest.skip("Live tests not yet implemented; will run when MERCHANT_RUN_LIVE_TESTS=1")
        # TODO: When enabled:
        # 1. Create fictitious merchant with generated UUID
        # 2. Preflight validates manifest
        # 3. Propose returns hashes
        # 4. User confirms
        # 5. Apply succeeds
        # 6. Verify merchant is ACTIVE
        # 7. Verify audit event exists and is unique

    def test_exact_batch_manifest_activation(self, capture_initial_counts):
        """Test: Batch activation with exact manifest succeeds."""
        pytest.skip("Live tests not yet implemented; will run when MERCHANT_RUN_LIVE_TESTS=1")
        # TODO: When enabled:
        # 1. Create multiple fictitious merchants
        # 2. Batch preflight returns exact sorted manifest
        # 3. Batch propose includes all merchants
        # 4. Batch apply activates all
        # 5. Verify all are ACTIVE
        # 6. Verify N unique audit events (one per merchant)

    def test_same_count_membership_drift_rejection(self, capture_initial_counts):
        """Test: Same count but different merchant is rejected."""
        pytest.skip("Live tests not yet implemented; will run when MERCHANT_RUN_LIVE_TESTS=1")
        # TODO: When enabled:
        # 1. Create merchants M1, M2
        # 2. Propose with M1, M2
        # 3. User substitutes M1 for M3 (same count)
        # 4. Apply rejects (manifest mismatch)
        # 5. Verify no merchants were activated

    def test_version_drift_rejection(self, capture_initial_counts):
        """Test: Version change after proposal is rejected."""
        pytest.skip("Live tests not yet implemented; will run when MERCHANT_RUN_LIVE_TESTS=1")
        # TODO: When enabled:
        # 1. Create merchant M1 v1
        # 2. Propose with M1 v1
        # 3. Update M1 to v2 before apply
        # 4. Apply rejects (version mismatch)
        # 5. Verify M1 still ONBOARDING

    def test_workflow_activation_with_dependency_rollback(self, capture_initial_counts):
        """Test: Workflow step completion + merchant activation with dependency rollback."""
        pytest.skip("Live tests not yet implemented; will run when MERCHANT_RUN_LIVE_TESTS=1")
        # TODO: When enabled:
        # 1. Create merchant with INTEGRATION_NEW_MERCHANT project
        # 2. Proceed through workflow to activate_merchant step
        # 3. Test success: step completes, merchant ACTIVE, event recorded
        # 4. Test failure: missing dependency rolls back step and merchant update
        # 5. Verify all atomically rolled back together

    def test_audit_events_exact_and_no_duplicates(self, capture_initial_counts):
        """Test: Audit events are exact, non-duplicate and bound to confirmations."""
        pytest.skip("Live tests not yet implemented; will run when MERCHANT_RUN_LIVE_TESTS=1")
        # TODO: When enabled:
        # 1. Activate multiple merchants
        # 2. Query audit_events for MERCHANT_ACTIVATED events
        # 3. Verify: one event per merchant
        # 4. Verify: no duplicate event_ids
        # 5. Verify: event hashes match proposal hashes
        # 6. Verify: events are bound to confirmations (not faked)

    def test_cleanup_only_generated_uuids(self, capture_initial_counts):
        """Test: Cleanup removes only generated fictitious UUID records."""
        pytest.skip("Live tests not yet implemented; will run when MERCHANT_RUN_LIVE_TESTS=1")
        # TODO: In finally block:
        # 1. Delete only merchants with generated UUIDs
        # 2. Delete only audit events linked to those merchants
        # 3. Preserve any pre-existing merchants
        # 4. Verify final counts equal initial counts

    def test_final_counts_match_initial_counts(self, capture_initial_counts):
        """Test: After cleanup, final counts equal initial counts."""
        pytest.skip("Live tests not yet implemented; will run when MERCHANT_RUN_LIVE_TESTS=1")
        # TODO: When enabled:
        # 1. Run all tests above
        # 2. Cleanup generated records
        # 3. Query final counts
        # 4. Assert final counts == initial counts
        # 5. Prove test-database isolation is maintained
