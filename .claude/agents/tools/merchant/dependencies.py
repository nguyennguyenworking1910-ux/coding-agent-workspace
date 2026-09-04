"""Dependency graph validation and readiness evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from claude.agents.tools.merchant.state_machine import (
    normalize_step_status,
)
from claude.agents.tools.merchant.workflow import (
    DEPENDENCY_TYPES,
)


class DependencyValidationError(ValueError):
    """Base error for invalid project-step dependencies."""


class UnknownDependencyStepError(DependencyValidationError):
    """Raised when a dependency references an unknown step."""


class DuplicateDependencyError(DependencyValidationError):
    """Raised when a dependency edge is repeated."""


class DependencyCycleError(DependencyValidationError):
    """Raised when project-step dependencies contain a cycle."""


@dataclass(frozen=True, slots=True)
class DependencyReadiness:
    """Dependency readiness result for one project step."""

    step_id: str
    is_ready: bool
    direct_predecessor_ids: tuple[str, ...]
    transitive_predecessor_ids: tuple[str, ...]
    unmet_direct_predecessor_ids: tuple[str, ...]
    unmet_transitive_predecessor_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible readiness result."""

        return asdict(self)


def validate_dependency_graph(
    steps: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
) -> None:
    """Validate references, edge types, duplicates, and cycles."""

    _index_and_validate(steps, dependencies)


def transitive_predecessor_ids(
    step_id: str,
    steps: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return every direct and indirect predecessor."""

    step_index, predecessors = _index_and_validate(
        steps,
        dependencies,
    )
    normalized_step_id = _normalize_identifier(
        step_id,
        "step_id",
    )

    if normalized_step_id not in step_index:
        raise UnknownDependencyStepError(
            f"Unknown project step: {normalized_step_id}"
        )

    return _predecessor_closure(
        normalized_step_id,
        predecessors,
    )


def evaluate_dependency_readiness(
    step_id: str,
    steps: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
) -> DependencyReadiness:
    """Evaluate direct and transitive dependency readiness."""

    step_index, predecessors = _index_and_validate(
        steps,
        dependencies,
    )
    normalized_step_id = _normalize_identifier(
        step_id,
        "step_id",
    )

    if normalized_step_id not in step_index:
        raise UnknownDependencyStepError(
            f"Unknown project step: {normalized_step_id}"
        )

    direct_ids = tuple(
        sorted(predecessors[normalized_step_id])
    )
    transitive_ids = _predecessor_closure(
        normalized_step_id,
        predecessors,
    )

    unmet_direct = tuple(
        predecessor_id
        for predecessor_id in direct_ids
        if _step_status(
            step_index[predecessor_id]
        ) != "COMPLETED"
    )
    unmet_transitive = tuple(
        predecessor_id
        for predecessor_id in transitive_ids
        if _step_status(
            step_index[predecessor_id]
        ) != "COMPLETED"
    )

    return DependencyReadiness(
        step_id=normalized_step_id,
        is_ready=not unmet_transitive,
        direct_predecessor_ids=direct_ids,
        transitive_predecessor_ids=transitive_ids,
        unmet_direct_predecessor_ids=unmet_direct,
        unmet_transitive_predecessor_ids=unmet_transitive,
    )


def dependency_ready_step_ids(
    steps: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return pending or blocked steps whose dependencies are met."""

    step_index, predecessors = _index_and_validate(
        steps,
        dependencies,
    )
    ready_ids = []

    for step_id in sorted(step_index):
        status = _step_status(step_index[step_id])

        if status not in {"PENDING", "BLOCKED"}:
            continue

        predecessor_ids = _predecessor_closure(
            step_id,
            predecessors,
        )

        if all(
            _step_status(step_index[predecessor_id])
            == "COMPLETED"
            for predecessor_id in predecessor_ids
        ):
            ready_ids.append(step_id)

    return tuple(ready_ids)


def _index_and_validate(
    steps: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, set[str]],
]:
    step_index: dict[str, Mapping[str, Any]] = {}

    for step in steps:
        step_id = _normalize_identifier(
            step.get("id"),
            "step.id",
        )

        if step_id in step_index:
            raise DependencyValidationError(
                f"Duplicate project step id: {step_id}"
            )

        # Validate status before graph evaluation.
        _step_status(step)
        step_index[step_id] = step

    predecessors = {
        step_id: set()
        for step_id in step_index
    }
    successors = {
        step_id: set()
        for step_id in step_index
    }
    edge_keys: set[tuple[str, str, str]] = set()

    for dependency in dependencies:
        from_step_id = _normalize_identifier(
            dependency.get("from_step_id"),
            "dependency.from_step_id",
        )
        to_step_id = _normalize_identifier(
            dependency.get("to_step_id"),
            "dependency.to_step_id",
        )
        dependency_type = str(
            dependency.get("dependency_type", "")
        ).strip().upper()

        if dependency_type not in DEPENDENCY_TYPES:
            raise DependencyValidationError(
                "Unsupported dependency type: "
                f"{dependency_type!r}"
            )

        if from_step_id not in step_index:
            raise UnknownDependencyStepError(
                "Dependency references unknown source step: "
                f"{from_step_id}"
            )

        if to_step_id not in step_index:
            raise UnknownDependencyStepError(
                "Dependency references unknown destination step: "
                f"{to_step_id}"
            )

        if from_step_id == to_step_id:
            raise DependencyCycleError(
                f"Step cannot depend on itself: {from_step_id}"
            )

        edge_key = (
            from_step_id,
            to_step_id,
            dependency_type,
        )

        if edge_key in edge_keys:
            raise DuplicateDependencyError(
                "Duplicate dependency edge: "
                f"{from_step_id} -> {to_step_id} "
                f"({dependency_type})"
            )

        edge_keys.add(edge_key)
        predecessors[to_step_id].add(from_step_id)
        successors[from_step_id].add(to_step_id)

    _assert_acyclic(step_index, predecessors, successors)

    return step_index, predecessors


def _assert_acyclic(
    step_index: Mapping[str, Mapping[str, Any]],
    predecessors: Mapping[str, set[str]],
    successors: Mapping[str, set[str]],
) -> None:
    remaining_counts = {
        step_id: len(predecessors[step_id])
        for step_id in step_index
    }
    ready = sorted(
        step_id
        for step_id, count in remaining_counts.items()
        if count == 0
    )
    visited = 0

    while ready:
        step_id = ready.pop(0)
        visited += 1

        for successor_id in sorted(successors[step_id]):
            remaining_counts[successor_id] -= 1

            if remaining_counts[successor_id] == 0:
                ready.append(successor_id)
                ready.sort()

    if visited != len(step_index):
        cyclic_ids = sorted(
            step_id
            for step_id, count in remaining_counts.items()
            if count > 0
        )

        raise DependencyCycleError(
            "Dependency graph contains a cycle involving: "
            + ", ".join(cyclic_ids)
        )


def _predecessor_closure(
    step_id: str,
    predecessors: Mapping[str, set[str]],
) -> tuple[str, ...]:
    discovered: set[str] = set()
    pending = list(predecessors[step_id])

    while pending:
        predecessor_id = pending.pop()

        if predecessor_id in discovered:
            continue

        discovered.add(predecessor_id)
        pending.extend(predecessors[predecessor_id])

    return tuple(sorted(discovered))


def _step_status(step: Mapping[str, Any]) -> str:
    try:
        return normalize_step_status(step.get("status"))
    except ValueError as error:
        step_id = step.get("id")

        raise DependencyValidationError(
            f"Invalid status for project step {step_id!r}: "
            f"{error}"
        ) from error


def _normalize_identifier(
    value: Any,
    field_name: str,
) -> str:
    if value is None:
        raise DependencyValidationError(
            f"{field_name} is required"
        )

    normalized = str(value).strip()

    if not normalized:
        raise DependencyValidationError(
            f"{field_name} cannot be empty"
        )

    return normalized