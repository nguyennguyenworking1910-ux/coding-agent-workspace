"""Tests for Merchant project-instantiation planning."""

from __future__ import annotations

import json
import uuid

import pytest

from claude.agents.tools.merchant.project_factory import (
    ProjectInstantiationError,
    build_project_instantiation_plan,
)
from claude.agents.tools.merchant.workflow_templates import (
    STANDARD_WORKFLOW_TEMPLATES,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
CREATED_BY = "00000000-0000-0000-0000-000000000003"
REVISION_ID = "00000000-0000-0000-0000-000000000004"


def template_named(name):
    return next(
        template
        for template in STANDARD_WORKFLOW_TEMPLATES
        if template.name == name
    )


def build_opening(**overrides):
    arguments = {
        "merchant_id": MERCHANT_ID,
        "merchant_status": "ACTIVE",
        "template": template_named(
            "OPENING_NEW_CINEMA_STANDARD"
        ),
        "requires_procurement": False,
        "project_id": PROJECT_ID,
    }
    arguments.update(overrides)

    return build_project_instantiation_plan(
        **arguments
    )


def test_opening_without_procurement():
    plan = build_opening()

    assert plan.project["project_type"] == (
        "OPENING_NEW_CINEMA"
    )
    assert plan.project["status"] == "PLANNED"
    assert not plan.project["requires_procurement"]
    assert plan.project["payment_period_number"] is None
    assert len(plan.steps) == 22
    assert len(plan.dependencies) == 22

    skipped = {
        step["step_name"]
        for step in plan.steps
        if step["status"] == "SKIPPED"
    }

    assert len(skipped) == 2


def test_opening_with_procurement():
    plan = build_opening(
        requires_procurement=True
    )

    assert len(plan.steps) == 22
    assert len(plan.dependencies) == 24
    assert not any(
        step["status"] == "SKIPPED"
        for step in plan.steps
    )


def test_media_top_up_new_document():
    plan = build_project_instantiation_plan(
        merchant_id=MERCHANT_ID,
        merchant_status="ACTIVE",
        template=template_named(
            "MEDIA_TOP_UP_NEW_DOCUMENT"
        ),
        requires_procurement=True,
        payment_period_number=3,
        project_id=PROJECT_ID,
    )

    assert plan.project["project_type"] == "MEDIA_TOP_UP"
    assert plan.project["payment_period_number"] == 3
    assert (
        plan.project["reused_document_revision_id"]
        is None
    )
    assert len(plan.steps) == 12
    assert len(plan.dependencies) == 12


def test_media_top_up_existing_document():
    plan = build_project_instantiation_plan(
        merchant_id=MERCHANT_ID,
        merchant_status="ACTIVE",
        template=template_named(
            "MEDIA_TOP_UP_EXISTING_DOCUMENT"
        ),
        requires_procurement=False,
        payment_period_number=5,
        reused_document_revision_id=REVISION_ID,
        project_id=PROJECT_ID,
    )

    assert plan.project["payment_period_number"] == 5
    assert (
        plan.project["reused_document_revision_id"]
        == REVISION_ID
    )
    assert len(plan.steps) == 4
    assert len(plan.dependencies) == 3


@pytest.mark.parametrize(
    "requires_procurement",
    (
        False,
        True,
    ),
)
def test_integration_project_requires_onboarding_merchant(
    requires_procurement,
):
    plan = build_project_instantiation_plan(
        merchant_id=MERCHANT_ID,
        merchant_status="ONBOARDING",
        template=template_named(
            "INTEGRATION_NEW_MERCHANT_STANDARD"
        ),
        requires_procurement=requires_procurement,
        project_id=PROJECT_ID,
    )

    assert plan.project["project_type"] == (
        "INTEGRATION_NEW_MERCHANT"
    )
    assert len(plan.steps) == 26


@pytest.mark.parametrize(
    "template_name",
    (
        "MEDIA_TOP_UP_NEW_DOCUMENT",
        "MEDIA_TOP_UP_EXISTING_DOCUMENT",
        "OPENING_NEW_CINEMA_STANDARD",
    ),
)
def test_nonintegration_workflow_rejects_nonactive_merchant(
    template_name,
):
    arguments = {
        "merchant_id": MERCHANT_ID,
        "merchant_status": "ONBOARDING",
        "template": template_named(template_name),
        "requires_procurement": (
            template_name
            == "MEDIA_TOP_UP_NEW_DOCUMENT"
        ),
        "project_id": PROJECT_ID,
    }

    if template_name.startswith("MEDIA_TOP_UP"):
        arguments["payment_period_number"] = 1

    if template_name == (
        "MEDIA_TOP_UP_EXISTING_DOCUMENT"
    ):
        arguments[
            "reused_document_revision_id"
        ] = REVISION_ID

    with pytest.raises(
        ProjectInstantiationError,
        match="expected ACTIVE",
    ):
        build_project_instantiation_plan(**arguments)


def test_integration_rejects_active_merchant():
    with pytest.raises(
        ProjectInstantiationError,
        match="expected ONBOARDING",
    ):
        build_project_instantiation_plan(
            merchant_id=MERCHANT_ID,
            merchant_status="ACTIVE",
            template=template_named(
                "INTEGRATION_NEW_MERCHANT_STANDARD"
            ),
            requires_procurement=False,
            project_id=PROJECT_ID,
        )


@pytest.mark.parametrize(
    "invalid_period",
    (
        None,
        0,
        -1,
        True,
        1.5,
        "1",
    ),
)
def test_media_top_up_requires_positive_integer_period(
    invalid_period,
):
    with pytest.raises(
        ProjectInstantiationError,
        match="payment_period_number >= 1",
    ):
        build_project_instantiation_plan(
            merchant_id=MERCHANT_ID,
            merchant_status="ACTIVE",
            template=template_named(
                "MEDIA_TOP_UP_NEW_DOCUMENT"
            ),
            requires_procurement=True,
            payment_period_number=invalid_period,
            project_id=PROJECT_ID,
        )


def test_non_media_project_rejects_payment_period():
    with pytest.raises(
        ProjectInstantiationError,
        match="only valid for MEDIA_TOP_UP",
    ):
        build_opening(payment_period_number=1)


def test_existing_document_requires_revision_id():
    with pytest.raises(
        ProjectInstantiationError,
        match="requires reused_document_revision_id",
    ):
        build_project_instantiation_plan(
            merchant_id=MERCHANT_ID,
            merchant_status="ACTIVE",
            template=template_named(
                "MEDIA_TOP_UP_EXISTING_DOCUMENT"
            ),
            requires_procurement=False,
            payment_period_number=1,
            project_id=PROJECT_ID,
        )


def test_other_workflow_rejects_reused_revision():
    with pytest.raises(
        ProjectInstantiationError,
        match="only valid for",
    ):
        build_opening(
            reused_document_revision_id=REVISION_ID
        )


def test_new_document_top_up_requires_procurement():
    with pytest.raises(
        ProjectInstantiationError,
        match="always requires procurement",
    ):
        build_project_instantiation_plan(
            merchant_id=MERCHANT_ID,
            merchant_status="ACTIVE",
            template=template_named(
                "MEDIA_TOP_UP_NEW_DOCUMENT"
            ),
            requires_procurement=False,
            payment_period_number=1,
            project_id=PROJECT_ID,
        )


def test_existing_document_variant_rejects_pr_branch():
    with pytest.raises(
        ProjectInstantiationError,
        match="does not include a Purchase Request",
    ):
        build_project_instantiation_plan(
            merchant_id=MERCHANT_ID,
            merchant_status="ACTIVE",
            template=template_named(
                "MEDIA_TOP_UP_EXISTING_DOCUMENT"
            ),
            requires_procurement=True,
            payment_period_number=1,
            reused_document_revision_id=REVISION_ID,
            project_id=PROJECT_ID,
        )


@pytest.mark.parametrize(
    "invalid_value",
    (
        None,
        0,
        1,
        "true",
    ),
)
def test_requires_procurement_must_be_boolean(
    invalid_value,
):
    with pytest.raises(
        ProjectInstantiationError,
        match="must be boolean",
    ):
        build_opening(
            requires_procurement=invalid_value
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("merchant_id", "not-a-uuid"),
        ("project_id", "not-a-uuid"),
        ("created_by", "not-a-uuid"),
        (
            "reused_document_revision_id",
            "not-a-uuid",
        ),
    ),
)
def test_invalid_uuid_is_rejected(field, value):
    arguments = {
        "merchant_id": MERCHANT_ID,
        "merchant_status": "ACTIVE",
        "template": template_named(
            "MEDIA_TOP_UP_EXISTING_DOCUMENT"
        ),
        "requires_procurement": False,
        "payment_period_number": 1,
        "reused_document_revision_id": REVISION_ID,
        "project_id": PROJECT_ID,
    }
    arguments[field] = value

    with pytest.raises(
        ProjectInstantiationError,
        match="valid UUID",
    ):
        build_project_instantiation_plan(**arguments)


def test_blank_title_becomes_none():
    plan = build_opening(title="   ")

    assert plan.project["title"] is None


def test_title_is_trimmed():
    plan = build_opening(
        title="  New cinema opening  "
    )

    assert plan.project["title"] == (
        "New cinema opening"
    )


def test_overlong_title_is_rejected():
    with pytest.raises(
        ProjectInstantiationError,
        match="cannot exceed 500",
    ):
        build_opening(title="x" * 501)


def test_generated_project_id_is_valid_uuid():
    plan = build_project_instantiation_plan(
        merchant_id=MERCHANT_ID,
        merchant_status="ACTIVE",
        template=template_named(
            "OPENING_NEW_CINEMA_STANDARD"
        ),
        requires_procurement=False,
    )

    assert str(
        uuid.UUID(plan.project["id"])
    ) == plan.project["id"]


def test_step_and_dependency_ids_are_deterministic():
    first = build_opening()
    second = build_opening()

    assert [
        step["id"]
        for step in first.steps
    ] == [
        step["id"]
        for step in second.steps
    ]
    assert [
        dependency["id"]
        for dependency in first.dependencies
    ] == [
        dependency["id"]
        for dependency in second.dependencies
    ]


def test_different_projects_have_different_step_ids():
    first = build_opening(project_id=PROJECT_ID)
    second = build_opening(
        project_id=(
            "00000000-0000-0000-0000-000000000099"
        )
    )

    assert {
        step["id"]
        for step in first.steps
    }.isdisjoint(
        {
            step["id"]
            for step in second.steps
        }
    )


def test_all_project_instance_ids_are_unique():
    plan = build_opening(
        requires_procurement=True
    )

    step_ids = [
        step["id"]
        for step in plan.steps
    ]
    dependency_ids = [
        dependency["id"]
        for dependency in plan.dependencies
    ]

    assert len(step_ids) == len(set(step_ids))
    assert len(dependency_ids) == len(
        set(dependency_ids)
    )


def test_dependencies_reference_instantiated_steps():
    plan = build_opening(
        requires_procurement=True
    )
    step_ids = {
        step["id"]
        for step in plan.steps
    }

    assert all(
        dependency["from_step_id"] in step_ids
        and dependency["to_step_id"] in step_ids
        for dependency in plan.dependencies
    )


def test_creation_event_matches_project():
    plan = build_opening(created_by=CREATED_BY)

    assert plan.event["merchant_id"] == MERCHANT_ID
    assert plan.event["project_id"] == PROJECT_ID
    assert plan.event["entity_id"] == PROJECT_ID
    assert plan.event["entity_type"] == "PROJECT"
    assert plan.event["event_type"] == (
        "PROJECT_CREATED"
    )
    assert plan.event["triggered_by"] == CREATED_BY
    assert plan.event["old_values"] is None
    assert plan.event["new_values"]["status"] == (
        "PLANNED"
    )


def test_creation_event_excludes_title():
    sensitive_title = "Confidential partner project"
    plan = build_opening(title=sensitive_title)

    encoded_event = json.dumps(plan.event)

    assert sensitive_title not in encoded_event


def test_plan_is_json_compatible():
    plan = build_opening(
        title="Opening project",
        created_by=CREATED_BY,
    )

    decoded = json.loads(
        json.dumps(plan.to_dict())
    )

    assert decoded["project"]["id"] == PROJECT_ID
    assert len(decoded["steps"]) == 22
    assert decoded["event"]["event_type"] == (
        "PROJECT_CREATED"
    )