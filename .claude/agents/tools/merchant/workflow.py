"""Pure workflow definitions and dependency validation for Merchant."""

from __future__ import annotations

import hashlib
import heapq
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any


STEP_TYPES = frozenset(
    {
        "SEQUENTIAL",
        "PARALLEL_BRANCH",
        "CONDITIONAL",
        "APPROVAL_GATE",
    }
)

DEPENDENCY_TYPES = frozenset(
    {
        "MUST_COMPLETE_BEFORE",
        "BLOCKS",
        "REQUIRES",
    }
)

PROJECT_TYPES = frozenset(
    {
        "MEDIA_TOP_UP",
        "OPENING_NEW_CINEMA",
        "INTEGRATION_NEW_MERCHANT",
    }
)

ALLOWED_CONDITION_KEYS = frozenset(
    {
        "requires_procurement",
    }
)

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_VARIANT_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

WORKFLOW_ID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://coding-agent-workspace/merchant/workflows",
)


class WorkflowDefinitionError(ValueError):
    """Raised when a workflow definition violates its contract."""


@dataclass(frozen=True, slots=True)
class WorkflowStepDefinition:
    """One immutable step in a workflow template."""

    key: str
    sequence_number: int
    step_type: str
    name: str
    description: str | None = None
    branch_key: str | None = None
    is_optional: bool = False
    condition_key: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowDependencyDefinition:
    """One directed dependency between two template steps."""

    from_step_key: str
    to_step_key: str
    dependency_type: str = "MUST_COMPLETE_BEFORE"


@dataclass(frozen=True, slots=True)
class WorkflowTemplateDefinition:
    """One immutable, versioned workflow template."""

    name: str
    version: int
    project_type: str
    variant: str
    description: str
    steps: tuple[WorkflowStepDefinition, ...]
    dependencies: tuple[
        WorkflowDependencyDefinition,
        ...,
    ] = ()
    is_active: bool = True


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowDefinitionError(
            f"{field_name} must be a non-empty string"
        )


def _require_key(value: str, field_name: str) -> None:
    _require_non_empty(value, field_name)

    if _KEY_PATTERN.fullmatch(value) is None:
        raise WorkflowDefinitionError(
            f"{field_name} must match "
            "^[a-z][a-z0-9_]*$"
        )


def _topological_order_unchecked(
    template: WorkflowTemplateDefinition,
) -> tuple[str, ...]:
    step_by_key = {
        step.key: step
        for step in template.steps
    }
    successors = {
        key: set()
        for key in step_by_key
    }
    indegree = {
        key: 0
        for key in step_by_key
    }

    for dependency in template.dependencies:
        source = dependency.from_step_key
        destination = dependency.to_step_key

        successors[source].add(destination)
        indegree[destination] += 1

    ready = [
        (
            step_by_key[key].sequence_number,
            key,
        )
        for key, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(ready)

    ordered: list[str] = []

    while ready:
        _, key = heapq.heappop(ready)
        ordered.append(key)

        for destination in sorted(
            successors[key],
            key=lambda item: (
                step_by_key[item].sequence_number,
                item,
            ),
        ):
            indegree[destination] -= 1

            if indegree[destination] == 0:
                heapq.heappush(
                    ready,
                    (
                        step_by_key[
                            destination
                        ].sequence_number,
                        destination,
                    ),
                )

    if len(ordered) != len(step_by_key):
        cyclic_keys = sorted(
            key
            for key, degree in indegree.items()
            if degree > 0
        )
        raise WorkflowDefinitionError(
            "Workflow dependencies contain a cycle: "
            + ", ".join(cyclic_keys)
        )

    return tuple(ordered)


def validate_template_definition(
    template: WorkflowTemplateDefinition,
) -> WorkflowTemplateDefinition:
    """Validate one template and return it unchanged."""

    if not isinstance(template, WorkflowTemplateDefinition):
        raise WorkflowDefinitionError(
            "template must be a WorkflowTemplateDefinition"
        )

    _require_non_empty(template.name, "template.name")
    _require_non_empty(
        template.description,
        "template.description",
    )

    if template.version <= 0:
        raise WorkflowDefinitionError(
            "template.version must be greater than zero"
        )

    if template.project_type not in PROJECT_TYPES:
        raise WorkflowDefinitionError(
            "Unsupported project type: "
            f"{template.project_type}"
        )

    if (
        _VARIANT_PATTERN.fullmatch(template.variant)
        is None
    ):
        raise WorkflowDefinitionError(
            "template.variant must match "
            "^[A-Z][A-Z0-9_]*$"
        )

    if template.name != template.variant:
        raise WorkflowDefinitionError(
            "Standard template name and variant must match"
        )

    if not template.steps:
        raise WorkflowDefinitionError(
            "Workflow template must contain at least one step"
        )

    step_by_key: dict[str, WorkflowStepDefinition] = {}
    sequence_numbers: set[int] = set()

    for step in template.steps:
        _require_key(step.key, "step.key")
        _require_non_empty(step.name, "step.name")

        if step.key in step_by_key:
            raise WorkflowDefinitionError(
                f"Duplicate workflow step key: {step.key}"
            )

        if step.sequence_number <= 0:
            raise WorkflowDefinitionError(
                "Step sequence numbers must be positive"
            )

        if step.sequence_number in sequence_numbers:
            raise WorkflowDefinitionError(
                "Duplicate workflow step sequence number: "
                f"{step.sequence_number}"
            )

        if step.step_type not in STEP_TYPES:
            raise WorkflowDefinitionError(
                f"Unsupported step type: {step.step_type}"
            )

        if step.branch_key is not None:
            _require_key(
                step.branch_key,
                "step.branch_key",
            )

        if (
            step.step_type == "PARALLEL_BRANCH"
            and step.branch_key is None
        ):
            raise WorkflowDefinitionError(
                "PARALLEL_BRANCH steps require branch_key"
            )

        if step.condition_key is not None:
            _require_key(
                step.condition_key,
                "step.condition_key",
            )

            if (
                step.condition_key
                not in ALLOWED_CONDITION_KEYS
            ):
                raise WorkflowDefinitionError(
                    "Unsupported condition key: "
                    f"{step.condition_key}"
                )

            if not step.is_optional:
                raise WorkflowDefinitionError(
                    "Conditional steps must be optional"
                )

        if step.is_optional and step.condition_key is None:
            raise WorkflowDefinitionError(
                "Optional steps require condition_key"
            )

        if step.step_type == "CONDITIONAL":
            if (
                not step.is_optional
                or step.condition_key is None
            ):
                raise WorkflowDefinitionError(
                    "CONDITIONAL steps must be optional "
                    "and declare condition_key"
                )

        step_by_key[step.key] = step
        sequence_numbers.add(step.sequence_number)

    expected_sequences = set(
        range(1, len(template.steps) + 1)
    )

    if sequence_numbers != expected_sequences:
        raise WorkflowDefinitionError(
            "Step sequence numbers must be contiguous "
            "starting at 1"
        )

    dependency_pairs: set[tuple[str, str]] = set()

    for dependency in template.dependencies:
        source = dependency.from_step_key
        destination = dependency.to_step_key

        if source not in step_by_key:
            raise WorkflowDefinitionError(
                "Dependency references unknown source step: "
                f"{source}"
            )

        if destination not in step_by_key:
            raise WorkflowDefinitionError(
                "Dependency references unknown destination "
                f"step: {destination}"
            )

        if source == destination:
            raise WorkflowDefinitionError(
                f"Step cannot depend on itself: {source}"
            )

        if (
            dependency.dependency_type
            not in DEPENDENCY_TYPES
        ):
            raise WorkflowDefinitionError(
                "Unsupported dependency type: "
                f"{dependency.dependency_type}"
            )

        pair = (source, destination)

        if pair in dependency_pairs:
            raise WorkflowDefinitionError(
                "Duplicate dependency edge: "
                f"{source} -> {destination}"
            )

        dependency_pairs.add(pair)

    _topological_order_unchecked(template)

    return template


def topological_step_keys(
    template: WorkflowTemplateDefinition,
) -> tuple[str, ...]:
    """Return deterministic dependency-safe step order."""

    validate_template_definition(template)
    return _topological_order_unchecked(template)


def transitive_dependency_closure(
    template: WorkflowTemplateDefinition,
) -> dict[str, tuple[str, ...]]:
    """Return all direct and indirect predecessors per step."""

    validate_template_definition(template)

    step_by_key = {
        step.key: step
        for step in template.steps
    }
    direct_predecessors = {
        key: set()
        for key in step_by_key
    }

    for dependency in template.dependencies:
        direct_predecessors[
            dependency.to_step_key
        ].add(dependency.from_step_key)

    closure = {
        key: set()
        for key in step_by_key
    }

    for key in _topological_order_unchecked(template):
        for predecessor in direct_predecessors[key]:
            closure[key].add(predecessor)
            closure[key].update(
                closure[predecessor]
            )

    def sort_key(key: str) -> tuple[int, str]:
        return (
            step_by_key[key].sequence_number,
            key,
        )

    return {
        key: tuple(
            sorted(
                predecessors,
                key=sort_key,
            )
        )
        for key, predecessors in closure.items()
    }


def template_uuid(
    template: WorkflowTemplateDefinition,
) -> uuid.UUID:
    """Return the stable UUID for a template version."""

    return uuid.uuid5(
        WORKFLOW_ID_NAMESPACE,
        (
            f"template:{template.name}:"
            f"{template.version}"
        ),
    )


def template_step_uuid(
    template: WorkflowTemplateDefinition,
    step_key: str,
) -> uuid.UUID:
    """Return the stable UUID for one template step."""

    if step_key not in {
        step.key
        for step in template.steps
    }:
        raise WorkflowDefinitionError(
            f"Unknown workflow step key: {step_key}"
        )

    return uuid.uuid5(
        template_uuid(template),
        f"step:{step_key}",
    )


def template_dependency_uuid(
    template: WorkflowTemplateDefinition,
    dependency: WorkflowDependencyDefinition,
) -> uuid.UUID:
    """Return the stable UUID for one dependency edge."""

    if dependency not in template.dependencies:
        raise WorkflowDefinitionError(
            "Dependency does not belong to template"
        )

    return uuid.uuid5(
        template_uuid(template),
        (
            "dependency:"
            f"{dependency.from_step_key}:"
            f"{dependency.to_step_key}:"
            f"{dependency.dependency_type}"
        ),
    )


def template_payload(
    template: WorkflowTemplateDefinition,
) -> dict[str, Any]:
    """Return the canonical serializable template payload."""

    validate_template_definition(template)

    return {
        "name": template.name,
        "version": template.version,
        "project_type": template.project_type,
        "variant": template.variant,
        "description": template.description,
        "is_active": template.is_active,
        "steps": [
            {
                "key": step.key,
                "sequence_number":
                    step.sequence_number,
                "step_type": step.step_type,
                "name": step.name,
                "description": step.description,
                "branch_key": step.branch_key,
                "is_optional": step.is_optional,
                "condition_key": step.condition_key,
            }
            for step in sorted(
                template.steps,
                key=lambda item: (
                    item.sequence_number,
                    item.key,
                ),
            )
        ],
        "dependencies": [
            {
                "from_step_key":
                    dependency.from_step_key,
                "to_step_key":
                    dependency.to_step_key,
                "dependency_type":
                    dependency.dependency_type,
            }
            for dependency in sorted(
                template.dependencies,
                key=lambda item: (
                    item.from_step_key,
                    item.to_step_key,
                    item.dependency_type,
                ),
            )
        ],
    }


def template_fingerprint(
    template: WorkflowTemplateDefinition,
) -> str:
    """Return a stable SHA-256 definition fingerprint."""

    canonical_json = json.dumps(
        template_payload(template),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(canonical_json).hexdigest()