"""Unit tests for the Merchant PostgreSQL repository."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pytest

from claude.clients.merchant.repository import (
    AlertClaimLostError,
    MerchantRepository,
    ProjectScanLimitExceededError,
    ProjectNotFoundError,
    RepositoryConfig,
    RUNTIME_DATABASE,
    TEST_DATABASE,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
STEP_ID = "00000000-0000-0000-0000-000000000002"
ALERT_ID = "00000000-0000-0000-0000-000000000003"
CLAIM_TOKEN = "00000000-0000-0000-0000-000000000004"


def make_config() -> RepositoryConfig:
    return RepositoryConfig(
        host="127.0.0.1",
        port=5434,
        database=RUNTIME_DATABASE,
        user="merchant_alert",
        password="super-secret-password",
    )


def make_repository():
    cursor = MagicMock()
    connection = MagicMock()

    connection.cursor.return_value.__enter__.return_value = cursor
    connection.cursor.return_value.__exit__.return_value = None
    connection.transaction.return_value.__enter__.return_value = None
    connection.transaction.return_value.__exit__.return_value = None

    repository = MerchantRepository(
        config=make_config(),
        connect_fn=MagicMock(),
    )

    @contextmanager
    def fake_connection(*, read_only=False):
        repository.connection_modes.append(read_only)
        yield connection

    repository.connection_modes = []
    repository.connection = fake_connection

    return repository, connection, cursor


def test_config_from_environment_for_alert_role(monkeypatch):
    monkeypatch.setenv("MERCHANT_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("MERCHANT_DB_PORT", "5434")
    monkeypatch.setenv("MERCHANT_DB_NAME", RUNTIME_DATABASE)
    monkeypatch.setenv("MERCHANT_ALERT_USER", "merchant_alert")
    monkeypatch.setenv(
        "MERCHANT_ALERT_PASSWORD",
        "alert-secret",
    )

    config = RepositoryConfig.from_env("alert")

    assert config.host == "127.0.0.1"
    assert config.port == 5434
    assert config.database == RUNTIME_DATABASE
    assert config.user == "merchant_alert"
    assert config.password == "alert-secret"


def test_config_repr_does_not_expose_password():
    config = make_config()

    representation = repr(config)

    assert "super-secret-password" not in representation
    assert "password=" not in representation


def test_missing_password_fails_closed(monkeypatch):
    monkeypatch.setenv("MERCHANT_DB_NAME", RUNTIME_DATABASE)
    monkeypatch.setenv("MERCHANT_DB_USER", "merchant_app")
    monkeypatch.delenv("MERCHANT_DB_PASSWORD", raising=False)

    with pytest.raises(
        ValueError,
        match="MERCHANT_DB_PASSWORD is empty",
    ):
        RepositoryConfig.from_env("app")


def test_test_role_rejects_runtime_database(monkeypatch):
    monkeypatch.setenv(
        "MERCHANT_TEST_DB_NAME",
        RUNTIME_DATABASE,
    )
    monkeypatch.setenv(
        "MERCHANT_TEST_USER",
        "merchant_test",
    )
    monkeypatch.setenv(
        "MERCHANT_TEST_PASSWORD",
        "test-secret",
    )

    with pytest.raises(
        ValueError,
        match=TEST_DATABASE,
    ):
        RepositoryConfig.from_env("test")


def test_invalid_project_uuid_fails_before_database_access():
    repository, connection, cursor = make_repository()

    with pytest.raises(
        ValueError,
        match="project_id must be a valid UUID",
    ):
        repository.get_project_snapshot("not-a-uuid")

    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()


def test_list_open_project_ids():
    repository, connection, cursor = make_repository()

    cursor.fetchall.return_value = [
        {"id": uuid.UUID(PROJECT_ID)},
        {
            "id": uuid.UUID(
                "00000000-0000-0000-0000-000000000010"
            )
        },
    ]

    result = repository.list_open_project_ids()

    assert result == [
        PROJECT_ID,
        "00000000-0000-0000-0000-000000000010",
    ]

    query, parameters = cursor.execute.call_args.args

    assert "COMPLETED" in query
    assert "CANCELLED" in query
    assert "LIMIT %s" in query
    assert parameters == (101,)
    assert repository.connection_modes == [True]


def test_open_project_scan_refuses_silent_truncation():
    repository, connection, cursor = make_repository()
    cursor.fetchall.return_value = [
        {"id": uuid.UUID(PROJECT_ID)},
        {"id": uuid.UUID(STEP_ID)},
        {"id": uuid.UUID(ALERT_ID)},
    ]

    with pytest.raises(
        ProjectScanLimitExceededError,
        match="exceeds configured limit",
    ):
        repository.list_open_project_ids(limit=2)

    assert cursor.execute.call_args.args[1] == (3,)


@pytest.mark.parametrize("limit", [0, 501, True, "100"])
def test_open_project_scan_rejects_invalid_limit_before_database(limit):
    repository, connection, cursor = make_repository()

    with pytest.raises(ValueError, match="limit"):
        repository.list_open_project_ids(limit=limit)

    cursor.execute.assert_not_called()


def test_get_complete_project_snapshot():
    repository, connection, cursor = make_repository()

    project = {
        "id": uuid.UUID(PROJECT_ID),
        "merchant_id": uuid.UUID(
            "00000000-0000-0000-0000-000000000020"
        ),
        "merchant_code": "TEST",
        "merchant_name": "Test Merchant",
        "status": "IN_PROGRESS",
        "requires_procurement": False,
    }
    steps = [
        {
            "id": uuid.UUID(STEP_ID),
            "project_id": uuid.UUID(PROJECT_ID),
            "step_name": "Test Step",
            "status": "READY",
        }
    ]
    dependencies = []
    revisions = []
    approvals = []
    procurement = []

    cursor.fetchone.return_value = project
    cursor.fetchall.side_effect = [
        steps,
        dependencies,
        revisions,
        approvals,
        procurement,
    ]

    snapshot = repository.get_project_snapshot(PROJECT_ID)

    assert snapshot["project"] == project
    assert snapshot["steps"] == steps
    assert snapshot["dependencies"] == dependencies
    assert snapshot["document_revisions"] == revisions
    assert snapshot["document_approvals"] == approvals
    assert snapshot["procurement_records"] == procurement

    assert cursor.execute.call_count == 6

    expected_uuid = uuid.UUID(PROJECT_ID)
    project_query = cursor.execute.call_args_list[0].args[0]
    revision_query = cursor.execute.call_args_list[3].args[0]
    assert "p.reused_document_revision_id" in project_query
    assert "p.payment_period_number" in project_query
    assert "project.reused_document_revision_id" in revision_query

    for execute_call in cursor.execute.call_args_list:
        query, parameters = execute_call.args

        # User input must be passed as a parameter, never placed in SQL.
        assert PROJECT_ID not in query

        if "FROM merchant_ops.document_revisions" in query:
            assert parameters == (expected_uuid, expected_uuid)
        else:
            assert parameters == (expected_uuid,)


def test_project_not_found():
    repository, connection, cursor = make_repository()

    cursor.fetchone.return_value = None

    with pytest.raises(
        ProjectNotFoundError,
        match=PROJECT_ID,
    ):
        repository.get_project_snapshot(PROJECT_ID)


def test_enqueue_alert_uses_parameterized_insert():
    repository, connection, cursor = make_repository()

    cursor.rowcount = 1

    alerts = [
        {
            "project_id": PROJECT_ID,
            "project_step_id": STEP_ID,
            "alert_type": "DUE_TODAY",
            "business_due_date": date(2026, 9, 2),
            "condition_fingerprint": None,
            "deduplication_key": "stable-deduplication-key",
        }
    ]

    inserted = repository.enqueue_alerts(
        alerts,
        delivery_channel="INTERNAL",
    )

    assert inserted == 1

    query, parameters = cursor.execute.call_args.args

    assert "ON CONFLICT" in query
    assert "DO NOTHING" in query
    assert PROJECT_ID not in query
    assert STEP_ID not in query

    assert isinstance(parameters[0], uuid.UUID)
    assert parameters[1] == uuid.UUID(PROJECT_ID)
    assert parameters[2] == uuid.UUID(STEP_ID)
    assert parameters[3] == "DUE_TODAY"
    assert parameters[4] == date(2026, 9, 2)
    assert parameters[6] == "stable-deduplication-key"
    assert parameters[7] == "INTERNAL"


def test_enqueue_empty_alert_collection_does_nothing():
    repository, connection, cursor = make_repository()

    inserted = repository.enqueue_alerts([])

    assert inserted == 0
    cursor.execute.assert_not_called()


def test_claim_uses_skip_locked():
    repository, connection, cursor = make_repository()

    delivery = {
        "id": uuid.UUID(ALERT_ID),
        "project_id": uuid.UUID(PROJECT_ID),
        "project_step_id": uuid.UUID(STEP_ID),
        "alert_type": "OVERDUE",
        "business_due_date": date(2026, 9, 1),
        "condition_fingerprint": None,
        "deduplication_key": "stable-key",
        "delivery_channel": "INTERNAL",
        "delivery_status": "CLAIMED",
        "delivery_attempt_count": 1,
        "claim_token": uuid.UUID(CLAIM_TOKEN),
    }

    cursor.fetchall.return_value = [delivery]

    claimed = repository.claim_pending_alerts(
        delivery_channel="INTERNAL",
        limit=10,
        max_attempts=5,
        lease_seconds=120,
    )

    assert claimed == [delivery]

    query, parameters = cursor.execute.call_args.args

    assert "FOR UPDATE SKIP LOCKED" in query
    assert "delivery_status = 'CLAIMED'" in query
    assert "delivery_status = 'DEAD_LETTER'" in query
    assert "claim_expires_at <= CURRENT_TIMESTAMP" in query
    assert "next_attempt_at <= CURRENT_TIMESTAMP" in query
    assert "delivery_attempt_count" in query
    assert parameters[:6] == (
        "INTERNAL",
        5,
        10,
        "INTERNAL",
        5,
        10,
    )
    assert isinstance(parameters[6], uuid.UUID)
    assert parameters[7] == 120


def test_mark_alert_sent():
    repository, connection, cursor = make_repository()

    cursor.rowcount = 1

    repository.mark_alert_sent(
        ALERT_ID,
        CLAIM_TOKEN,
        provider_message_id=f"internal:{ALERT_ID}",
    )

    query, parameters = cursor.execute.call_args.args

    assert "delivery_status = 'SENT'" in query
    assert "delivered_at = CURRENT_TIMESTAMP" in query
    assert "claim_token = %s" in query
    assert parameters == (
        f"internal:{ALERT_ID}",
        uuid.UUID(ALERT_ID),
        uuid.UUID(CLAIM_TOKEN),
    )


def test_mark_alert_failed_schedules_retry_with_safe_reason_code():
    repository, connection, cursor = make_repository()

    cursor.rowcount = 1

    repository.mark_alert_failed(
        ALERT_ID,
        CLAIM_TOKEN,
        "TRANSPORT_UNAVAILABLE",
        retry_after_seconds=300,
    )

    query, parameters = cursor.execute.call_args.args

    assert "delivery_status = 'FAILED'" in query
    assert "next_attempt_at" in query
    assert "claim_token = %s" in query
    assert parameters == (
        300,
        "TRANSPORT_UNAVAILABLE",
        uuid.UUID(ALERT_ID),
        uuid.UUID(CLAIM_TOKEN),
    )


def test_mark_alert_failed_without_retry_enters_dead_letter():
    repository, connection, cursor = make_repository()

    cursor.rowcount = 1

    repository.mark_alert_failed(
        ALERT_ID,
        CLAIM_TOKEN,
        "PROVIDER_REJECTED",
        retry_after_seconds=None,
    )

    query, parameters = cursor.execute.call_args.args

    assert "delivery_status = 'DEAD_LETTER'" in query
    assert "next_attempt_at = NULL" in query
    assert parameters == (
        "PROVIDER_REJECTED",
        uuid.UUID(ALERT_ID),
        uuid.UUID(CLAIM_TOKEN),
    )


def test_stale_delivery_claim_is_rejected_without_identifiers():
    repository, connection, cursor = make_repository()

    cursor.rowcount = 0

    with pytest.raises(
        AlertClaimLostError,
        match="claim is no longer current",
    ):
        repository.mark_alert_sent(ALERT_ID, CLAIM_TOKEN)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"max_attempts": 0}, "max_attempts"),
        ({"max_attempts": 11}, "max_attempts"),
        ({"lease_seconds": 29}, "lease_seconds"),
        ({"lease_seconds": 901}, "lease_seconds"),
        ({"delivery_channel": "WEBHOOK"}, "delivery_channel"),
    ],
)
def test_claim_rejects_invalid_configuration_before_database_access(
    arguments,
    message,
):
    repository, connection, cursor = make_repository()

    with pytest.raises(ValueError, match=message):
        repository.claim_pending_alerts(**arguments)

    cursor.execute.assert_not_called()


def test_delivery_failure_rejects_unredacted_error_before_database():
    repository, connection, cursor = make_repository()

    with pytest.raises(ValueError, match="safe reason code"):
        repository.mark_alert_failed(
            ALERT_ID,
            CLAIM_TOKEN,
            "SMTP failed for private.user@example.invalid",
            retry_after_seconds=300,
        )

    cursor.execute.assert_not_called()


def test_delivery_failure_rejects_unknown_reason_code_before_database():
    repository, connection, cursor = make_repository()

    with pytest.raises(ValueError, match="safe reason code"):
        repository.mark_alert_failed(
            ALERT_ID,
            CLAIM_TOKEN,
            "PRIVATE_SECRET",
            retry_after_seconds=300,
        )

    cursor.execute.assert_not_called()


def test_alert_queue_status_is_aggregated_and_parameterized():
    repository, connection, cursor = make_repository()
    result = [
        {
            "delivery_channel": "INTERNAL",
            "total_count": 4,
            "ready_count": 1,
            "active_claim_count": 1,
            "expired_claim_count": 0,
            "retryable_failure_count": 1,
            "dead_letter_count": 1,
        }
    ]
    cursor.fetchall.return_value = result

    assert repository.get_alert_queue_status(
        delivery_channel="internal"
    ) == result

    query, parameters = cursor.execute.call_args.args

    assert "COUNT(*) FILTER" in query
    assert "delivery_status = 'CLAIMED'" in query
    assert "delivery_status = 'DEAD_LETTER'" in query
    assert "GROUP BY delivery_channel" in query
    assert "CAST(%s AS VARCHAR) IS NULL" in query
    assert parameters == ("INTERNAL", "INTERNAL")
    assert repository.connection_modes == [True]


def test_alert_worker_health_snapshot_is_read_only_and_non_business():
    repository, connection, cursor = make_repository()
    cursor.fetchone.side_effect = [
        {
            "database": RUNTIME_DATABASE,
            "user": "merchant_alert",
            "read_only": "on",
            "encoding": "UTF8",
        },
        {
            "indexdef": (
                "CREATE INDEX alert_deliveries_claim_idx ON "
                "merchant_ops.alert_deliveries "
                "(delivery_channel, delivery_status, "
                "next_attempt_at, claim_expires_at, created_at, id)"
            )
        },
        {
            "can_select": True,
            "can_insert": True,
            "can_update": True,
        },
    ]
    cursor.fetchall.side_effect = [
        [
            {"column_name": "claim_expires_at"},
            {"column_name": "claim_token"},
            {"column_name": "last_attempt_at"},
            {"column_name": "next_attempt_at"},
            {"column_name": "provider_message_id"},
        ],
        [
            {"constraint_name": "alert_deliveries_claim_state_check"},
            {"constraint_name": "alert_deliveries_dead_letter_state_check"},
            {"constraint_name": "alert_deliveries_next_attempt_state_check"},
            {"constraint_name": "alert_deliveries_provider_message_state_check"},
            {"constraint_name": "alert_deliveries_status_check"},
        ],
    ]

    snapshot = repository.get_alert_worker_health_snapshot()

    assert snapshot["database"] == RUNTIME_DATABASE
    assert snapshot["user"] == "merchant_alert"
    assert snapshot["read_only"] == "on"
    assert snapshot["encoding"] == "UTF8"
    assert set(snapshot["lease_columns"]) == {
        "claim_token",
        "claim_expires_at",
        "next_attempt_at",
        "last_attempt_at",
        "provider_message_id",
    }
    assert snapshot["alert_table_privileges"] == {
        "select": True,
        "insert": True,
        "update": True,
    }
    assert repository.connection_modes == [True]
    assert cursor.execute.call_count == 5

    all_queries = " ".join(
        call.args[0] for call in cursor.execute.call_args_list
    ).lower()
    for business_table in (
        "merchant_ops.merchants",
        "merchant_ops.projects",
        "merchant_ops.merchant_contacts",
        "merchant_ops.project_events",
    ):
        assert business_table not in all_queries
