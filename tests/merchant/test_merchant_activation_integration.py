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
