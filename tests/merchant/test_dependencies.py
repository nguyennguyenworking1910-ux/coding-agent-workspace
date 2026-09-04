"""Tests for Merchant project-step dependency validation."""

from __future__ import annotations

import json

import pytest

from claude.agents.tools.merchant.dependencies import (
    DependencyCycleError,
    DependencyValidationError,
    DuplicateDependencyError,
    UnknownDependencyStepError,
    dependency_ready_step_ids,
    evaluate_dependency_readiness,
    transitive_predecessor_ids,
    validate_dependency_graph,
)
from claude.agents.tools.merchant.workflow import (
    DEPENDENCY_TYPES,
)


def step(step_id, status="PENDING"):
    return {
        "id": step_id,
        "status": status,
    }


def dependency(
    from_step_id,
    to_step_id,
    dependency_type="MUST_COMPLETE_BEFORE",
):
    return {
        "from_step_id": from_step_id,
        "to_step_id": to_step_id,
        "dependency_type": dependency_type,
    }


def test_step_without_dependencies_is_ready():
    steps = [step("draft")]
    dependencies = []

    result = evaluate_dependency_readiness(
        "draft",
        steps,
        dependencies,
    )

    assert result.is_ready
    assert result.direct_predecessor_ids == ()
    assert result.transitive_predecessor_ids == ()
    assert result.unmet_direct_predecessor_ids == ()
    assert result.unmet_transitive_predecessor_ids == ()


def test_completed_direct_predecessor_satisfies_dependency():
    steps = [
        step("draft", "COMPLETED"),
        step("review"),
    ]
    dependencies = [
        dependency("draft", "review"),
    ]

    result = evaluate_dependency_readiness(
        "review",
        steps,
        dependencies,
    )

    assert result.is_ready
    assert result.direct_predecessor_ids == ("draft",)
    assert result.unmet_direct_predecessor_ids == ()


@pytest.mark.parametrize(
    "status",
    (
        "PENDING",
        "READY",
        "IN_PROGRESS",
        "BLOCKED",
        "SKIPPED",
        "SUPERSEDED",
    ),
)
def test_non_completed_predecessor_blocks_readiness(status):
    steps = [
        step("draft", status),
        step("review"),
    ]
    dependencies = [
        dependency("draft", "review"),
    ]

    result = evaluate_dependency_readiness(
        "review",
        steps,
        dependencies,
    )

    assert not result.is_ready
    assert result.unmet_direct_predecessor_ids == (
        "draft",
    )
    assert result.unmet_transitive_predecessor_ids == (
        "draft",
    )


def test_transitive_incomplete_predecessor_blocks_readiness():
    steps = [
        step("draft", "IN_PROGRESS"),
        step("review", "COMPLETED"),
        step("sign", "PENDING"),
    ]
    dependencies = [
        dependency("draft", "review"),
        dependency("review", "sign"),
    ]

    result = evaluate_dependency_readiness(
        "sign",
        steps,
        dependencies,
    )

    assert not result.is_ready
    assert result.direct_predecessor_ids == ("review",)
    assert result.transitive_predecessor_ids == (
        "draft",
        "review",
    )
    assert result.unmet_direct_predecessor_ids == ()
    assert result.unmet_transitive_predecessor_ids == (
        "draft",
    )


def test_transitive_predecessors_are_deduplicated():
    steps = [
        step("root", "COMPLETED"),
        step("left", "COMPLETED"),
        step("right", "COMPLETED"),
        step("finish"),
    ]
    dependencies = [
        dependency("root", "left"),
        dependency("root", "right"),
        dependency("left", "finish"),
        dependency("right", "finish"),
    ]

    assert transitive_predecessor_ids(
        "finish",
        steps,
        dependencies,
    ) == (
        "left",
        "right",
        "root",
    )


def test_parallel_predecessors_must_both_complete():
    steps = [
        step("production", "COMPLETED"),
        step("uat", "IN_PROGRESS"),
        step("launch"),
    ]
    dependencies = [
        dependency("production", "launch"),
        dependency("uat", "launch"),
    ]

    result = evaluate_dependency_readiness(
        "launch",
        steps,
        dependencies,
    )

    assert not result.is_ready
    assert result.unmet_direct_predecessor_ids == (
        "uat",
    )


def test_ready_step_ids_include_pending_and_blocked():
    steps = [
        step("root", "COMPLETED"),
        step("pending", "PENDING"),
        step("blocked", "BLOCKED"),
        step("already_ready", "READY"),
        step("active", "IN_PROGRESS"),
        step("finished", "COMPLETED"),
    ]
    dependencies = [
        dependency("root", "pending"),
        dependency("root", "blocked"),
        dependency("root", "already_ready"),
        dependency("root", "active"),
        dependency("root", "finished"),
    ]

    assert dependency_ready_step_ids(
        steps,
        dependencies,
    ) == (
        "blocked",
        "pending",
    )


def test_ready_step_ids_exclude_unmet_steps():
    steps = [
        step("root", "IN_PROGRESS"),
        step("destination", "PENDING"),
    ]
    dependencies = [
        dependency("root", "destination"),
    ]

    assert dependency_ready_step_ids(
        steps,
        dependencies,
    ) == ()


@pytest.mark.parametrize(
    "dependency_type",
    sorted(DEPENDENCY_TYPES),
)
def test_every_supported_dependency_type_is_accepted(
    dependency_type,
):
    steps = [
        step("source", "COMPLETED"),
        step("destination"),
    ]
    dependencies = [
        dependency(
            "source",
            "destination",
            dependency_type,
        ),
    ]

    validate_dependency_graph(steps, dependencies)

    assert evaluate_dependency_readiness(
        "destination",
        steps,
        dependencies,
    ).is_ready


def test_unsupported_dependency_type_is_rejected():
    steps = [
        step("source"),
        step("destination"),
    ]

    with pytest.raises(
        DependencyValidationError,
        match="Unsupported dependency type",
    ):
        validate_dependency_graph(
            steps,
            [
                dependency(
                    "source",
                    "destination",
                    "UNKNOWN",
                )
            ],
        )


def test_unknown_source_step_is_rejected():
    with pytest.raises(
        UnknownDependencyStepError,
        match="unknown source",
    ):
        validate_dependency_graph(
            [step("destination")],
            [
                dependency(
                    "missing",
                    "destination",
                )
            ],
        )


def test_unknown_destination_step_is_rejected():
    with pytest.raises(
        UnknownDependencyStepError,
        match="unknown destination",
    ):
        validate_dependency_graph(
            [step("source")],
            [
                dependency(
                    "source",
                    "missing",
                )
            ],
        )


def test_unknown_evaluated_step_is_rejected():
    with pytest.raises(
        UnknownDependencyStepError,
        match="Unknown project step",
    ):
        evaluate_dependency_readiness(
            "missing",
            [step("known")],
            [],
        )


def test_duplicate_step_id_is_rejected():
    with pytest.raises(
        DependencyValidationError,
        match="Duplicate project step id",
    ):
        validate_dependency_graph(
            [
                step("duplicate"),
                step("duplicate"),
            ],
            [],
        )


def test_duplicate_dependency_is_rejected():
    steps = [
        step("source"),
        step("destination"),
    ]
    edge = dependency("source", "destination")

    with pytest.raises(
        DuplicateDependencyError,
        match="Duplicate dependency edge",
    ):
        validate_dependency_graph(
            steps,
            [edge, dict(edge)],
        )


def test_self_dependency_is_rejected():
    with pytest.raises(
        DependencyCycleError,
        match="depend on itself",
    ):
        validate_dependency_graph(
            [step("self")],
            [dependency("self", "self")],
        )


def test_two_step_cycle_is_rejected():
    steps = [
        step("a"),
        step("b"),
    ]
    dependencies = [
        dependency("a", "b"),
        dependency("b", "a"),
    ]

    with pytest.raises(
        DependencyCycleError,
        match="a, b",
    ):
        validate_dependency_graph(
            steps,
            dependencies,
        )


def test_cycle_inside_larger_graph_is_rejected():
    steps = [
        step("root"),
        step("a"),
        step("b"),
        step("finish"),
    ]
    dependencies = [
        dependency("root", "a"),
        dependency("a", "b"),
        dependency("b", "a"),
        dependency("b", "finish"),
    ]

    with pytest.raises(DependencyCycleError):
        validate_dependency_graph(
            steps,
            dependencies,
        )


@pytest.mark.parametrize(
    "invalid_step",
    (
        {"id": None, "status": "PENDING"},
        {"id": "", "status": "PENDING"},
        {"id": "step", "status": "UNKNOWN"},
        {"id": "step", "status": None},
    ),
)
def test_invalid_step_record_is_rejected(invalid_step):
    with pytest.raises(DependencyValidationError):
        validate_dependency_graph(
            [invalid_step],
            [],
        )


def test_dependency_identifiers_are_normalized():
    steps = [
        step("source", "completed"),
        step("destination", "pending"),
    ]
    dependencies = [
        dependency(
            " source ",
            " destination ",
            "must_complete_before",
        ),
    ]

    result = evaluate_dependency_readiness(
        " destination ",
        steps,
        dependencies,
    )

    assert result.is_ready
    assert result.step_id == "destination"
    assert result.direct_predecessor_ids == (
        "source",
    )


def test_readiness_result_is_json_compatible():
    steps = [
        step("source", "IN_PROGRESS"),
        step("destination"),
    ]
    dependencies = [
        dependency("source", "destination"),
    ]

    result = evaluate_dependency_readiness(
        "destination",
        steps,
        dependencies,
    )

    decoded = json.loads(
        json.dumps(result.to_dict())
    )

    assert decoded == {
        "step_id": "destination",
        "is_ready": False,
        "direct_predecessor_ids": ["source"],
        "transitive_predecessor_ids": ["source"],
        "unmet_direct_predecessor_ids": ["source"],
        "unmet_transitive_predecessor_ids": [
            "source"
        ],
    }