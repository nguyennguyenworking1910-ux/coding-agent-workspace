"""Pure workflow transition planning for Merchant projects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from claude.agents.tools.merchant.dependencies import (
    evaluate_dependency_readiness,
)
from claude.agents.tools.merchant.gates import (
    GateValidationResult,
)
from claude.agents.tools.merchant.state_machine import (
    validate_step_transition,
)


class WorkflowEngineError(ValueError):
    """Base workflow transition planning error."""


class WorkflowStepNotFoundError(WorkflowEngineError):
    """Raised when the requested project step is absent."""


class WorkflowVersionConflictError(WorkflowEngineError):
    """Raised when optimistic versions do not match."""


class WorkflowDependencyNotMetError(
    WorkflowEngineError
):
    """Raised when a transition has unmet dependencies."""


class WorkflowGateNotMetError(WorkflowEngineError):
    """Raised when a required gate has not passed."""


@dataclass(frozen=True, slots=True)
class StepTransitionPlan:
    """Validated plan for one atomic step mutation."""

    merchant_id: str
    project_id: str
    step_id: str
    current_status: str
    target_status: str
    expected_version: int
    new_version: int
    actual_start: datetime | None
    actual_completion: datetime | None
    is_reopen: bool
    event_type: str
    old_values: dict[str, Any]
    new_values: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        result = asdict(self)

        for field_name in (
            "actual_start",
            "actual_completion",
        ):
            value = result[field_name]

            if isinstance(value, datetime):
                result[field_name] = value.isoformat()

        return result


def propose_step_transition(
    snapshot: Mapping[str, Any],
    step_id: str,
    target_status: str,
    *,
    expected_version: int,
    occurred_at: datetime | None = None,
    allow_reopen: bool = False,
    gate_required: bool = False,
    gate_result: GateValidationResult | None = None,
) -> StepTransitionPlan:
    """Validate and plan a project-step status transition."""

    project = dict(snapshot.get("project") or {})

    if not project:
        raise WorkflowEngineError(
            "Project snapshot has no project record"
        )

    merchant_id = _identifier(
        project.get("merchant_id"),
        "project.merchant_id",
    )
    project_id = _identifier(
        project.get("id"),
        "project.id",
    )
    normalized_step_id = _identifier(
        step_id,
        "step_id",
    )

    steps = [
        dict(step)
        for step in snapshot.get("steps", ())
    ]
    dependencies = [
        dict(dependency)
        for dependency in snapshot.get(
            "dependencies",
            (),
        )
    ]

    matching_steps = [
        step
        for step in steps
        if _identifier(
            step.get("id"),
            "project_step.id",
        ) == normalized_step_id
    ]

    if not matching_steps:
        raise WorkflowStepNotFoundError(
            f"Project step not found: {normalized_step_id}"
        )

    if len(matching_steps) > 1:
        raise WorkflowEngineError(
            "Project snapshot contains duplicate step id: "
            f"{normalized_step_id}"
        )

    step = matching_steps[0]
    step_project_id = _identifier(
        step.get("project_id"),
        "project_step.project_id",
    )

    if step_project_id != project_id:
        raise WorkflowEngineError(
            "Project step does not belong to snapshot project"
        )

    current_version = _positive_version(
        step.get("version"),
        "project_step.version",
    )
    normalized_expected_version = _positive_version(
        expected_version,
        "expected_version",
    )

    if current_version != normalized_expected_version:
        raise WorkflowVersionConflictError(
            "Project step version conflict: "
            f"expected {normalized_expected_version}, "
            f"current {current_version}"
        )

    decision = validate_step_transition(
        str(step.get("status", "")),
        target_status,
        allow_reopen=allow_reopen,
    )

    if decision.target_status in {
        "READY",
        "IN_PROGRESS",
        "COMPLETED",
    }:
        readiness = evaluate_dependency_readiness(
            normalized_step_id,
            steps,
            dependencies,
        )

        if not readiness.is_ready:
            raise WorkflowDependencyNotMetError(
                "Project step has unmet dependencies: "
                + ", ".join(
                    readiness.unmet_transitive_predecessor_ids
                )
            )

    if gate_required:
        _validate_gate(
            project_id,
            gate_result,
        )

    effective_time = _effective_time(occurred_at)
    existing_actual_start = _optional_datetime(
        step.get("actual_start"),
        "project_step.actual_start",
    )
    existing_actual_completion = _optional_datetime(
        step.get("actual_completion"),
        "project_step.actual_completion",
    )

    actual_start = existing_actual_start
    actual_completion = existing_actual_completion

    if decision.is_reopen:
        actual_start = None
        actual_completion = None

    elif decision.requires_actual_start:
        actual_start = effective_time

    if decision.requires_actual_completion:
        actual_completion = effective_time

    new_version = current_version + 1
    event_type = _event_type(decision)

    old_values = {
        "status": decision.current_status,
        "version": current_version,
        "actual_start": _serialized_datetime(
            existing_actual_start
        ),
        "actual_completion": _serialized_datetime(
            existing_actual_completion
        ),
    }
    new_values = {
        "status": decision.target_status,
        "version": new_version,
        "actual_start": _serialized_datetime(
            actual_start
        ),
        "actual_completion": _serialized_datetime(
            actual_completion
        ),
    }

    return StepTransitionPlan(
        merchant_id=merchant_id,
        project_id=project_id,
        step_id=normalized_step_id,
        current_status=decision.current_status,
        target_status=decision.target_status,
        expected_version=current_version,
        new_version=new_version,
        actual_start=actual_start,
        actual_completion=actual_completion,
        is_reopen=decision.is_reopen,
        event_type=event_type,
        old_values=old_values,
        new_values=new_values,
    )


def _validate_gate(
    project_id: str,
    gate_result: GateValidationResult | None,
) -> None:
    if gate_result is None:
        raise WorkflowGateNotMetError(
            "A gate result is required for this transition"
        )

    if gate_result.project_id != project_id:
        raise WorkflowGateNotMetError(
            "Gate result belongs to another project"
        )

    if not gate_result.all_met:
        blocking_codes = ", ".join(
            gate_result.blocking_codes
        )

        raise WorkflowGateNotMetError(
            "Workflow gate is not satisfied: "
            f"{blocking_codes}"
        )


def _event_type(decision: Any) -> str:
    if decision.is_reopen:
        return "STEP_REOPENED"

    if decision.target_status == "COMPLETED":
        return "STEP_COMPLETED"

    if decision.target_status == "BLOCKED":
        return "STEP_BLOCKED"

    if decision.target_status == "SKIPPED":
        return "STEP_SKIPPED"

    if decision.target_status == "SUPERSEDED":
        return "STEP_SUPERSEDED"

    if decision.target_status == "IN_PROGRESS":
        return "STEP_STARTED"

    if decision.target_status == "READY":
        return "STEP_READY"

    return "STEP_STATUS_CHANGED"


def _effective_time(
    value: datetime | None,
) -> datetime:
    effective = value or datetime.now(timezone.utc)

    if not isinstance(effective, datetime):
        raise WorkflowEngineError(
            "occurred_at must be a datetime or None"
        )

    if effective.tzinfo is None:
        raise WorkflowEngineError(
            "occurred_at must be timezone-aware"
        )

    return effective.astimezone(timezone.utc)


def _optional_datetime(
    value: Any,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None

    if not isinstance(value, datetime):
        raise WorkflowEngineError(
            f"{field_name} must be a datetime or None"
        )

    if value.tzinfo is None:
        raise WorkflowEngineError(
            f"{field_name} must be timezone-aware"
        )

    return value.astimezone(timezone.utc)


def _serialized_datetime(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    return value.isoformat()


def _positive_version(
    value: Any,
    field_name: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise WorkflowEngineError(
            f"{field_name} must be a positive integer"
        )

    return value


def _identifier(value: Any, field_name: str) -> str:
    if value is None:
        raise WorkflowEngineError(
            f"{field_name} is required"
        )

    normalized = str(value).strip()

    if not normalized:
        raise WorkflowEngineError(
            f"{field_name} cannot be empty"
        )

    return normalized