"""Tests for atomic Merchant document approval persistence."""

from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from psycopg import errors

from claude.agents.tools.merchant.approval_engine import (
    ApprovalConflictError,
    ApprovalFinalizedError,
    ApprovalLifecycleClosedError,
    ApprovalRevisionNotActiveError,
)
from claude.clients.merchant.approval_repository import (
    ApprovalMutationResult,
    ApprovalPersistenceError,
    ApprovalRevisionNotFoundError,
    MerchantApprovalRepository,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
REVISION_1_ID = (
    "00000000-0000-0000-0000-000000000003"
)
REVISION_2_ID = (
    "00000000-0000-0000-0000-000000000004"
)
APPROVAL_1_ID = (
    "00000000-0000-0000-0000-000000000005"
)
APPROVAL_2_ID = (
    "00000000-0000-0000-0000-000000000006"
)
ACTED_BY = "00000000-0000-0000-0000-000000000007"

OCCURRED_AT = datetime(
    2026,
    9,
    4,
    12,
    0,
    tzinfo=timezone.utc,
)
CONTENT_HASH = "sensitive-document-content-hash"
SENSITIVE_NOTES = "Sensitive legal decision notes"


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


def make_approval_repository():
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

    approval_repository = MerchantApprovalRepository(
        repository
    )

    return (
        approval_repository,
        repository,
        connection,
        cursor,
        transaction_context,
    )


def project_record(*, status="IN_PROGRESS"):
    return {
        "id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "status": status,
        "title": "Sensitive project title",
    }


def revision_record(
    *,
    revision_id=REVISION_1_ID,
    revision_number=1,
    signed=False,
    superseded_by=None,
):
    return {
        "id": revision_id,
        "project_id": PROJECT_ID,
        "document_type": "MERCHANT_AGREEMENT",
        "revision_number": revision_number,
        "content_hash": CONTENT_HASH,
        "signed": signed,
        "signed_at": None,
        "effective_date": None,
        "expiry_date": None,
        "superseded_by": superseded_by,
        "created_at": None,
        "created_by": ACTED_BY,
    }


def approval_record(
    *,
    approval_id=APPROVAL_1_ID,
    revision_id=REVISION_1_ID,
    role="LEGAL",
    status="PENDING",
    approved_at=None,
    approved_by=None,
    notes=None,
):
    return {
        "id": approval_id,
        "document_revision_id": revision_id,
        "approver_role": role,
        "approval_status": status,
        "approved_at": approved_at,
        "approved_by": approved_by,
        "notes": notes,
        "created_at": None,
    }


def prepare_snapshot(
    cursor,
    *,
    project=None,
    revisions=None,
    approvals=(),
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
        list(approvals),
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


class MerchantApprovalRepositoryTests(
    unittest.TestCase
):
    def test_pending_approval_is_inserted_and_audited(self):
        (
            approval_repository,
            repository,
            connection,
            cursor,
            transaction_context,
        ) = make_approval_repository()
        prepare_snapshot(cursor)

        result = approval_repository.record_approval(
            document_revision_id=REVISION_1_ID,
            approver_role="legal",
            approval_status="pending",
            acted_by=ACTED_BY,
            notes=SENSITIVE_NOTES,
            approval_id=APPROVAL_1_ID,
        )

        self.assertIsInstance(
            result,
            ApprovalMutationResult,
        )
        self.assertEqual(result.project_id, PROJECT_ID)
        self.assertEqual(
            result.document_revision_id,
            REVISION_1_ID,
        )
        self.assertEqual(
            result.approval_id,
            APPROVAL_1_ID,
        )
        self.assertEqual(result.approver_role, "LEGAL")
        self.assertIsNone(result.previous_status)
        self.assertEqual(result.current_status, "PENDING")
        self.assertEqual(result.operation, "INSERT")
        self.assertEqual(
            result.event_type,
            "DOCUMENT_APPROVAL_REQUESTED",
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
        self.assertTrue(
            sql[3].startswith(
                "INSERT INTO merchant_ops.document_approvals"
            )
        )
        self.assertTrue(
            sql[4].startswith(
                "INSERT INTO merchant_ops.project_events"
            )
        )
        self.assertEqual(len(sql), 5)

    def test_direct_approval_persists_actor_and_time(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            _,
        ) = make_approval_repository()
        prepare_snapshot(cursor)

        approval_repository.record_approval(
            document_revision_id=REVISION_1_ID,
            approver_role="ACCOUNTING",
            approval_status="APPROVED",
            occurred_at=OCCURRED_AT,
            acted_by=ACTED_BY,
            approval_id=APPROVAL_1_ID,
        )

        insert_call = next(
            call
            for call in cursor.execute.call_args_list
            if "INSERT INTO merchant_ops.document_approvals"
            in call.args[0]
        )
        parameters = insert_call.args[1]

        self.assertEqual(
            parameters,
            (
                uuid.UUID(APPROVAL_1_ID),
                uuid.UUID(REVISION_1_ID),
                "ACCOUNTING",
                "APPROVED",
                OCCURRED_AT,
                uuid.UUID(ACTED_BY),
                None,
            ),
        )

    def test_pending_approval_is_finalized_with_guard(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            _,
        ) = make_approval_repository()
        prepare_snapshot(
            cursor,
            approvals=[approval_record()],
        )

        result = approval_repository.record_approval(
            document_revision_id=REVISION_1_ID,
            approver_role="LEGAL",
            approval_status="APPROVED",
            expected_status="PENDING",
            occurred_at=OCCURRED_AT,
            acted_by=ACTED_BY,
            approval_id=APPROVAL_2_ID,
        )

        self.assertEqual(result.operation, "UPDATE")
        self.assertEqual(result.approval_id, APPROVAL_1_ID)
        self.assertEqual(result.previous_status, "PENDING")
        self.assertEqual(result.current_status, "APPROVED")

        update_call = next(
            call
            for call in cursor.execute.call_args_list
            if "UPDATE merchant_ops.document_approvals"
            in call.args[0]
        )
        sql = " ".join(update_call.args[0].split())
        parameters = update_call.args[1]

        self.assertIn("WHERE id = %s", sql)
        self.assertIn(
            "AND document_revision_id = %s",
            sql,
        )
        self.assertIn("AND approver_role = %s", sql)
        self.assertIn("AND approval_status = %s", sql)
        self.assertEqual(
            parameters,
            (
                "APPROVED",
                OCCURRED_AT,
                uuid.UUID(ACTED_BY),
                None,
                uuid.UUID(APPROVAL_1_ID),
                uuid.UUID(REVISION_1_ID),
                "LEGAL",
                "PENDING",
            ),
        )

        executed = executed_sql(cursor)
        update_index = next(
            index
            for index, query in enumerate(executed)
            if query.startswith(
                "UPDATE merchant_ops.document_approvals"
            )
        )
        event_index = next(
            index
            for index, query in enumerate(executed)
            if query.startswith(
                "INSERT INTO merchant_ops.project_events"
            )
        )
        self.assertEqual(event_index, update_index + 1)
        self.assertEqual(event_index, len(executed) - 1)

    def test_rejection_clears_approval_fields(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            _,
        ) = make_approval_repository()
        prepare_snapshot(
            cursor,
            approvals=[approval_record()],
        )

        result = approval_repository.record_approval(
            document_revision_id=REVISION_1_ID,
            approver_role="LEGAL",
            approval_status="REJECTED",
            expected_status="PENDING",
            occurred_at=OCCURRED_AT,
            acted_by=ACTED_BY,
            notes=SENSITIVE_NOTES,
        )

        self.assertEqual(
            result.event_type,
            "DOCUMENT_REJECTED",
        )
        update_call = next(
            call
            for call in cursor.execute.call_args_list
            if "UPDATE merchant_ops.document_approvals"
            in call.args[0]
        )
        parameters = update_call.args[1]
        self.assertIsNone(parameters[1])
        self.assertIsNone(parameters[2])
        self.assertEqual(parameters[3], SENSITIVE_NOTES)

    def test_stale_status_rolls_back_before_mutation(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_approval_repository()
        prepare_snapshot(
            cursor,
            approvals=[approval_record()],
        )

        with self.assertRaises(
            ApprovalConflictError
        ):
            approval_repository.record_approval(
                document_revision_id=REVISION_1_ID,
                approver_role="LEGAL",
                approval_status="APPROVED",
                expected_status="REJECTED",
            )

        self.assertIs(
            transaction_context.exception_type,
            ApprovalConflictError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "UPDATE merchant_ops.document_approvals",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_zero_row_update_rolls_back_without_event(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_approval_repository()
        prepare_snapshot(
            cursor,
            approvals=[approval_record()],
            rowcount=0,
        )

        with self.assertRaisesRegex(
            ApprovalConflictError,
            "changed before",
        ):
            approval_repository.record_approval(
                document_revision_id=REVISION_1_ID,
                approver_role="LEGAL",
                approval_status="APPROVED",
                expected_status="PENDING",
            )

        self.assertIs(
            transaction_context.exception_type,
            ApprovalConflictError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "UPDATE merchant_ops.document_approvals",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_missing_revision_stops_before_evidence_locks(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_approval_repository()
        cursor.fetchone.return_value = None

        with self.assertRaises(
            ApprovalRevisionNotFoundError
        ):
            approval_repository.record_approval(
                document_revision_id=REVISION_1_ID,
                approver_role="LEGAL",
                approval_status="PENDING",
            )

        self.assertIs(
            transaction_context.exception_type,
            ApprovalRevisionNotFoundError,
        )
        self.assertEqual(
            len(cursor.execute.call_args_list),
            1,
        )

    def test_inactive_revision_rolls_back(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_approval_repository()
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
            ApprovalRevisionNotActiveError
        ):
            approval_repository.record_approval(
                document_revision_id=REVISION_1_ID,
                approver_role="LEGAL",
                approval_status="PENDING",
            )

        self.assertIs(
            transaction_context.exception_type,
            ApprovalRevisionNotActiveError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "INSERT INTO merchant_ops.document_approvals",
            combined,
        )

    def test_closed_lifecycles_roll_back(self):
        cases = (
            (
                project_record(status="COMPLETED"),
                [revision_record()],
            ),
            (
                project_record(),
                [revision_record(signed=True)],
            ),
        )

        for project, revisions in cases:
            with self.subTest(
                project_status=project["status"],
                signed=revisions[0]["signed"],
            ):
                (
                    approval_repository,
                    _,
                    _,
                    cursor,
                    transaction_context,
                ) = make_approval_repository()
                prepare_snapshot(
                    cursor,
                    project=project,
                    revisions=revisions,
                )

                with self.assertRaises(
                    ApprovalLifecycleClosedError
                ):
                    approval_repository.record_approval(
                        document_revision_id=(
                            REVISION_1_ID
                        ),
                        approver_role="LEGAL",
                        approval_status="PENDING",
                    )

                self.assertIs(
                    transaction_context.exception_type,
                    ApprovalLifecycleClosedError,
                )
                combined = "\n".join(
                    executed_sql(cursor)
                )
                self.assertNotIn(
                    "INSERT INTO merchant_ops.document_approvals",
                    combined,
                )

    def test_finalized_decision_rolls_back(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_approval_repository()
        prepare_snapshot(
            cursor,
            approvals=[
                approval_record(
                    status="APPROVED",
                    approved_at=OCCURRED_AT,
                    approved_by=ACTED_BY,
                )
            ],
        )

        with self.assertRaises(
            ApprovalFinalizedError
        ):
            approval_repository.record_approval(
                document_revision_id=REVISION_1_ID,
                approver_role="LEGAL",
                approval_status="REJECTED",
                expected_status="APPROVED",
            )

        self.assertIs(
            transaction_context.exception_type,
            ApprovalFinalizedError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "UPDATE merchant_ops.document_approvals",
            combined,
        )

    def test_audit_payload_is_redacted_and_safe(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            _,
        ) = make_approval_repository()
        prepare_snapshot(cursor)

        approval_repository.record_approval(
            document_revision_id=REVISION_1_ID,
            approver_role="LEGAL",
            approval_status="APPROVED",
            occurred_at=OCCURRED_AT,
            acted_by=ACTED_BY,
            notes=SENSITIVE_NOTES,
            approval_id=APPROVAL_1_ID,
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

        self.assertNotIn(SENSITIVE_NOTES, encoded)
        self.assertNotIn(CONTENT_HASH, encoded)
        self.assertNotIn(ACTED_BY, encoded)
        self.assertNotIn(REVISION_1_ID, encoded)
        self.assertEqual(
            set(old_values),
            {
                "document_type",
                "revision_number",
                "approver_role",
                "approval_status",
            },
        )
        self.assertEqual(set(new_values), set(old_values))
        self.assertEqual(
            parameters[4],
            uuid.UUID(REVISION_1_ID),
        )
        self.assertEqual(
            parameters[8],
            uuid.UUID(ACTED_BY),
        )

    def test_result_is_json_compatible(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            _,
        ) = make_approval_repository()
        prepare_snapshot(cursor)

        result = approval_repository.record_approval(
            document_revision_id=REVISION_1_ID,
            approver_role="PARTNER",
            approval_status="REJECTED",
            approval_id=APPROVAL_1_ID,
        )

        payload = result.to_dict()
        self.assertEqual(
            json.loads(json.dumps(payload)),
            payload,
        )
        self.assertEqual(payload["project_id"], PROJECT_ID)
        self.assertEqual(
            payload["current_status"],
            "REJECTED",
        )
        self.assertEqual(
            payload["event_type"],
            "DOCUMENT_REJECTED",
        )

    def test_invalid_identifier_fails_before_connection(self):
        (
            approval_repository,
            repository,
            _,
            _,
            _,
        ) = make_approval_repository()

        invalid_arguments = (
            {
                "document_revision_id": "not-a-uuid",
            },
            {
                "document_revision_id": REVISION_1_ID,
                "approval_id": "not-a-uuid",
            },
            {
                "document_revision_id": REVISION_1_ID,
                "acted_by": "not-a-uuid",
            },
        )

        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(
                    ApprovalPersistenceError
                ):
                    approval_repository.record_approval(
                        approver_role="LEGAL",
                        approval_status="PENDING",
                        **arguments,
                    )

        repository.connection.assert_not_called()

    def test_unique_violation_is_translated(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_approval_repository()
        prepare_snapshot(cursor)

        def execute(query, parameters=None):
            del parameters
            if (
                "INSERT INTO merchant_ops.document_approvals"
                in query
            ):
                raise errors.UniqueViolation(
                    "duplicate approval"
                )

        cursor.execute.side_effect = execute

        with self.assertRaisesRegex(
            ApprovalConflictError,
            "existing revision-role record",
        ):
            approval_repository.record_approval(
                document_revision_id=REVISION_1_ID,
                approver_role="LEGAL",
                approval_status="PENDING",
                approval_id=APPROVAL_1_ID,
            )

        self.assertIs(
            transaction_context.exception_type,
            errors.UniqueViolation,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_event_failure_rolls_back_approval_change(self):
        (
            approval_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_approval_repository()
        prepare_snapshot(
            cursor,
            approvals=[approval_record()],
        )

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
            approval_repository.record_approval(
                document_revision_id=REVISION_1_ID,
                approver_role="LEGAL",
                approval_status="APPROVED",
                expected_status="PENDING",
            )

        self.assertIs(
            transaction_context.exception_type,
            RuntimeError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "UPDATE merchant_ops.document_approvals",
            combined,
        )
        self.assertIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )


if __name__ == "__main__":
    unittest.main()
