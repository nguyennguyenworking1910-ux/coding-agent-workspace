"""Opt-in live lifecycle for Merchant document signing."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import pytest
from psycopg.rows import dict_row

from claude.agents.tools.merchant.gates import (
    evaluate_signing_gate,
)
from claude.agents.tools.merchant.signing_engine import (
    DocumentAlreadySignedError,
    DocumentSigningGateError,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
    TEST_DATABASE,
)
from claude.clients.merchant.signing_repository import (
    MerchantSigningRepository,
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
    5,
    10,
    0,
    tzinfo=timezone.utc,
)
SIGNED_AT = datetime(
    2026,
    9,
    5,
    12,
    0,
    tzinfo=timezone.utc,
)

SENSITIVE_PROJECT_TITLE = (
    "DO_NOT_AUDIT_SIGNING_PROJECT_TITLE"
)
SENSITIVE_CONTENT_HASH = (
    "DO_NOT_AUDIT_SIGNING_CONTENT_HASH"
)
SENSITIVE_APPROVAL_NOTES = (
    "DO_NOT_AUDIT_SIGNING_APPROVAL_NOTES"
)
SENSITIVE_PR_NUMBER = "DO_NOT_AUDIT_SIGNING_PR_12345"
SAFE_AUDIT_KEYS = {
    "document_type",
    "revision_number",
    "signed",
    "signed_at_recorded",
}


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_LIVE_TESTS=1 to run the "
        "Merchant test-database lifecycle"
    ),
)
def test_document_signing_live_lifecycle():
    """Prove signing gates, one-way state, audit, and cleanup."""

    config = RepositoryConfig.from_env("test")
    assert config.database == TEST_DATABASE
    assert config.database.endswith("_test")
    assert config.user == "merchant_test"

    repository = MerchantRepository(config)
    signing_repository = MerchantSigningRepository(
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

        with pytest.raises(
            DocumentSigningGateError
        ) as missing_all:
            signing_repository.sign_document(
                document_revision_id=str(
                    identifiers["revision_id"]
                ),
                occurred_at=SIGNED_AT,
                signed_by=str(
                    identifiers["signed_by"]
                ),
            )

        assert missing_all.value.gate_result.blocking_codes == (
            "MISSING_REQUIRED_APPROVALS",
            "MISSING_PURCHASE_REQUEST",
        )
        assert _document_state(
            repository,
            identifiers["revision_id"],
        ) == {
            "signed": False,
            "signed_at": None,
        }
        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 0

        _insert_approvals(repository, identifiers)

        with pytest.raises(
            DocumentSigningGateError
        ) as missing_procurement:
            signing_repository.sign_document(
                document_revision_id=str(
                    identifiers["revision_id"]
                ),
                occurred_at=SIGNED_AT,
                signed_by=str(
                    identifiers["signed_by"]
                ),
            )

        assert (
            missing_procurement.value.gate_result.blocking_codes
            == ("MISSING_PURCHASE_REQUEST",)
        )
        assert _document_state(
            repository,
            identifiers["revision_id"],
        )["signed"] is False
        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 0

        _insert_purchase_request(repository, identifiers)

        result = signing_repository.sign_document(
            document_revision_id=str(
                identifiers["revision_id"]
            ),
            occurred_at=SIGNED_AT,
            signed_by=str(identifiers["signed_by"]),
        )
        assert result.project_id == str(
            identifiers["project_id"]
        )
        assert result.document_revision_id == str(
            identifiers["revision_id"]
        )
        assert result.document_type == DOCUMENT_TYPE
        assert result.revision_number == 1
        assert result.signed_at == SIGNED_AT
        assert result.event_type == "DOCUMENT_SIGNED"

        with pytest.raises(DocumentAlreadySignedError):
            signing_repository.sign_document(
                document_revision_id=str(
                    identifiers["revision_id"]
                ),
                occurred_at=SIGNED_AT,
                signed_by=str(
                    identifiers["signed_by"]
                ),
            )

        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 1
        assert _document_state(
            repository,
            identifiers["revision_id"],
        ) == {
            "signed": True,
            "signed_at": SIGNED_AT,
        }

        snapshot = repository.get_project_snapshot(
            str(identifiers["project_id"])
        )
        gate = evaluate_signing_gate(
            snapshot["project"],
            snapshot["document_revisions"],
            snapshot["document_approvals"],
            snapshot["procurement_records"],
            document_type=DOCUMENT_TYPE,
        )
        assert gate.document_revision_id == str(
            identifiers["revision_id"]
        )
        assert gate.all_met is False
        assert gate.blocking_codes == (
            "DOCUMENT_ALREADY_SIGNED",
        )
        assert gate.approved_roles == (
            "LEGAL",
            "ACCOUNTING",
            "PARTNER",
        )
        assert gate.missing_roles == ()
        assert gate.requires_procurement is True
        assert gate.purchase_request_present is True
        assert gate.already_signed is True

        events = _document_events(
            repository,
            identifiers["project_id"],
        )
        assert len(events) == 1
        event = events[0]
        assert event["event_type"] == "DOCUMENT_SIGNED"
        assert event["entity_type"] == "DOCUMENT"
        assert event["entity_id"] == (
            identifiers["revision_id"]
        )
        assert event["triggered_by"] == (
            identifiers["signed_by"]
        )
        assert event["old_values"] == {
            "document_type": DOCUMENT_TYPE,
            "revision_number": 1,
            "signed": False,
            "signed_at_recorded": False,
        }
        assert event["new_values"] == {
            "document_type": DOCUMENT_TYPE,
            "revision_number": 1,
            "signed": True,
            "signed_at_recorded": True,
        }
        assert set(event["old_values"]) == SAFE_AUDIT_KEYS
        assert set(event["new_values"]) == SAFE_AUDIT_KEYS

        encoded = json.dumps(
            {
                "change_summary": event["change_summary"],
                "old_values": event["old_values"],
                "new_values": event["new_values"],
            }
        )
        sensitive_values = (
            SENSITIVE_PROJECT_TITLE,
            SENSITIVE_CONTENT_HASH,
            SENSITIVE_APPROVAL_NOTES,
            SENSITIVE_PR_NUMBER,
            str(identifiers["signed_by"]),
        )

        for sensitive_value in sensitive_values:
            assert sensitive_value not in encoded

    finally:
        cleanup_counts = _cleanup_temporary_records(
            repository,
            identifiers,
        )

    assert cleanup_counts == {
        "document_approvals": 3,
        "project_events": 1,
        "procurement_records": 1,
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
        "partner_approval_id": uuid.uuid4(),
        "purchase_request_id": uuid.uuid4(),
        "signed_by": uuid.uuid4(),
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
        "LIVE_SIGNING_"
        + identifiers["merchant_id"].hex[:12]
    )
    template_name = (
        "LIVE_SIGNING_"
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
                        "Temporary signing merchant",
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
                        "Temporary signing template",
                        "LIVE_DOCUMENT_SIGNING",
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
                        "LIVE_DOCUMENT_SIGNING",
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
                        identifiers["signed_by"],
                    ),
                )


def _insert_approvals(repository, identifiers):
    approval_rows = (
        (
            identifiers["legal_approval_id"],
            "LEGAL",
        ),
        (
            identifiers["accounting_approval_id"],
            "ACCOUNTING",
        ),
        (
            identifiers["partner_approval_id"],
            "PARTNER",
        ),
    )

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                for approval_id, role in approval_rows:
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
                            %s, %s, %s, 'APPROVED',
                            %s, %s, %s
                        )
                        """,
                        (
                            approval_id,
                            identifiers["revision_id"],
                            role,
                            APPROVED_AT,
                            identifiers["signed_by"],
                            SENSITIVE_APPROVAL_NOTES,
                        ),
                    )


def _insert_purchase_request(repository, identifiers):
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO
                        merchant_ops.procurement_records (
                            id,
                            project_id,
                            procurement_type,
                            external_id,
                            status,
                            version
                        )
                    VALUES (
                        %s, %s, 'PURCHASE_REQUEST',
                        %s, 'CREATED', 1
                    )
                    """,
                    (
                        identifiers["purchase_request_id"],
                        identifiers["project_id"],
                        SENSITIVE_PR_NUMBER,
                    ),
                )


def _document_state(repository, revision_id):
    with repository.connection(
        read_only=True
    ) as connection:
        with connection.transaction():
            with connection.cursor(
                row_factory=dict_row
            ) as cursor:
                cursor.execute(
                    """
                    SELECT signed, signed_at
                    FROM merchant_ops.document_revisions
                    WHERE id = %s
                    """,
                    (revision_id,),
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
                    ORDER BY created_at, id
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
                            FROM merchant_ops.document_approvals
                            WHERE document_revision_id = %s
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
                        identifiers["revision_id"],
                        identifiers["project_id"],
                        identifiers["project_id"],
                    ),
                )
                return cursor.fetchone()["record_count"]
