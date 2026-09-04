"""Pure status-transition rules for Merchant workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


PROJECT_STATUSES = frozenset(
    {
        "PLANNED",
        "IN_PROGRESS",
        "BLOCKED",
        "ON_HOLD",
        "COMPLETED",
        "CANCELLED",
    }
)

STEP_STATUSES = frozenset(
    {
        "PENDING",
        "READY",
        "IN_PROGRESS",
        "BLOCKED",
        "COMPLETED",
        "SKIPPED",
        "SUPERSEDED",
    }
)

TERMINAL_PROJECT_STATUSES = frozenset(
    {
        "COMPLETED",
        "CANCELLED",
    }
)

TERMINAL_STEP_STATUSES = frozenset(
    {
        "COMPLETED",
        "SKIPPED",
        "SUPERSEDED",
    }
)

PROJECT_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "PLANNED": frozenset(
        {
            "IN_PROGRESS",
            "CANCELLED",
        }
    ),
    "IN_PROGRESS": frozenset(
        {
            "BLOCKED",
            "ON_HOLD",
            "COMPLETED",
            "CANCELLED",
        }
    ),
    "BLOCKED": frozenset(
        {
            "IN_PROGRESS",
            "ON_HOLD",
            "CANCELLED",
        }
    ),
    "ON_HOLD": frozenset(
        {
            "IN_PROGRESS",
            "CANCELLED",
        }
    ),
    "COMPLETED": frozenset(),
    "CANCELLED": frozenset(),
}

STEP_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "PENDING": frozenset(
        {
            "READY",
            "BLOCKED",
            "SKIPPED",
            "SUPERSEDED",
        }
    ),
    "READY": frozenset(
        {
            "IN_PROGRESS",
            "BLOCKED",
            "SKIPPED",
            "SUPERSEDED",
        }
    ),
    "IN_PROGRESS": frozenset(
        {
            "BLOCKED",
            "COMPLETED",
            "SUPERSEDED",
        }
    ),
    "BLOCKED": frozenset(
        {
            "READY",
            "SUPERSEDED",
        }
    ),
    "COMPLETED": frozenset(
        {
            "SUPERSEDED",
        }
    ),
    "SKIPPED": frozenset(),
    "SUPERSEDED": frozenset(),
}

PROJECT_REOPEN_TRANSITIONS = frozenset(
    {
        ("COMPLETED", "IN_PROGRESS"),
    }
)

STEP_REOPEN_TRANSITIONS = frozenset(
    {
        ("COMPLETED", "READY"),
        ("SKIPPED", "READY"),
    }
)


class WorkflowStateError(ValueError):
    """Base error for workflow status validation."""


class UnknownProjectStatusError(WorkflowStateError):
    """Raised when a project status is not recognized."""


class UnknownStepStatusError(WorkflowStateError):
    """Raised when a step status is not recognized."""


class InvalidProjectTransitionError(WorkflowStateError):
    """Raised when a project transition is not allowed."""


class InvalidStepTransitionError(WorkflowStateError):
    """Raised when a step transition is not allowed."""


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    """Normalized result of a valid transition request."""

    entity_type: str
    current_status: str
    target_status: str
    is_reopen: bool
    requires_actual_start: bool
    requires_actual_completion: bool
    clears_actual_completion: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible transition description."""

        return asdict(self)


def normalize_project_status(status: str) -> str:
    """Normalize and validate a project status."""

    try:
        normalized = _normalize_status(status)
    except WorkflowStateError as error:
        raise UnknownProjectStatusError(
            str(error)
        ) from error

    if normalized not in PROJECT_STATUSES:
        raise UnknownProjectStatusError(
            f"Unknown project status: {status!r}"
        )

    return normalized


def normalize_step_status(status: str) -> str:
    """Normalize and validate a project-step status."""

    try:
        normalized = _normalize_status(status)
    except WorkflowStateError as error:
        raise UnknownStepStatusError(
            str(error)
        ) from error

    if normalized not in STEP_STATUSES:
        raise UnknownStepStatusError(
            f"Unknown step status: {status!r}"
        )

    return normalized

def can_transition_project(
    current_status: str,
    target_status: str,
    *,
    allow_reopen: bool = False,
) -> bool:
    """Return whether a project transition is valid."""

    try:
        current = normalize_project_status(current_status)
        target = normalize_project_status(target_status)
    except WorkflowStateError:
        return False

    if current == target:
        return False

    if target in PROJECT_TRANSITIONS[current]:
        return True

    return (
        allow_reopen
        and (current, target)
        in PROJECT_REOPEN_TRANSITIONS
    )


def can_transition_step(
    current_status: str,
    target_status: str,
    *,
    allow_reopen: bool = False,
) -> bool:
    """Return whether a step transition is valid."""

    try:
        current = normalize_step_status(current_status)
        target = normalize_step_status(target_status)
    except WorkflowStateError:
        return False

    if current == target:
        return False

    if target in STEP_TRANSITIONS[current]:
        return True

    return (
        allow_reopen
        and (current, target)
        in STEP_REOPEN_TRANSITIONS
    )


def validate_project_transition(
    current_status: str,
    target_status: str,
    *,
    allow_reopen: bool = False,
) -> TransitionDecision:
    """Validate and describe a project transition."""

    current = normalize_project_status(current_status)
    target = normalize_project_status(target_status)

    if current == target:
        raise InvalidProjectTransitionError(
            "Project status is already "
            f"{current}; no state change requested"
        )

    is_reopen = (
        (current, target)
        in PROJECT_REOPEN_TRANSITIONS
    )

    if (
        target not in PROJECT_TRANSITIONS[current]
        and not (allow_reopen and is_reopen)
    ):
        raise InvalidProjectTransitionError(
            "Invalid project transition: "
            f"{current} -> {target}"
        )

    return TransitionDecision(
        entity_type="PROJECT",
        current_status=current,
        target_status=target,
        is_reopen=is_reopen,
        requires_actual_start=False,
        requires_actual_completion=(
            target == "COMPLETED"
        ),
        clears_actual_completion=is_reopen,
    )


def validate_step_transition(
    current_status: str,
    target_status: str,
    *,
    allow_reopen: bool = False,
) -> TransitionDecision:
    """Validate and describe a project-step transition."""

    current = normalize_step_status(current_status)
    target = normalize_step_status(target_status)

    if current == target:
        raise InvalidStepTransitionError(
            "Step status is already "
            f"{current}; no state change requested"
        )

    is_reopen = (
        (current, target)
        in STEP_REOPEN_TRANSITIONS
    )

    if (
        target not in STEP_TRANSITIONS[current]
        and not (allow_reopen and is_reopen)
    ):
        raise InvalidStepTransitionError(
            "Invalid step transition: "
            f"{current} -> {target}"
        )

    return TransitionDecision(
        entity_type="STEP",
        current_status=current,
        target_status=target,
        is_reopen=is_reopen,
        requires_actual_start=(
            target == "IN_PROGRESS"
            and current == "READY"
        ),
        requires_actual_completion=(
            target == "COMPLETED"
        ),
        clears_actual_completion=is_reopen,
    )


def _normalize_status(status: str) -> str:
    if not isinstance(status, str):
        raise WorkflowStateError(
            "Workflow status must be a string"
        )

    normalized = status.strip().upper()

    if not normalized:
        raise WorkflowStateError(
            "Workflow status cannot be empty"
        )

    return normalized