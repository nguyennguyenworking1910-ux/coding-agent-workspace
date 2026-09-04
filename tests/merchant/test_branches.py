"""Tests for Merchant workflow branch resolution."""

from __future__ import annotations

import json

import pytest

from claude.agents.tools.merchant.branches import (
    BranchResolutionError,
    resolve_workflow_branches,
)
from claude.agents.tools.merchant.workflow_templates import (
    STANDARD_WORKFLOW_TEMPLATES,
)


def template_named(name):
    return next(
        template
        for template in STANDARD_WORKFLOW_TEMPLATES
        if template.name == name
    )


def expected_active_dependencies(
    template,
    active_step_keys,
):
    active = set(active_step_keys)

    return {
        (
            dependency.from_step_key,
            dependency.to_step_key,
            dependency.dependency_type,
        )
        for dependency in template.dependencies
        if dependency.from_step_key in active
        and dependency.to_step_key in active
    }


@pytest.mark.parametrize(
    ("template_name", "step_count", "dependency_count"),
    (
        (
            "MEDIA_TOP_UP_NEW_DOCUMENT",
            12,
            12,
        ),
        (
            "MEDIA_TOP_UP_EXISTING_DOCUMENT",
            4,
            3,
        ),
    ),
)
def test_nonconditional_templates_remain_fully_active(
    template_name,
    step_count,
    dependency_count,
):
    template = template_named(template_name)

    result = resolve_workflow_branches(
        template,
        {},
    )

    assert len(result.active_step_keys) == step_count
    assert result.skipped_step_keys == ()
    assert len(result.dependencies) == dependency_count
    assert result.skipped_branch_keys == ()


@pytest.mark.parametrize(
    ("template_name", "expected_active"),
    (
        (
            "OPENING_NEW_CINEMA_STANDARD",
            20,
        ),
        (
            "INTEGRATION_NEW_MERCHANT_STANDARD",
            24,
        ),
    ),
)
def test_false_procurement_condition_skips_two_steps(
    template_name,
    expected_active,
):
    template = template_named(template_name)

    result = resolve_workflow_branches(
        template,
        {"requires_procurement": False},
    )

    assert len(result.active_step_keys) == expected_active
    assert set(result.skipped_step_keys) == {
        "create_purchase_request",
        "record_purchase_request_number",
    }
    assert result.skipped_branch_keys == (
        "procurement_branch",
    )


@pytest.mark.parametrize(
    ("template_name", "expected_active"),
    (
        (
            "OPENING_NEW_CINEMA_STANDARD",
            22,
        ),
        (
            "INTEGRATION_NEW_MERCHANT_STANDARD",
            26,
        ),
    ),
)
def test_true_procurement_condition_includes_all_steps(
    template_name,
    expected_active,
):
    template = template_named(template_name)

    result = resolve_workflow_branches(
        template,
        {"requires_procurement": True},
    )

    assert len(result.active_step_keys) == expected_active
    assert result.skipped_step_keys == ()
    assert "procurement_branch" in (
        result.active_branch_keys
    )
    assert result.skipped_branch_keys == ()


@pytest.mark.parametrize(
    "template_name",
    (
        "OPENING_NEW_CINEMA_STANDARD",
        "INTEGRATION_NEW_MERCHANT_STANDARD",
    ),
)
def test_uat_and_production_branches_are_parallel(
    template_name,
):
    template = template_named(template_name)

    result = resolve_workflow_branches(
        template,
        {"requires_procurement": False},
    )

    assert "production_branch" in (
        result.active_branch_keys
    )
    assert "uat_branch" in result.active_branch_keys


def test_skipped_steps_receive_skipped_status():
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    result = resolve_workflow_branches(
        template,
        {"requires_procurement": False},
    )
    status_by_key = {
        step.key: step.initial_status
        for step in result.steps
    }

    assert (
        status_by_key["create_purchase_request"]
        == "SKIPPED"
    )
    assert (
        status_by_key[
            "record_purchase_request_number"
        ]
        == "SKIPPED"
    )


def test_active_root_steps_are_ready():
    template = template_named(
        "INTEGRATION_NEW_MERCHANT_STANDARD"
    )

    result = resolve_workflow_branches(
        template,
        {"requires_procurement": False},
    )
    active_keys = set(result.active_step_keys)
    predecessor_keys = {
        dependency.to_step_key
        for dependency in result.dependencies
    }

    for step in result.steps:
        if step.key not in active_keys:
            continue

        if step.key not in predecessor_keys:
            assert step.initial_status == "READY"


def test_active_dependent_steps_are_pending():
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    result = resolve_workflow_branches(
        template,
        {"requires_procurement": True},
    )
    predecessor_keys = {
        dependency.to_step_key
        for dependency in result.dependencies
    }

    for step in result.steps:
        if step.key in predecessor_keys:
            assert step.initial_status == "PENDING"


@pytest.mark.parametrize(
    "requires_procurement",
    (
        False,
        True,
    ),
)
def test_resolved_dependencies_only_reference_active_steps(
    requires_procurement,
):
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    result = resolve_workflow_branches(
        template,
        {
            "requires_procurement":
                requires_procurement
        },
    )
    active = set(result.active_step_keys)

    for dependency in result.dependencies:
        assert dependency.from_step_key in active
        assert dependency.to_step_key in active


@pytest.mark.parametrize(
    "requires_procurement",
    (
        False,
        True,
    ),
)
def test_resolved_dependencies_match_filtered_template(
    requires_procurement,
):
    template = template_named(
        "INTEGRATION_NEW_MERCHANT_STANDARD"
    )

    result = resolve_workflow_branches(
        template,
        {
            "requires_procurement":
                requires_procurement
        },
    )

    actual = {
        (
            dependency.from_step_key,
            dependency.to_step_key,
            dependency.dependency_type,
        )
        for dependency in result.dependencies
    }

    assert actual == expected_active_dependencies(
        template,
        result.active_step_keys,
    )


def test_missing_condition_property_fails_closed():
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    with pytest.raises(
        BranchResolutionError,
        match="missing condition property",
    ):
        resolve_workflow_branches(
            template,
            {},
        )


@pytest.mark.parametrize(
    "invalid_value",
    (
        None,
        0,
        1,
        "true",
        "false",
        [],
    ),
)
def test_condition_property_must_be_boolean(
    invalid_value,
):
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    with pytest.raises(
        BranchResolutionError,
        match="must be boolean",
    ):
        resolve_workflow_branches(
            template,
            {
                "requires_procurement":
                    invalid_value
            },
        )


def test_step_order_is_deterministic():
    template = template_named(
        "INTEGRATION_NEW_MERCHANT_STANDARD"
    )

    result = resolve_workflow_branches(
        template,
        {"requires_procurement": True},
    )

    expected_order = tuple(
        step.key
        for step in sorted(
            template.steps,
            key=lambda item: (
                item.sequence_number,
                item.key,
            ),
        )
    )
    actual_order = tuple(
        step.key
        for step in result.steps
    )

    assert actual_order == expected_order


def test_resolution_has_stable_template_identity():
    template = template_named(
        "MEDIA_TOP_UP_EXISTING_DOCUMENT"
    )

    first = resolve_workflow_branches(template, {})
    second = resolve_workflow_branches(template, {})

    assert first.template_id == second.template_id
    assert first.template_name == template.name
    assert first.template_version == template.version


def test_resolution_does_not_expose_project_properties():
    secret_value = "DO-NOT-EXPOSE"
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    result = resolve_workflow_branches(
        template,
        {
            "requires_procurement": False,
            "secret": secret_value,
        },
    )

    encoded = json.dumps(result.to_dict())

    assert secret_value not in encoded


def test_resolution_is_json_compatible():
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    result = resolve_workflow_branches(
        template,
        {"requires_procurement": False},
    )

    decoded = json.loads(
        json.dumps(result.to_dict())
    )

    assert decoded["template_name"] == (
        "OPENING_NEW_CINEMA_STANDARD"
    )
    assert len(decoded["active_step_keys"]) == 20
    assert decoded["skipped_step_keys"] == [
        "create_purchase_request",
        "record_purchase_request_number",
    ]