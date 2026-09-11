"""Integration between workflow step transitions and merchant activation.

When the 'activate_merchant' step reaches COMPLETED status in the
INTEGRATION_NEW_MERCHANT_STANDARD workflow, this module triggers
the merchant's transition from ONBOARDING to ACTIVE within the
same transaction and cursor context.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb


WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT = "INTEGRATION_NEW_MERCHANT_STANDARD"
WORKFLOW_STEP_TEMPLATE_ACTIVATE_MERCHANT = "activate_merchant"
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
    1. Step name is 'activate_merchant' (case-insensitive, normalized)
    2. Transitioning to 'COMPLETED' status
    3. Project type is 'INTEGRATION_NEW_MERCHANT'
    """
    step_name = str(step.get("step_name", "")).lower().replace(
        " ", "_"
    ).replace("-", "_")
    project_type = str(project.get("project_type", "")).upper()
    target_status = str(target_step_status).upper()

    is_activate_merchant_step = (
        step_name == WORKFLOW_STEP_TEMPLATE_ACTIVATE_MERCHANT.lower()
    )

    return (
        is_activate_merchant_step
        and target_status == REQUIRED_STEP_STATUS_FOR_ACTIVATION
        and project_type == REQUIRED_WORKFLOW_PROJECT_TYPE
    )


def activate_merchant_in_workflow_transaction(
    cursor: Any,
    merchant_id: str,
    expected_version: int,
    project: dict[str, Any],
    step: dict[str, Any],
    project_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Activate merchant within the existing workflow transaction.

    Uses the provided cursor and transaction context to:
    - Validate activation prerequisites
    - Lock and read merchant state
    - Perform ONBOARDING -> ACTIVE transition
    - Insert audit event
    - Return activation result

    Must not open a new connection or transaction.
    Any failure raises an exception that causes the outer transaction to rollback.
    """
    from claude.agents.tools.merchant.merchant_engine import propose_merchant_activation
    import uuid as uuid_module

    validate_activation_prerequisites(
        project,
        step,
        project_steps,
    )

    merchant_uuid = merchant_id

    cursor.execute(
        """
        SELECT id, code, account_status, version
        FROM merchant_ops.merchants
        WHERE id = %s
        FOR UPDATE
        """,
        (uuid_module.UUID(merchant_uuid),),
    )

    merchant_row = cursor.fetchone()
    if merchant_row is None:
        raise WorkflowActivationIntegrationError(
            f"Merchant {merchant_uuid} not found"
        )

    merchant = {
        "id": merchant_row["id"],
        "code": merchant_row["code"],
        "account_status": merchant_row["account_status"],
        "version": merchant_row["version"],
    }

    step_name = str(step.get("step_name", "")).strip()
    reason = (
        f"Merchant activated by workflow step completion: {step_name}"
    )

    plan = propose_merchant_activation(
        merchant,
        expected_version=expected_version,
        reason=reason,
        triggered_by=None,
    )

    event_id = uuid_module.uuid4()

    cursor.execute(
        """
        UPDATE merchant_ops.merchants
        SET
            account_status = %s,
            version = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE
            id = %s
            AND account_status = %s
            AND version = %s
        """,
        (
            plan.target_status,
            plan.new_merchant_version,
            uuid_module.UUID(plan.merchant_id),
            plan.current_status,
            plan.expected_version,
        ),
    )

    rowcount = cursor.rowcount
    if rowcount != 1:
        raise WorkflowActivationIntegrationError(
            f"Merchant activation update affected {rowcount} rows, "
            f"expected exactly 1"
        )

    cursor.execute(
        """
        INSERT INTO merchant_ops.audit_events (
            id,
            merchant_id,
            event_type,
            event_data,
            created_at
        )
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        """,
        (
            event_id,
            uuid_module.UUID(plan.merchant_id),
            plan.event_type,
            Jsonb({
                "reason": plan.reason,
                "old_values": plan.old_values,
                "new_values": plan.new_values,
            }),
        ),
    )

    return {
        "success": True,
        "merchant_id": str(plan.merchant_id),
        "previous_status": plan.current_status,
        "current_status": plan.target_status,
        "previous_version": plan.expected_version,
        "current_version": plan.new_merchant_version,
        "event_id": str(event_id),
        "event_type": plan.event_type,
    }


def validate_activation_prerequisites(
    project: dict[str, Any],
    step: dict[str, Any],
    project_steps: list[dict[str, Any]],
) -> None:
    """Validate that all prerequisites for merchant activation are met.

    Checks:
    - Project is INTEGRATION_NEW_MERCHANT type
    - Step name is activate_merchant
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

    if step_name != WORKFLOW_STEP_TEMPLATE_ACTIVATE_MERCHANT.lower():
        raise WorkflowActivationIntegrationError(
            f"Step {step_name} does not trigger merchant activation"
        )

    step_id = step.get("id")
    current_step = next(
        (s for s in project_steps if str(s.get("id")) == str(step_id)),
        None,
    )

    if current_step is None:
        raise WorkflowActivationIntegrationError(
            f"Step {step_id} not found in project"
        )

    dependencies = current_step.get("dependencies", [])
    dependency_ids = [dep.get("predecessor_step_id") for dep in dependencies]

    for dep_id in dependency_ids:
        if dep_id is None:
            continue

        dep_step = next(
            (s for s in project_steps if str(s.get("id")) == str(dep_id)),
            None,
        )

        if dep_step is None:
            raise WorkflowActivationIntegrationError(
                f"Dependency step {dep_id} not found"
            )

        dep_status = str(dep_step.get("status", "")).upper()
        if dep_status != "COMPLETED":
            raise WorkflowActivationIntegrationError(
                f"Dependency step {dep_id} has not completed "
                f"(current status: {dep_status})"
            )


def prepare_merchant_activation_from_step(
    project: dict[str, Any],
    step: dict[str, Any],
) -> dict[str, Any]:
    """Build merchant activation request from step transition context.

    Returns a payload suitable for merchant activation that includes:
    - Merchant ID from project
    - Expected version (will be validated from current state)
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
        "expected_version": None,
        "reason": (
            f"Merchant activated by workflow step completion: {step_name}"
        ),
        "triggered_by": None,
    }


def format_activation_reason_for_workflow(
    workflow_variant: str,
    step_name: str,
) -> str:
    """Format a reason string for workflow-driven activation."""
    return (
        f"Workflow {workflow_variant} step '{step_name}' completed. "
        f"Merchant activated to ACTIVE status."
    )
