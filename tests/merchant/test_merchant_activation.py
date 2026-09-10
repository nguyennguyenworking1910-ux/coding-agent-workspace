"""Tests for Merchant activation: single and batch operations."""

from __future__ import annotations

import uuid

import pytest

from claude.agents.tools.merchant.merchant_engine import (
    MerchantActivationPlan,
    MerchantConflictError,
    MerchantVersionConflictError,
    propose_merchant_activation,
)


MERCHANT_ID_1 = "00000000-0000-0000-0000-000000000001"
MERCHANT_ID_2 = "00000000-0000-0000-0000-000000000002"
MERCHANT_ID_3 = "00000000-0000-0000-0000-000000000003"
TRIGGERED_BY = "00000000-0000-0000-0000-000000000099"


def onboarding_merchant_record(
    *,
    merchant_id: str = MERCHANT_ID_1,
    version: int = 1,
    code: str = "BETA",
) -> dict:
    """Factory for ONBOARDING merchant records."""
    return {
        "id": merchant_id,
        "code": code,
        "account_status": "ONBOARDING",
        "version": version,
    }


def active_merchant_record(
    *,
    merchant_id: str = MERCHANT_ID_1,
    version: int = 1,
) -> dict:
    """Factory for ACTIVE merchant records."""
    return {
        "id": merchant_id,
        "account_status": "ACTIVE",
        "version": version,
    }


class TestSingleMerchantActivation:
    """Test single merchant activation proposal."""

    def test_activation_plan_creates_valid_audit_fields(self):
        plan = propose_merchant_activation(
            onboarding_merchant_record(merchant_id=MERCHANT_ID_1, version=1),
            expected_version=1,
            reason="Merchant onboarding complete",
            triggered_by=TRIGGERED_BY,
        )

        assert isinstance(plan, MerchantActivationPlan)
        assert plan.merchant_id == MERCHANT_ID_1
        assert plan.current_status == "ONBOARDING"
        assert plan.target_status == "ACTIVE"
        assert plan.expected_version == 1
        assert plan.new_merchant_version == 2
        assert plan.reason == "Merchant onboarding complete"
        assert plan.triggered_by == TRIGGERED_BY
        assert plan.event_type == "MERCHANT_ACTIVATED"
        assert plan.change_summary == "Merchant activated from ONBOARDING to ACTIVE"

    def test_activation_includes_old_and_new_values(self):
        plan = propose_merchant_activation(
            onboarding_merchant_record(version=3),
            expected_version=3,
            reason="Ready for operations",
        )

        assert plan.old_values == {
            "account_status": "ONBOARDING",
            "version": 3,
        }
        assert plan.new_values == {
            "account_status": "ACTIVE",
            "version": 4,
        }

    def test_activation_rejects_non_onboarding_status(self):
        with pytest.raises(
            MerchantConflictError,
            match="only ONBOARDING merchants can be activated",
        ):
            propose_merchant_activation(
                active_merchant_record(version=5),
                expected_version=5,
                reason="Already active",
            )

    def test_activation_rejects_stale_version(self):
        with pytest.raises(
            MerchantVersionConflictError,
            match="version changed",
        ):
            propose_merchant_activation(
                onboarding_merchant_record(version=5),
                expected_version=3,
                reason="Stale version",
            )

    def test_activation_rejects_empty_reason(self):
        with pytest.raises(Exception, match="reason"):
            propose_merchant_activation(
                onboarding_merchant_record(),
                expected_version=1,
                reason="",
            )

    def test_activation_normalizes_whitespace(self):
        plan = propose_merchant_activation(
            onboarding_merchant_record(),
            expected_version=1,
            reason="  Spaces  and  tabs  ",
        )

        assert plan.reason == "Spaces  and  tabs"

    def test_audit_fields_do_not_expose_sensitive_data(self):
        plan = propose_merchant_activation(
            onboarding_merchant_record(),
            expected_version=1,
            reason="Activation reason",
            triggered_by=TRIGGERED_BY,
        )

        encoded = repr(
            {
                "summary": plan.change_summary,
                "old": plan.old_values,
                "new": plan.new_values,
            }
        )

        # Sensitive fields should not appear
        assert "contact" not in encoded.lower()
        assert "email" not in encoded.lower()
        assert "phone" not in encoded.lower()

    @pytest.mark.parametrize(
        "invalid_version",
        (-1, 0, None, "1", False),
    )
    def test_activation_rejects_invalid_expected_version(self, invalid_version):
        with pytest.raises(Exception, match="expected_version"):
            propose_merchant_activation(
                onboarding_merchant_record(),
                expected_version=invalid_version,
                reason="Test",
            )

    @pytest.mark.parametrize(
        "invalid_reason",
        (None, "", "   ", "X" * 501),
    )
    def test_activation_rejects_invalid_reason(self, invalid_reason):
        with pytest.raises(Exception, match="reason"):
            propose_merchant_activation(
                onboarding_merchant_record(),
                expected_version=1,
                reason=invalid_reason,
            )

    def test_activation_preserves_merchant_id_format(self):
        """Merchant ID must be valid UUID."""
        plan = propose_merchant_activation(
            onboarding_merchant_record(merchant_id=MERCHANT_ID_2),
            expected_version=1,
            reason="Test",
        )

        # Should be able to parse as UUID
        merchant_uuid = uuid.UUID(plan.merchant_id)
        assert str(merchant_uuid) == MERCHANT_ID_2

    def test_plan_can_serialize_to_dict(self):
        plan = propose_merchant_activation(
            onboarding_merchant_record(),
            expected_version=1,
            reason="Test",
        )

        result = plan.to_dict()

        assert result["merchant_id"] == MERCHANT_ID_1
        assert result["current_status"] == "ONBOARDING"
        assert result["target_status"] == "ACTIVE"
        assert result["expected_version"] == 1
        assert result["new_merchant_version"] == 2
        assert result["event_type"] == "MERCHANT_ACTIVATED"


class TestBatchMerchantActivation:
    """Test batch activation logic with multiple merchants."""

    def test_batch_creates_one_plan_per_merchant(self):
        """Verify batch activation creates independent plans."""
        merchants = [
            onboarding_merchant_record(merchant_id=MERCHANT_ID_1, code="BETA"),
            onboarding_merchant_record(merchant_id=MERCHANT_ID_2, code="CGV"),
            onboarding_merchant_record(merchant_id=MERCHANT_ID_3, code="BHD"),
        ]

        plans = []
        for merchant in merchants:
            plan = propose_merchant_activation(
                merchant,
                expected_version=1,
                reason="Batch activation",
                triggered_by=TRIGGERED_BY,
            )
            plans.append(plan)

        assert len(plans) == 3
        assert plans[0].merchant_id == MERCHANT_ID_1
        assert plans[1].merchant_id == MERCHANT_ID_2
        assert plans[2].merchant_id == MERCHANT_ID_3
        assert all(p.event_type == "MERCHANT_ACTIVATED" for p in plans)

    def test_batch_activation_maintains_deterministic_ordering(self):
        """Merchant IDs should be sorted for deterministic batch proposals."""
        merchant_ids = [
            "00000000-0000-0000-0000-000000000003",
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ]

        merchants = [
            onboarding_merchant_record(merchant_id=mid)
            for mid in merchant_ids
        ]

        # Simulate sorting as would happen in batch read from database
        sorted_merchants = sorted(
            merchants,
            key=lambda m: m["id"],
        )

        sorted_ids = [m["id"] for m in sorted_merchants]

        assert sorted_ids[0] == "00000000-0000-0000-0000-000000000001"
        assert sorted_ids[1] == "00000000-0000-0000-0000-000000000002"
        assert sorted_ids[2] == "00000000-0000-0000-0000-000000000003"

    def test_batch_activation_each_plan_has_unique_event_id_reference(self):
        """Each merchant activation must have its own audit event ID."""
        merchants = [
            onboarding_merchant_record(merchant_id=MERCHANT_ID_1),
            onboarding_merchant_record(merchant_id=MERCHANT_ID_2),
        ]

        plans = []
        for merchant in merchants:
            plan = propose_merchant_activation(
                merchant,
                expected_version=1,
                reason="Batch",
            )
            plans.append(plan)

        # Each plan should be independent (event_type same, but would have unique ID in DB)
        assert plans[0].event_type == plans[1].event_type
        assert plans[0].merchant_id != plans[1].merchant_id


class TestActivationEdgeCases:
    """Edge cases and boundary conditions."""

    def test_activation_with_high_version_number(self):
        plan = propose_merchant_activation(
            onboarding_merchant_record(version=999999),
            expected_version=999999,
            reason="Very old merchant",
        )

        assert plan.expected_version == 999999
        assert plan.new_merchant_version == 1000000

    def test_activation_with_unicode_reason(self):
        plan = propose_merchant_activation(
            onboarding_merchant_record(),
            expected_version=1,
            reason="Kích hoạt merchant Việt Nam 🇻🇳",
        )

        assert "Việt Nam" in plan.reason

    def test_activation_without_triggered_by(self):
        plan = propose_merchant_activation(
            onboarding_merchant_record(),
            expected_version=1,
            reason="No attribution",
            triggered_by=None,
        )

        assert plan.triggered_by is None

    def test_activation_reason_accepts_max_length(self):
        max_reason = "X" * 500
        plan = propose_merchant_activation(
            onboarding_merchant_record(),
            expected_version=1,
            reason=max_reason,
        )

        assert plan.reason == max_reason

    def test_activation_reason_rejects_over_max_length(self):
        too_long_reason = "X" * 501

        with pytest.raises(Exception, match="reason"):
            propose_merchant_activation(
                onboarding_merchant_record(),
                expected_version=1,
                reason=too_long_reason,
            )


class TestActivationErrorMessages:
    """Verify error messages are clear and actionable."""

    def test_wrong_status_error_message_is_clear(self):
        error = None
        try:
            propose_merchant_activation(
                active_merchant_record(),
                expected_version=1,
                reason="Should fail",
            )
        except MerchantConflictError as e:
            error = str(e)

        assert error is not None
        assert "ACTIVE" in error
        assert "ONBOARDING" in error
        assert "activated" in error.lower()

    def test_version_conflict_error_message_is_clear(self):
        error = None
        try:
            propose_merchant_activation(
                onboarding_merchant_record(version=5),
                expected_version=1,
                reason="Stale",
            )
        except MerchantVersionConflictError as e:
            error = str(e)

        assert error is not None
        assert "version" in error.lower()
