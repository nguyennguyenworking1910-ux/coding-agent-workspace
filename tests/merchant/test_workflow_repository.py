"""Unit tests for Merchant workflow persistence."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from psycopg import errors

from claude.agents.tools.merchant.workflow import (
    template_step_uuid,
    template_uuid,
)
from claude.agents.tools.merchant.workflow_templates import (
    STANDARD_WORKFLOW_TEMPLATES,
)
from claude.clients.merchant.workflow_repository import (
    MerchantNotFoundError,
    MerchantWorkflowRepository,
    ProjectCreationConflictError,
    ReusedDocumentValidationError,
    WorkflowTemplateNotInstalledError,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
CREATED_BY = "00000000-0000-0000-0000-000000000003"
REVISION_ID = "00000000-0000-0000-0000-000000000004"


class RecordingContext:
    def __init__(self, value):
        self.value = value
        self.entered = False
        self.exception_type = None

    def __enter__(self):
        self.entered = True
        return self.value

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ):
        self.exception_type = exception_type
        return False


def template_named(name):
    return next(
        template
        for template in STANDARD_WORKFLOW_TEMPLATES
        if template.name == name
    )


def make_workflow_repository():
    repository = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    connection_context = RecordingContext(connection)
    transaction_context = RecordingContext(None)
    cursor_context = RecordingContext(cursor)

    repository.connection.return_value = (
        connection_context
    )
    connection.transaction.return_value = (
        transaction_context
    )
    connection.cursor.return_value = cursor_context

    workflow_repository = MerchantWorkflowRepository(
        repository
    )

    return (
        workflow_repository,
        repository,
        connection,
        cursor,
        transaction_context,
    )


def stored_template(template, **overrides):
    record = {
        "id": template_uuid(template),
        "name": template.name,
        "version": template.version,
        "variant": template.variant,
        "is_active": template.is_active,
    }
    record.update(overrides)

    return record


def stored_template_steps(template):
    return [
        {
            "id": template_step_uuid(
                template,
                step.key,
            )
        }
        for step in template.steps
    ]


def executed_sql(cursor):
    return [
        " ".join(call.args[0].split())
        for call in cursor.execute.call_args_list
    ]


def prepare_standard_creation(
    cursor,
    template,
    *,
    merchant_status="ACTIVE",
    project_record=None,
):
    cursor.fetchone.side_effect = [
        {"account_status": merchant_status},
        stored_template(template),
        project_record,
    ]
    cursor.fetchall.return_value = (
        stored_template_steps(template)
    )


def test_opening_project_is_persisted_atomically():
    (
        workflow_repository,
        repository,
        connection,
        cursor,
        transaction_context,
    ) = make_workflow_repository()
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    prepare_standard_creation(cursor, template)

    result = workflow_repository.create_project(
        merchant_id=MERCHANT_ID,
        template=template,
        requires_procurement=False,
        project_id=PROJECT_ID,
        created_by=CREATED_BY,
        title="Opening project",
    )

    assert result.project_id == PROJECT_ID
    assert result.merchant_id == MERCHANT_ID
    assert result.workflow_variant == template.variant
    assert result.status == "PLANNED"
    assert result.steps_inserted == 22
    assert result.dependencies_inserted == 22

    repository.connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    assert transaction_context.entered
    assert transaction_context.exception_type is None

    sql = executed_sql(cursor)
    combined_sql = "\n".join(sql)

    assert combined_sql.count(
        "INSERT INTO merchant_ops.projects"
    ) == 1
    assert combined_sql.count(
        "INSERT INTO merchant_ops.project_steps"
    ) == 22
    assert combined_sql.count(
        "merchant_ops.project_step_dependencies"
    ) == 22
    assert combined_sql.count(
        "INSERT INTO merchant_ops.project_events"
    ) == 1


def test_project_event_is_inserted_after_project_state():
    (
        workflow_repository,
        _,
        _,
        cursor,
        _,
    ) = make_workflow_repository()
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    prepare_standard_creation(cursor, template)

    workflow_repository.create_project(
        merchant_id=MERCHANT_ID,
        template=template,
        requires_procurement=False,
        project_id=PROJECT_ID,
    )

    sql = executed_sql(cursor)
    project_insert = next(
        index
        for index, query in enumerate(sql)
        if query.startswith(
            "INSERT INTO merchant_ops.projects"
        )
    )
    event_insert = next(
        index
        for index, query in enumerate(sql)
        if query.startswith(
            "INSERT INTO merchant_ops.project_events"
        )
    )

    assert event_insert > project_insert
    assert event_insert == len(sql) - 1


def test_missing_merchant_rolls_back_before_writes():
    (
        workflow_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_workflow_repository()

    cursor.fetchone.return_value = None

    with pytest.raises(MerchantNotFoundError):
        workflow_repository.create_project(
            merchant_id=MERCHANT_ID,
            template=template_named(
                "OPENING_NEW_CINEMA_STANDARD"
            ),
            requires_procurement=False,
            project_id=PROJECT_ID,
        )

    assert transaction_context.exception_type is (
        MerchantNotFoundError
    )
    assert "INSERT INTO" not in "\n".join(
        executed_sql(cursor)
    )


def test_missing_template_rolls_back_before_writes():
    (
        workflow_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_workflow_repository()
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    cursor.fetchone.side_effect = [
        {"account_status": "ACTIVE"},
        None,
    ]

    with pytest.raises(
        WorkflowTemplateNotInstalledError
    ):
        workflow_repository.create_project(
            merchant_id=MERCHANT_ID,
            template=template,
            requires_procurement=False,
            project_id=PROJECT_ID,
        )

    assert transaction_context.exception_type is (
        WorkflowTemplateNotInstalledError
    )
    assert "INSERT INTO" not in "\n".join(
        executed_sql(cursor)
    )


def test_changed_template_metadata_is_rejected():
    (
        workflow_repository,
        _,
        _,
        cursor,
        _,
    ) = make_workflow_repository()
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    cursor.fetchone.side_effect = [
        {"account_status": "ACTIVE"},
        stored_template(
            template,
            variant="WRONG_VARIANT",
        ),
    ]

    with pytest.raises(
        WorkflowTemplateNotInstalledError,
        match="metadata",
    ):
        workflow_repository.create_project(
            merchant_id=MERCHANT_ID,
            template=template,
            requires_procurement=False,
            project_id=PROJECT_ID,
        )


def test_changed_template_steps_are_rejected():
    (
        workflow_repository,
        _,
        _,
        cursor,
        _,
    ) = make_workflow_repository()
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    cursor.fetchone.side_effect = [
        {"account_status": "ACTIVE"},
        stored_template(template),
    ]
    cursor.fetchall.return_value = [
        {"id": "00000000-0000-0000-0000-000000000099"}
    ]

    with pytest.raises(
        WorkflowTemplateNotInstalledError,
        match="steps",
    ):
        workflow_repository.create_project(
            merchant_id=MERCHANT_ID,
            template=template,
            requires_procurement=False,
            project_id=PROJECT_ID,
        )


def test_existing_project_id_is_rejected():
    (
        workflow_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_workflow_repository()
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    prepare_standard_creation(
        cursor,
        template,
        project_record={"id": PROJECT_ID},
    )

    with pytest.raises(
        ProjectCreationConflictError,
        match="already exists",
    ):
        workflow_repository.create_project(
            merchant_id=MERCHANT_ID,
            template=template,
            requires_procurement=False,
            project_id=PROJECT_ID,
        )

    assert transaction_context.exception_type is (
        ProjectCreationConflictError
    )
    assert "INSERT INTO" not in "\n".join(
        executed_sql(cursor)
    )


def prepare_reused_document_creation(
    cursor,
    *,
    revision_record,
):
    template = template_named(
        "MEDIA_TOP_UP_EXISTING_DOCUMENT"
    )
    cursor.fetchone.side_effect = [
        {"account_status": "ACTIVE"},
        stored_template(template),
        None,
        revision_record,
    ]
    cursor.fetchall.return_value = (
        stored_template_steps(template)
    )

    return template


def test_missing_reused_document_is_rejected():
    (
        workflow_repository,
        _,
        _,
        cursor,
        _,
    ) = make_workflow_repository()

    template = prepare_reused_document_creation(
        cursor,
        revision_record=None,
    )

    with pytest.raises(
        ReusedDocumentValidationError,
        match="not found",
    ):
        workflow_repository.create_project(
            merchant_id=MERCHANT_ID,
            template=template,
            requires_procurement=False,
            payment_period_number=1,
            reused_document_revision_id=REVISION_ID,
            project_id=PROJECT_ID,
        )


def test_unsigned_reused_document_is_rejected():
    (
        workflow_repository,
        _,
        _,
        cursor,
        _,
    ) = make_workflow_repository()

    template = prepare_reused_document_creation(
        cursor,
        revision_record={
            "id": REVISION_ID,
            "signed": False,
            "signed_at": None,
            "superseded_by": None,
        },
    )

    with pytest.raises(
        ReusedDocumentValidationError,
        match="must be signed",
    ):
        workflow_repository.create_project(
            merchant_id=MERCHANT_ID,
            template=template,
            requires_procurement=False,
            payment_period_number=1,
            reused_document_revision_id=REVISION_ID,
            project_id=PROJECT_ID,
        )


def test_superseded_reused_document_is_rejected():
    (
        workflow_repository,
        _,
        _,
        cursor,
        _,
    ) = make_workflow_repository()

    template = prepare_reused_document_creation(
        cursor,
        revision_record={
            "id": REVISION_ID,
            "signed": True,
            "signed_at": "timestamp",
            "superseded_by": (
                "00000000-0000-0000-0000-000000000099"
            ),
        },
    )

    with pytest.raises(
        ReusedDocumentValidationError,
        match="superseded",
    ):
        workflow_repository.create_project(
            merchant_id=MERCHANT_ID,
            template=template,
            requires_procurement=False,
            payment_period_number=1,
            reused_document_revision_id=REVISION_ID,
            project_id=PROJECT_ID,
        )


def test_valid_reused_document_project_is_inserted():
    (
        workflow_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_workflow_repository()

    template = prepare_reused_document_creation(
        cursor,
        revision_record={
            "id": REVISION_ID,
            "signed": True,
            "signed_at": "timestamp",
            "superseded_by": None,
        },
    )

    result = workflow_repository.create_project(
        merchant_id=MERCHANT_ID,
        template=template,
        requires_procurement=False,
        payment_period_number=2,
        reused_document_revision_id=REVISION_ID,
        project_id=PROJECT_ID,
    )

    assert result.steps_inserted == 4
    assert result.dependencies_inserted == 3
    assert transaction_context.exception_type is None

    combined_sql = "\n".join(
        executed_sql(cursor)
    )
    assert combined_sql.count(
        "INSERT INTO merchant_ops.projects"
    ) == 1
    assert combined_sql.count(
        "INSERT INTO merchant_ops.project_events"
    ) == 1


def test_unique_violation_is_wrapped_and_rolled_back():
    (
        workflow_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_workflow_repository()
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    prepare_standard_creation(cursor, template)

    def execute(query, parameters=None):
        normalized = " ".join(query.split())

        if normalized.startswith(
            "INSERT INTO merchant_ops.projects"
        ):
            raise errors.UniqueViolation(
                "duplicate project"
            )

    cursor.execute.side_effect = execute

    with pytest.raises(
        ProjectCreationConflictError,
        match="conflicts",
    ):
        workflow_repository.create_project(
            merchant_id=MERCHANT_ID,
            template=template,
            requires_procurement=False,
            project_id=PROJECT_ID,
        )

    assert transaction_context.exception_type is (
        errors.UniqueViolation
    )

    assert not any(
        query.startswith(
            "INSERT INTO merchant_ops.project_events"
        )
        for query in executed_sql(cursor)
    )


def test_creation_result_is_json_compatible():
    (
        workflow_repository,
        _,
        _,
        cursor,
        _,
    ) = make_workflow_repository()
    template = template_named(
        "OPENING_NEW_CINEMA_STANDARD"
    )

    prepare_standard_creation(cursor, template)

    result = workflow_repository.create_project(
        merchant_id=MERCHANT_ID,
        template=template,
        requires_procurement=False,
        project_id=PROJECT_ID,
    )

    assert result.to_dict() == {
        "project_id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "workflow_variant": (
            "OPENING_NEW_CINEMA_STANDARD"
        ),
        "status": "PLANNED",
        "steps_inserted": 22,
        "dependencies_inserted": 22,
        "event_id": result.event_id,
    }