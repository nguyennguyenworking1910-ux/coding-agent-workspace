"""Opt-in live lifecycle for Merchant document approvals."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import pytest
from psycopg.rows import dict_row

from claude.agents.tools.merchant.approval_engine import (
    ApprovalConflictError,
    ApprovalFinalizedError,
)
from claude.agents.tools.merchant.gates import (
    evaluate_approval_gate,
)
from claude.clients.merchant.approval_repository import (
    MerchantApprovalRepository,
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
APPROVED_AT = datetime(
    2026,
    9,
    4,
    13,
    0,
    tzinfo=timezone.utc,
)

SENSITIVE_PROJECT_TITLE = (
    "DO_NOT_AUDIT_APPROVAL_PROJECT_TITLE"
)
SENSITIVE_CONTENT_HASH = (
    "DO_NOT_AUDIT_APPROVAL_CONTENT_HASH"
)
SENSITIVE_LEGAL_NOTES = (
    "DO_NOT_AUDIT_PRIVATE_LEGAL_NOTES"
)
SENSITIVE_ACCOUNTING_NOTES = (
    "DO_NOT_AUDIT_PRIVATE_ACCOUNTING_NOTES"
)
SAFE_AUDIT_KEYS = {
    "document_type",
    "revision_number",
    "approver_role",
    "approval_status",
}


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_LIVE_TESTS=1 to run the "
        "Merchant test-database lifecycle"
    ),
)
def test_document_approval_live_lifecycle():
    """Prove guarded decisions, gate evidence, and audit safety."""

    config = RepositoryConfig.from_env("test")
    assert config.database == TEST_DATABASE
    assert config.database.endswith("_test")
    assert config.user == "merchant_test"

    repository = MerchantRepository(config)
    approval_repository = MerchantApprovalRepository(
        repository
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

        pending = approval_repository.record_approval(
            document_revision_id=str(
                identifiers["revision_id"]
            ),
            approver_role="LEGAL",
            approval_status="PENDING",
            acted_by=str(identifiers["acted_by"]),
            notes=SENSITIVE_LEGAL_NOTES,
            approval_id=str(
                identifiers["legal_approval_id"]
            ),
        )
        assert pending.previous_status is None
        assert pending.current_status == "PENDING"
        assert pending.operation == "INSERT"
        assert (
            pending.event_type
            == "DOCUMENT_APPROVAL_REQUESTED"
        )

        with pytest.raises(ApprovalConflictError):
            approval_repository.record_approval(
                document_revision_id=str(
                    identifiers["revision_id"]
                ),
                approver_role="LEGAL",
                approval_status="APPROVED",
                expected_status="REJECTED",
                occurred_at=APPROVED_AT,
                acted_by=str(identifiers["acted_by"]),
            )

        state_after_stale = _approval_state(
            repository,
            identifiers["revision_id"],
            "LEGAL",
        )
        assert state_after_stale["approval_status"] == (
            "PENDING"
        )
        assert state_after_stale["approved_at"] is None
        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 1

        approved = approval_repository.record_approval(
            document_revision_id=str(
                identifiers["revision_id"]
            ),
            approver_role="LEGAL",
            approval_status="APPROVED",
            expected_status="PENDING",
            occurred_at=APPROVED_AT,
            acted_by=str(identifiers["acted_by"]),
            notes=SENSITIVE_LEGAL_NOTES,
        )
        assert approved.approval_id == str(
            identifiers["legal_approval_id"]
        )
        assert approved.previous_status == "PENDING"
        assert approved.current_status == "APPROVED"
        assert approved.operation == "UPDATE"
        assert approved.event_type == "DOCUMENT_APPROVED"

        with pytest.raises(ApprovalFinalizedError):
            approval_repository.record_approval(
                document_revision_id=str(
                    identifiers["revision_id"]
                ),
                approver_role="LEGAL",
                approval_status="REJECTED",
                expected_status="APPROVED",
                acted_by=str(identifiers["acted_by"]),
            )

        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 2

        rejected = approval_repository.record_approval(
            document_revision_id=str(
                identifiers["revision_id"]
            ),
            approver_role="ACCOUNTING",
            approval_status="REJECTED",
            acted_by=str(identifiers["acted_by"]),
            notes=SENSITIVE_ACCOUNTING_NOTES,
            approval_id=str(
                identifiers["accounting_approval_id"]
            ),
        )
        assert rejected.previous_status is None
        assert rejected.current_status == "REJECTED"
        assert rejected.operation == "INSERT"
        assert rejected.event_type == "DOCUMENT_REJECTED"

        snapshot = repository.get_project_snapshot(
            str(identifiers["project_id"])
        )
        revisions = snapshot["document_revisions"]
        approvals = snapshot["document_approvals"]

        assert len(revisions) == 1
        assert len(approvals) == 2
        approval_by_role = {
            approval["approver_role"]: approval
            for approval in approvals
        }

        stored_legal = approval_by_role["LEGAL"]
        assert stored_legal["id"] == (
            identifiers["legal_approval_id"]
        )
        assert stored_legal["approval_status"] == (
            "APPROVED"
        )
        assert stored_legal["approved_at"] == APPROVED_AT
        assert stored_legal["notes"] == (
            SENSITIVE_LEGAL_NOTES
        )

        stored_accounting = approval_by_role["ACCOUNTING"]
        assert stored_accounting["id"] == (
            identifiers["accounting_approval_id"]
        )
        assert stored_accounting["approval_status"] == (
            "REJECTED"
        )
        assert stored_accounting["approved_at"] is None
        assert stored_accounting["notes"] == (
            SENSITIVE_ACCOUNTING_NOTES
        )

        gate = evaluate_approval_gate(
            str(identifiers["project_id"]),
            revisions,
            approvals,
            required_roles=("LEGAL", "ACCOUNTING"),
            document_type=DOCUMENT_TYPE,
        )
        assert gate.document_revision_id == str(
            identifiers["revision_id"]
        )
        assert gate.all_met is False
        assert gate.approved_roles == ("LEGAL",)
        assert gate.missing_roles == ("ACCOUNTING",)
        assert gate.blocking_codes == (
            "MISSING_REQUIRED_APPROVALS",
        )

        events = _document_events(
            repository,
            identifiers["project_id"],
        )
        assert len(events) == 3
        assert [
            event["event_type"]
            for event in events
        ] == [
            "DOCUMENT_APPROVAL_REQUESTED",
            "DOCUMENT_APPROVED",
            "DOCUMENT_REJECTED",
        ]
        assert [
            event["old_values"]["approval_status"]
            for event in events
        ] == [None, "PENDING", None]
        assert [
            event["new_values"]["approval_status"]
            for event in events
        ] == ["PENDING", "APPROVED", "REJECTED"]

        sensitive_values = (
            SENSITIVE_PROJECT_TITLE,
            SENSITIVE_CONTENT_HASH,
            SENSITIVE_LEGAL_NOTES,
            SENSITIVE_ACCOUNTING_NOTES,
            str(identifiers["acted_by"]),
            str(identifiers["legal_approval_id"]),
            str(identifiers["accounting_approval_id"]),
        )

        for event in events:
            assert event["entity_type"] == "DOCUMENT"
            assert event["entity_id"] == (
                identifiers["revision_id"]
            )
            assert event["triggered_by"] == (
                identifiers["acted_by"]
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
        "document_approvals": 2,
        "project_events": 3,
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
        "legal_approval_id": uuid.uuid4(),
        "accounting_approval_id": uuid.uuid4(),
        "acted_by": uuid.uuid4(),
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
        "LIVE_APPROVAL_"
        + identifiers["merchant_id"].hex[:12]
    )
    template_name = (
        "LIVE_APPROVAL_"
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
                        "Temporary approval merchant",
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
                        "Temporary approval template",
                        "LIVE_DOCUMENT_APPROVAL",
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
                        FALSE, 1
                    )
                    """,
                    (
                        identifiers["project_id"],
                        identifiers["merchant_id"],
                        "LIVE_DOCUMENT_APPROVAL",
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
                        FALSE, NULL, NULL, %s
                    )
                    """,
                    (
                        identifiers["revision_id"],
                        identifiers["project_id"],
                        DOCUMENT_TYPE,
                        SENSITIVE_CONTENT_HASH,
                        identifiers["acted_by"],
                    ),
                )


def _approval_state(
    repository,
    revision_id,
    approver_role,
):
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
                        approval_status,
                        approved_at,
                        approved_by,
                        notes
                    FROM merchant_ops.document_approvals
                    WHERE document_revision_id = %s
                      AND approver_role = %s
                    """,
                    (revision_id, approver_role),
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


def _document_events(repository, project_id):
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
                      AND entity_type = 'DOCUMENT'
                    ORDER BY
                        CASE event_type
                            WHEN 'DOCUMENT_APPROVAL_REQUESTED'
                                THEN 1
                            WHEN 'DOCUMENT_APPROVED'
                                THEN 2
                            WHEN 'DOCUMENT_REJECTED'
                                THEN 3
                            ELSE 4
                        END,
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
                    DELETE FROM merchant_ops.document_approvals
                    WHERE document_revision_id = %s
                    """,
                    (identifiers["revision_id"],),
                )
                deleted["document_approvals"] = (
                    cursor.rowcount
                )

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
                            FROM merchant_ops.document_approvals
                            WHERE document_revision_id = %s
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
                        identifiers["revision_id"],
                        identifiers["project_id"],
                    ),
                )
                return cursor.fetchone()["record_count"]
