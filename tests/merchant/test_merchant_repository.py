"""Tests for atomic Merchant and contact persistence."""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest
from psycopg import errors

from claude.agents.tools.merchant.merchant_engine import (
    MerchantEngineError,
    MerchantVersionConflictError,
)
from claude.clients.merchant.merchant_repository import (
    ContactImportResult,
    MerchantAlreadyExistsError,
    MerchantContactConflictError,
    MerchantCreationResult,
    MerchantEntityNotFoundError,
    MerchantEntityRepository,
    MerchantPersistenceError,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
CONTACT_ID = "00000000-0000-0000-0000-000000000002"
SECOND_CONTACT_ID = "00000000-0000-0000-0000-000000000003"
TRIGGERED_BY = "00000000-0000-0000-0000-000000000004"

PRIVATE_NAME = "Private Person"
PRIVATE_EMAIL = "private@example.com"
PRIVATE_PHONE = "0900000000"


class RecordingContext:
    def __init__(self, value):
        self.value = value
        self.entered = False
        self.exception_type = None

    def __enter__(self):
        self.entered = True
        return self.value

    def __exit__(self, exception_type, exception, traceback):
        self.exception_type = exception_type
        return False


def make_repository():
    repository = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()
    connection_context = RecordingContext(connection)
    transaction_context = RecordingContext(None)
    cursor_context = RecordingContext(cursor)
    repository.connection.return_value = connection_context
    connection.transaction.return_value = transaction_context
    connection.cursor.return_value = cursor_context

    return (
        MerchantEntityRepository(repository),
        repository,
        connection,
        cursor,
        transaction_context,
    )


def contact_record(*, contact_id=CONTACT_ID):
    return {
        "contact_id": contact_id,
        "contact_type": "PRIMARY",
        "contact_name": PRIVATE_NAME,
        "contact_email": PRIVATE_EMAIL,
        "contact_phone": PRIVATE_PHONE,
        "privacy_classification": "PII",
        "is_primary": True,
    }


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


def test_create_merchant_is_atomic_and_audited():
    entity_repository, repository, connection, cursor, tx = (
        make_repository()
    )

    result = entity_repository.create_merchant(
        merchant_id=MERCHANT_ID,
        code="beta",
        name="Beta Việt Nam",
        region_code="vn_s",
        created_by=TRIGGERED_BY,
    )

    assert isinstance(result, MerchantCreationResult)
    assert result.merchant_id == MERCHANT_ID
    assert result.code == "BETA"
    assert result.name == "Beta Việt Nam"
    assert result.region_code == "VN_S"
    assert result.account_status == "ONBOARDING"
    assert result.version == 1
    assert result.event_type == "MERCHANT_CREATED"
    repository.connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    assert tx.entered is True
    assert tx.exception_type is None
    sql = executed_sql(cursor)
    assert len(sql) == 2
    assert sql[0].startswith(
        "INSERT INTO merchant_ops.merchants"
    )
    assert sql[1].startswith(
        "INSERT INTO merchant_ops.project_events"
    )


def test_create_merchant_uses_parameterized_values():
    entity_repository, _, _, cursor, _ = make_repository()

    entity_repository.create_merchant(
        merchant_id=MERCHANT_ID,
        code="BETA",
        name="Beta Việt Nam",
        region_code="VN_S",
        created_by=TRIGGERED_BY,
    )

    query, parameters = cursor.execute.call_args_list[0].args
    assert "Beta Việt Nam" not in query
    assert parameters == (
        uuid.UUID(MERCHANT_ID),
        "BETA",
        "Beta Việt Nam",
        "VN_S",
        "ONBOARDING",
        uuid.UUID(TRIGGERED_BY),
        1,
    )


def test_create_merchant_maps_unique_conflict():
    entity_repository, _, _, cursor, tx = make_repository()
    cursor.execute.side_effect = errors.UniqueViolation()

    with pytest.raises(MerchantAlreadyExistsError):
        entity_repository.create_merchant(
            merchant_id=MERCHANT_ID,
            code="BETA",
            name="Beta",
        )

    assert tx.exception_type is errors.UniqueViolation


def test_invalid_create_input_fails_before_connection():
    entity_repository, repository, _, cursor, _ = (
        make_repository()
    )

    with pytest.raises(MerchantEngineError):
        entity_repository.create_merchant(
            merchant_id="not-a-uuid",
            code="BETA",
            name="Beta",
        )

    repository.connection.assert_not_called()
    cursor.execute.assert_not_called()


def test_contact_import_is_atomic_and_versioned():
    entity_repository, repository, connection, cursor, tx = (
        make_repository()
    )
    cursor.fetchone.return_value = {
        "id": uuid.UUID(MERCHANT_ID),
        "code": "BETA",
        "account_status": "ACTIVE",
        "version": 3,
    }
    cursor.rowcount = 1
    contacts = [
        contact_record(),
        contact_record(contact_id=SECOND_CONTACT_ID),
    ]

    result = entity_repository.import_contacts(
        merchant_id=MERCHANT_ID,
        contacts=contacts,
        expected_version=3,
        triggered_by=TRIGGERED_BY,
    )

    assert isinstance(result, ContactImportResult)
    assert result.merchant_id == MERCHANT_ID
    assert result.contacts_imported == 2
    assert result.previous_merchant_version == 3
    assert result.current_merchant_version == 4
    assert result.event_type == "MERCHANT_CONTACTS_IMPORTED"
    repository.connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    assert tx.entered is True
    assert tx.exception_type is None
    sql = executed_sql(cursor)
    assert len(sql) == 5
    assert "FOR UPDATE OF merchant" in sql[0]
    assert sql[1].startswith(
        "INSERT INTO merchant_ops.merchant_contacts"
    )
    assert sql[2].startswith(
        "INSERT INTO merchant_ops.merchant_contacts"
    )
    assert sql[3].startswith(
        "UPDATE merchant_ops.merchants"
    )
    assert sql[4].startswith(
        "INSERT INTO merchant_ops.project_events"
    )


def test_contact_values_are_parameterized_but_not_audited():
    entity_repository, _, _, cursor, _ = make_repository()
    cursor.fetchone.return_value = {
        "id": MERCHANT_ID,
        "version": 1,
    }
    cursor.rowcount = 1

    entity_repository.import_contacts(
        merchant_id=MERCHANT_ID,
        contacts=[contact_record()],
        expected_version=1,
    )

    contact_call = cursor.execute.call_args_list[1]
    contact_query, contact_parameters = contact_call.args
    assert PRIVATE_NAME not in contact_query
    assert PRIVATE_EMAIL not in contact_query
    assert PRIVATE_PHONE not in contact_query
    assert PRIVATE_NAME in contact_parameters
    assert PRIVATE_EMAIL in contact_parameters
    assert PRIVATE_PHONE in contact_parameters

    parameters = event_parameters(cursor)
    audit_payload = {
        "summary": parameters[4],
        "old": parameters[5].obj,
        "new": parameters[6].obj,
    }
    encoded = json.dumps(audit_payload)
    assert PRIVATE_NAME not in encoded
    assert PRIVATE_EMAIL not in encoded
    assert PRIVATE_PHONE not in encoded
    assert audit_payload["new"]["contacts_imported"] == 1


def test_contact_import_requires_existing_merchant():
    entity_repository, _, _, cursor, tx = make_repository()
    cursor.fetchone.return_value = None

    with pytest.raises(
        MerchantEntityNotFoundError,
        match=MERCHANT_ID,
    ):
        entity_repository.import_contacts(
            merchant_id=MERCHANT_ID,
            contacts=[contact_record()],
            expected_version=1,
        )

    assert cursor.execute.call_count == 1
    assert tx.exception_type is MerchantEntityNotFoundError


def test_stale_contact_import_rolls_back_before_inserts():
    entity_repository, _, _, cursor, tx = make_repository()
    cursor.fetchone.return_value = {
        "id": MERCHANT_ID,
        "version": 2,
    }

    with pytest.raises(MerchantVersionConflictError):
        entity_repository.import_contacts(
            merchant_id=MERCHANT_ID,
            contacts=[contact_record()],
            expected_version=1,
        )

    assert cursor.execute.call_count == 1
    assert tx.exception_type is MerchantVersionConflictError


def test_version_guard_failure_rolls_back_without_event():
    entity_repository, _, _, cursor, tx = make_repository()
    cursor.fetchone.return_value = {
        "id": MERCHANT_ID,
        "version": 1,
    }
    cursor.rowcount = 0

    with pytest.raises(
        MerchantVersionConflictError,
        match="committed",
    ):
        entity_repository.import_contacts(
            merchant_id=MERCHANT_ID,
            contacts=[contact_record()],
            expected_version=1,
        )

    sql = executed_sql(cursor)
    assert any(
        statement.startswith(
            "INSERT INTO merchant_ops.merchant_contacts"
        )
        for statement in sql
    )
    assert not any(
        "INSERT INTO merchant_ops.project_events" in statement
        for statement in sql
    )
    assert tx.exception_type is MerchantVersionConflictError


def test_contact_unique_conflict_is_safely_mapped():
    entity_repository, _, _, cursor, tx = make_repository()
    cursor.fetchone.return_value = {
        "id": MERCHANT_ID,
        "version": 1,
    }

    def execute(query, parameters):
        if "merchant_contacts" in query:
            raise errors.UniqueViolation()

    cursor.execute.side_effect = execute

    with pytest.raises(MerchantContactConflictError):
        entity_repository.import_contacts(
            merchant_id=MERCHANT_ID,
            contacts=[contact_record()],
            expected_version=1,
        )

    assert tx.exception_type is errors.UniqueViolation


def test_invalid_import_merchant_uuid_fails_before_connection():
    entity_repository, repository, _, cursor, _ = (
        make_repository()
    )

    with pytest.raises(MerchantPersistenceError):
        entity_repository.import_contacts(
            merchant_id="not-a-uuid",
            contacts=[contact_record()],
            expected_version=1,
        )

    repository.connection.assert_not_called()
    cursor.execute.assert_not_called()


def test_contact_import_result_contains_no_pii():
    entity_repository, _, _, cursor, _ = make_repository()
    cursor.fetchone.return_value = {
        "id": MERCHANT_ID,
        "version": 1,
    }
    cursor.rowcount = 1

    result = entity_repository.import_contacts(
        merchant_id=MERCHANT_ID,
        contacts=[contact_record()],
        expected_version=1,
    )
    encoded = json.dumps(result.to_dict())

    assert PRIVATE_NAME not in encoded
    assert PRIVATE_EMAIL not in encoded
    assert PRIVATE_PHONE not in encoded
