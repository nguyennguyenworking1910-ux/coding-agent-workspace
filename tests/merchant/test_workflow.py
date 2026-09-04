"""Unit tests for the pure Merchant workflow domain."""

from __future__ import annotations

from dataclasses import replace

import pytest

from claude.agents.tools.merchant.workflow import (
    WorkflowDefinitionError,
    WorkflowDependencyDefinition,
    WorkflowStepDefinition,
    WorkflowTemplateDefinition,
    template_dependency_uuid,
    template_fingerprint,
    template_payload,
    template_step_uuid,
    template_uuid,
    topological_step_keys,
    transitive_dependency_closure,
    validate_template_definition,
)


def make_template() -> WorkflowTemplateDefinition:
    return WorkflowTemplateDefinition(
        name="TEST_WORKFLOW",
        version=1,
        project_type="OPENING_NEW_CINEMA",
        variant="TEST_WORKFLOW",
        description="Workflow domain unit-test template",
        steps=(
            WorkflowStepDefinition(
                key="start",
                sequence_number=1,
                step_type="SEQUENTIAL",
                name="Start",
            ),
            WorkflowStepDefinition(
                key="review",
                sequence_number=2,
                step_type="PARALLEL_BRANCH",
                name="Review",
                branch_key="review_branch",
            ),
            WorkflowStepDefinition(
                key="finish",
                sequence_number=3,
                step_type="APPROVAL_GATE",
                name="Finish",
            ),
        ),
        dependencies=(
            WorkflowDependencyDefinition(
                "start",
                "review",
            ),
            WorkflowDependencyDefinition(
                "review",
                "finish",
            ),
        ),
    )


def replace_step(
    template: WorkflowTemplateDefinition,
    key: str,
    **changes,
) -> WorkflowTemplateDefinition:
    steps = tuple(
        replace(step, **changes)
        if step.key == key
        else step
        for step in template.steps
    )
    return replace(template, steps=steps)


def test_valid_definition_is_returned_unchanged():
    template = make_template()

    assert validate_template_definition(template) is template


def test_topological_order_is_dependency_safe():
    template = make_template()

    assert topological_step_keys(template) == (
        "start",
        "review",
        "finish",
    )


def test_transitive_dependency_closure():
    template = make_template()

    assert transitive_dependency_closure(template) == {
        "start": (),
        "review": ("start",),
        "finish": ("start", "review"),
    }


def test_cycle_is_rejected():
    template = make_template()
    cyclic = replace(
        template,
        dependencies=(
            *template.dependencies,
            WorkflowDependencyDefinition(
                "finish",
                "start",
            ),
        ),
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="contain a cycle",
    ):
        validate_template_definition(cyclic)


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("missing", "finish"),
        ("start", "missing"),
    ],
)
def test_unknown_dependency_reference_is_rejected(
    source,
    destination,
):
    template = make_template()
    invalid = replace(
        template,
        dependencies=(
            WorkflowDependencyDefinition(
                source,
                destination,
            ),
        ),
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="unknown",
    ):
        validate_template_definition(invalid)


def test_self_dependency_is_rejected():
    template = make_template()
    invalid = replace(
        template,
        dependencies=(
            WorkflowDependencyDefinition(
                "start",
                "start",
            ),
        ),
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="depend on itself",
    ):
        validate_template_definition(invalid)


def test_duplicate_dependency_edge_is_rejected():
    template = make_template()
    invalid = replace(
        template,
        dependencies=(
            WorkflowDependencyDefinition(
                "start",
                "review",
            ),
            WorkflowDependencyDefinition(
                "start",
                "review",
                "BLOCKS",
            ),
        ),
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="Duplicate dependency edge",
    ):
        validate_template_definition(invalid)


def test_duplicate_step_key_is_rejected():
    template = make_template()
    duplicate = replace(
        template.steps[1],
        sequence_number=3,
    )
    invalid = replace(
        template,
        steps=(
            template.steps[0],
            template.steps[1],
            duplicate,
        ),
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="Duplicate workflow step key",
    ):
        validate_template_definition(invalid)


def test_duplicate_sequence_number_is_rejected():
    template = replace_step(
        make_template(),
        "finish",
        sequence_number=2,
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="Duplicate workflow step sequence",
    ):
        validate_template_definition(template)


def test_non_contiguous_sequence_is_rejected():
    template = replace_step(
        make_template(),
        "finish",
        sequence_number=4,
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="must be contiguous",
    ):
        validate_template_definition(template)


def test_unsupported_step_type_is_rejected():
    template = replace_step(
        make_template(),
        "start",
        step_type="EXECUTE_SQL",
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="Unsupported step type",
    ):
        validate_template_definition(template)


def test_parallel_step_requires_branch():
    template = replace_step(
        make_template(),
        "review",
        branch_key=None,
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="require branch_key",
    ):
        validate_template_definition(template)


def test_unknown_condition_key_is_rejected():
    template = replace_step(
        make_template(),
        "start",
        step_type="CONDITIONAL",
        is_optional=True,
        condition_key="execute_dynamic_sql",
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="Unsupported condition key",
    ):
        validate_template_definition(template)


def test_conditional_step_must_be_optional():
    template = replace_step(
        make_template(),
        "start",
        step_type="CONDITIONAL",
        is_optional=False,
        condition_key="requires_procurement",
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="must be optional",
    ):
        validate_template_definition(template)


def test_optional_step_requires_condition():
    template = replace_step(
        make_template(),
        "start",
        is_optional=True,
        condition_key=None,
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="Optional steps require condition_key",
    ):
        validate_template_definition(template)


def test_unsupported_project_type_is_rejected():
    template = replace(
        make_template(),
        project_type="UNKNOWN_PROJECT",
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="Unsupported project type",
    ):
        validate_template_definition(template)


def test_template_name_must_match_variant():
    template = replace(
        make_template(),
        name="DIFFERENT_WORKFLOW",
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="name and variant must match",
    ):
        validate_template_definition(template)


def test_template_version_must_be_positive():
    template = replace(
        make_template(),
        version=0,
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="greater than zero",
    ):
        validate_template_definition(template)


def test_template_and_step_uuids_are_stable():
    template = make_template()
    version_two = replace(template, version=2)

    assert template_uuid(template) == template_uuid(template)
    assert template_uuid(template) != template_uuid(version_two)

    assert (
        template_step_uuid(template, "start")
        == template_step_uuid(template, "start")
    )
    assert (
        template_step_uuid(template, "start")
        != template_step_uuid(template, "review")
    )


def test_unknown_step_uuid_is_rejected():
    with pytest.raises(
        WorkflowDefinitionError,
        match="Unknown workflow step key",
    ):
        template_step_uuid(
            make_template(),
            "missing",
        )


def test_dependency_uuid_is_stable_and_distinct():
    template = make_template()
    first, second = template.dependencies

    assert (
        template_dependency_uuid(template, first)
        == template_dependency_uuid(template, first)
    )
    assert (
        template_dependency_uuid(template, first)
        != template_dependency_uuid(template, second)
    )


def test_foreign_dependency_uuid_is_rejected():
    template = make_template()
    foreign_dependency = WorkflowDependencyDefinition(
        "start",
        "finish",
    )

    with pytest.raises(
        WorkflowDefinitionError,
        match="does not belong",
    ):
        template_dependency_uuid(
            template,
            foreign_dependency,
        )


def test_payload_and_fingerprint_ignore_tuple_order():
    template = make_template()
    reordered = replace(
        template,
        steps=tuple(reversed(template.steps)),
        dependencies=tuple(
            reversed(template.dependencies)
        ),
    )

    assert template_payload(template) == template_payload(
        reordered
    )
    assert template_fingerprint(
        template
    ) == template_fingerprint(reordered)


def test_fingerprint_changes_when_definition_changes():
    template = make_template()
    changed = replace_step(
        template,
        "review",
        name="Changed review",
    )

    assert template_fingerprint(
        template
    ) != template_fingerprint(changed)


def test_payload_is_json_compatible_and_complete():
    template = make_template()
    payload = template_payload(template)

    assert payload["name"] == "TEST_WORKFLOW"
    assert payload["version"] == 1
    assert payload["project_type"] == (
        "OPENING_NEW_CINEMA"
    )
    assert [
        step["key"]
        for step in payload["steps"]
    ] == [
        "start",
        "review",
        "finish",
    ]
    assert payload["dependencies"] == [
        {
            "from_step_key": "review",
            "to_step_key": "finish",
            "dependency_type":
                "MUST_COMPLETE_BEFORE",
        },
        {
            "from_step_key": "start",
            "to_step_key": "review",
            "dependency_type":
                "MUST_COMPLETE_BEFORE",
        },
    ]