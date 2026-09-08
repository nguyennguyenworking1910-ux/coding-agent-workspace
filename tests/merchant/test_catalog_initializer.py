"""Unit tests for atomic private runtime catalog initialization."""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from claude.agents.tools.merchant.catalog_contract import (
    validate_private_catalog_bytes,
)
from claude.agents.tools.merchant.catalog_plan import CATALOG_NO_OP
from claude.clients.merchant.catalog_initializer import (
    CATALOG_AUDIT_EVENT_TYPE,
    RuntimeCatalogInitializationError,
    RuntimeCatalogInitializer,
    _event_id,
)
from claude.clients.merchant.runtime_catalog_plan import (
    build_runtime_catalog_initialization_plan,
)
from claude.clients.merchant.runtime_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS,
    EXPECTED_PENDING_MIGRATIONS,
)
from claude.clients.merchant.runtime_readiness import (
    BUSINESS_TABLES,
    CATALOG_INITIALIZATION_READY,
    RuntimeBackupEvidence,
    RuntimeReadinessReport,
)
from claude.clients.merchant.runtime_template_plan import (
    EXPECTED_READINESS_TEMPLATE_SHA256,
)


BACKUP_SHA256 = "5" * 64


def _catalog(*, onboarding_count=5):
    records = [
        {
            "code": f"PRIVATE_{number:02d}",
            "name": f"Đối Tác Riêng {number:02d}",
            "account_status": (
                "ONBOARDING"
                if number <= onboarding_count
                else "ACTIVE"
            ),
        }
        for number in range(1, 23)
    ]
    return validate_private_catalog_bytes(
        json.dumps(records, ensure_ascii=False).encode("utf-8")
    )


def _runtime_plan(*, onboarding_count=5):
    catalog = _catalog(onboarding_count=onboarding_count)
    backup = RuntimeBackupEvidence(
        backup_sha256=BACKUP_SHA256,
        size_bytes=1024,
        created_at_utc=datetime(
            2026,
            9,
            8,
            tzinfo=timezone.utc,
        ),
        format="POSTGRESQL_CUSTOM",
        restore_list_verified=True,
        recovery_procedure_reviewed=True,
        roles_recoverable=True,
    )
    readiness = RuntimeReadinessReport(
        success=True,
        state=CATALOG_INITIALIZATION_READY,
        checks={"ready": True},
        database="coding_agent_merchant",
        user="merchant_app",
        encoding="UTF8",
        read_only="on",
        schema_owner="merchant_owner",
        applied_versions=(1, 2, 3),
        pending_versions=(),
        migration_3_sha256="2" * 64,
        business_counts={name: 0 for name in BUSINESS_TABLES},
        merchant_status_counts={},
        stored_template_count=4,
        expected_template_sha256=(
            EXPECTED_READINESS_TEMPLATE_SHA256
        ),
        stored_template_sha256=(
            EXPECTED_READINESS_TEMPLATE_SHA256
        ),
        source_sha256=catalog.source_sha256,
        catalog_sha256=catalog.catalog_sha256,
        backup=backup,
    )
    return build_runtime_catalog_initialization_plan(
        readiness,
        catalog,
        existing_records=(),
        expected_source_sha256=catalog.source_sha256,
        expected_catalog_sha256=catalog.catalog_sha256,
        expected_backup_sha256=BACKUP_SHA256,
    )


def _repository():
    repository = MagicMock()
    repository.config = SimpleNamespace(
        host="127.0.0.1",
        port=5434,
        database="coding_agent_merchant",
        user="merchant_app",
    )
    connection = MagicMock()
    cursor = MagicMock()
    repository.connection.return_value = nullcontext(connection)
    connection.transaction.return_value = nullcontext()
    connection.cursor.return_value = nullcontext(cursor)
    return repository, connection, cursor


def _target_records(plan):
    return [
        {
            "merchant_id": record.merchant_id,
            "code": record.code,
            "name": record.name,
            "region_code": record.region_code,
            "account_status": record.account_status,
            "version": 1,
        }
        for record in plan.catalog_plan.records
    ]


def _event_rows(plan):
    return [
        {
            "id": str(
                _event_id(
                    plan.catalog_plan.catalog_sha256,
                    record.merchant_id,
                )
            ),
            "merchant_id": record.merchant_id,
            "project_id": None,
            "entity_type": "MERCHANT",
            "entity_id": record.merchant_id,
            "change_summary": (
                "Merchant initialized from reviewed private catalog"
            ),
            "old_values": {},
            "new_values": {
                "account_status": record.account_status,
                "catalog_sha256": plan.catalog_plan.catalog_sha256,
                "version": 1,
            },
            "triggered_by": None,
        }
        for record in plan.catalog_plan.records
    ]


def _run_with_mocked_database(existing_records):
    plan = _runtime_plan()
    repository, connection, cursor = _repository()
    initializer = RuntimeCatalogInitializer(repository)
    status_counts = plan.catalog_plan.status_counts

    with (
        patch.object(initializer, "_acquire_lock"),
        patch.object(initializer, "_validate_runtime_identity"),
        patch.object(initializer, "_validate_migrations"),
        patch.object(initializer, "_validate_templates"),
        patch.object(
            initializer,
            "_read_catalog",
            return_value=existing_records,
        ),
        patch.object(
            initializer,
            "_validate_empty_business_state",
        ) as empty_check,
        patch.object(initializer, "_insert_records") as insert,
        patch.object(
            initializer,
            "_verify_committed_shape",
            return_value={
                "merchant_count": 22,
                "status_counts": status_counts,
            },
        ),
    ):
        result = initializer.initialize(plan)

    return (
        plan,
        result,
        repository,
        connection,
        cursor,
        empty_check,
        insert,
    )


def test_empty_target_inserts_once_inside_one_transaction():
    (
        _plan,
        result,
        repository,
        connection,
        _cursor,
        empty_check,
        insert,
    ) = _run_with_mocked_database([])

    assert result.action == "INSERT"
    assert result.merchants_inserted == 22
    assert result.merchants_unchanged == 0
    assert result.audit_events_inserted == 22
    repository.connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    empty_check.assert_called_once()
    insert.assert_called_once()


def test_identical_target_is_verified_no_op():
    plan = _runtime_plan()
    (
        _plan,
        result,
        _repository_value,
        _connection,
        _cursor,
        empty_check,
        insert,
    ) = _run_with_mocked_database(_target_records(plan))

    assert result.action == CATALOG_NO_OP
    assert result.merchants_inserted == 0
    assert result.merchants_unchanged == 22
    assert result.audit_events_inserted == 0
    empty_check.assert_not_called()
    insert.assert_not_called()


def test_wrong_repository_target_fails_before_connection():
    repository, _, _ = _repository()
    repository.config.database = "coding_agent_merchant_test"
    initializer = RuntimeCatalogInitializer(repository)

    with pytest.raises(RuntimeCatalogInitializationError) as error:
        initializer.initialize(_runtime_plan())

    assert error.value.reason_code == "UNSAFE_REPOSITORY_CONFIG"
    repository.connection.assert_not_called()


def test_plain_object_cannot_authorize_initialization():
    repository, _, _ = _repository()
    initializer = RuntimeCatalogInitializer(repository)

    with pytest.raises(RuntimeCatalogInitializationError) as error:
        initializer.initialize({"authorized": True})

    assert error.value.reason_code == "INVALID_RUNTIME_PLAN"
    repository.connection.assert_not_called()


def test_event_identifiers_are_deterministic_and_catalog_bound():
    plan = _runtime_plan()
    first = plan.catalog_plan.records[0]

    event_id = _event_id(
        plan.catalog_plan.catalog_sha256,
        first.merchant_id,
    )

    assert event_id == _event_id(
        plan.catalog_plan.catalog_sha256,
        first.merchant_id,
    )
    assert event_id != _event_id(
        "a" * 64,
        first.merchant_id,
    )


def test_migration_validation_accepts_exact_three_column_history():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "version": item.version,
            "description": item.description,
            "checksum": item.checksum,
        }
        for item in (
            *EXPECTED_APPLIED_MIGRATIONS,
            *EXPECTED_PENDING_MIGRATIONS,
        )
    ]

    RuntimeCatalogInitializer._validate_migrations(cursor)


def test_committed_shape_normalizes_absent_status_to_zero():
    plan = _runtime_plan()
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [
            {
                "account_status": "ACTIVE",
                "count": 17,
            },
            {
                "account_status": "ONBOARDING",
                "count": 5,
            },
        ],
        [
            *_event_rows(plan),
        ],
    ]

    evidence = RuntimeCatalogInitializer._verify_committed_shape(
        cursor,
        plan,
    )

    assert evidence == {
        "merchant_count": 22,
        "status_counts": {
            "ACTIVE": 17,
            "ONBOARDING": 5,
        },
    }


def test_committed_shape_keeps_zero_for_absent_active_status():
    plan = _runtime_plan(onboarding_count=22)
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [
            {
                "account_status": "ONBOARDING",
                "count": 22,
            }
        ],
        _event_rows(plan),
    ]

    evidence = RuntimeCatalogInitializer._verify_committed_shape(
        cursor,
        plan,
    )

    assert evidence == {
        "merchant_count": 22,
        "status_counts": {
            "ACTIVE": 0,
            "ONBOARDING": 22,
        },
    }


def test_insert_sql_is_parameterized_and_audit_is_redacted():
    plan = _runtime_plan()
    cursor = MagicMock()

    RuntimeCatalogInitializer._insert_records(cursor, plan)

    assert cursor.execute.call_count == 44
    merchant_query, merchant_parameters = (
        cursor.execute.call_args_list[0].args
    )
    event_query, event_parameters = (
        cursor.execute.call_args_list[1].args
    )
    first = plan.catalog_plan.records[0]

    assert first.code not in merchant_query
    assert first.name not in merchant_query
    assert first.code in merchant_parameters
    assert first.name in merchant_parameters
    assert first.code not in event_query
    assert first.name not in event_query
    assert first.code not in str(event_parameters)
    assert first.name not in str(event_parameters)
    assert CATALOG_AUDIT_EVENT_TYPE in event_parameters


def test_result_output_contains_no_private_records():
    plan, result, *_rest = _run_with_mocked_database([])
    rendered = json.dumps(result.safe_summary()) + repr(result)

    for record in plan.catalog_plan.records:
        assert record.code not in rendered
        assert record.name not in rendered
        assert record.merchant_id not in rendered
