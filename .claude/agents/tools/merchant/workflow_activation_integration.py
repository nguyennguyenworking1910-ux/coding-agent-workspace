"""Integration between workflow step transitions and merchant activation.

When the 'activate_merchant' step reaches COMPLETED status in the
INTEGRATION_NEW_MERCHANT_STANDARD workflow, this module triggers
the merchant's transition from ONBOARDING to ACTIVE.
"""

from __future__ import annotations

from typing import Any


WORKFLOW_STEP_KEY_ACTIVATE_MERCHANT = "activate_merchant"
REQUIRED_STEP_STATUS_FOR_ACTIVATION = "COMPLETED"
REQUIRED_WORKFLOW_PROJECT_TYPE = "INTEGRATION_NEW_MERCHANT"


class WorkflowActivationIntegrationError(RuntimeError):
    """Raised when workflow-to-activation integration fails."""


def should_activate_merchant_on_step_transition(
    step: dict[str, Any],
    project: dict[str, Any],
    target_step_status: str,
) -> bool:
    """Determine if merchant activation should occur.

    Returns True when:
    1. Step is 'activate_merchant'
    2. Transitioning to 'COMPLETED' status
    3. Project type is 'INTEGRATION_NEW_MERCHANT'
    """
    step_key = str(step.get("step_name", "")).lower().replace(
        " ", "_"
    ).replace("-", "_")
    project_type = str(project.get("project_type", "")).upper()
    target_status = str(target_step_status).upper()

    return (
        step_key == WORKFLOW_STEP_KEY_ACTIVATE_MERCHANT
        and target_status == REQUIRED_STEP_STATUS_FOR_ACTIVATION
        and project_type == REQUIRED_WORKFLOW_PROJECT_TYPE
    )


def prepare_merchant_activation_from_step(
    project: dict[str, Any],
    step: dict[str, Any],
) -> dict[str, Any]:
    """Build merchant activation request from step transition context.

    Returns a payload suitable for merchant activation that includes:
    - Merchant ID from project
    - Expected version
    - Reason referencing the step completion
    """
    merchant_id = project.get("merchant_id")
    if not merchant_id:
        raise WorkflowActivationIntegrationError(
            "Project has no merchant_id"
        )

    step_name = str(step.get("step_name", "")).strip()

    return {
        "merchant_id": str(merchant_id),
        "expected_version": None,  # Will be validated from current state
        "reason": (
            f"Merchant activated by workflow step completion: {step_name}"
        ),
        "triggered_by": None,  # Workflow-driven, no user attribution
    }


def validate_activation_prerequisites(
    project: dict[str, Any],
    step: dict[str, Any],
    project_steps: list[dict[str, Any]],
) -> None:
    """Validate that all prerequisites for merchant activation are met.

    Checks:
    - Project is INTEGRATION_NEW_MERCHANT type
    - Step is activate_merchant
    - All dependency steps have been completed
    """
    project_type = str(project.get("project_type", "")).upper()
    step_name = str(step.get("step_name", "")).lower().replace(
        " ", "_"
    ).replace("-", "_")

    if project_type != REQUIRED_WORKFLOW_PROJECT_TYPE:
        raise WorkflowActivationIntegrationError(
            f"Project type {project_type} does not support "
            "workflow-driven merchant activation"
        )

    if step_name != WORKFLOW_STEP_KEY_ACTIVATE_MERCHANT:
        raise WorkflowActivationIntegrationError(
            f"Step {step_name} does not trigger merchant activation"
        )

    # Verify dependencies have been completed
    step_id = step.get("id")
    dependencies = [
        s for s in project_steps
        if str(s.get("id")) == str(step_id)
    ]

    if not dependencies:
        raise WorkflowActivationIntegrationError(
            f"Step {step_id} not found in project"
        )


def format_activation_reason_for_workflow(
    workflow_variant: str,
    step_name: str,
) -> str:
    """Format a reason string for workflow-driven activation."""
    return (
        f"Workflow {workflow_variant} step '{step_name}' completed. "
        f"Merchant activated to ACTIVE status."
    )
