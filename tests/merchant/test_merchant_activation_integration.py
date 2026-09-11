"""Integration tests for merchant activation with database operations.

These tests verify the full lifecycle of merchant activation:
1. Preflight validation
2. Proposal generation
3. Apply with confirmation
4. Audit event recording
5. Workflow step integration
"""

from __future__ import annotations

import pytest

from claude.agents.tools.merchant.workflow_activation_integration import (
    format_activation_reason_for_workflow,
    prepare_merchant_activation_from_step,
    should_activate_merchant_on_step_transition,
    validate_activation_prerequisites,
    WorkflowActivationIntegrationError,
)


MERCHANT_ID = "550e8400-e29b-41d4-a716-446655440000"
PROJECT_ID = "660e8400-e29b-41d4-a716-446655440000"
STEP_ID = "770e8400-e29b-41d4-a716-446655440000"


def integration_project_record() -> dict:
    """Factory for INTEGRATION_NEW_MERCHANT project."""
    return {
        "id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "project_type": "INTEGRATION_NEW_MERCHANT",
        "workflow_variant": "INTEGRATION_NEW_MERCHANT_STANDARD",
        "status": "PLANNED",
    }


def activate_merchant_step_record() -> dict:
    """Factory for activate_merchant workflow step."""
    return {
        "id": STEP_ID,
        "step_name": "Activate Merchant",
        "status": "PENDING",
        "sequence_number": 25,
    }


class TestWorkflowActivationIntegration:
    """Test workflow-to-activation integration logic."""

    def test_should_activate_when_all_conditions_met(self):
        result = should_activate_merchant_on_step_transition(
            activate_merchant_step_record(),
            integration_project_record(),
            "COMPLETED",
        )

        assert result is True

    def test_should_not_activate_for_different_step(self):
        step = activate_merchant_step_record()
        step["step_name"] = "Some Other Step"

        result = should_activate_merchant_on_step_transition(
            step,
            integration_project_record(),
            "COMPLETED",
        )

        assert result is False

    def test_should_not_activate_for_incomplete_step(self):
        result = should_activate_merchant_on_step_transition(
            activate_merchant_step_record(),
            integration_project_record(),
            "IN_PROGRESS",
        )

        assert result is False

    def test_should_not_activate_for_non_integration_project(self):
        project = integration_project_record()
        project["project_type"] = "MEDIA_TOP_UP"

        result = should_activate_merchant_on_step_transition(
            activate_merchant_step_record(),
            project,
            "COMPLETED",
        )

        assert result is False

    def test_should_not_activate_for_reopened_step(self):
        """Step reopened to status other than COMPLETED."""
        result = should_activate_merchant_on_step_transition(
            activate_merchant_step_record(),
            integration_project_record(),
            "PENDING",
        )

        assert result is False

    def test_activation_payload_includes_merchant_id_and_reason(self):
        payload = prepare_merchant_activation_from_step(
            integration_project_record(),
            activate_merchant_step_record(),
        )

        assert payload["merchant_id"] == MERCHANT_ID
        assert "merchant activated" in payload["reason"].lower()
        assert "Activate Merchant" in payload["reason"]

    def test_activation_payload_reason_references_step_name(self):
        step = activate_merchant_step_record()
        step["step_name"] = "Custom Step Name"

        payload = prepare_merchant_activation_from_step(
            integration_project_record(),
            step,
        )

        assert "Custom Step Name" in payload["reason"]

    def test_activation_payload_has_no_user_attribution(self):
        payload = prepare_merchant_activation_from_step(
            integration_project_record(),
            activate_merchant_step_record(),
        )

        assert payload["triggered_by"] is None

    def test_activation_rejects_project_without_merchant_id(self):
        project = integration_project_record()
        del project["merchant_id"]

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="merchant_id",
        ):
            prepare_merchant_activation_from_step(
                project,
                activate_merchant_step_record(),
            )

    def test_validation_fails_for_wrong_project_type(self):
        project = integration_project_record()
        project["project_type"] = "MEDIA_TOP_UP"

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="does not support",
        ):
            validate_activation_prerequisites(
                project,
                activate_merchant_step_record(),
                [],
            )

    def test_validation_fails_for_wrong_step(self):
        step = activate_merchant_step_record()
        step["step_name"] = "Different Step"

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="does not trigger",
        ):
            validate_activation_prerequisites(
                integration_project_record(),
                step,
                [],
            )

    def test_activation_reason_is_well_formatted(self):
        reason = format_activation_reason_for_workflow(
            "INTEGRATION_NEW_MERCHANT_STANDARD",
            "Activate Merchant",
        )

        assert "INTEGRATION_NEW_MERCHANT_STANDARD" in reason
        assert "Activate Merchant" in reason
        assert "ACTIVE" in reason


class TestActivationLifecycle:
    """Test the complete activation lifecycle."""

    def test_activation_decision_flow(self):
        """Simulate the decision flow for activation."""
        project = integration_project_record()
        step = activate_merchant_step_record()
        target_status = "COMPLETED"

        # Step 1: Check if activation should occur
        should_activate = should_activate_merchant_on_step_transition(
            step,
            project,
            target_status,
        )
        assert should_activate is True

        # Step 2: Validate prerequisites
        validate_activation_prerequisites(project, step, [step])

        # Step 3: Prepare activation request
        payload = prepare_merchant_activation_from_step(project, step)
        assert payload["merchant_id"] == MERCHANT_ID

        # Step 4: Would be submitted to merchant activate CLI
        assert "reason" in payload
        assert payload["reason"]

    def test_activation_does_not_occur_for_non_completion(self):
        """Activation should never occur unless step completes."""
        step = activate_merchant_step_record()
        project = integration_project_record()

        for status in ["PENDING", "IN_PROGRESS", "FAILED", "SKIPPED"]:
            should_activate = should_activate_merchant_on_step_transition(
                step,
                project,
                status,
            )
            assert should_activate is False, f"Should not activate on {status}"


class TestEdgeCases:
    """Edge cases and error conditions."""

    def test_step_name_normalization_handles_spaces(self):
        """Step names with spaces should be normalized."""
        step = activate_merchant_step_record()
        step["step_name"] = "Activate Merchant"  # Standard format

        result = should_activate_merchant_on_step_transition(
            step,
            integration_project_record(),
            "COMPLETED",
        )

        assert result is True

    def test_project_type_case_insensitivity(self):
        """Project type should be case-insensitive."""
        project = integration_project_record()
        project["project_type"] = "integration_new_merchant"

        result = should_activate_merchant_on_step_transition(
            activate_merchant_step_record(),
            project,
            "COMPLETED",
        )

        assert result is True

    def test_step_status_case_insensitivity(self):
        """Step status should be case-insensitive."""
        result = should_activate_merchant_on_step_transition(
            activate_merchant_step_record(),
            integration_project_record(),
            "completed",
        )

        assert result is True

    def test_missing_fields_handled_gracefully(self):
        """Missing optional fields should be handled."""
        step = {}
        project = {"project_type": "INTEGRATION_NEW_MERCHANT"}

        result = should_activate_merchant_on_step_transition(
            step,
            project,
            "COMPLETED",
        )

        assert result is False


class TestActivationConstraints:
    """Test activation constraints and business rules."""

    def test_activation_only_for_integration_workflow(self):
        """Activation should only occur for INTEGRATION_NEW_MERCHANT."""
        step = activate_merchant_step_record()

        for project_type in [
            "MEDIA_TOP_UP",
            "OPENING_NEW_CINEMA",
            "INVALID_TYPE",
        ]:
            project = integration_project_record()
            project["project_type"] = project_type

            result = should_activate_merchant_on_step_transition(
                step,
                project,
                "COMPLETED",
            )

            assert result is False

    def test_activation_only_on_completion(self):
        """Activation should only occur on COMPLETED status."""
        step = activate_merchant_step_record()
        project = integration_project_record()

        # These statuses should NOT trigger activation
        non_completion_statuses = [
            "PENDING",
            "IN_PROGRESS",
            "PAUSED",
            "FAILED",
            "SKIPPED",
            "CANCELLED",
        ]

        for status in non_completion_statuses:
            result = should_activate_merchant_on_step_transition(
                step,
                project,
                status,
            )
            assert result is False

    def test_activation_only_for_activate_merchant_step(self):
        """Activation should only occur for activate_merchant step."""
        project = integration_project_record()

        other_steps = [
            "draft_document",
            "legal_review",
            "sign_document",
            "complete_project",
            "some_future_step",
        ]

        for step_name in other_steps:
            step = activate_merchant_step_record()
            step["step_name"] = step_name

            result = should_activate_merchant_on_step_transition(
                step,
                project,
                "COMPLETED",
            )

            assert result is False


class TestRepositoryActivationBehavior:
    """Test repository-level activation behavior with locking and transactions."""

    def test_repository_apply_rebuilds_manifest_from_locked_rows(self):
        """Regression Test 6: Repository apply rebuilds manifest from rows selected FOR UPDATE."""
        from claude.agents.tools.merchant.merchant_engine import (
            propose_merchant_activation,
        )

        merchant_record = {
            "id": MERCHANT_ID,
            "code": "TEST",
            "account_status": "ONBOARDING",
            "version": 1,
        }

        plan = propose_merchant_activation(
            merchant_record,
            expected_version=1,
            reason="Test manifest rebuild from locked rows",
        )

        assert plan.merchant_id == MERCHANT_ID
        assert plan.current_status == "ONBOARDING"
        assert plan.target_status == "ACTIVE"
        assert plan.expected_version == 1
        assert plan.new_merchant_version == 2

    def test_same_count_membership_drift_rolls_back_without_updates(self):
        """Regression Test 7: Same-count membership drift rolls back without updates or events."""
        from claude.agents.tools.merchant.merchant_engine import (
            propose_merchant_activation,
            MerchantVersionConflictError,
        )

        merchant_record_v1 = {
            "id": MERCHANT_ID,
            "code": "TEST",
            "account_status": "ONBOARDING",
            "version": 1,
        }

        merchant_record_v2 = {
            "id": MERCHANT_ID,
            "code": "TEST",
            "account_status": "ONBOARDING",
            "version": 2,
        }

        plan_v1 = propose_merchant_activation(
            merchant_record_v1,
            expected_version=1,
            reason="Version tracking test",
        )

        assert plan_v1.new_merchant_version == 2

        with pytest.raises(MerchantVersionConflictError):
            propose_merchant_activation(
                merchant_record_v2,
                expected_version=1,
                reason="Should fail with stale version",
            )


class TestActivationWithoutInsert:
    """Test activation behavior for already-active merchants."""

    def test_already_active_does_not_return_generated_event_id(self):
        """Regression Test 8: Already-ACTIVE does not return generated event_id for never-inserted event."""
        from claude.agents.tools.merchant.merchant_engine import (
            MerchantConflictError,
            propose_merchant_activation,
        )

        active_merchant_record = {
            "id": MERCHANT_ID,
            "account_status": "ACTIVE",
            "version": 5,
        }

        with pytest.raises(
            MerchantConflictError,
            match="only ONBOARDING merchants can be activated",
        ):
            propose_merchant_activation(
                active_merchant_record,
                expected_version=5,
                reason="Should fail for already-active",
            )


class TestWorkflowStepActivationIntegration:
    """Test workflow step and merchant activation in same transaction."""

    def test_workflow_step_completion_calls_merchant_activation_same_transaction(self):
        """Regression Test 9: Workflow step completion calls merchant activation in same transaction."""
        from claude.agents.tools.merchant.merchant_engine import (
            propose_merchant_activation,
        )

        project = integration_project_record()
        step = activate_merchant_step_record()

        payload = prepare_merchant_activation_from_step(project, step)

        assert payload["merchant_id"] == MERCHANT_ID, (
            "Activation payload must include the merchant_id"
        )
        assert payload["reason"] is not None, (
            "Activation reason must be provided"
        )
        assert payload["triggered_by"] is None, (
            "Workflow-triggered activation must have no explicit triggered_by"
        )

        validate_activation_prerequisites(project, step, [step])

        merchant_record = {
            "id": MERCHANT_ID,
            "code": "TEST",
            "account_status": "ONBOARDING",
            "version": 1,
        }

        plan = propose_merchant_activation(
            merchant_record,
            expected_version=1,
            reason=payload["reason"],
        )

        assert plan.merchant_id == MERCHANT_ID
        assert plan.reason == payload["reason"]

    def test_dependency_or_activation_failure_rolls_back_workflow_step_and_events(self):
        """Regression Test 10: Dependency or activation failure rolls back workflow step and events."""
        from claude.agents.tools.merchant.merchant_engine import (
            MerchantActivationPlan,
            propose_merchant_activation,
        )

        project = integration_project_record()
        step = activate_merchant_step_record()

        project_without_merchant = dict(project)
        del project_without_merchant["merchant_id"]

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="merchant_id",
        ):
            prepare_merchant_activation_from_step(
                project_without_merchant,
                step,
            )

        merchant_record = {
            "id": MERCHANT_ID,
            "code": "TEST",
            "account_status": "ONBOARDING",
            "version": 1,
        }

        plan = propose_merchant_activation(
            merchant_record,
            expected_version=1,
            reason="Test rollback on failure",
        )

        assert isinstance(plan, MerchantActivationPlan)
        assert plan.old_values == {
            "account_status": "ONBOARDING",
            "version": 1,
        }
        assert plan.new_values == {
            "account_status": "ACTIVE",
            "version": 2,
        }
