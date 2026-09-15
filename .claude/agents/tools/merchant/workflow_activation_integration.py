"""Integration between workflow step transitions and merchant activation.

When the canonical ``activate_merchant`` step of the persisted
INTEGRATION_NEW_MERCHANT_STANDARD template reaches COMPLETED status, this
module transitions the merchant from ONBOARDING to ACTIVE inside the caller's
transaction and cursor.

Authorization is taken from persisted joins only:

- ``merchant_ops.workflow_templates`` supplies the template id, name and
  variant;
- ``merchant_ops.workflow_template_steps`` supplies the template-step id and
  its canonical name;
- ``merchant_ops.projects`` supplies the project type and the template version
  the project was instantiated from;
- ``merchant_ops.project_steps`` supplies the persisted ``template_step_id``.

Caller-supplied strings such as ``project["template_name"]`` or the mutable,
copied ``project_steps.step_name`` never authorize an activation on their own.
"""

from __future__ import annotations

import uuid
from typing import Any


WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT = "INTEGRATION_NEW_MERCHANT_STANDARD"
WORKFLOW_STEP_TEMPLATE_ACTIVATE_MERCHANT = "activate_merchant"
REQUIRED_STEP_STATUS_FOR_ACTIVATION = "COMPLETED"
REQUIRED_WORKFLOW_PROJECT_TYPE = "INTEGRATION_NEW_MERCHANT"
COMPLETED_DEPENDENCY_STATUS = "COMPLETED"
BLOCKING_DEPENDENCY_TYPES = frozenset(
    {
        "MUST_COMPLETE_BEFORE",
        "BLOCKS",
        "REQUIRES",
    }
)

# Workflow-driven activation is attributed to the system, not to the operator
# who completed the step. project_events.triggered_by is nullable and NULL is
# the established convention for system-generated Merchant events.
WORKFLOW_ACTIVATION_TRIGGERED_BY: str | None = None

# Namespace seed used by claude.agents.tools.merchant.workflow.template_step_uuid.
# The canonical template-step id for a key is uuid5(template_id, "step:<key>"),
# so the canonical activation step can be derived from the *persisted* template
# id without pinning a template version.
TEMPLATE_STEP_UUID_PREFIX = "step:"


class WorkflowActivationIntegrationError(RuntimeError):
    """Raised when workflow-to-activation integration fails."""


def normalize_step_key(value: Any) -> str:
    """Normalize a step name or key to its canonical lowercase key form."""

    return (
        str(value or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def canonical_activation_template_step_id(template_id: Any) -> str:
    """Return the canonical activate_merchant step id for a persisted template."""

    return str(
        uuid.uuid5(
            _uuid(template_id, "template_id"),
            f"{TEMPLATE_STEP_UUID_PREFIX}"
            f"{WORKFLOW_STEP_TEMPLATE_ACTIVATE_MERCHANT}",
        )
    )


def require_persisted_activation_identity(
    project: dict[str, Any],
    step: dict[str, Any],
) -> dict[str, str]:
    """Authorize activation from persisted template and template-step identity.

    Returns the persisted identity that authorized the activation.

    Raises:
        WorkflowActivationIntegrationError: when any persisted field is
            missing, inconsistent, or not the canonical activation pair.
    """

    project_type = str(project.get("project_type", "")).strip().upper()

    if project_type != REQUIRED_WORKFLOW_PROJECT_TYPE:
        raise WorkflowActivationIntegrationError(
            f"Project type {project_type or '<missing>'} does not support "
            "workflow-driven merchant activation"
        )

    template_id = _required_identity(
        project.get("template_id"),
        "persisted workflow template id",
    )
    project_template_id = _required_identity(
        project.get("workflow_template_version_id"),
        "project workflow_template_version_id",
    )

    if template_id != project_template_id:
        raise WorkflowActivationIntegrationError(
            "Persisted workflow template id does not match the project's "
            f"workflow_template_version_id: {template_id} != "
            f"{project_template_id}"
        )

    template_name = str(project.get("template_name", "")).strip().upper()

    if template_name != WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT:
        raise WorkflowActivationIntegrationError(
            f"Persisted workflow template {template_name or '<missing>'} "
            "does not support workflow-driven merchant activation"
        )

    template_variant = str(
        project.get("template_variant", "")
    ).strip().upper()

    if template_variant != WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT:
        raise WorkflowActivationIntegrationError(
            f"Persisted workflow variant {template_variant or '<missing>'} "
            "does not support workflow-driven merchant activation"
        )

    step_template_step_id = _required_identity(
        step.get("template_step_id"),
        "project step template_step_id",
    )
    joined_template_step_id = _required_identity(
        step.get("template_step_row_id"),
        "persisted workflow template step id",
    )

    if step_template_step_id != joined_template_step_id:
        raise WorkflowActivationIntegrationError(
            "Project step does not reference the persisted template step: "
            f"{step_template_step_id} != {joined_template_step_id}"
        )

    owning_template_id = _required_identity(
        step.get("template_step_template_id"),
        "persisted workflow template step template_id",
    )

    if owning_template_id != template_id:
        raise WorkflowActivationIntegrationError(
            "Persisted template step belongs to template "
            f"{owning_template_id}, not to the project's template "
            f"{template_id}"
        )

    canonical_step_id = canonical_activation_template_step_id(template_id)

    if step_template_step_id != canonical_step_id:
        raise WorkflowActivationIntegrationError(
            f"Persisted template step {step_template_step_id} is not the "
            "canonical "
            f"{WORKFLOW_STEP_TEMPLATE_ACTIVATE_MERCHANT} step "
            f"{canonical_step_id}"
        )

    canonical_step_name = normalize_step_key(step.get("template_step_name"))

    if canonical_step_name != WORKFLOW_STEP_TEMPLATE_ACTIVATE_MERCHANT:
        raise WorkflowActivationIntegrationError(
            f"Persisted template step {canonical_step_name or '<missing>'} "
            "does not trigger merchant activation"
        )

    return {
        "project_id": _required_identity(project.get("id"), "project id"),
        "project_type": project_type,
        "template_id": template_id,
        "template_name": template_name,
        "template_variant": template_variant,
        "template_step_id": step_template_step_id,
        "template_step_name": canonical_step_name,
    }


def should_activate_merchant_on_step_transition(
    step: dict[str, Any],
    project: dict[str, Any],
    target_step_status: str,
) -> bool:
    """Determine whether merchant activation should occur.

    Returns True only when the persisted template and template-step identity
    is the canonical INTEGRATION_NEW_MERCHANT_STANDARD activation pair and the
    step is transitioning to COMPLETED.
    """

    if str(target_step_status).strip().upper() != (
        REQUIRED_STEP_STATUS_FOR_ACTIVATION
    ):
        return False

    try:
        require_persisted_activation_identity(project, step)
    except WorkflowActivationIntegrationError:
        return False

    return True


def validate_activation_prerequisites(
    project: dict[str, Any],
    step: dict[str, Any],
    project_steps: list[dict[str, Any]],
    dependencies: list[dict[str, Any]] | tuple = (),
) -> dict[str, str]:
    """Validate every prerequisite for workflow-driven merchant activation.

    Checks persisted template identity, that the step belongs to the locked
    project snapshot, and that every blocking predecessor step has completed.
    """

    identity = require_persisted_activation_identity(project, step)

    step_id = str(step.get("id", ""))
    steps_by_id = {
        str(record.get("id")): record
        for record in project_steps
    }

    if step_id not in steps_by_id:
        raise WorkflowActivationIntegrationError(
            f"Step {step_id or '<missing>'} not found in project"
        )

    for dependency in dependencies or ():
        if str(dependency.get("to_step_id", "")) != step_id:
            continue

        dependency_type = str(
            dependency.get("dependency_type", "")
        ).strip().upper()

        if dependency_type not in BLOCKING_DEPENDENCY_TYPES:
            continue

        predecessor_id = str(dependency.get("from_step_id", ""))
        predecessor = steps_by_id.get(predecessor_id)

        if predecessor is None:
            raise WorkflowActivationIntegrationError(
                f"Dependency step {predecessor_id or '<missing>'} not found"
            )

        predecessor_status = str(
            predecessor.get("status", "")
        ).strip().upper()

        if predecessor_status != COMPLETED_DEPENDENCY_STATUS:
            raise WorkflowActivationIntegrationError(
                f"Dependency step {predecessor_id} has not completed "
                f"(current status: {predecessor_status or '<missing>'})"
            )

    return identity


def activate_merchant_in_workflow_transaction(
    cursor: Any,
    merchant_id: str,
    expected_version: int,
    project: dict[str, Any],
    step: dict[str, Any],
    project_steps: list[dict[str, Any]],
    dependencies: list[dict[str, Any]] | tuple = (),
) -> dict[str, Any]:
    """Activate a merchant inside the caller's workflow transaction.

    Uses the provided cursor to validate persisted authorization, lock and read
    the merchant, perform the ONBOARDING -> ACTIVE transition, and insert one
    project-scoped MERCHANT activation event.

    Opens no connection and no transaction. Any failure raises, which rolls the
    caller's transaction back.
    """

    from claude.agents.tools.merchant.merchant_engine import (
        propose_merchant_activation,
    )
    from claude.clients.merchant.merchant_repository import (
        insert_merchant_activation_event,
    )

    identity = validate_activation_prerequisites(
        project,
        step,
        project_steps,
        dependencies,
    )

    merchant_uuid = _uuid(merchant_id, "merchant_id")

    cursor.execute(
        """
        SELECT id, code, account_status, version
        FROM merchant_ops.merchants
        WHERE id = %s
        FOR UPDATE
        """,
        (merchant_uuid,),
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

    reason = format_activation_reason_for_workflow(
        identity["template_variant"],
        identity["template_step_name"],
    )

    plan = propose_merchant_activation(
        merchant,
        expected_version=expected_version,
        reason=reason,
        triggered_by=WORKFLOW_ACTIVATION_TRIGGERED_BY,
    )

    event_id = uuid.uuid4()

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
            uuid.UUID(plan.merchant_id),
            plan.current_status,
            plan.expected_version,
        ),
    )

    rowcount = cursor.rowcount

    if rowcount != 1:
        raise WorkflowActivationIntegrationError(
            f"Merchant activation update affected {rowcount} rows, "
            "expected exactly 1"
        )

    # project_events_valid_entity_check requires project_id IS NULL on every
    # MERCHANT event, so the authorizing project, template and template step
    # are recorded in new_values instead of the project_id column.
    insert_merchant_activation_event(
        cursor,
        plan,
        event_id,
        triggered_by=WORKFLOW_ACTIVATION_TRIGGERED_BY,
        provenance={
            "project_id": identity["project_id"],
            "workflow_template_id": identity["template_id"],
            "workflow_template_name": identity["template_name"],
            "workflow_template_step_id": identity["template_step_id"],
            "workflow_template_step_name": identity["template_step_name"],
        },
    )

    return {
        "success": True,
        "merchant_id": str(plan.merchant_id),
        "project_id": identity["project_id"],
        "template_id": identity["template_id"],
        "template_step_id": identity["template_step_id"],
        "previous_status": plan.current_status,
        "current_status": plan.target_status,
        "previous_version": plan.expected_version,
        "current_version": plan.new_merchant_version,
        "event_id": str(event_id),
        "event_type": plan.event_type,
    }


def prepare_merchant_activation_from_step(
    project: dict[str, Any],
    step: dict[str, Any],
) -> dict[str, Any]:
    """Build a merchant activation request from step transition context."""

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
        "triggered_by": WORKFLOW_ACTIVATION_TRIGGERED_BY,
    }


def format_activation_reason_for_workflow(
    workflow_variant: str,
    step_name: str,
) -> str:
    """Format a reason string for workflow-driven activation."""

    return (
        f"Workflow {workflow_variant} step '{step_name}' completed. "
        "Merchant activated to ACTIVE status."
    )


def _required_identity(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()

    if not normalized:
        raise WorkflowActivationIntegrationError(
            f"Missing {field_name} required for workflow activation"
        )

    return str(_uuid(normalized, field_name))


def _uuid(value: Any, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value

    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise WorkflowActivationIntegrationError(
            f"{field_name} must be a valid UUID"
        ) from error
