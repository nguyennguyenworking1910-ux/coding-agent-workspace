"""Unit tests for the immutable workflow-template loader."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from claude.agents.tools.merchant.workflow import (
    template_uuid,
)
from claude.agents.tools.merchant.workflow_templates import (
    STANDARD_WORKFLOW_TEMPLATES,
)
from claude.clients.merchant.template_loader import (
    WorkflowTemplateConflictError,
    WorkflowTemplateLoader,
    WorkflowTemplateLoadError,
    WorkflowTemplateLoadResult,
)


def make_loader():
    repository = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    repository.connection.return_value = nullcontext(
        connection
    )
    connection.transaction.return_value = nullcontext()
    connection.cursor.return_value = nullcontext(cursor)

    return (
        WorkflowTemplateLoader(repository),
        repository,
        connection,
        cursor,
    )


def expected_existing_records(loader, template):
    template_record = loader._expected_template_record(
        template
    )
    step_records = loader._expected_step_records(template)
    dependency_records = (
        loader._expected_dependency_records(template)
    )

    return (
        template_record,
        step_records,
        dependency_records,
    )


def executed_sql(cursor):
    return "\n".join(
        " ".join(call.args[0].split())
        for call in cursor.execute.call_args_list
    )


def test_empty_collection_does_not_access_database():
    loader, repository, _, _ = make_loader()

    result = loader.load_templates(())

    assert result == WorkflowTemplateLoadResult()
    repository.connection.assert_not_called()


def test_duplicate_template_identity_rejected_before_database():
    loader, repository, _, _ = make_loader()
    template = STANDARD_WORKFLOW_TEMPLATES[0]

    with pytest.raises(
        WorkflowTemplateLoadError,
        match="Duplicate workflow template identity",
    ):
        loader.load_templates((template, template))

    repository.connection.assert_not_called()


def test_missing_template_is_inserted_with_steps_and_dependencies():
    loader, repository, connection, cursor = make_loader()
    template = STANDARD_WORKFLOW_TEMPLATES[0]

    # First fetch: no matching name/version.
    # Second fetch: deterministic UUID is also unused.
    cursor.fetchone.side_effect = [None, None]

    result = loader.load_templates((template,))

    assert result == WorkflowTemplateLoadResult(
        templates_inserted=1,
        templates_unchanged=0,
        steps_inserted=len(template.steps),
        dependencies_inserted=len(
            template.dependencies
        ),
    )

    repository.connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    connection.cursor.assert_called_once()

    sql = executed_sql(cursor)

    assert "pg_advisory_xact_lock" in sql
    assert (
        "INSERT INTO merchant_ops.workflow_templates"
        in sql
    )
    assert (
        "INSERT INTO merchant_ops.workflow_template_steps"
        in sql
    )
    assert (
        "merchant_ops.workflow_template_dependencies"
        in sql
    )

    assert sql.count(
        "INSERT INTO merchant_ops.workflow_templates"
    ) == 1
    assert sql.count(
        "INSERT INTO merchant_ops.workflow_template_steps"
    ) == len(template.steps)
    assert sql.count(
        "merchant_ops.workflow_template_dependencies"
    ) == len(template.dependencies)


def test_identical_existing_template_is_a_no_op():
    loader, _, _, cursor = make_loader()
    template = STANDARD_WORKFLOW_TEMPLATES[0]

    (
        template_record,
        step_records,
        dependency_records,
    ) = expected_existing_records(loader, template)

    cursor.fetchone.return_value = template_record
    cursor.fetchall.side_effect = [
        step_records,
        dependency_records,
    ]

    result = loader.load_templates((template,))

    assert result == WorkflowTemplateLoadResult(
        templates_inserted=0,
        templates_unchanged=1,
        steps_inserted=0,
        dependencies_inserted=0,
    )

    sql = executed_sql(cursor)

    assert "INSERT INTO" not in sql
    assert (
        "FROM merchant_ops.workflow_template_steps"
        in sql
    )
    assert (
        "merchant_ops.workflow_template_dependencies"
        in sql
    )


def test_changed_template_metadata_is_rejected():
    loader, _, _, cursor = make_loader()
    template = STANDARD_WORKFLOW_TEMPLATES[0]

    (
        template_record,
        step_records,
        dependency_records,
    ) = expected_existing_records(loader, template)

    changed_template_record = dict(template_record)
    changed_template_record["description"] = (
        "Unexpected stored description"
    )

    cursor.fetchone.return_value = changed_template_record
    cursor.fetchall.side_effect = [
        step_records,
        dependency_records,
    ]

    with pytest.raises(
        WorkflowTemplateConflictError,
        match="template metadata",
    ):
        loader.load_templates((template,))

    assert "INSERT INTO" not in executed_sql(cursor)


def test_changed_template_steps_are_rejected():
    loader, _, _, cursor = make_loader()
    template = STANDARD_WORKFLOW_TEMPLATES[0]

    (
        template_record,
        step_records,
        dependency_records,
    ) = expected_existing_records(loader, template)

    changed_steps = [
        dict(record)
        for record in step_records
    ]
    changed_steps[0]["name"] = "Unexpected stored step"

    cursor.fetchone.return_value = template_record
    cursor.fetchall.side_effect = [
        changed_steps,
        dependency_records,
    ]

    with pytest.raises(
        WorkflowTemplateConflictError,
        match="template steps",
    ):
        loader.load_templates((template,))


def test_changed_dependencies_are_rejected():
    loader, _, _, cursor = make_loader()
    template = STANDARD_WORKFLOW_TEMPLATES[0]

    (
        template_record,
        step_records,
        dependency_records,
    ) = expected_existing_records(loader, template)

    changed_dependencies = [
        dict(record)
        for record in dependency_records
    ]
    changed_dependencies[0]["dependency_type"] = "BLOCKS"

    cursor.fetchone.return_value = template_record
    cursor.fetchall.side_effect = [
        step_records,
        changed_dependencies,
    ]

    with pytest.raises(
        WorkflowTemplateConflictError,
        match="template dependencies",
    ):
        loader.load_templates((template,))


def test_deterministic_uuid_collision_is_rejected():
    loader, _, _, cursor = make_loader()
    template = STANDARD_WORKFLOW_TEMPLATES[0]

    cursor.fetchone.side_effect = [
        None,
        {
            "name": "ANOTHER_TEMPLATE",
            "version": 99,
        },
    ]

    with pytest.raises(
        WorkflowTemplateConflictError,
        match="already belongs to another record",
    ):
        loader.load_templates((template,))

    assert str(template_uuid(template)) in str(
        cursor.execute.call_args_list
    )
    assert "INSERT INTO" not in executed_sql(cursor)


def test_standard_templates_produce_expected_totals():
    loader, _, _, cursor = make_loader()

    # Each template performs two existence lookups:
    # one by name/version and one by deterministic UUID.
    cursor.fetchone.side_effect = [
        value
        for _ in STANDARD_WORKFLOW_TEMPLATES
        for value in (None, None)
    ]

    result = loader.load_standard_templates()

    assert result == WorkflowTemplateLoadResult(
        templates_inserted=4,
        templates_unchanged=0,
        steps_inserted=64,
        dependencies_inserted=68,
    )


def test_result_is_json_compatible():
    result = WorkflowTemplateLoadResult(
        templates_inserted=1,
        templates_unchanged=2,
        steps_inserted=3,
        dependencies_inserted=4,
    )

    assert result.to_dict() == {
        "templates_inserted": 1,
        "templates_unchanged": 2,
        "steps_inserted": 3,
        "dependencies_inserted": 4,
    }