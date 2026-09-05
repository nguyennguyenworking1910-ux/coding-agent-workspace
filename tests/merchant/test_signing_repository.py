"""Tests for atomic Merchant document signing persistence."""

from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from claude.agents.tools.merchant.signing_engine import (
    DocumentAlreadySignedError,
    DocumentSigningConflictError,
    DocumentSigningGateError,
    DocumentSigningLifecycleClosedError,
)
from claude.clients.merchant.signing_repository import (
    DocumentSigningResult,
    MerchantSigningRepository,
    SigningPersistenceError,
    SigningRevisionNotFoundError,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
REVISION_1_ID = (
    "00000000-0000-0000-0000-000000000003"
)
REVISION_2_ID = (
    "00000000-0000-0000-0000-000000000004"
)
SIGNED_BY = "00000000-0000-0000-0000-000000000005"

SIGNED_AT = datetime(
    2026,
    9,
    5,
    12,
    0,
    tzinfo=timezone.utc,
)
SENSITIVE_CONTENT_HASH = "sensitive-document-hash"
SENSITIVE_NOTES = "Sensitive approval notes"
SENSITIVE_PR_NUMBER = "JRA-SENSITIVE-12345"


class RecordingContext:
    def __init__(self, value):
        self.value = value
        self.entered = False
        self.exception_type = None

    def __enter__(self):
        self.entered = True
        return self.value

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ):
        self.exception_type = exception_type
        return False


def make_signing_repository():
    repository = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    connection_context = RecordingContext(connection)
    transaction_context = RecordingContext(None)
    cursor_context = RecordingContext(cursor)

    repository.connection.return_value = (
        connection_context
    )
    connection.transaction.return_value = (
        transaction_context
    )
    connection.cursor.return_value = cursor_context

    signing_repository = MerchantSigningRepository(
        repository
    )

    return (
        signing_repository,
        repository,
        connection,
        cursor,
        transaction_context,
    )


def project_record(
    *,
    status="IN_PROGRESS",
    requires_procurement=False,
):
    return {
        "id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "status": status,
        "requires_procurement": requires_procurement,
        "title": "Sensitive project title",
    }


def revision_record(
    *,
    revision_id=REVISION_1_ID,
    revision_number=1,
    signed=False,
    signed_at=None,
    superseded_by=None,
):
    return {
        "id": revision_id,
        "project_id": PROJECT_ID,
        "document_type": "MERCHANT_AGREEMENT",
        "revision_number": revision_number,
        "content_hash": SENSITIVE_CONTENT_HASH,
        "signed": signed,
        "signed_at": signed_at,
        "effective_date": None,
        "expiry_date": None,
        "superseded_by": superseded_by,
        "created_at": None,
        "created_by": SIGNED_BY,
    }


def approval_record(role):
    return {
        "id": f"approval-{role.lower()}",
        "document_revision_id": REVISION_1_ID,
        "approver_role": role,
        "approval_status": "APPROVED",
        "approved_at": SIGNED_AT,
        "approved_by": SIGNED_BY,
        "notes": SENSITIVE_NOTES,
        "created_at": None,
    }


def all_approvals():
    return [
        approval_record(role)
        for role in ("LEGAL", "ACCOUNTING", "PARTNER")
    ]


def purchase_request():
    return {
        "id": "purchase-request-1",
        "project_id": PROJECT_ID,
        "procurement_type": "PURCHASE_REQUEST",
        "external_id": SENSITIVE_PR_NUMBER,
        "status": "CREATED",
        "created_at": None,
        "updated_at": None,
        "version": 1,
    }


def prepare_snapshot(
    cursor,
    *,
    project=None,
    revisions=None,
    approvals=None,
    procurement_records=(),
    rowcount=1,
):
    cursor.fetchone.return_value = (
        project
        if project is not None
        else project_record()
    )
    cursor.fetchall.side_effect = [
        list(
            revisions
            if revisions is not None
            else [revision_record()]
        ),
        list(
            approvals
            if approvals is not None
            else all_approvals()
        ),
        list(procurement_records),
    ]
    cursor.rowcount = rowcount


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


class MerchantSigningRepositoryTests(
    unittest.TestCase
):
    def test_eligible_revision_is_signed_and_audited(self):
        (
            signing_repository,
            repository,
            connection,
            cursor,
            transaction_context,
        ) = make_signing_repository()
        prepare_snapshot(cursor)

        result = signing_repository.sign_document(
            document_revision_id=REVISION_1_ID,
            occurred_at=SIGNED_AT,
            signed_by=SIGNED_BY,
        )

        self.assertIsInstance(
            result,
            DocumentSigningResult,
        )
        self.assertEqual(result.project_id, PROJECT_ID)
        self.assertEqual(
            result.document_revision_id,
            REVISION_1_ID,
        )
        self.assertEqual(
            result.document_type,
            "MERCHANT_AGREEMENT",
        )
        self.assertEqual(result.revision_number, 1)
        self.assertEqual(result.signed_at, SIGNED_AT)
        self.assertEqual(
            result.event_type,
            "DOCUMENT_SIGNED",
        )

        repository.connection.assert_called_once_with()
        connection.transaction.assert_called_once_with()
        self.assertTrue(transaction_context.entered)
        self.assertIsNone(
            transaction_context.exception_type
        )

        sql = executed_sql(cursor)
        self.assertIn("FOR UPDATE OF project", sql[0])
        self.assertIn("FOR UPDATE OF revision", sql[1])
        self.assertIn("FOR UPDATE OF approval", sql[2])
        self.assertIn(
            "FOR UPDATE OF procurement",
            sql[3],
        )
        self.assertTrue(
            sql[4].startswith(
                "UPDATE merchant_ops.document_revisions"
            )
        )
        self.assertTrue(
            sql[5].startswith(
                "INSERT INTO merchant_ops.project_events"
            )
        )
        self.assertEqual(len(sql), 6)

    def test_signing_update_has_one_way_guards(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            _,
        ) = make_signing_repository()
        prepare_snapshot(cursor)

        signing_repository.sign_document(
            document_revision_id=REVISION_1_ID,
            occurred_at=SIGNED_AT,
        )

        update_call = next(
            call
            for call in cursor.execute.call_args_list
            if "UPDATE merchant_ops.document_revisions"
            in call.args[0]
        )
        sql = " ".join(update_call.args[0].split())
        parameters = update_call.args[1]

        self.assertIn("AND project_id = %s", sql)
        self.assertIn("AND document_type = %s", sql)
        self.assertIn("AND revision_number = %s", sql)
        self.assertIn("AND signed = FALSE", sql)
        self.assertIn("AND signed_at IS NULL", sql)
        self.assertIn("AND superseded_by IS NULL", sql)
        self.assertEqual(
            parameters,
            (
                SIGNED_AT,
                uuid.UUID(REVISION_1_ID),
                uuid.UUID(PROJECT_ID),
                "MERCHANT_AGREEMENT",
                1,
            ),
        )

    def test_zero_row_update_rolls_back_without_event(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_signing_repository()
        prepare_snapshot(cursor, rowcount=0)

        with self.assertRaisesRegex(
            DocumentSigningConflictError,
            "changed before signing",
        ):
            signing_repository.sign_document(
                document_revision_id=REVISION_1_ID,
                occurred_at=SIGNED_AT,
            )

        self.assertIs(
            transaction_context.exception_type,
            DocumentSigningConflictError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "UPDATE merchant_ops.document_revisions",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_missing_approvals_roll_back_before_update(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_signing_repository()
        prepare_snapshot(cursor, approvals=[])

        with self.assertRaises(
            DocumentSigningGateError
        ):
            signing_repository.sign_document(
                document_revision_id=REVISION_1_ID,
                occurred_at=SIGNED_AT,
            )

        self.assertIs(
            transaction_context.exception_type,
            DocumentSigningGateError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "UPDATE merchant_ops.document_revisions",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_missing_required_pr_rolls_back(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_signing_repository()
        prepare_snapshot(
            cursor,
            project=project_record(
                requires_procurement=True
            ),
        )

        with self.assertRaises(
            DocumentSigningGateError
        ) as context:
            signing_repository.sign_document(
                document_revision_id=REVISION_1_ID,
                occurred_at=SIGNED_AT,
            )

        self.assertIn(
            "MISSING_PURCHASE_REQUEST",
            context.exception.gate_result.blocking_codes,
        )
        self.assertIs(
            transaction_context.exception_type,
            DocumentSigningGateError,
        )

    def test_required_pr_allows_signing(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            _,
        ) = make_signing_repository()
        prepare_snapshot(
            cursor,
            project=project_record(
                requires_procurement=True
            ),
            procurement_records=[purchase_request()],
        )

        result = signing_repository.sign_document(
            document_revision_id=REVISION_1_ID,
            occurred_at=SIGNED_AT,
        )

        self.assertEqual(
            result.event_type,
            "DOCUMENT_SIGNED",
        )

    def test_inactive_revision_rolls_back(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_signing_repository()
        prepare_snapshot(
            cursor,
            revisions=[
                revision_record(
                    superseded_by=REVISION_2_ID,
                ),
                revision_record(
                    revision_id=REVISION_2_ID,
                    revision_number=2,
                ),
            ],
        )

        with self.assertRaises(
            DocumentSigningLifecycleClosedError
        ):
            signing_repository.sign_document(
                document_revision_id=REVISION_1_ID,
                occurred_at=SIGNED_AT,
            )

        self.assertIs(
            transaction_context.exception_type,
            DocumentSigningLifecycleClosedError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "UPDATE merchant_ops.document_revisions",
            combined,
        )

    def test_already_signed_revision_rolls_back(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_signing_repository()
        prepare_snapshot(
            cursor,
            revisions=[
                revision_record(
                    signed=True,
                    signed_at=SIGNED_AT,
                )
            ],
        )

        with self.assertRaises(
            DocumentAlreadySignedError
        ):
            signing_repository.sign_document(
                document_revision_id=REVISION_1_ID,
            )

        self.assertIs(
            transaction_context.exception_type,
            DocumentAlreadySignedError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "UPDATE merchant_ops.document_revisions",
            combined,
        )

    def test_terminal_project_rolls_back(self):
        for status in ("COMPLETED", "CANCELLED"):
            with self.subTest(status=status):
                (
                    signing_repository,
                    _,
                    _,
                    cursor,
                    transaction_context,
                ) = make_signing_repository()
                prepare_snapshot(
                    cursor,
                    project=project_record(status=status),
                )

                with self.assertRaises(
                    DocumentSigningLifecycleClosedError
                ):
                    signing_repository.sign_document(
                        document_revision_id=(
                            REVISION_1_ID
                        ),
                    )

                self.assertIs(
                    transaction_context.exception_type,
                    DocumentSigningLifecycleClosedError,
                )
                combined = "\n".join(
                    executed_sql(cursor)
                )
                self.assertNotIn(
                    "UPDATE "
                    "merchant_ops.document_revisions",
                    combined,
                )

    def test_missing_revision_stops_before_evidence_locks(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_signing_repository()
        cursor.fetchone.return_value = None

        with self.assertRaises(
            SigningRevisionNotFoundError
        ):
            signing_repository.sign_document(
                document_revision_id=REVISION_1_ID,
            )

        self.assertIs(
            transaction_context.exception_type,
            SigningRevisionNotFoundError,
        )
        self.assertEqual(
            len(cursor.execute.call_args_list),
            1,
        )

    def test_audit_payload_is_redacted_and_safe(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            _,
        ) = make_signing_repository()
        prepare_snapshot(cursor)

        signing_repository.sign_document(
            document_revision_id=REVISION_1_ID,
            occurred_at=SIGNED_AT,
            signed_by=SIGNED_BY,
        )

        parameters = event_parameters(cursor)
        old_values = parameters[6].obj
        new_values = parameters[7].obj
        encoded = json.dumps(
            {
                "summary": parameters[5],
                "old_values": old_values,
                "new_values": new_values,
            }
        )

        sensitive_values = (
            SENSITIVE_CONTENT_HASH,
            SENSITIVE_NOTES,
            SENSITIVE_PR_NUMBER,
            SIGNED_BY,
            REVISION_1_ID,
        )

        for sensitive_value in sensitive_values:
            self.assertNotIn(sensitive_value, encoded)

        self.assertEqual(
            set(old_values),
            {
                "document_type",
                "revision_number",
                "signed",
                "signed_at_recorded",
            },
        )
        self.assertEqual(set(new_values), set(old_values))
        self.assertEqual(
            parameters[4],
            uuid.UUID(REVISION_1_ID),
        )
        self.assertEqual(
            parameters[8],
            uuid.UUID(SIGNED_BY),
        )

        event_call = next(
            call
            for call in cursor.execute.call_args_list
            if "INSERT INTO merchant_ops.project_events"
            in call.args[0]
        )
        event_sql = " ".join(
            event_call.args[0].split()
        )
        self.assertIn("'DOCUMENT'", event_sql)

    def test_result_is_json_compatible_and_redacted(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            _,
        ) = make_signing_repository()
        prepare_snapshot(cursor)

        result = signing_repository.sign_document(
            document_revision_id=REVISION_1_ID,
            occurred_at=SIGNED_AT,
        )
        payload = result.to_dict()

        self.assertEqual(
            payload["signed_at"],
            SIGNED_AT.isoformat(),
        )
        self.assertEqual(
            json.loads(json.dumps(payload)),
            payload,
        )
        self.assertNotIn(
            SENSITIVE_CONTENT_HASH,
            json.dumps(payload),
        )

    def test_invalid_identifier_fails_before_connection(self):
        (
            signing_repository,
            repository,
            _,
            _,
            _,
        ) = make_signing_repository()

        invalid_arguments = (
            {
                "document_revision_id": "not-a-uuid",
            },
            {
                "document_revision_id": REVISION_1_ID,
                "signed_by": "not-a-uuid",
            },
        )

        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(
                    SigningPersistenceError
                ):
                    signing_repository.sign_document(
                        **arguments
                    )

        repository.connection.assert_not_called()

    def test_event_failure_rolls_back_signing(self):
        (
            signing_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_signing_repository()
        prepare_snapshot(cursor)

        def execute(query, parameters=None):
            del parameters
            if (
                "INSERT INTO merchant_ops.project_events"
                in query
            ):
                raise RuntimeError("audit insert failed")

        cursor.execute.side_effect = execute

        with self.assertRaisesRegex(
            RuntimeError,
            "audit insert failed",
        ):
            signing_repository.sign_document(
                document_revision_id=REVISION_1_ID,
                occurred_at=SIGNED_AT,
            )

        self.assertIs(
            transaction_context.exception_type,
            RuntimeError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "UPDATE merchant_ops.document_revisions",
            combined,
        )
        self.assertIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )


if __name__ == "__main__":
    unittest.main()
