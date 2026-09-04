"""Conditional and parallel workflow branch resolution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from claude.agents.tools.merchant.workflow import (
    WorkflowTemplateDefinition,
    template_payload,
    template_uuid,
)


class BranchResolutionError(ValueError):
    """Raised when workflow branch input is invalid."""


@dataclass(frozen=True, slots=True)
class ResolvedStep:
    """Resolved inclusion and initial status for one step."""

    key: str
    branch_key: str | None
    included: bool
    initial_status: str
    condition_key: str | None
    condition_value: bool | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResolvedDependency:
    """Dependency remaining after conditional resolution."""

    from_step_key: str
    to_step_key: str
    dependency_type: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BranchResolution:
    """Complete resolved workflow-instantiation plan."""

    template_id: str
    template_name: str
    template_version: int
    steps: tuple[ResolvedStep, ...]
    dependencies: tuple[ResolvedDependency, ...]
    active_step_keys: tuple[str, ...]
    skipped_step_keys: tuple[str, ...]
    active_branch_keys: tuple[str, ...]
    skipped_branch_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def resolve_workflow_branches(
    template: WorkflowTemplateDefinition,
    project: Mapping[str, Any],
) -> BranchResolution:
    """Resolve conditional steps without collapsing parallel work."""

    # Validate the complete immutable definition first.
    template_payload(template)

    resolved_inclusion: dict[str, bool] = {}
    condition_values: dict[str, bool | None] = {}

    for step in template.steps:
        if step.step_type == "CONDITIONAL":
            if not step.is_optional:
                raise BranchResolutionError(
                    "Conditional step must be optional: "
                    f"{step.key}"
                )

            if step.condition_key is None:
                raise BranchResolutionError(
                    "Conditional step has no condition_key: "
                    f"{step.key}"
                )

            condition_value = _condition_value(
                project,
                step.condition_key,
            )
            resolved_inclusion[step.key] = condition_value
            condition_values[step.key] = condition_value
        else:
            if step.condition_key is not None:
                raise BranchResolutionError(
                    "Only CONDITIONAL steps may define "
                    f"condition_key: {step.key}"
                )

            resolved_inclusion[step.key] = True
            condition_values[step.key] = None

    active_dependencies = tuple(
        ResolvedDependency(
            from_step_key=dependency.from_step_key,
            to_step_key=dependency.to_step_key,
            dependency_type=dependency.dependency_type,
        )
        for dependency in template.dependencies
        if resolved_inclusion[dependency.from_step_key]
        and resolved_inclusion[dependency.to_step_key]
    )

    active_predecessors = {
        step.key: set()
        for step in template.steps
        if resolved_inclusion[step.key]
    }

    for dependency in active_dependencies:
        active_predecessors[
            dependency.to_step_key
        ].add(dependency.from_step_key)

    resolved_steps = tuple(
        ResolvedStep(
            key=step.key,
            branch_key=step.branch_key,
            included=resolved_inclusion[step.key],
            initial_status=(
                "SKIPPED"
                if not resolved_inclusion[step.key]
                else (
                    "PENDING"
                    if active_predecessors[step.key]
                    else "READY"
                )
            ),
            condition_key=step.condition_key,
            condition_value=condition_values[step.key],
        )
        for step in sorted(
            template.steps,
            key=lambda item: (
                item.sequence_number,
                item.key,
            ),
        )
    )

    active_step_keys = tuple(
        step.key
        for step in resolved_steps
        if step.included
    )
    skipped_step_keys = tuple(
        step.key
        for step in resolved_steps
        if not step.included
    )

    branch_members: dict[str, list[ResolvedStep]] = {}

    for step in resolved_steps:
        if step.branch_key is None:
            continue

        branch_members.setdefault(
            step.branch_key,
            [],
        ).append(step)

    active_branch_keys = tuple(
        sorted(
            branch_key
            for branch_key, members
            in branch_members.items()
            if any(member.included for member in members)
        )
    )
    skipped_branch_keys = tuple(
        sorted(
            branch_key
            for branch_key, members
            in branch_members.items()
            if all(
                not member.included
                for member in members
            )
        )
    )

    return BranchResolution(
        template_id=str(template_uuid(template)),
        template_name=template.name,
        template_version=template.version,
        steps=resolved_steps,
        dependencies=active_dependencies,
        active_step_keys=active_step_keys,
        skipped_step_keys=skipped_step_keys,
        active_branch_keys=active_branch_keys,
        skipped_branch_keys=skipped_branch_keys,
    )


def _condition_value(
    project: Mapping[str, Any],
    condition_key: str,
) -> bool:
    if condition_key not in project:
        raise BranchResolutionError(
            "Project is missing condition property: "
            f"{condition_key}"
        )

    value = project[condition_key]

    if not isinstance(value, bool):
        raise BranchResolutionError(
            "Project condition property must be boolean: "
            f"{condition_key}"
        )

    return value