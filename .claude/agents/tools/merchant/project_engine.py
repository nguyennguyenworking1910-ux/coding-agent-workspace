"""Pure planning for Merchant project status transitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from claude.agents.tools.merchant.engine import (
    WorkflowVersionConflictError,
)
from claude.agents.tools.merchant.state_machine import (
    validate_project_transition,
)


PROJECT_TERMINAL_STEP_STATUSES = frozenset(
    {
        "COMPLETED",
        "SKIPPED",
        "SUPERSEDED",
    }
)


class ProjectEngineError(ValueError):
    """Base error for project-transition planning."""


class ProjectCompletionBlockedError(ProjectEngineError):
    """Raised when unfinished steps block completion."""


@dataclass(frozen=True, slots=True)
class ProjectTransitionPlan:
    """Validated, database-independent project mutation."""

    merchant_id: str
    project_id: str
    current_status: str
    target_status: str
    expected_version: int
    new_version: int
    started_at: datetime | None
    completed_at: datetime | None
    is_reopen: bool
    event_type: str
    old_values: dict[str, object]
    new_values: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["started_at"] = _serialized_datetime(
            self.started_at
        )
        payload["completed_at"] = _serialized_datetime(
            self.completed_at
        )
        return payload


def propose_project_transition(
    snapshot: Mapping[str, Any],
    target_status: str,
    *,
    expected_version: int,
    occurred_at: datetime | None = None,
    allow_reopen: bool = False,
) -> ProjectTransitionPlan:
    """Validate and plan one project status transition."""

    project = dict(snapshot.get("project") or {})

    if not project:
        raise ProjectEngineError(
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

    current_version = _positive_version(
        project.get("version"),
        "project.version",
    )
    normalized_expected_version = _positive_version(
        expected_version,
        "expected_version",
    )

    if current_version != normalized_expected_version:
        raise WorkflowVersionConflictError(
            "Project version conflict: "
            f"expected {normalized_expected_version}, "
            f"current {current_version}"
        )

    decision = validate_project_transition(
        str(project.get("status", "")),
        target_status,
        allow_reopen=allow_reopen,
    )

    steps = [
        dict(step)
        for step in snapshot.get("steps", ())
    ]

    if decision.target_status == "COMPLETED":
        _validate_project_completion(
            project_id,
            steps,
        )

    effective_time = _effective_time(occurred_at)

    started_at = _optional_datetime(
        project.get("started_at"),
        "project.started_at",
    )
    completed_at = _optional_datetime(
        project.get("completed_at"),
        "project.completed_at",
    )

    if (
        decision.current_status == "PLANNED"
        and decision.target_status == "IN_PROGRESS"
        and started_at is None
    ):
        started_at = effective_time

    if decision.target_status == "COMPLETED":
        completed_at = effective_time

    if decision.is_reopen:
        completed_at = None

    new_version = current_version + 1

    old_values = {
        "status": decision.current_status,
        "version": current_version,
        "started_at": _serialized_datetime(
            _optional_datetime(
                project.get("started_at"),
                "project.started_at",
            )
        ),
        "completed_at": _serialized_datetime(
            _optional_datetime(
                project.get("completed_at"),
                "project.completed_at",
            )
        ),
    }

    new_values = {
        "status": decision.target_status,
        "version": new_version,
        "started_at": _serialized_datetime(
            started_at
        ),
        "completed_at": _serialized_datetime(
            completed_at
        ),
    }

    return ProjectTransitionPlan(
        merchant_id=merchant_id,
        project_id=project_id,
        current_status=decision.current_status,
        target_status=decision.target_status,
        expected_version=current_version,
        new_version=new_version,
        started_at=started_at,
        completed_at=completed_at,
        is_reopen=decision.is_reopen,
        event_type=_project_event_type(
            decision.target_status,
            decision.is_reopen,
        ),
        old_values=old_values,
        new_values=new_values,
    )


def _validate_project_completion(
    project_id: str,
    steps: Sequence[Mapping[str, Any]],
) -> None:
    if not steps:
        raise ProjectCompletionBlockedError(
            "Project cannot complete without workflow steps"
        )

    unfinished = []

    for step in steps:
        step_project_id = _identifier(
            step.get("project_id"),
            "project_step.project_id",
        )

        if step_project_id != project_id:
            raise ProjectEngineError(
                "Project snapshot contains a step "
                "from another project"
            )

        status = str(
            step.get("status", "")
        ).strip().upper()

        if status not in PROJECT_TERMINAL_STEP_STATUSES:
            unfinished.append(
                _identifier(
                    step.get("id"),
                    "project_step.id",
                )
            )

    if unfinished:
        raise ProjectCompletionBlockedError(
            "Project has unfinished workflow steps: "
            + ", ".join(sorted(unfinished))
        )


def _project_event_type(
    target_status: str,
    is_reopen: bool,
) -> str:
    if is_reopen:
        return "PROJECT_REOPENED"

    return {
        "IN_PROGRESS": "PROJECT_STARTED",
        "BLOCKED": "PROJECT_BLOCKED",
        "ON_HOLD": "PROJECT_ON_HOLD",
        "COMPLETED": "PROJECT_COMPLETED",
        "CANCELLED": "PROJECT_CANCELLED",
    }.get(
        target_status,
        "PROJECT_STATUS_CHANGED",
    )


def _identifier(
    value: Any,
    field_name: str,
) -> str:
    if value is None:
        raise ProjectEngineError(
            f"{field_name} is required"
        )

    normalized = str(value).strip()

    if not normalized:
        raise ProjectEngineError(
            f"{field_name} cannot be empty"
        )

    return normalized


def _positive_version(
    value: Any,
    field_name: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ProjectEngineError(
            f"{field_name} must be a positive integer"
        )

    return value


def _effective_time(
    value: datetime | None,
) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)

    if not isinstance(value, datetime):
        raise ProjectEngineError(
            "occurred_at must be a datetime"
        )

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _optional_datetime(
    value: Any,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None

    if not isinstance(value, datetime):
        raise ProjectEngineError(
            f"{field_name} must be a datetime or None"
        )

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _serialized_datetime(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    return value.astimezone(
        timezone.utc
    ).isoformat()