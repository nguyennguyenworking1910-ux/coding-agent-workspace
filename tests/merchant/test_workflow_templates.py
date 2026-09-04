"""Contract tests for the four standard Merchant workflows."""

from __future__ import annotations

import uuid

import pytest

from claude.agents.tools.merchant.workflow import (
    ALLOWED_CONDITION_KEYS,
    WorkflowDefinitionError,
    template_dependency_uuid,
    template_step_uuid,
    template_uuid,
    topological_step_keys,
    transitive_dependency_closure,
    validate_template_definition,
)
from claude.agents.tools.merchant.workflow_templates import (
    INTEGRATION_NEW_MERCHANT_STANDARD,
    MEDIA_TOP_UP_EXISTING_DOCUMENT,
    MEDIA_TOP_UP_NEW_DOCUMENT,
    OPENING_NEW_CINEMA_STANDARD,
    STANDARD_WORKFLOW_TEMPLATES,
    get_standard_workflow_template,
    standard_template_manifest,
)


EXPECTED_MANIFEST = (
    {
        "name": "MEDIA_TOP_UP_NEW_DOCUMENT",
        "variant": "MEDIA_TOP_UP_NEW_DOCUMENT",
        "version": 1,
        "project_type": "MEDIA_TOP_UP",
        "template_id":
            "f48689c2-67a7-58cf-9a12-0bcdec07477b",
        "fingerprint":
            "6ae497dab32398bcc8f01e5d7990a3e4"
            "43f39a449de2bc82ce5b78e1de284b36",
        "step_count": 12,
        "dependency_count": 12,
    },
    {
        "name": "MEDIA_TOP_UP_EXISTING_DOCUMENT",
        "variant": "MEDIA_TOP_UP_EXISTING_DOCUMENT",
        "version": 1,
        "project_type": "MEDIA_TOP_UP",
        "template_id":
            "8099202a-6449-52e6-8eca-c8012767c883",
        "fingerprint":
            "b23c9faba36a725c10b7a9a2b10322f"
            "6381c6732139df1d0cc5d9da232b93ba3",
        "step_count": 4,
        "dependency_count": 3,
    },
    {
        "name": "OPENING_NEW_CINEMA_STANDARD",
        "variant": "OPENING_NEW_CINEMA_STANDARD",
        "version": 1,
        "project_type": "OPENING_NEW_CINEMA",
        "template_id":
            "a3cc7546-6b0f-58a7-b78d-8e7a3289dc10",
        "fingerprint":
            "5dd4ee7e98ee578c708d7a8988ad9925"
            "72a6dabeacd37cd0ce0d40426103a564",
        "step_count": 22,
        "dependency_count": 24,
    },
    {
        "name": "INTEGRATION_NEW_MERCHANT_STANDARD",
        "variant": "INTEGRATION_NEW_MERCHANT_STANDARD",
        "version": 1,
        "project_type": "INTEGRATION_NEW_MERCHANT",
        "template_id":
            "4ce4df94-da4e-55b5-968b-ca24d4ecc3d3",
        "fingerprint":
            "552800356f8327baa2b78c90d37913ab"
            "e1eb9e60bf6be4d67212eae4bb8fc4ef",
        "step_count": 26,
        "dependency_count": 29,
    },
)


def step_by_key(template):
    return {
        step.key: step
        for step in template.steps
    }


def direct_predecessors(template, destination):
    return {
        dependency.from_step_key
        for dependency in template.dependencies
        if dependency.to_step_key == destination
    }


def direct_successors(template, source):
    return {
        dependency.to_step_key
        for dependency in template.dependencies
        if dependency.from_step_key == source
    }


def test_registry_contains_exactly_four_variants():
    assert [
        template.variant
        for template in STANDARD_WORKFLOW_TEMPLATES
    ] == [
        "MEDIA_TOP_UP_NEW_DOCUMENT",
        "MEDIA_TOP_UP_EXISTING_DOCUMENT",
        "OPENING_NEW_CINEMA_STANDARD",
        "INTEGRATION_NEW_MERCHANT_STANDARD",
    ]


def test_standard_template_manifest_is_frozen():
    assert standard_template_manifest() == EXPECTED_MANIFEST


def test_all_standard_templates_are_valid_and_acyclic():
    for template in STANDARD_WORKFLOW_TEMPLATES:
        assert validate_template_definition(
            template
        ) is template

        ordered = topological_step_keys(template)

        assert len(ordered) == len(template.steps)
        assert set(ordered) == {
            step.key
            for step in template.steps
        }


@pytest.mark.parametrize(
    "template",
    STANDARD_WORKFLOW_TEMPLATES,
)
def test_registry_returns_exact_template(template):
    selected = get_standard_workflow_template(
        template.variant,
        template.version,
    )

    assert selected is template


@pytest.mark.parametrize(
    ("variant", "version"),
    [
        ("UNKNOWN_WORKFLOW", 1),
        ("MEDIA_TOP_UP_NEW_DOCUMENT", 2),
    ],
)
def test_registry_rejects_unknown_template(
    variant,
    version,
):
    with pytest.raises(
        WorkflowDefinitionError,
        match="Unknown standard workflow template",
    ):
        get_standard_workflow_template(
            variant,
            version,
        )


def test_all_generated_identifiers_are_unique():
    template_ids = {
        template_uuid(template)
        for template in STANDARD_WORKFLOW_TEMPLATES
    }
    step_ids = {
        template_step_uuid(template, step.key)
        for template in STANDARD_WORKFLOW_TEMPLATES
        for step in template.steps
    }
    dependency_ids = {
        template_dependency_uuid(
            template,
            dependency,
        )
        for template in STANDARD_WORKFLOW_TEMPLATES
        for dependency in template.dependencies
    }

    assert len(template_ids) == 4
    assert len(step_ids) == 64
    assert len(dependency_ids) == 68

    assert all(
        isinstance(identifier, uuid.UUID)
        for identifier in (
            template_ids
            | step_ids
            | dependency_ids
        )
    )


def test_new_document_top_up_has_mandatory_procurement():
    template = MEDIA_TOP_UP_NEW_DOCUMENT
    steps = step_by_key(template)

    assert not any(
        step.is_optional
        for step in template.steps
    )
    assert steps[
        "create_purchase_request"
    ].branch_key == "procurement_branch"
    assert direct_predecessors(
        template,
        "validate_signing_gate",
    ) == {
        "record_partner_approval",
        "record_purchase_request_number",
    }


def test_existing_document_top_up_is_linear():
    template = MEDIA_TOP_UP_EXISTING_DOCUMENT

    assert [
        step.key
        for step in template.steps
    ] == [
        "validate_existing_document",
        "create_purchase_order",
        "create_payment_request",
        "close_payment_period",
    ]

    assert topological_step_keys(template) == (
        "validate_existing_document",
        "create_purchase_order",
        "create_payment_request",
        "close_payment_period",
    )

    assert not any(
        step.is_optional
        for step in template.steps
    )


def test_opening_procurement_steps_are_conditional():
    steps = step_by_key(
        OPENING_NEW_CINEMA_STANDARD
    )

    for key in (
        "create_purchase_request",
        "record_purchase_request_number",
    ):
        step = steps[key]

        assert step.step_type == "CONDITIONAL"
        assert step.is_optional is True
        assert (
            step.condition_key
            == "requires_procurement"
        )


def test_integration_procurement_steps_are_conditional():
    steps = step_by_key(
        INTEGRATION_NEW_MERCHANT_STANDARD
    )

    for key in (
        "create_purchase_request",
        "record_purchase_request_number",
    ):
        step = steps[key]

        assert step.step_type == "CONDITIONAL"
        assert step.is_optional is True
        assert (
            step.condition_key
            == "requires_procurement"
        )


def test_opening_branches_fan_out_after_signing():
    assert direct_successors(
        OPENING_NEW_CINEMA_STANDARD,
        "sign_document",
    ) == {
        "create_purchase_order",
        "create_production_agent",
        "configure_uat_agent",
    }


def test_integration_requires_both_onboarding_checks():
    template = INTEGRATION_NEW_MERCHANT_STANDARD

    assert direct_predecessors(
        template,
        "validate_master_merchant_identity",
    ) == {
        "aml_check",
        "partner_information_check",
    }

    assert direct_successors(
        template,
        "validate_master_merchant_identity",
    ) == {
        "draft_document",
        "create_purchase_request",
    }


def test_integration_activation_requires_all_branches():
    assert direct_predecessors(
        INTEGRATION_NEW_MERCHANT_STANDARD,
        "activate_merchant",
    ) == {
        "create_payment_request",
        "send_production_information",
        "complete_uat_acceptance",
    }

    assert direct_successors(
        INTEGRATION_NEW_MERCHANT_STANDARD,
        "activate_merchant",
    ) == {
        "complete_project",
    }


@pytest.mark.parametrize(
    "template",
    STANDARD_WORKFLOW_TEMPLATES,
)
def test_terminal_step_depends_on_all_prior_steps(
    template,
):
    terminal_step = max(
        template.steps,
        key=lambda step: step.sequence_number,
    )
    closure = transitive_dependency_closure(template)

    assert set(closure[terminal_step.key]) == {
        step.key
        for step in template.steps
        if step.key != terminal_step.key
    }


@pytest.mark.parametrize(
    ("template", "expected_branches"),
    [
        (
            MEDIA_TOP_UP_NEW_DOCUMENT,
            {
                "document_branch",
                "document_review_branch",
                "procurement_branch",
                "payment_branch",
            },
        ),
        (
            MEDIA_TOP_UP_EXISTING_DOCUMENT,
            {
                "document_branch",
                "payment_branch",
            },
        ),
        (
            OPENING_NEW_CINEMA_STANDARD,
            {
                "document_branch",
                "document_review_branch",
                "procurement_branch",
                "payment_branch",
                "production_branch",
                "uat_branch",
            },
        ),
        (
            INTEGRATION_NEW_MERCHANT_STANDARD,
            {
                "pre_document_branch",
                "document_branch",
                "document_review_branch",
                "procurement_branch",
                "payment_branch",
                "production_branch",
                "uat_branch",
            },
        ),
    ],
)
def test_templates_have_expected_branch_groups(
    template,
    expected_branches,
):
    assert {
        step.branch_key
        for step in template.steps
        if step.branch_key is not None
    } == expected_branches


def test_templates_use_only_allowlisted_conditions():
    condition_keys = {
        step.condition_key
        for template in STANDARD_WORKFLOW_TEMPLATES
        for step in template.steps
        if step.condition_key is not None
    }

    assert condition_keys == {"requires_procurement"}
    assert condition_keys <= ALLOWED_CONDITION_KEYS