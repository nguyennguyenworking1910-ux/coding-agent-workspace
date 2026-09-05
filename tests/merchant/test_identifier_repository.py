"""Tests for atomic integration identifier persistence."""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest
from psycopg import errors

from claude.agents.tools.merchant.identifier_engine import (
    IdentifierConflictError,
    IdentifierVersionConflictError,
)
from claude.clients.merchant.identifier_repository import (
    IdentifierBindingConflictError,
    IdentifierMerchantNotFoundError,
    IdentifierMutationResult,
    IdentifierPersistenceError,
    IdentifierProjectNotFoundError,
    MerchantIdentifierRepository,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
IDENTIFIER_ID = "00000000-0000-0000-0000-000000000003"
TRIGGERED_BY = "00000000-0000-0000-0000-000000000004"
PRIVATE_VALUE = "private-product-id"


class RecordingContext:
    def __init__(self, value):
        self.value = value
        self.exception_type = None

    def __enter__(self):
        return self.value

    def __exit__(self, exception_type, exception, traceback):
        self.exception_type = exception_type
        return False


def make_repository():
    repository = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()
    transaction_context = RecordingContext(None)
    repository.connection.return_value = RecordingContext(connection)
    connection.transaction.return_value = transaction_context
    connection.cursor.return_value = RecordingContext(cursor)

    return (
        MerchantIdentifierRepository(repository),
        repository,
        connection,
        cursor,
        transaction_context,
    )


def identifier_record(**overrides):
    record = {
        "id": uuid.UUID(IDENTIFIER_ID),
        "merchant_id": uuid.UUID(MERCHANT_ID),
        "project_id": uuid.UUID(PROJECT_ID),
        "identifier_type": "PRODUCT_ID",
        "identifier_value": PRIVATE_VALUE,
        "scope": "UAT",
        "is_active": True,
        "version": 3,
    }
    record.update(overrides)
    return record


def executed_sql(cursor):
    return [
        " ".join(call.args[0].split())
        for call in cursor.execute.call_args_list
    ]


def event_parameters(cursor):
    event_call = next(
        call
        for call in cursor.execute.call_args_list
        if "INSERT INTO merchant_ops.project_events"
        in call.args[0]
    )
    return event_call.args[1]


def prepare_project_binding(cursor, *, current=()):
    cursor.fetchone.side_effect = [
        {"id": MERCHANT_ID},
        {"id": PROJECT_ID},
    ]
    cursor.fetchall.return_value = list(current)
    cursor.rowcount = 1


def test_project_identifier_insert_is_atomic():
    identifier_repository, repository, connection, cursor, tx = (
        make_repository()
    )
    prepare_project_binding(cursor)

    result = identifier_repository.set_identifier(
        merchant_id=MERCHANT_ID,
        project_id=PROJECT_ID,
        identifier_type="product_id",
        identifier_value=PRIVATE_VALUE,
        scope="uat",
        identifier_id=IDENTIFIER_ID,
        triggered_by=TRIGGERED_BY,
    )

    assert isinstance(result, IdentifierMutationResult)
    assert result.identifier_id == IDENTIFIER_ID
    assert result.identifier_type == "PRODUCT_ID"
    assert result.scope == "UAT"
    assert result.previous_version is None
    assert result.current_version == 1
    assert result.operation == "INSERT"
    assert result.event_type == "INTEGRATION_IDENTIFIER_SET"
    repository.connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    assert tx.exception_type is None
    sql = executed_sql(cursor)
    assert len(sql) == 5
    assert "FOR SHARE OF merchant" in sql[0]
    assert "FOR SHARE OF project" in sql[1]
    assert "FOR UPDATE OF identifier" in sql[2]
    assert sql[3].startswith(
        "INSERT INTO merchant_ops.integration_identifiers"
    )
    assert sql[4].startswith(
        "INSERT INTO merchant_ops.project_events"
    )


def test_new_identifier_generates_id_when_omitted():
    identifier_repository, _, _, cursor, _ = make_repository()
    prepare_project_binding(cursor)

    result = identifier_repository.set_identifier(
        merchant_id=MERCHANT_ID,
        project_id=PROJECT_ID,
        identifier_type="PRODUCT_ID",
        identifier_value=PRIVATE_VALUE,
        scope="UAT",
    )

    assert uuid.UUID(result.identifier_id)
    insert_parameters = cursor.execute.call_args_list[3].args[1]
    assert insert_parameters[0] == uuid.UUID(
        result.identifier_id
    )


def test_insert_values_are_parameterized():
    identifier_repository, _, _, cursor, _ = make_repository()
    prepare_project_binding(cursor)

    identifier_repository.set_identifier(
        merchant_id=MERCHANT_ID,
        project_id=PROJECT_ID,
        identifier_type="PRODUCT_ID",
        identifier_value=PRIVATE_VALUE,
        scope="UAT",
        identifier_id=IDENTIFIER_ID,
    )

    insert_call = cursor.execute.call_args_list[3]
    query, parameters = insert_call.args
    assert PRIVATE_VALUE not in query
    assert parameters == (
        uuid.UUID(IDENTIFIER_ID),
        uuid.UUID(PROJECT_ID),
        uuid.UUID(MERCHANT_ID),
        "PRODUCT_ID",
        PRIVATE_VALUE,
        "UAT",
        True,
        1,
    )


def test_existing_identifier_uses_optimistic_update():
    identifier_repository, _, _, cursor, tx = make_repository()
    prepare_project_binding(
        cursor,
        current=[identifier_record()],
    )

    result = identifier_repository.set_identifier(
        merchant_id=MERCHANT_ID,
        project_id=PROJECT_ID,
        identifier_type="PRODUCT_ID",
        identifier_value="updated-private-id",
        scope="UAT",
        expected_version=3,
        triggered_by=TRIGGERED_BY,
    )

    assert result.identifier_id == IDENTIFIER_ID
    assert result.previous_version == 3
    assert result.current_version == 4
    assert result.operation == "UPDATE"
    assert tx.exception_type is None
    update_call = cursor.execute.call_args_list[3]
    query, parameters = update_call.args
    assert query.lstrip().startswith(
        "UPDATE merchant_ops.integration_identifiers"
    )
    assert "version = %s" in query
    assert parameters[-1] == 3


def test_merchant_scoped_identifier_uses_null_project():
    identifier_repository, _, _, cursor, _ = make_repository()
    cursor.fetchone.return_value = {"id": MERCHANT_ID}
    cursor.fetchall.return_value = []
    cursor.rowcount = 1

    result = identifier_repository.set_identifier(
        merchant_id=MERCHANT_ID,
        project_id=None,
        identifier_type="MASTER_MID",
        identifier_value=PRIVATE_VALUE,
        scope="MASTER",
        identifier_id=IDENTIFIER_ID,
    )

    assert result.project_id is None
    sql = executed_sql(cursor)
    assert len(sql) == 4
    assert not any(
        "FROM merchant_ops.projects" in statement
        for statement in sql
    )
    assert "IS NOT DISTINCT FROM %s" in sql[1]


def test_identifier_value_is_never_audited_or_returned():
    identifier_repository, _, _, cursor, _ = make_repository()
    prepare_project_binding(cursor)

    result = identifier_repository.set_identifier(
        merchant_id=MERCHANT_ID,
        project_id=PROJECT_ID,
        identifier_type="PRODUCT_ID",
        identifier_value=PRIVATE_VALUE,
        scope="UAT",
        identifier_id=IDENTIFIER_ID,
    )

    parameters = event_parameters(cursor)
    audit = {
        "summary": parameters[6],
        "old": parameters[7].obj,
        "new": parameters[8].obj,
    }
    assert PRIVATE_VALUE not in json.dumps(audit)
    assert PRIVATE_VALUE not in json.dumps(result.to_dict())
    assert "identifier_value" not in result.to_dict()


def test_missing_merchant_stops_before_project_read():
    identifier_repository, _, _, cursor, tx = make_repository()
    cursor.fetchone.return_value = None

    with pytest.raises(IdentifierMerchantNotFoundError):
        identifier_repository.set_identifier(
            merchant_id=MERCHANT_ID,
            project_id=PROJECT_ID,
            identifier_type="PRODUCT_ID",
            identifier_value=PRIVATE_VALUE,
            scope="UAT",
            identifier_id=IDENTIFIER_ID,
        )

    assert cursor.execute.call_count == 1
    assert tx.exception_type is IdentifierMerchantNotFoundError


def test_project_must_belong_to_merchant():
    identifier_repository, _, _, cursor, tx = make_repository()
    cursor.fetchone.side_effect = [
        {"id": MERCHANT_ID},
        None,
    ]

    with pytest.raises(IdentifierProjectNotFoundError):
        identifier_repository.set_identifier(
            merchant_id=MERCHANT_ID,
            project_id=PROJECT_ID,
            identifier_type="PRODUCT_ID",
            identifier_value=PRIVATE_VALUE,
            scope="UAT",
            identifier_id=IDENTIFIER_ID,
        )

    assert cursor.execute.call_count == 2
    assert tx.exception_type is IdentifierProjectNotFoundError


def test_duplicate_stored_binding_fails_closed():
    identifier_repository, _, _, cursor, tx = make_repository()
    prepare_project_binding(
        cursor,
        current=[
            identifier_record(),
            identifier_record(
                id=uuid.uuid4(),
                identifier_value="another-private-id",
            ),
        ],
    )

    with pytest.raises(
        IdentifierBindingConflictError,
        match="Multiple",
    ):
        identifier_repository.set_identifier(
            merchant_id=MERCHANT_ID,
            project_id=PROJECT_ID,
            identifier_type="PRODUCT_ID",
            identifier_value="updated-id",
            scope="UAT",
            expected_version=3,
        )

    assert cursor.execute.call_count == 3
    assert tx.exception_type is IdentifierBindingConflictError


def test_existing_identifier_requires_expected_version():
    identifier_repository, _, _, cursor, tx = make_repository()
    prepare_project_binding(
        cursor,
        current=[identifier_record()],
    )

    with pytest.raises(IdentifierConflictError):
        identifier_repository.set_identifier(
            merchant_id=MERCHANT_ID,
            project_id=PROJECT_ID,
            identifier_type="PRODUCT_ID",
            identifier_value="updated-id",
            scope="UAT",
        )

    assert cursor.execute.call_count == 3
    assert tx.exception_type is IdentifierConflictError


def test_update_version_guard_failure_has_no_event():
    identifier_repository, _, _, cursor, tx = make_repository()
    prepare_project_binding(
        cursor,
        current=[identifier_record()],
    )
    cursor.rowcount = 0

    with pytest.raises(IdentifierVersionConflictError):
        identifier_repository.set_identifier(
            merchant_id=MERCHANT_ID,
            project_id=PROJECT_ID,
            identifier_type="PRODUCT_ID",
            identifier_value="updated-id",
            scope="UAT",
            expected_version=3,
        )

    assert cursor.execute.call_count == 4
    assert not any(
        "INSERT INTO merchant_ops.project_events" in statement
        for statement in executed_sql(cursor)
    )
    assert tx.exception_type is IdentifierVersionConflictError


def test_unique_violation_is_safely_mapped():
    identifier_repository, _, _, cursor, tx = make_repository()
    prepare_project_binding(cursor)

    def execute(query, parameters):
        if "INSERT INTO merchant_ops.integration_identifiers" in query:
            raise errors.UniqueViolation()

    cursor.execute.side_effect = execute

    with pytest.raises(IdentifierBindingConflictError):
        identifier_repository.set_identifier(
            merchant_id=MERCHANT_ID,
            project_id=PROJECT_ID,
            identifier_type="PRODUCT_ID",
            identifier_value=PRIVATE_VALUE,
            scope="UAT",
            identifier_id=IDENTIFIER_ID,
        )

    assert tx.exception_type is errors.UniqueViolation


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("merchant_id", "not-a-uuid"),
        ("project_id", "not-a-uuid"),
    ),
)
def test_invalid_binding_uuid_fails_before_connection(field, value):
    identifier_repository, repository, _, cursor, _ = (
        make_repository()
    )
    arguments = {
        "merchant_id": MERCHANT_ID,
        "project_id": PROJECT_ID,
        "identifier_type": "PRODUCT_ID",
        "identifier_value": PRIVATE_VALUE,
        "scope": "UAT",
        "identifier_id": IDENTIFIER_ID,
        field: value,
    }

    with pytest.raises(IdentifierPersistenceError, match=field):
        identifier_repository.set_identifier(**arguments)

    repository.connection.assert_not_called()
    cursor.execute.assert_not_called()
