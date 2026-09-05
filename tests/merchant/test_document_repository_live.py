"""Opt-in live lifecycle for Merchant document revisions."""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timezone

import pytest
from psycopg.rows import dict_row

from claude.agents.tools.merchant.document_engine import (
    DocumentRevisionConflictError,
)
from claude.agents.tools.merchant.gates import (
    evaluate_approval_gate,
)
from claude.clients.merchant.document_repository import (
    MerchantDocumentRepository,
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
REVISION_1_EFFECTIVE_DATE = date(2026, 9, 4)
REVISION_1_EXPIRY_DATE = date(2027, 9, 4)
REVISION_2_EFFECTIVE_DATE = date(2026, 10, 4)
REVISION_2_EXPIRY_DATE = date(2027, 10, 4)
APPROVED_AT = datetime(
    2026,
    9,
    4,
    10,
    0,
    tzinfo=timezone.utc,
)

SENSITIVE_PROJECT_TITLE = (
    "DO_NOT_AUDIT_DOCUMENT_PROJECT_TITLE"
)
SENSITIVE_CONTENT_HASH_1 = (
    "DO_NOT_AUDIT_DOCUMENT_CONTENT_HASH_ONE"
)
SENSITIVE_CONTENT_HASH_2 = (
    "DO_NOT_AUDIT_DOCUMENT_CONTENT_HASH_TWO"
)
SAFE_OLD_VALUE_KEYS = {
    "active_revision_number",
    "active_revision_signed",
}
SAFE_NEW_VALUE_KEYS = {
    "document_type",
    "revision_number",
    "signed",
    "superseded_previous",
}


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_LIVE_TESTS=1 to run the "
        "Merchant test-database lifecycle"
    ),
)
def test_document_revision_live_lifecycle():
    """Prove supersession, approval isolation, and audit safety."""

    config = RepositoryConfig.from_env("test")
    assert config.database == TEST_DATABASE
    assert config.database.endswith("_test")
    assert config.user == "merchant_test"

    repository = MerchantRepository(config)
    document_repository = MerchantDocumentRepository(
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

        _insert_temporary_project(
            repository,
            identifiers,
        )

        revision_1 = document_repository.create_revision(
            project_id=str(identifiers["project_id"]),
            document_type=DOCUMENT_TYPE,
            content_hash=SENSITIVE_CONTENT_HASH_1,
            effective_date=(
                REVISION_1_EFFECTIVE_DATE
            ),
            expiry_date=REVISION_1_EXPIRY_DATE,
            created_by=str(identifiers["created_by"]),
            revision_id=str(
                identifiers["revision_1_id"]
            ),
        )
        assert revision_1.revision_number == 1
        assert revision_1.previous_revision_id is None
        assert (
            revision_1.event_type
            == "DOCUMENT_REVISION_CREATED"
        )

        _approve_first_revision(
            repository,
            identifiers,
        )

        revision_2 = document_repository.create_revision(
            project_id=str(identifiers["project_id"]),
            document_type=DOCUMENT_TYPE,
            content_hash=SENSITIVE_CONTENT_HASH_2,
            effective_date=(
                REVISION_2_EFFECTIVE_DATE
            ),
            expiry_date=REVISION_2_EXPIRY_DATE,
            created_by=str(identifiers["created_by"]),
            revision_id=str(
                identifiers["revision_2_id"]
            ),
        )
        assert revision_2.revision_number == 2
        assert revision_2.previous_revision_id == str(
            identifiers["revision_1_id"]
        )
        assert (
            revision_2.event_type
            == "DOCUMENT_REVISION_CREATED"
        )

        snapshot = repository.get_project_snapshot(
            str(identifiers["project_id"])
        )
        revisions = snapshot["document_revisions"]
        approvals = snapshot["document_approvals"]

        assert [
            revision["revision_number"]
            for revision in revisions
        ] == [1, 2]

        stored_revision_1 = revisions[0]
        stored_revision_2 = revisions[1]

        assert stored_revision_1["id"] == (
            identifiers["revision_1_id"]
        )
        assert stored_revision_1["content_hash"] == (
            SENSITIVE_CONTENT_HASH_1
        )
        assert stored_revision_1["signed"] is False
        assert stored_revision_1["superseded_by"] == (
            identifiers["revision_2_id"]
        )

        assert stored_revision_2["id"] == (
            identifiers["revision_2_id"]
        )
        assert stored_revision_2["content_hash"] == (
            SENSITIVE_CONTENT_HASH_2
        )
        assert stored_revision_2["signed"] is False
        assert stored_revision_2["superseded_by"] is None

        assert len(approvals) == 1
        assert approvals[0][
            "document_revision_id"
        ] == identifiers["revision_1_id"]
        assert approvals[0]["approver_role"] == "LEGAL"
        assert (
            approvals[0]["approval_status"]
            == "APPROVED"
        )

        approval_gate = evaluate_approval_gate(
            str(identifiers["project_id"]),
            revisions,
            approvals,
            required_roles=("LEGAL",),
            document_type=DOCUMENT_TYPE,
        )
        assert approval_gate.document_revision_id == str(
            identifiers["revision_2_id"]
        )
        assert approval_gate.all_met is False
        assert approval_gate.approved_roles == ()
        assert approval_gate.missing_roles == ("LEGAL",)
        assert approval_gate.blocking_codes == (
            "MISSING_REQUIRED_APPROVALS",
        )

        with pytest.raises(
            DocumentRevisionConflictError
        ):
            document_repository.create_revision(
                project_id=str(
                    identifiers["project_id"]
                ),
                document_type=DOCUMENT_TYPE,
                content_hash="duplicate-revision-id",
                revision_id=str(
                    identifiers["revision_2_id"]
                ),
            )

        events = _document_events(
            repository,
            identifiers["project_id"],
        )
        assert len(events) == 2
        assert [
            event["event_type"]
            for event in events
        ] == [
            "DOCUMENT_REVISION_CREATED",
            "DOCUMENT_REVISION_CREATED",
        ]
        assert [
            event["entity_id"]
            for event in events
        ] == [
            identifiers["revision_1_id"],
            identifiers["revision_2_id"],
        ]

        assert events[0]["old_values"] == {
            "active_revision_number": None,
            "active_revision_signed": None,
        }
        assert events[0]["new_values"] == {
            "document_type": DOCUMENT_TYPE,
            "revision_number": 1,
            "signed": False,
            "superseded_previous": False,
        }
        assert events[1]["old_values"] == {
            "active_revision_number": 1,
            "active_revision_signed": False,
        }
        assert events[1]["new_values"] == {
            "document_type": DOCUMENT_TYPE,
            "revision_number": 2,
            "signed": False,
            "superseded_previous": True,
        }

        for event in events:
            assert event["entity_type"] == "DOCUMENT"
            assert set(event["old_values"]) == (
                SAFE_OLD_VALUE_KEYS
            )
            assert set(event["new_values"]) == (
                SAFE_NEW_VALUE_KEYS
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
            assert SENSITIVE_PROJECT_TITLE not in encoded
            assert SENSITIVE_CONTENT_HASH_1 not in encoded
            assert SENSITIVE_CONTENT_HASH_2 not in encoded

    finally:
        cleanup_counts = _cleanup_temporary_records(
            repository,
            identifiers,
        )

    assert cleanup_counts == {
        "document_approvals": 1,
        "project_events": 2,
        "document_revisions": 2,
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
        "revision_1_id": uuid.uuid4(),
        "revision_2_id": uuid.uuid4(),
        "approval_id": uuid.uuid4(),
        "created_by": uuid.uuid4(),
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


def _insert_temporary_project(
    repository,
    identifiers,
):
    merchant_code = (
        "LIVE_DOCUMENT_"
        + identifiers["merchant_id"].hex[:12]
    )
    template_name = (
        "LIVE_DOCUMENT_REVISION_"
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
                        "Temporary document merchant",
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
                        "Temporary document template",
                        "LIVE_DOCUMENT_REVISION",
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
                        "LIVE_DOCUMENT_REVISION",
                        identifiers["template_id"],
                        SENSITIVE_PROJECT_TITLE,
                    ),
                )


def _approve_first_revision(
    repository,
    identifiers,
):
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO
                        merchant_ops.document_approvals (
                            id,
                            document_revision_id,
                            approver_role,
                            approval_status,
                            approved_at,
                            approved_by,
                            notes
                        )
                    VALUES (
                        %s, %s, 'LEGAL', 'APPROVED',
                        %s, %s, %s
                    )
                    """,
                    (
                        identifiers["approval_id"],
                        identifiers["revision_1_id"],
                        APPROVED_AT,
                        identifiers["created_by"],
                        "Approval belongs only to revision one",
                    ),
                )


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
                        new_values
                    FROM merchant_ops.project_events
                    WHERE project_id = %s
                      AND entity_type = 'DOCUMENT'
                    ORDER BY
                        (
                            new_values
                            ->> 'revision_number'
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
                    DELETE FROM merchant_ops.document_approvals
                    WHERE document_revision_id IN (%s, %s)
                    """,
                    (
                        identifiers["revision_1_id"],
                        identifiers["revision_2_id"],
                    ),
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
                    WHERE project_id = %s
                    """,
                    (identifiers["project_id"],),
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
                            WHERE project_id = %s
                        )
                        +
                        (
                            SELECT COUNT(*)
                            FROM merchant_ops.document_approvals
                            WHERE document_revision_id IN (
                                %s,
                                %s
                            )
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
                        identifiers["project_id"],
                        identifiers["revision_1_id"],
                        identifiers["revision_2_id"],
                        identifiers["project_id"],
                    ),
                )
                return cursor.fetchone()["record_count"]
