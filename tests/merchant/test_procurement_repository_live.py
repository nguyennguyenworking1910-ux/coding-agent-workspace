"""Opt-in live lifecycle for Merchant procurement records."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import pytest
from psycopg.rows import dict_row

from claude.agents.tools.merchant.procurement_engine import (
    ProcurementConflictError,
    ProcurementDependencyError,
)
from claude.clients.merchant.procurement_repository import (
    MerchantProcurementRepository,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
    TEST_DATABASE,
)


LIVE_TESTS_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_LIVE_TESTS",
        "",
    ).strip()
    == "1"
)

DOCUMENT_TYPE = "MERCHANT_AGREEMENT"
SIGNED_AT = datetime(
    2026,
    9,
    5,
    9,
    0,
    tzinfo=timezone.utc,
)

SENSITIVE_PROJECT_TITLE = (
    "DO_NOT_AUDIT_PROCUREMENT_PROJECT_TITLE"
)
SENSITIVE_CONTENT_HASH = (
    "DO_NOT_AUDIT_PROCUREMENT_CONTENT_HASH"
)
SENSITIVE_PR_NUMBER = "DO_NOT_AUDIT_PR_12345"
SENSITIVE_PO_NUMBER = "DO_NOT_AUDIT_PO_67890"
SENSITIVE_PAYMENT_NUMBER = "DO_NOT_AUDIT_PAY_24680"
SAFE_AUDIT_KEYS = {
    "procurement_type",
    "status",
    "external_id_recorded",
    "version",
}


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_LIVE_TESTS=1 to run the "
        "Merchant test-database lifecycle"
    ),
)
def test_procurement_live_lifecycle():
    """Prove dependencies, versioning, audit safety, and cleanup."""

    config = RepositoryConfig.from_env("test")
    assert config.database == TEST_DATABASE
    assert config.database.endswith("_test")
    assert config.user == "merchant_test"

    repository = MerchantRepository(config)
    procurement_repository = (
        MerchantProcurementRepository(repository)
    )
    identifiers = _temporary_identifiers()
    cleanup_counts = None

    try:
        identity = _database_identity(repository)
        assert identity == {
            "database": TEST_DATABASE,
            "user": "merchant_test",
            "read_only": "on",
        }

        _insert_temporary_evidence(
            repository,
            identifiers,
        )

        with pytest.raises(ProcurementDependencyError):
            procurement_repository.record_procurement(
                project_id=str(
                    identifiers["project_id"]
                ),
                procurement_type="PURCHASE_ORDER",
                external_id=SENSITIVE_PO_NUMBER,
                status="CREATED",
                document_type=DOCUMENT_TYPE,
                triggered_by=str(
                    identifiers["triggered_by"]
                ),
                procurement_id=str(
                    identifiers["po_id"]
                ),
            )

        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 0

        pr_created = (
            procurement_repository.record_procurement(
                project_id=str(
                    identifiers["project_id"]
                ),
                procurement_type="PURCHASE_REQUEST",
                external_id=SENSITIVE_PR_NUMBER,
                status="CREATED",
                triggered_by=str(
                    identifiers["triggered_by"]
                ),
                procurement_id=str(
                    identifiers["pr_id"]
                ),
            )
        )
        assert pr_created.procurement_id == str(
            identifiers["pr_id"]
        )
        assert pr_created.previous_version is None
        assert pr_created.current_version == 1
        assert pr_created.operation == "INSERT"
        assert pr_created.event_type == (
            "PROCUREMENT_CREATED"
        )

        with pytest.raises(ProcurementConflictError):
            procurement_repository.record_procurement(
                project_id=str(
                    identifiers["project_id"]
                ),
                procurement_type="PURCHASE_REQUEST",
                external_id=SENSITIVE_PR_NUMBER,
                status="APPROVED",
                expected_version=2,
                triggered_by=str(
                    identifiers["triggered_by"]
                ),
            )

        pr_after_stale = _procurement_state(
            repository,
            identifiers["pr_id"],
        )
        assert pr_after_stale["status"] == "CREATED"
        assert pr_after_stale["version"] == 1
        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 1

        pr_updated = (
            procurement_repository.record_procurement(
                project_id=str(
                    identifiers["project_id"]
                ),
                procurement_type="PURCHASE_REQUEST",
                external_id=SENSITIVE_PR_NUMBER,
                status="APPROVED",
                expected_version=1,
                triggered_by=str(
                    identifiers["triggered_by"]
                ),
            )
        )
        assert pr_updated.procurement_id == str(
            identifiers["pr_id"]
        )
        assert pr_updated.previous_version == 1
        assert pr_updated.current_version == 2
        assert pr_updated.operation == "UPDATE"
        assert pr_updated.event_type == (
            "PROCUREMENT_UPDATED"
        )

        with pytest.raises(ProcurementDependencyError):
            procurement_repository.record_procurement(
                project_id=str(
                    identifiers["project_id"]
                ),
                procurement_type="PAYMENT_REQUEST",
                external_id=SENSITIVE_PAYMENT_NUMBER,
                status="CREATED",
                document_type=DOCUMENT_TYPE,
                triggered_by=str(
                    identifiers["triggered_by"]
                ),
                procurement_id=str(
                    identifiers["payment_id"]
                ),
            )

        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 2

        po_created = (
            procurement_repository.record_procurement(
                project_id=str(
                    identifiers["project_id"]
                ),
                procurement_type="PURCHASE_ORDER",
                external_id=SENSITIVE_PO_NUMBER,
                status="CREATED",
                document_type=DOCUMENT_TYPE,
                triggered_by=str(
                    identifiers["triggered_by"]
                ),
                procurement_id=str(
                    identifiers["po_id"]
                ),
            )
        )
        assert po_created.procurement_id == str(
            identifiers["po_id"]
        )
        assert po_created.current_version == 1
        assert po_created.operation == "INSERT"

        payment_created = (
            procurement_repository.record_procurement(
                project_id=str(
                    identifiers["project_id"]
                ),
                procurement_type="PAYMENT_REQUEST",
                external_id=SENSITIVE_PAYMENT_NUMBER,
                status="CREATED",
                document_type=DOCUMENT_TYPE,
                triggered_by=str(
                    identifiers["triggered_by"]
                ),
                procurement_id=str(
                    identifiers["payment_id"]
                ),
            )
        )
        assert payment_created.procurement_id == str(
            identifiers["payment_id"]
        )
        assert payment_created.current_version == 1
        assert payment_created.operation == "INSERT"

        snapshot = repository.get_project_snapshot(
            str(identifiers["project_id"])
        )
        records = snapshot["procurement_records"]
        assert len(records) == 3

        record_by_type = {
            record["procurement_type"]: record
            for record in records
        }
        stored_pr = record_by_type["PURCHASE_REQUEST"]
        stored_po = record_by_type["PURCHASE_ORDER"]
        stored_payment = record_by_type[
            "PAYMENT_REQUEST"
        ]

        assert stored_pr["id"] == identifiers["pr_id"]
        assert stored_pr["external_id"] == (
            SENSITIVE_PR_NUMBER
        )
        assert stored_pr["status"] == "APPROVED"
        assert stored_pr["version"] == 2

        assert stored_po["id"] == identifiers["po_id"]
        assert stored_po["external_id"] == (
            SENSITIVE_PO_NUMBER
        )
        assert stored_po["status"] == "CREATED"
        assert stored_po["version"] == 1

        assert stored_payment["id"] == (
            identifiers["payment_id"]
        )
        assert stored_payment["external_id"] == (
            SENSITIVE_PAYMENT_NUMBER
        )
        assert stored_payment["status"] == "CREATED"
        assert stored_payment["version"] == 1

        events = _procurement_events(
            repository,
            identifiers["project_id"],
        )
        assert len(events) == 4
        assert [
            event["event_type"]
            for event in events
        ] == [
            "PROCUREMENT_CREATED",
            "PROCUREMENT_UPDATED",
            "PROCUREMENT_CREATED",
            "PROCUREMENT_CREATED",
        ]
        assert [
            event["entity_id"]
            for event in events
        ] == [
            identifiers["pr_id"],
            identifiers["pr_id"],
            identifiers["po_id"],
            identifiers["payment_id"],
        ]
        assert [
            event["new_values"]["version"]
            for event in events
        ] == [1, 2, 1, 1]

        sensitive_values = (
            SENSITIVE_PROJECT_TITLE,
            SENSITIVE_CONTENT_HASH,
            SENSITIVE_PR_NUMBER,
            SENSITIVE_PO_NUMBER,
            SENSITIVE_PAYMENT_NUMBER,
            str(identifiers["triggered_by"]),
        )

        for event in events:
            assert event["entity_type"] == "PROCUREMENT"
            assert event["triggered_by"] == (
                identifiers["triggered_by"]
            )
            assert set(event["old_values"]) == (
                SAFE_AUDIT_KEYS
            )
            assert set(event["new_values"]) == (
                SAFE_AUDIT_KEYS
            )

            encoded = json.dumps(
                {
                    "change_summary": (
                        event["change_summary"]
                    ),
                    "old_values": event["old_values"],
                    "new_values": event["new_values"],
                }
            )

            for sensitive_value in sensitive_values:
                assert sensitive_value not in encoded

    finally:
        cleanup_counts = _cleanup_temporary_records(
            repository,
            identifiers,
        )

    assert cleanup_counts == {
        "project_events": 4,
        "procurement_records": 3,
        "document_revisions": 1,
        "projects": 1,
        "workflow_templates": 1,
        "merchants": 1,
    }
    assert _temporary_record_count(
        repository,
        identifiers,
    ) == 0


def _temporary_identifiers():
    return {
        "merchant_id": uuid.uuid4(),
        "template_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "revision_id": uuid.uuid4(),
        "pr_id": uuid.uuid4(),
        "po_id": uuid.uuid4(),
        "payment_id": uuid.uuid4(),
        "triggered_by": uuid.uuid4(),
    }


def _database_identity(repository):
    with repository.connection(
        read_only=True
    ) as connection:
        with connection.transaction():
            with connection.cursor(
                row_factory=dict_row
            ) as cursor:
                cursor.execute(
                    """
                    SELECT
                        current_database() AS database,
                        current_user AS user,
                        current_setting(
                            'transaction_read_only'
                        ) AS read_only
                    """,
                    (),
                )
                return dict(cursor.fetchone())


def _insert_temporary_evidence(
    repository,
    identifiers,
):
    merchant_code = (
        "LIVE_PROCUREMENT_"
        + identifiers["merchant_id"].hex[:12]
    )
    template_name = (
        "LIVE_PROCUREMENT_"
        + identifiers["template_id"].hex[:12]
    )

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.merchants (
                        id,
                        code,
                        name,
                        account_status,
                        version
                    )
                    VALUES (%s, %s, %s, 'ACTIVE', 1)
                    """,
                    (
                        identifiers["merchant_id"],
                        merchant_code,
                        "Temporary procurement merchant",
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO
                        merchant_ops.workflow_templates (
                            id,
                            name,
                            version,
                            description,
                            variant,
                            is_active
                        )
                    VALUES (%s, %s, 1, %s, %s, TRUE)
                    """,
                    (
                        identifiers["template_id"],
                        template_name,
                        "Temporary procurement template",
                        "LIVE_PROCUREMENT",
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.projects (
                        id,
                        merchant_id,
                        project_type,
                        workflow_variant,
                        workflow_template_version_id,
                        title,
                        status,
                        requires_procurement,
                        version
                    )
                    VALUES (
                        %s, %s, 'OPENING_NEW_CINEMA',
                        %s, %s, %s, 'IN_PROGRESS',
                        TRUE, 1
                    )
                    """,
                    (
                        identifiers["project_id"],
                        identifiers["merchant_id"],
                        "LIVE_PROCUREMENT",
                        identifiers["template_id"],
                        SENSITIVE_PROJECT_TITLE,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.document_revisions (
                        id,
                        project_id,
                        document_type,
                        revision_number,
                        content_hash,
                        signed,
                        signed_at,
                        superseded_by,
                        created_by
                    )
                    VALUES (
                        %s, %s, %s, 1, %s,
                        TRUE, %s, NULL, %s
                    )
                    """,
                    (
                        identifiers["revision_id"],
                        identifiers["project_id"],
                        DOCUMENT_TYPE,
                        SENSITIVE_CONTENT_HASH,
                        SIGNED_AT,
                        identifiers["triggered_by"],
                    ),
                )


def _procurement_state(repository, procurement_id):
    with repository.connection(
        read_only=True
    ) as connection:
        with connection.transaction():
            with connection.cursor(
                row_factory=dict_row
            ) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        external_id,
                        status,
                        version
                    FROM merchant_ops.procurement_records
                    WHERE id = %s
                    """,
                    (procurement_id,),
                )
                return dict(cursor.fetchone())


def _event_count(repository, project_id):
    with repository.connection(
        read_only=True
    ) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS event_count
                    FROM merchant_ops.project_events
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                return cursor.fetchone()["event_count"]


def _procurement_events(repository, project_id):
    with repository.connection(
        read_only=True
    ) as connection:
        with connection.transaction():
            with connection.cursor(
                row_factory=dict_row
            ) as cursor:
                cursor.execute(
                    """
                    SELECT
                        event_type,
                        entity_type,
                        entity_id,
                        change_summary,
                        old_values,
                        new_values,
                        triggered_by
                    FROM merchant_ops.project_events
                    WHERE project_id = %s
                      AND entity_type = 'PROCUREMENT'
                    ORDER BY
                        CASE (
                            new_values
                            ->> 'procurement_type'
                        )
                            WHEN 'PURCHASE_REQUEST' THEN 1
                            WHEN 'PURCHASE_ORDER' THEN 2
                            WHEN 'PAYMENT_REQUEST' THEN 3
                            ELSE 4
                        END,
                        (
                            new_values
                            ->> 'version'
                        )::INTEGER,
                        created_at,
                        id
                    """,
                    (project_id,),
                )
                return [
                    dict(record)
                    for record in cursor.fetchall()
                ]


def _cleanup_temporary_records(
    repository,
    identifiers,
):
    deleted = {}

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM merchant_ops.project_events
                    WHERE project_id = %s
                    """,
                    (identifiers["project_id"],),
                )
                deleted["project_events"] = cursor.rowcount

                cursor.execute(
                    """
                    DELETE FROM merchant_ops.procurement_records
                    WHERE project_id = %s
                    """,
                    (identifiers["project_id"],),
                )
                deleted["procurement_records"] = (
                    cursor.rowcount
                )

                cursor.execute(
                    """
                    DELETE FROM merchant_ops.document_revisions
                    WHERE id = %s
                    """,
                    (identifiers["revision_id"],),
                )
                deleted["document_revisions"] = (
                    cursor.rowcount
                )

                cursor.execute(
                    """
                    DELETE FROM merchant_ops.projects
                    WHERE id = %s
                    """,
                    (identifiers["project_id"],),
                )
                deleted["projects"] = cursor.rowcount

                cursor.execute(
                    """
                    DELETE FROM merchant_ops.workflow_templates
                    WHERE id = %s
                    """,
                    (identifiers["template_id"],),
                )
                deleted["workflow_templates"] = (
                    cursor.rowcount
                )

                cursor.execute(
                    """
                    DELETE FROM merchant_ops.merchants
                    WHERE id = %s
                    """,
                    (identifiers["merchant_id"],),
                )
                deleted["merchants"] = cursor.rowcount

    return deleted


def _temporary_record_count(
    repository,
    identifiers,
):
    with repository.connection(
        read_only=True
    ) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        (
                            SELECT COUNT(*)
                            FROM merchant_ops.merchants
                            WHERE id = %s
                        )
                        +
                        (
                            SELECT COUNT(*)
                            FROM merchant_ops.workflow_templates
                            WHERE id = %s
                        )
                        +
                        (
                            SELECT COUNT(*)
                            FROM merchant_ops.projects
                            WHERE id = %s
                        )
                        +
                        (
                            SELECT COUNT(*)
                            FROM merchant_ops.document_revisions
                            WHERE id = %s
                        )
                        +
                        (
                            SELECT COUNT(*)
                            FROM merchant_ops.procurement_records
                            WHERE project_id = %s
                        )
                        +
                        (
                            SELECT COUNT(*)
                            FROM merchant_ops.project_events
                            WHERE project_id = %s
                        ) AS record_count
                    """,
                    (
                        identifiers["merchant_id"],
                        identifiers["template_id"],
                        identifiers["project_id"],
                        identifiers["revision_id"],
                        identifiers["project_id"],
                        identifiers["project_id"],
                    ),
                )
                return cursor.fetchone()["record_count"]
