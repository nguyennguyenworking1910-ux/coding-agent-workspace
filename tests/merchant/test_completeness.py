import pytest

from claude.agents.tools.merchant.completeness import (
    REQUIRED_WRITE_FIELDS,
    StatefulCompletenessContext,
    build_clarification_payload,
    validate_stateful_write_completeness,
    validate_write_completeness,
)


def test_document_revision_create_reports_all_missing_fields():
    result = validate_write_completeness(
        "document revision-create",
        {},
    )

    assert result.complete is False

    assert result.missing_fields == (
        "project_id",
        "document_type",
        "content_hash",
    )


def test_document_revision_create_does_not_stop_at_first_missing_field():
    result = validate_write_completeness(
        "document revision-create",
        {
            "project_id": (
                "2da7ab08-1eda-5ca2-b28e-f94f3e1be0d0"
            ),
        },
    )

    assert result.complete is False

    assert result.missing_fields == (
        "document_type",
        "content_hash",
    )


def test_document_revision_create_is_complete_only_with_all_required_fields():
    result = validate_write_completeness(
        "document revision-create",
        {
            "project_id": "project-123",
            "document_type": "APPENDIX",
            "content_hash": "abc123",
        },
    )

    assert result.complete is True
    assert result.missing_fields == ()


def test_blank_required_string_is_missing():
    result = validate_write_completeness(
        "document revision-create",
        {
            "project_id": "project-123",
            "document_type": "   ",
            "content_hash": "abc123",
        },
    )

    assert result.complete is False

    assert result.missing_fields == (
        "document_type",
    )


@pytest.mark.parametrize(
    ("command", "required_fields"),
    [
        (
            "merchant create",
            (
                "code",
                "name",
            ),
        ),
        (
            "merchant activate",
            (
                "merchant_id",
                "expected_version",
                "reason",
                "triggered_by",
            ),
        ),
        (
            "merchant activate-all",
            (
                "from_status",
                "expected_count",
                "reason",
                "triggered_by",
            ),
        ),
        (
            "contact import",
            (
                "merchant_id",
                "file",
                "expected_version",
            ),
        ),
        (
            "project create",
            (
                "merchant_id",
                "project_type",
                "workflow_variant",
            ),
        ),
        (
            "project update",
            (
                "project_id",
                "status",
                "expected_version",
            ),
        ),
        (
            "step update",
            (
                "step_id",
                "status",
                "expected_version",
            ),
        ),
        (
            "document revision-create",
            (
                "project_id",
                "document_type",
                "content_hash",
            ),
        ),
        (
            "document approve",
            (
                "revision_id",
                "approver_role",
                "approval_status",
            ),
        ),
        (
            "procurement update",
            (
                "project_id",
                "procurement_type",
            ),
        ),
        (
            "integration identifier-set",
            (
                "merchant_id",
                "identifier_type",
                "value",
                "scope",
            ),
        ),
    ],
)
def test_all_write_commands_report_all_static_required_fields(
    command,
    required_fields,
):
    result = validate_write_completeness(
        command,
        {},
    )

    assert result.complete is False

    assert (
        result.missing_fields
        == required_fields
    )


def test_static_completeness_contract_covers_all_write_commands():
    expected_commands = {
        "merchant create",
        "merchant activate",
        "merchant activate-all",
        "contact import",
        "project create",
        "project update",
        "step update",
        "document revision-create",
        "document approve",
        "procurement update",
        "integration identifier-set",
    }

    assert (
        set(REQUIRED_WRITE_FIELDS)
        == expected_commands
    )


def test_false_and_zero_are_not_missing_values():
    result = validate_write_completeness(
        "project create",
        {
            "merchant_id": "merchant-123",
            "project_type": "MEDIA_TOP_UP",
            "workflow_variant": "STANDARD",
            "requires_procurement": False,
        },
    )

    assert result.complete is True


def test_new_procurement_requires_status_or_external_id():
    result = validate_stateful_write_completeness(
        "procurement update",
        {
            "project_id": "project-123",
            "procurement_type": "PURCHASE_REQUEST",
        },
        StatefulCompletenessContext(
            current_record_exists=False,
        ),
    )

    assert result.complete is False
    assert result.missing_fields == ()

    assert result.missing_one_of == (
        (
            "status",
            "external_id",
        ),
    )


@pytest.mark.parametrize(
    "field",
    (
        "status",
        "external_id",
    ),
)
def test_new_procurement_accepts_either_evidence_field(
    field,
):
    result = validate_stateful_write_completeness(
        "procurement update",
        {
            "project_id": "project-123",
            "procurement_type": "PURCHASE_REQUEST",
            field: "VALUE",
        },
        StatefulCompletenessContext(
            current_record_exists=False,
        ),
    )

    assert result.complete is True
    assert result.missing_one_of == ()


def test_existing_procurement_requires_expected_version():
    result = validate_stateful_write_completeness(
        "procurement update",
        {
            "project_id": "project-123",
            "procurement_type": "PURCHASE_REQUEST",
            "status": "APPROVED",
        },
        StatefulCompletenessContext(
            current_record_exists=True,
        ),
    )

    assert result.complete is False

    assert result.missing_fields == (
        "expected_version",
    )


def test_existing_identifier_requires_expected_version():
    result = validate_stateful_write_completeness(
        "integration identifier-set",
        {
            "merchant_id": "merchant-123",
            "identifier_type": "PRODUCT_ID",
            "value": "private-id",
            "scope": "UAT",
        },
        StatefulCompletenessContext(
            current_record_exists=True,
        ),
    )

    assert result.complete is False

    assert result.missing_fields == (
        "expected_version",
    )


def test_new_identifier_does_not_require_expected_version():
    result = validate_stateful_write_completeness(
        "integration identifier-set",
        {
            "merchant_id": "merchant-123",
            "identifier_type": "PRODUCT_ID",
            "value": "private-id",
            "scope": "UAT",
        },
        StatefulCompletenessContext(
            current_record_exists=False,
        ),
    )

    assert result.complete is True


def test_procurement_with_multiple_active_document_types_requires_document_type():
    result = validate_stateful_write_completeness(
        "procurement update",
        {
            "project_id": "project-123",
            "procurement_type": "PURCHASE_ORDER",
            "status": "CREATED",
        },
        StatefulCompletenessContext(
            current_record_exists=False,
            active_document_types=(
                "MERCHANT_AGREEMENT",
                "APPENDIX",
            ),
        ),
    )

    assert result.complete is False

    assert result.missing_fields == (
        "document_type",
    )


def test_clarification_payload_for_multiple_missing_fields():
    result = validate_write_completeness(
        "document revision-create",
        {},
    )

    clarification = (
        build_clarification_payload(
            result
        )
    )

    assert clarification is not None

    assert (
        clarification.outcome
        == "REQUIRES_CLARIFICATION"
    )

    assert clarification.missing_fields == (
        "project_id",
        "document_type",
        "content_hash",
    )

    assert (
        clarification.missing_one_of
        == ()
    )

    assert clarification.question == (
        "Please provide project_id, "
        "document_type, and content_hash."
    )


def test_clarification_payload_for_one_missing_field():
    result = validate_write_completeness(
        "document revision-create",
        {
            "project_id": "project-123",
            "document_type": "APPENDIX",
        },
    )

    clarification = (
        build_clarification_payload(
            result
        )
    )

    assert clarification is not None

    assert clarification.question == (
        "Please provide content_hash."
    )


def test_clarification_payload_for_one_of_requirement():
    result = validate_stateful_write_completeness(
        "procurement update",
        {
            "project_id": "project-123",
            "procurement_type": (
                "PURCHASE_REQUEST"
            ),
        },
        StatefulCompletenessContext(
            current_record_exists=False,
        ),
    )

    clarification = (
        build_clarification_payload(
            result
        )
    )

    assert clarification is not None

    assert clarification.missing_fields == ()

    assert clarification.missing_one_of == (
        (
            "status",
            "external_id",
        ),
    )

    assert clarification.question == (
        "Please provide at least one of "
        "status and external_id."
    )


def test_clarification_payload_combines_direct_and_one_of_requirements():
    result = validate_stateful_write_completeness(
        "procurement update",
        {
            "project_id": "project-123",
            "procurement_type": (
                "PURCHASE_ORDER"
            ),
        },
        StatefulCompletenessContext(
            current_record_exists=False,
            active_document_types=(
                "MERCHANT_AGREEMENT",
                "APPENDIX",
            ),
        ),
    )

    clarification = (
        build_clarification_payload(
            result
        )
    )

    assert clarification is not None

    assert clarification.missing_fields == (
        "document_type",
    )

    assert clarification.missing_one_of == (
        (
            "status",
            "external_id",
        ),
    )

    assert clarification.question == (
        "Please provide document_type; "
        "Please provide at least one of "
        "status and external_id."
    )


def test_complete_request_has_no_clarification_payload():
    result = validate_write_completeness(
        "merchant create",
        {
            "code": "CGV",
            "name": "CGV",
        },
    )

    assert result.complete is True

    assert (
        build_clarification_payload(
            result
        )
        is None
    )


def test_clarification_payload_serializes_to_plain_json_shape():
    result = validate_write_completeness(
        "project update",
        {},
    )

    clarification = (
        build_clarification_payload(
            result
        )
    )

    assert clarification is not None

    assert clarification.to_dict() == {
        "outcome": (
            "REQUIRES_CLARIFICATION"
        ),
        "missing_fields": [
            "project_id",
            "status",
            "expected_version",
        ],
        "missing_one_of": [],
        "question": (
            "Please provide project_id, "
            "status, and expected_version."
        ),
    }