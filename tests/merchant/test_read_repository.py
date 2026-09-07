"""Unit tests for the Merchant CLI read repository."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from claude.clients.merchant.read_repository import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    MERCHANT_ACCOUNT_STATUSES,
    PROJECT_STATUSES,
    MerchantReadRepository,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    ProjectNotFoundError,
    RepositoryConfig,
    TEST_DATABASE,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
MERCHANT_ID = "00000000-0000-0000-0000-000000000002"
EVENT_ID = "00000000-0000-0000-0000-000000000003"


def make_repository():
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    connection.cursor.return_value.__exit__.return_value = None
    connection.transaction.return_value.__enter__.return_value = None
    connection.transaction.return_value.__exit__.return_value = None

    base = MerchantRepository(
        config=RepositoryConfig(
            host="127.0.0.1",
            port=5434,
            database=TEST_DATABASE,
            user="merchant_test",
            password="test-secret",
        ),
        connect_fn=MagicMock(),
    )
    connection_modes = []

    @contextmanager
    def fake_connection(*, read_only=False):
        connection_modes.append(read_only)
        yield connection

    base.connection = fake_connection

    return (
        MerchantReadRepository(base),
        connection,
        cursor,
        connection_modes,
    )


def test_status_contract_matches_database_schema():
    assert MERCHANT_ACCOUNT_STATUSES == {
        "ONBOARDING",
        "ACTIVE",
        "INACTIVE",
        "SUSPENDED",
    }
    assert PROJECT_STATUSES == {
        "PLANNED",
        "IN_PROGRESS",
        "BLOCKED",
        "ON_HOLD",
        "COMPLETED",
        "CANCELLED",
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (None, None),
        (" active ", "ACTIVE"),
        ("SUSPENDED", "SUSPENDED"),
    ),
)
def test_list_merchants_uses_read_only_parameterized_query(
    status,
    expected,
):
    repository, connection, cursor, modes = make_repository()
    merchant = {
        "id": uuid.UUID(MERCHANT_ID),
        "code": "BETA",
        "name": "Beta Media",
        "account_status": "ACTIVE",
        "contact_count": 1,
    }
    cursor.fetchall.return_value = [merchant]

    result = repository.list_merchants(status=status)

    assert result == [merchant]
    assert modes == [True]
    query, parameters = cursor.execute.call_args.args
    assert "merchant_ops.merchants" in query
    assert "merchant_ops.merchant_contacts" in query
    assert parameters == (expected, expected)
    assert "Beta Media" not in query
    assert connection.transaction.call_count == 1


@pytest.mark.parametrize(
    "status",
    ("", "deleted", 1),
)
def test_invalid_merchant_status_fails_before_database_access(
    status,
):
    repository, connection, cursor, modes = make_repository()

    with pytest.raises(ValueError, match="status must be one of"):
        repository.list_merchants(status=status)

    assert modes == []
    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()


def test_list_projects_normalizes_both_filters():
    repository, connection, cursor, modes = make_repository()
    project = {
        "id": uuid.UUID(PROJECT_ID),
        "merchant_id": uuid.UUID(MERCHANT_ID),
        "merchant_code": "BETA",
        "merchant_name": "Beta Media",
        "status": "IN_PROGRESS",
        "payment_period_number": 2,
    }
    cursor.fetchall.return_value = [project]

    result = repository.list_projects(
        merchant_id=MERCHANT_ID,
        status=" in_progress ",
    )

    assert result == [project]
    assert modes == [True]
    query, parameters = cursor.execute.call_args.args
    merchant_uuid = uuid.UUID(MERCHANT_ID)
    assert "merchant_ops.projects" in query
    assert "merchant_ops.merchants" in query
    assert "payment_period_number" in query
    assert PROJECT_ID not in query
    assert MERCHANT_ID not in query
    assert parameters == (
        merchant_uuid,
        merchant_uuid,
        "IN_PROGRESS",
        "IN_PROGRESS",
    )
    assert connection.transaction.call_count == 1


@pytest.mark.parametrize(
    ("merchant_id", "status", "message"),
    (
        ("not-a-uuid", None, "merchant_id must be a valid UUID"),
        (None, "unknown", "status must be one of"),
        (None, False, "status must be one of"),
    ),
)
def test_invalid_project_filter_fails_before_database_access(
    merchant_id,
    status,
    message,
):
    repository, connection, cursor, modes = make_repository()

    with pytest.raises(ValueError, match=message):
        repository.list_projects(
            merchant_id=merchant_id,
            status=status,
        )

    assert modes == []
    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()


def test_project_detail_returns_complete_internal_state():
    repository, connection, cursor, modes = make_repository()
    project = {
        "id": uuid.UUID(PROJECT_ID),
        "merchant_id": uuid.UUID(MERCHANT_ID),
        "merchant_code": "BETA",
        "merchant_name": "Beta Media",
        "status": "IN_PROGRESS",
        "payment_period_number": 2,
    }
    contacts = [
        {
            "contact_name": "Private Person",
            "contact_email": "private@example.com",
            "contact_phone": "0900000000",
        }
    ]
    steps = [{"step_name": "Contract", "status": "READY"}]
    dependencies = [{"dependency_type": "REQUIRES"}]
    revisions = [{"content_hash": "private-document-hash"}]
    approvals = [{"approval_status": "PENDING"}]
    procurement = [{"status": "CREATED"}]
    identifiers = [
        {
            "identifier_type": "PRODUCT_ID",
            "identifier_value": "private-product-id",
        }
    ]
    cursor.fetchone.return_value = project
    cursor.fetchall.side_effect = [
        contacts,
        steps,
        dependencies,
        revisions,
        approvals,
        procurement,
        identifiers,
    ]

    result = repository.get_project_detail(PROJECT_ID)

    assert result == {
        "project": project,
        "merchant_contacts": contacts,
        "steps": steps,
        "dependencies": dependencies,
        "document_revisions": revisions,
        "document_approvals": approvals,
        "procurement_records": procurement,
        "integration_identifiers": identifiers,
    }
    assert modes == [True]
    assert cursor.execute.call_count == 8
    assert connection.transaction.call_count == 1

    expected_project_id = uuid.UUID(PROJECT_ID)
    expected_merchant_id = uuid.UUID(MERCHANT_ID)
    calls = cursor.execute.call_args_list
    assert calls[0].args[1] == (expected_project_id,)
    assert calls[1].args[1] == (expected_merchant_id,)
    assert "contact.name AS contact_name" in calls[1].args[0]
    assert "contact.email AS contact_email" in calls[1].args[0]
    assert "contact.phone AS contact_phone" in calls[1].args[0]
    assert "project.reused_document_revision_id" in calls[4].args[0]

    for execute_call in calls[2:7]:
        query, parameters = execute_call.args
        assert PROJECT_ID not in query

        if "FROM merchant_ops.document_revisions" in query:
            assert parameters == (
                expected_project_id,
                expected_project_id,
            )
        else:
            assert parameters == (expected_project_id,)

    assert calls[7].args[1] == (
        expected_merchant_id,
        expected_project_id,
    )


def test_project_detail_not_found_stops_related_reads():
    repository, connection, cursor, modes = make_repository()
    cursor.fetchone.return_value = None

    with pytest.raises(ProjectNotFoundError, match=PROJECT_ID):
        repository.get_project_detail(PROJECT_ID)

    assert modes == [True]
    assert cursor.execute.call_count == 1
    assert connection.transaction.call_count == 1


def test_invalid_detail_uuid_fails_before_database_access():
    repository, connection, cursor, modes = make_repository()

    with pytest.raises(
        ValueError,
        match="project_id must be a valid UUID",
    ):
        repository.get_project_detail("not-a-uuid")

    assert modes == []
    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()


def test_project_history_is_chronological_and_limited():
    repository, connection, cursor, modes = make_repository()
    event = {
        "id": uuid.UUID(EVENT_ID),
        "project_id": uuid.UUID(PROJECT_ID),
        "event_type": "PROJECT_STATUS_CHANGED",
    }
    cursor.fetchone.return_value = {"exists": 1}
    cursor.fetchall.return_value = [event]

    result = repository.get_project_history(
        PROJECT_ID,
        limit=25,
    )

    assert result == [event]
    assert modes == [True]
    assert cursor.execute.call_count == 2
    exists_call, history_call = cursor.execute.call_args_list
    project_uuid = uuid.UUID(PROJECT_ID)
    assert exists_call.args[1] == (project_uuid,)
    history_query, history_parameters = history_call.args
    assert "merchant_ops.project_events" in history_query
    assert "ORDER BY event.created_at, event.id" in history_query
    assert "LIMIT %s" in history_query
    assert history_parameters == (project_uuid, 25)
    assert connection.transaction.call_count == 1


def test_project_history_uses_default_limit():
    repository, connection, cursor, modes = make_repository()
    cursor.fetchone.return_value = {"exists": 1}
    cursor.fetchall.return_value = []

    assert repository.get_project_history(PROJECT_ID) == []

    _, parameters = cursor.execute.call_args.args
    assert parameters == (
        uuid.UUID(PROJECT_ID),
        DEFAULT_HISTORY_LIMIT,
    )
    assert modes == [True]


def test_project_history_requires_existing_project():
    repository, connection, cursor, modes = make_repository()
    cursor.fetchone.return_value = None

    with pytest.raises(ProjectNotFoundError, match=PROJECT_ID):
        repository.get_project_history(PROJECT_ID)

    assert modes == [True]
    assert cursor.execute.call_count == 1
    assert connection.transaction.call_count == 1


@pytest.mark.parametrize(
    ("limit", "message"),
    (
        (0, "limit must be between"),
        (MAX_HISTORY_LIMIT + 1, "limit must be between"),
        (True, "limit must be an integer"),
        ("50", "limit must be an integer"),
    ),
)
def test_invalid_history_limit_fails_before_database_access(
    limit,
    message,
):
    repository, connection, cursor, modes = make_repository()

    with pytest.raises(ValueError, match=message):
        repository.get_project_history(
            PROJECT_ID,
            limit=limit,
        )

    assert modes == []
    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()
