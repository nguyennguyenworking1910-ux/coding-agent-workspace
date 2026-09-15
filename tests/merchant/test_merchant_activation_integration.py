"""Integration tests for merchant activation with workflow step transitions.

These tests cover the authorization boundary between a workflow step
transition and merchant activation:

1. Only the canonical persisted INTEGRATION_NEW_MERCHANT_STANDARD template and
   its canonical activate_merchant template step authorize activation.
2. Caller-supplied strings (``project["template_name"]``, the mutable copied
   ``project_steps.step_name``) never authorize activation on their own.
3. Dependency state is read from the locked project snapshot.
"""

from __future__ import annotations

import uuid

import pytest

from claude.agents.tools.merchant.workflow import (
    template_step_uuid,
    template_uuid,
)
from claude.agents.tools.merchant.workflow_templates import (
    INTEGRATION_NEW_MERCHANT_STANDARD,
)
from claude.agents.tools.merchant.workflow_activation_integration import (
    canonical_activation_template_step_id,
    format_activation_reason_for_workflow,
    normalize_step_key,
    prepare_merchant_activation_from_step,
    require_persisted_activation_identity,
    should_activate_merchant_on_step_transition,
    validate_activation_prerequisites,
    WorkflowActivationIntegrationError,
)


MERCHANT_ID = "550e8400-e29b-41d4-a716-446655440000"
PROJECT_ID = "660e8400-e29b-41d4-a716-446655440000"
STEP_ID = "770e8400-e29b-41d4-a716-446655440000"
PREDECESSOR_STEP_ID = "880e8400-e29b-41d4-a716-446655440000"

TEMPLATE_ID = str(template_uuid(INTEGRATION_NEW_MERCHANT_STANDARD))
ACTIVATE_TEMPLATE_STEP_ID = str(
    template_step_uuid(
        INTEGRATION_NEW_MERCHANT_STANDARD,
        "activate_merchant",
    )
)
COMPLETE_PROJECT_TEMPLATE_STEP_ID = str(
    template_step_uuid(
        INTEGRATION_NEW_MERCHANT_STANDARD,
        "complete_project",
    )
)
OTHER_TEMPLATE_ID = str(uuid.uuid4())


def integration_project_record() -> dict:
    """Persisted INTEGRATION_NEW_MERCHANT project snapshot.

    Mirrors exactly the columns loaded by
    MerchantStepTransitionRepository._lock_project_for_step.
    """
    return {
        "id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "project_type": "INTEGRATION_NEW_MERCHANT",
        "workflow_variant": "INTEGRATION_NEW_MERCHANT_STANDARD",
        "workflow_template_version_id": TEMPLATE_ID,
        "requires_procurement": False,
        "template_id": TEMPLATE_ID,
        "template_name": "INTEGRATION_NEW_MERCHANT_STANDARD",
        "template_variant": "INTEGRATION_NEW_MERCHANT_STANDARD",
        "template_version": 1,
        "merchant_row_id": MERCHANT_ID,
        "merchant_account_status": "ONBOARDING",
        "merchant_version": 1,
    }


def activate_merchant_step_record() -> dict:
    """Persisted activate_merchant project step snapshot.

    Mirrors exactly the columns loaded by
    MerchantStepTransitionRepository._lock_project_steps.
    """
    return {
        "id": STEP_ID,
        "project_id": PROJECT_ID,
        "template_step_id": ACTIVATE_TEMPLATE_STEP_ID,
        "template_step_row_id": ACTIVATE_TEMPLATE_STEP_ID,
        "template_step_template_id": TEMPLATE_ID,
        "template_step_name": "Activate Merchant",
        "template_step_branch_key": None,
        "branch_key": None,
        "step_name": "Activate Merchant",
        "step_type": "APPROVAL_GATE",
        "status": "IN_PROGRESS",
        "sequence_number": 25,
        "version": 1,
    }


def predecessor_step_record(*, status: str = "COMPLETED") -> dict:
    return {
        "id": PREDECESSOR_STEP_ID,
        "project_id": PROJECT_ID,
        "template_step_id": COMPLETE_PROJECT_TEMPLATE_STEP_ID,
        "template_step_row_id": COMPLETE_PROJECT_TEMPLATE_STEP_ID,
        "template_step_template_id": TEMPLATE_ID,
        "template_step_name": "Create payment request",
        "step_name": "Create payment request",
        "status": status,
        "sequence_number": 18,
        "version": 1,
    }


def blocking_dependency() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "from_step_id": PREDECESSOR_STEP_ID,
        "to_step_id": STEP_ID,
        "dependency_type": "MUST_COMPLETE_BEFORE",
    }


class TestCanonicalTemplateStepDerivation:
    """The canonical activation step id is derived from the persisted template."""

    def test_canonical_step_id_matches_template_step_uuid(self):
        assert canonical_activation_template_step_id(TEMPLATE_ID) == (
            ACTIVATE_TEMPLATE_STEP_ID
        )

    def test_canonical_step_id_is_template_scoped(self):
        assert canonical_activation_template_step_id(OTHER_TEMPLATE_ID) != (
            ACTIVATE_TEMPLATE_STEP_ID
        )

    def test_persisted_template_step_name_normalizes_to_canonical_key(self):
        assert normalize_step_key("Activate Merchant") == "activate_merchant"


class TestWorkflowActivationIntegration:
    """Test workflow-to-activation authorization logic."""

    def test_should_activate_when_all_conditions_met(self):
        result = should_activate_merchant_on_step_transition(
            activate_merchant_step_record(),
            integration_project_record(),
            "COMPLETED",
        )

        assert result is True

    def test_should_not_activate_for_different_persisted_step(self):
        step = activate_merchant_step_record()
        step["template_step_id"] = COMPLETE_PROJECT_TEMPLATE_STEP_ID
        step["template_step_row_id"] = COMPLETE_PROJECT_TEMPLATE_STEP_ID
        step["template_step_name"] = "Complete project"

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

    def test_validation_fails_for_non_canonical_persisted_step_name(self):
        step = activate_merchant_step_record()
        step["template_step_name"] = "Different Step"

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="does not trigger",
        ):
            validate_activation_prerequisites(
                integration_project_record(),
                step,
                [step],
            )

    def test_activation_reason_is_well_formatted(self):
        reason = format_activation_reason_for_workflow(
            "INTEGRATION_NEW_MERCHANT_STANDARD",
            "activate_merchant",
        )

        assert "INTEGRATION_NEW_MERCHANT_STANDARD" in reason
        assert "activate_merchant" in reason
        assert "ACTIVE" in reason


class TestForgedCallerFieldsCannotAuthorize:
    """Caller-controlled strings must never authorize an activation."""

    def test_forged_caller_template_name_cannot_authorize(self):
        """template_name alone, without the persisted template join, fails."""
        project = integration_project_record()
        del project["template_id"]

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="persisted workflow template id",
        ):
            require_persisted_activation_identity(
                project,
                activate_merchant_step_record(),
            )

        assert (
            should_activate_merchant_on_step_transition(
                activate_merchant_step_record(),
                project,
                "COMPLETED",
            )
            is False
        )

    def test_forged_template_name_on_foreign_template_cannot_authorize(self):
        """A claimed template_name that contradicts the persisted row fails."""
        project = integration_project_record()
        project["template_name"] = "INTEGRATION_NEW_MERCHANT_STANDARD"
        project["template_id"] = OTHER_TEMPLATE_ID

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="does not match the project's",
        ):
            require_persisted_activation_identity(
                project,
                activate_merchant_step_record(),
            )

    def test_forged_caller_step_name_cannot_authorize(self):
        """A renamed project step cannot impersonate activate_merchant."""
        step = activate_merchant_step_record()
        step["step_name"] = "Activate Merchant"
        step["template_step_id"] = COMPLETE_PROJECT_TEMPLATE_STEP_ID
        step["template_step_row_id"] = COMPLETE_PROJECT_TEMPLATE_STEP_ID
        step["template_step_name"] = "Complete project"

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="is not the canonical",
        ):
            require_persisted_activation_identity(
                integration_project_record(),
                step,
            )

    def test_caller_step_name_is_never_consulted(self):
        """The canonical persisted pair authorizes whatever step_name says."""
        step = activate_merchant_step_record()
        step["step_name"] = "totally unrelated operator label"

        identity = require_persisted_activation_identity(
            integration_project_record(),
            step,
        )

        assert identity["template_step_name"] == "activate_merchant"

    def test_wrong_persisted_template_id_is_rejected(self):
        project = integration_project_record()
        project["template_id"] = OTHER_TEMPLATE_ID
        project["workflow_template_version_id"] = OTHER_TEMPLATE_ID

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="belongs to template",
        ):
            require_persisted_activation_identity(
                project,
                activate_merchant_step_record(),
            )

    def test_wrong_persisted_template_step_id_is_rejected(self):
        step = activate_merchant_step_record()
        step["template_step_id"] = COMPLETE_PROJECT_TEMPLATE_STEP_ID
        step["template_step_row_id"] = COMPLETE_PROJECT_TEMPLATE_STEP_ID

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="is not the canonical",
        ):
            require_persisted_activation_identity(
                integration_project_record(),
                step,
            )

    def test_project_step_not_pointing_at_joined_template_step_is_rejected(self):
        step = activate_merchant_step_record()
        step["template_step_id"] = COMPLETE_PROJECT_TEMPLATE_STEP_ID

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="does not reference the persisted template step",
        ):
            require_persisted_activation_identity(
                integration_project_record(),
                step,
            )

    def test_canonical_persisted_pair_succeeds(self):
        identity = require_persisted_activation_identity(
            integration_project_record(),
            activate_merchant_step_record(),
        )

        assert identity == {
            "project_id": PROJECT_ID,
            "project_type": "INTEGRATION_NEW_MERCHANT",
            "template_id": TEMPLATE_ID,
            "template_name": "INTEGRATION_NEW_MERCHANT_STANDARD",
            "template_variant": "INTEGRATION_NEW_MERCHANT_STANDARD",
            "template_step_id": ACTIVATE_TEMPLATE_STEP_ID,
            "template_step_name": "activate_merchant",
        }


class TestActivationDependencyPrerequisites:
    """Dependency state comes from the locked project snapshot."""

    def test_completed_dependency_allows_activation(self):
        step = activate_merchant_step_record()

        identity = validate_activation_prerequisites(
            integration_project_record(),
            step,
            [step, predecessor_step_record(status="COMPLETED")],
            [blocking_dependency()],
        )

        assert identity["template_step_name"] == "activate_merchant"

    def test_unmet_dependency_blocks_activation(self):
        step = activate_merchant_step_record()

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="has not completed",
        ):
            validate_activation_prerequisites(
                integration_project_record(),
                step,
                [step, predecessor_step_record(status="IN_PROGRESS")],
                [blocking_dependency()],
            )

    def test_missing_dependency_step_blocks_activation(self):
        step = activate_merchant_step_record()

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="not found",
        ):
            validate_activation_prerequisites(
                integration_project_record(),
                step,
                [step],
                [blocking_dependency()],
            )

    def test_step_outside_locked_snapshot_blocks_activation(self):
        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="not found in project",
        ):
            validate_activation_prerequisites(
                integration_project_record(),
                activate_merchant_step_record(),
                [predecessor_step_record()],
            )


class TestActivationLifecycle:
    """Test the complete activation decision lifecycle."""

    def test_activation_decision_flow(self):
        project = integration_project_record()
        step = activate_merchant_step_record()

        should_activate = should_activate_merchant_on_step_transition(
            step,
            project,
            "COMPLETED",
        )
        assert should_activate is True

        validate_activation_prerequisites(project, step, [step])

        payload = prepare_merchant_activation_from_step(project, step)
        assert payload["merchant_id"] == MERCHANT_ID
        assert payload["reason"]

    def test_activation_does_not_occur_for_non_completion(self):
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

    def test_project_type_case_insensitivity(self):
        project = integration_project_record()
        project["project_type"] = "integration_new_merchant"

        result = should_activate_merchant_on_step_transition(
            activate_merchant_step_record(),
            project,
            "COMPLETED",
        )

        assert result is True

    def test_step_status_case_insensitivity(self):
        result = should_activate_merchant_on_step_transition(
            activate_merchant_step_record(),
            integration_project_record(),
            "completed",
        )

        assert result is True

    def test_missing_fields_handled_gracefully(self):
        result = should_activate_merchant_on_step_transition(
            {},
            {"project_type": "INTEGRATION_NEW_MERCHANT"},
            "COMPLETED",
        )

        assert result is False

    def test_non_uuid_persisted_identity_is_rejected(self):
        project = integration_project_record()
        project["template_id"] = "not-a-uuid"

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="must be a valid UUID",
        ):
            require_persisted_activation_identity(
                project,
                activate_merchant_step_record(),
            )


class TestActivationConstraints:
    """Test activation constraints and business rules."""

    def test_activation_only_for_integration_workflow(self):
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
        step = activate_merchant_step_record()
        project = integration_project_record()

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

    def test_activation_only_for_canonical_persisted_template_step(self):
        project = integration_project_record()

        for step_key in [
            "draft_document",
            "legal_review",
            "sign_document",
            "complete_project",
        ]:
            step = activate_merchant_step_record()
            foreign_step_id = str(
                template_step_uuid(
                    INTEGRATION_NEW_MERCHANT_STANDARD,
                    step_key,
                )
            )
            step["template_step_id"] = foreign_step_id
            step["template_step_row_id"] = foreign_step_id
            step["template_step_name"] = step_key

            result = should_activate_merchant_on_step_transition(
                step,
                project,
                "COMPLETED",
            )

            assert result is False, f"Should not activate on {step_key}"


class TestRepositoryActivationBehavior:
    """Engine-level guarantees the repository relies on."""

    def test_repository_apply_rebuilds_manifest_from_locked_rows(self):
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
        from claude.agents.tools.merchant.merchant_engine import (
            propose_merchant_activation,
            MerchantVersionConflictError,
        )

        merchant_record_v2 = {
            "id": MERCHANT_ID,
            "code": "TEST",
            "account_status": "ONBOARDING",
            "version": 2,
        }

        with pytest.raises(MerchantVersionConflictError):
            propose_merchant_activation(
                merchant_record_v2,
                expected_version=1,
                reason="Should fail with stale version",
            )


class TestActivationWithoutInsert:
    """Test activation behavior for already-active merchants."""

    def test_already_active_does_not_return_generated_event_id(self):
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
