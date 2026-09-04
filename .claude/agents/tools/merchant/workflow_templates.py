"""Canonical Merchant workflow template definitions."""

from __future__ import annotations

from types import MappingProxyType

from .workflow import (
    WorkflowDefinitionError,
    WorkflowDependencyDefinition,
    WorkflowStepDefinition,
    WorkflowTemplateDefinition,
    template_fingerprint,
    template_uuid,
    validate_template_definition,
)


def _step(
    sequence_number: int,
    key: str,
    name: str,
    *,
    step_type: str = "SEQUENTIAL",
    branch_key: str | None = None,
    is_optional: bool = False,
    condition_key: str | None = None,
) -> WorkflowStepDefinition:
    return WorkflowStepDefinition(
        key=key,
        sequence_number=sequence_number,
        step_type=step_type,
        name=name,
        branch_key=branch_key,
        is_optional=is_optional,
        condition_key=condition_key,
    )


def _dependency(
    source: str,
    destination: str,
    dependency_type: str = "MUST_COMPLETE_BEFORE",
) -> WorkflowDependencyDefinition:
    return WorkflowDependencyDefinition(
        from_step_key=source,
        to_step_key=destination,
        dependency_type=dependency_type,
    )


MEDIA_TOP_UP_NEW_DOCUMENT = WorkflowTemplateDefinition(
    name="MEDIA_TOP_UP_NEW_DOCUMENT",
    version=1,
    project_type="MEDIA_TOP_UP",
    variant="MEDIA_TOP_UP_NEW_DOCUMENT",
    description=(
        "Media top-up requiring a new or renewed document "
        "and mandatory procurement."
    ),
    steps=(
        _step(
            1,
            "draft_document",
            "Draft or renew document",
            branch_key="document_branch",
        ),
        _step(
            2,
            "legal_review",
            "Legal review",
            step_type="PARALLEL_BRANCH",
            branch_key="document_review_branch",
        ),
        _step(
            3,
            "accounting_review",
            "Accounting review",
            step_type="PARALLEL_BRANCH",
            branch_key="document_review_branch",
        ),
        _step(
            4,
            "send_reviewed_revision_to_partner",
            "Send reviewed revision to Partner",
            branch_key="document_branch",
        ),
        _step(
            5,
            "record_partner_approval",
            "Record Partner approval",
            step_type="APPROVAL_GATE",
            branch_key="document_branch",
        ),
        _step(
            6,
            "create_purchase_request",
            "Create Purchase Request",
            step_type="PARALLEL_BRANCH",
            branch_key="procurement_branch",
        ),
        _step(
            7,
            "record_purchase_request_number",
            "Record Purchase Request number",
            step_type="PARALLEL_BRANCH",
            branch_key="procurement_branch",
        ),
        _step(
            8,
            "validate_signing_gate",
            "Validate signing gate",
            step_type="APPROVAL_GATE",
            branch_key="document_branch",
        ),
        _step(
            9,
            "sign_document",
            "Sign document",
            branch_key="document_branch",
        ),
        _step(
            10,
            "create_purchase_order",
            "Create Purchase Order",
            branch_key="payment_branch",
        ),
        _step(
            11,
            "create_payment_request",
            "Create Payment Request",
            branch_key="payment_branch",
        ),
        _step(
            12,
            "close_payment_period",
            "Close payment period",
            step_type="APPROVAL_GATE",
            branch_key="payment_branch",
        ),
    ),
    dependencies=(
        _dependency("draft_document", "legal_review"),
        _dependency("draft_document", "accounting_review"),
        _dependency(
            "legal_review",
            "send_reviewed_revision_to_partner",
        ),
        _dependency(
            "accounting_review",
            "send_reviewed_revision_to_partner",
        ),
        _dependency(
            "send_reviewed_revision_to_partner",
            "record_partner_approval",
        ),
        _dependency(
            "create_purchase_request",
            "record_purchase_request_number",
        ),
        _dependency(
            "record_partner_approval",
            "validate_signing_gate",
        ),
        _dependency(
            "record_purchase_request_number",
            "validate_signing_gate",
        ),
        _dependency(
            "validate_signing_gate",
            "sign_document",
        ),
        _dependency(
            "sign_document",
            "create_purchase_order",
        ),
        _dependency(
            "create_purchase_order",
            "create_payment_request",
        ),
        _dependency(
            "create_payment_request",
            "close_payment_period",
        ),
    ),
)


MEDIA_TOP_UP_EXISTING_DOCUMENT = WorkflowTemplateDefinition(
    name="MEDIA_TOP_UP_EXISTING_DOCUMENT",
    version=1,
    project_type="MEDIA_TOP_UP",
    variant="MEDIA_TOP_UP_EXISTING_DOCUMENT",
    description=(
        "Media top-up using a valid signed document for "
        "payment period two or later."
    ),
    steps=(
        _step(
            1,
            "validate_existing_document",
            "Validate existing signed document",
            step_type="APPROVAL_GATE",
            branch_key="document_branch",
        ),
        _step(
            2,
            "create_purchase_order",
            "Create Purchase Order",
            branch_key="payment_branch",
        ),
        _step(
            3,
            "create_payment_request",
            "Create Payment Request",
            branch_key="payment_branch",
        ),
        _step(
            4,
            "close_payment_period",
            "Close payment period",
            step_type="APPROVAL_GATE",
            branch_key="payment_branch",
        ),
    ),
    dependencies=(
        _dependency(
            "validate_existing_document",
            "create_purchase_order",
        ),
        _dependency(
            "create_purchase_order",
            "create_payment_request",
        ),
        _dependency(
            "create_payment_request",
            "close_payment_period",
        ),
    ),
)


OPENING_NEW_CINEMA_STANDARD = WorkflowTemplateDefinition(
    name="OPENING_NEW_CINEMA_STANDARD",
    version=1,
    project_type="OPENING_NEW_CINEMA",
    variant="OPENING_NEW_CINEMA_STANDARD",
    description=(
        "New cinema opening with document, optional "
        "procurement, Production, and UAT branches."
    ),
    steps=(
        _step(
            1,
            "draft_document",
            "Draft or renew document",
            branch_key="document_branch",
        ),
        _step(
            2,
            "legal_review",
            "Legal review",
            step_type="PARALLEL_BRANCH",
            branch_key="document_review_branch",
        ),
        _step(
            3,
            "accounting_review",
            "Accounting review",
            step_type="PARALLEL_BRANCH",
            branch_key="document_review_branch",
        ),
        _step(
            4,
            "send_reviewed_revision_to_partner",
            "Send reviewed revision to Partner",
            branch_key="document_branch",
        ),
        _step(
            5,
            "record_partner_approval",
            "Record Partner approval",
            step_type="APPROVAL_GATE",
            branch_key="document_branch",
        ),
        _step(
            6,
            "create_purchase_request",
            "Create Purchase Request",
            step_type="CONDITIONAL",
            branch_key="procurement_branch",
            is_optional=True,
            condition_key="requires_procurement",
        ),
        _step(
            7,
            "record_purchase_request_number",
            "Record Purchase Request number",
            step_type="CONDITIONAL",
            branch_key="procurement_branch",
            is_optional=True,
            condition_key="requires_procurement",
        ),
        _step(
            8,
            "validate_signing_gate",
            "Validate signing gate",
            step_type="APPROVAL_GATE",
            branch_key="document_branch",
        ),
        _step(
            9,
            "sign_document",
            "Sign document",
            branch_key="document_branch",
        ),
        _step(
            10,
            "create_purchase_order",
            "Create Purchase Order",
            branch_key="payment_branch",
        ),
        _step(
            11,
            "create_payment_request",
            "Create Payment Request",
            branch_key="payment_branch",
        ),
        _step(
            12,
            "create_production_agent",
            "Create Production agent",
            step_type="PARALLEL_BRANCH",
            branch_key="production_branch",
        ),
        _step(
            13,
            "configure_production_service_list",
            "Configure Production service list",
            step_type="PARALLEL_BRANCH",
            branch_key="production_branch",
        ),
        _step(
            14,
            "send_production_information",
            "Send Production information to Partner",
            step_type="PARALLEL_BRANCH",
            branch_key="production_branch",
        ),
        _step(
            15,
            "configure_uat_agent",
            "Configure UAT agent",
            step_type="PARALLEL_BRANCH",
            branch_key="uat_branch",
        ),
        _step(
            16,
            "configure_uat_product",
            "Configure UAT Product ID or orderGroupID",
            step_type="PARALLEL_BRANCH",
            branch_key="uat_branch",
        ),
        _step(
            17,
            "configure_uat_identity",
            "Configure UAT MID or partnerCode",
            step_type="PARALLEL_BRANCH",
            branch_key="uat_branch",
        ),
        _step(
            18,
            "send_uat_information",
            "Send UAT information to Partner",
            step_type="PARALLEL_BRANCH",
            branch_key="uat_branch",
        ),
        _step(
            19,
            "create_uat_jira_ticket",
            "Create UAT JIRA ticket",
            step_type="PARALLEL_BRANCH",
            branch_key="uat_branch",
        ),
        _step(
            20,
            "run_uat_test",
            "Run UAT test",
            step_type="PARALLEL_BRANCH",
            branch_key="uat_branch",
        ),
        _step(
            21,
            "complete_uat_acceptance",
            "Complete UAT acceptance",
            step_type="APPROVAL_GATE",
            branch_key="uat_branch",
        ),
        _step(
            22,
            "complete_project",
            "Complete project",
            step_type="APPROVAL_GATE",
        ),
    ),
    dependencies=(
        _dependency("draft_document", "legal_review"),
        _dependency("draft_document", "accounting_review"),
        _dependency(
            "legal_review",
            "send_reviewed_revision_to_partner",
        ),
        _dependency(
            "accounting_review",
            "send_reviewed_revision_to_partner",
        ),
        _dependency(
            "send_reviewed_revision_to_partner",
            "record_partner_approval",
        ),
        _dependency(
            "create_purchase_request",
            "record_purchase_request_number",
        ),
        _dependency(
            "record_partner_approval",
            "validate_signing_gate",
        ),
        _dependency(
            "record_purchase_request_number",
            "validate_signing_gate",
        ),
        _dependency(
            "validate_signing_gate",
            "sign_document",
        ),
        _dependency(
            "sign_document",
            "create_purchase_order",
        ),
        _dependency(
            "create_purchase_order",
            "create_payment_request",
        ),
        _dependency(
            "sign_document",
            "create_production_agent",
        ),
        _dependency(
            "create_production_agent",
            "configure_production_service_list",
        ),
        _dependency(
            "configure_production_service_list",
            "send_production_information",
        ),
        _dependency(
            "sign_document",
            "configure_uat_agent",
        ),
        _dependency(
            "configure_uat_agent",
            "configure_uat_product",
        ),
        _dependency(
            "configure_uat_product",
            "configure_uat_identity",
        ),
        _dependency(
            "configure_uat_identity",
            "send_uat_information",
        ),
        _dependency(
            "send_uat_information",
            "create_uat_jira_ticket",
        ),
        _dependency(
            "create_uat_jira_ticket",
            "run_uat_test",
        ),
        _dependency(
            "run_uat_test",
            "complete_uat_acceptance",
        ),
        _dependency(
            "create_payment_request",
            "complete_project",
        ),
        _dependency(
            "send_production_information",
            "complete_project",
        ),
        _dependency(
            "complete_uat_acceptance",
            "complete_project",
        ),
    ),
)


INTEGRATION_NEW_MERCHANT_STANDARD = (
    WorkflowTemplateDefinition(
        name="INTEGRATION_NEW_MERCHANT_STANDARD",
        version=1,
        project_type="INTEGRATION_NEW_MERCHANT",
        variant="INTEGRATION_NEW_MERCHANT_STANDARD",
        description=(
            "New Merchant integration with onboarding gates, "
            "document review, optional procurement, Production, "
            "UAT, and atomic Merchant activation."
        ),
        steps=(
            _step(
                1,
                "aml_check",
                "Complete AML check",
                step_type="PARALLEL_BRANCH",
                branch_key="pre_document_branch",
            ),
            _step(
                2,
                "partner_information_check",
                "Check Partner information",
                step_type="PARALLEL_BRANCH",
                branch_key="pre_document_branch",
            ),
            _step(
                3,
                "validate_master_merchant_identity",
                "Validate Master Merchant identity",
                step_type="APPROVAL_GATE",
                branch_key="pre_document_branch",
            ),
            _step(
                4,
                "draft_document",
                "Draft or renew document",
                branch_key="document_branch",
            ),
            _step(
                5,
                "legal_review",
                "Legal review",
                step_type="PARALLEL_BRANCH",
                branch_key="document_review_branch",
            ),
            _step(
                6,
                "accounting_review",
                "Accounting review",
                step_type="PARALLEL_BRANCH",
                branch_key="document_review_branch",
            ),
            _step(
                7,
                "send_reviewed_revision_to_partner",
                "Send reviewed revision to Partner",
                branch_key="document_branch",
            ),
            _step(
                8,
                "record_partner_approval",
                "Record Partner approval",
                step_type="APPROVAL_GATE",
                branch_key="document_branch",
            ),
            _step(
                9,
                "create_purchase_request",
                "Create Purchase Request",
                step_type="CONDITIONAL",
                branch_key="procurement_branch",
                is_optional=True,
                condition_key="requires_procurement",
            ),
            _step(
                10,
                "record_purchase_request_number",
                "Record Purchase Request number",
                step_type="CONDITIONAL",
                branch_key="procurement_branch",
                is_optional=True,
                condition_key="requires_procurement",
            ),
            _step(
                11,
                "validate_signing_gate",
                "Validate signing gate",
                step_type="APPROVAL_GATE",
                branch_key="document_branch",
            ),
            _step(
                12,
                "sign_document",
                "Sign document",
                branch_key="document_branch",
            ),
            _step(
                13,
                "create_purchase_order",
                "Create Purchase Order",
                branch_key="payment_branch",
            ),
            _step(
                14,
                "create_payment_request",
                "Create Payment Request",
                branch_key="payment_branch",
            ),
            _step(
                15,
                "create_production_agent",
                "Create Production agent",
                step_type="PARALLEL_BRANCH",
                branch_key="production_branch",
            ),
            _step(
                16,
                "configure_production_service_list",
                "Configure Production service list",
                step_type="PARALLEL_BRANCH",
                branch_key="production_branch",
            ),
            _step(
                17,
                "send_production_information",
                "Send Production information to Partner",
                step_type="PARALLEL_BRANCH",
                branch_key="production_branch",
            ),
            _step(
                18,
                "configure_uat_agent",
                "Configure UAT agent",
                step_type="PARALLEL_BRANCH",
                branch_key="uat_branch",
            ),
            _step(
                19,
                "configure_uat_product",
                "Configure UAT Product ID or orderGroupID",
                step_type="PARALLEL_BRANCH",
                branch_key="uat_branch",
            ),
            _step(
                20,
                "configure_uat_identity",
                "Configure UAT MID or partnerCode",
                step_type="PARALLEL_BRANCH",
                branch_key="uat_branch",
            ),
            _step(
                21,
                "send_uat_information",
                "Send UAT information to Partner",
                step_type="PARALLEL_BRANCH",
                branch_key="uat_branch",
            ),
            _step(
                22,
                "create_uat_jira_ticket",
                "Create UAT JIRA ticket",
                step_type="PARALLEL_BRANCH",
                branch_key="uat_branch",
            ),
            _step(
                23,
                "run_uat_test",
                "Run UAT test",
                step_type="PARALLEL_BRANCH",
                branch_key="uat_branch",
            ),
            _step(
                24,
                "complete_uat_acceptance",
                "Complete UAT acceptance",
                step_type="APPROVAL_GATE",
                branch_key="uat_branch",
            ),
            _step(
                25,
                "activate_merchant",
                "Activate Merchant",
                step_type="APPROVAL_GATE",
            ),
            _step(
                26,
                "complete_project",
                "Complete project",
                step_type="APPROVAL_GATE",
            ),
        ),
        dependencies=(
            _dependency(
                "aml_check",
                "validate_master_merchant_identity",
            ),
            _dependency(
                "partner_information_check",
                "validate_master_merchant_identity",
            ),
            _dependency(
                "validate_master_merchant_identity",
                "draft_document",
            ),
            _dependency(
                "validate_master_merchant_identity",
                "create_purchase_request",
            ),
            _dependency("draft_document", "legal_review"),
            _dependency(
                "draft_document",
                "accounting_review",
            ),
            _dependency(
                "legal_review",
                "send_reviewed_revision_to_partner",
            ),
            _dependency(
                "accounting_review",
                "send_reviewed_revision_to_partner",
            ),
            _dependency(
                "send_reviewed_revision_to_partner",
                "record_partner_approval",
            ),
            _dependency(
                "create_purchase_request",
                "record_purchase_request_number",
            ),
            _dependency(
                "record_partner_approval",
                "validate_signing_gate",
            ),
            _dependency(
                "record_purchase_request_number",
                "validate_signing_gate",
            ),
            _dependency(
                "validate_signing_gate",
                "sign_document",
            ),
            _dependency(
                "sign_document",
                "create_purchase_order",
            ),
            _dependency(
                "create_purchase_order",
                "create_payment_request",
            ),
            _dependency(
                "sign_document",
                "create_production_agent",
            ),
            _dependency(
                "create_production_agent",
                "configure_production_service_list",
            ),
            _dependency(
                "configure_production_service_list",
                "send_production_information",
            ),
            _dependency(
                "sign_document",
                "configure_uat_agent",
            ),
            _dependency(
                "configure_uat_agent",
                "configure_uat_product",
            ),
            _dependency(
                "configure_uat_product",
                "configure_uat_identity",
            ),
            _dependency(
                "configure_uat_identity",
                "send_uat_information",
            ),
            _dependency(
                "send_uat_information",
                "create_uat_jira_ticket",
            ),
            _dependency(
                "create_uat_jira_ticket",
                "run_uat_test",
            ),
            _dependency(
                "run_uat_test",
                "complete_uat_acceptance",
            ),
            _dependency(
                "create_payment_request",
                "activate_merchant",
            ),
            _dependency(
                "send_production_information",
                "activate_merchant",
            ),
            _dependency(
                "complete_uat_acceptance",
                "activate_merchant",
            ),
            _dependency(
                "activate_merchant",
                "complete_project",
            ),
        ),
    )
)


STANDARD_WORKFLOW_TEMPLATES = (
    MEDIA_TOP_UP_NEW_DOCUMENT,
    MEDIA_TOP_UP_EXISTING_DOCUMENT,
    OPENING_NEW_CINEMA_STANDARD,
    INTEGRATION_NEW_MERCHANT_STANDARD,
)

for _template in STANDARD_WORKFLOW_TEMPLATES:
    validate_template_definition(_template)

_template_keys = [
    (template.variant, template.version)
    for template in STANDARD_WORKFLOW_TEMPLATES
]

if len(_template_keys) != len(set(_template_keys)):
    raise WorkflowDefinitionError(
        "Duplicate standard workflow template version"
    )

STANDARD_WORKFLOW_TEMPLATES_BY_KEY = MappingProxyType(
    {
        (template.variant, template.version): template
        for template in STANDARD_WORKFLOW_TEMPLATES
    }
)


def get_standard_workflow_template(
    variant: str,
    version: int = 1,
) -> WorkflowTemplateDefinition:
    """Return one exact immutable standard template version."""

    try:
        return STANDARD_WORKFLOW_TEMPLATES_BY_KEY[
            (variant, version)
        ]
    except KeyError as error:
        raise WorkflowDefinitionError(
            "Unknown standard workflow template: "
            f"{variant!r} version {version}"
        ) from error


def standard_template_manifest() -> tuple[dict[str, object], ...]:
    """Return stable IDs and fingerprints for all templates."""

    return tuple(
        {
            "name": template.name,
            "variant": template.variant,
            "version": template.version,
            "project_type": template.project_type,
            "template_id": str(template_uuid(template)),
            "fingerprint": template_fingerprint(template),
            "step_count": len(template.steps),
            "dependency_count": len(
                template.dependencies
            ),
        }
        for template in STANDARD_WORKFLOW_TEMPLATES
    )