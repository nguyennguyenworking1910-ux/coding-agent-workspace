"""Tests for atomic Merchant procurement persistence."""

from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from psycopg import errors

from claude.agents.tools.merchant.procurement_engine import (
    ProcurementConflictError,
    ProcurementDependencyError,
    ProcurementLifecycleClosedError,
)
from claude.clients.merchant.procurement_repository import (
    MerchantProcurementRepository,
    ProcurementMutationResult,
    ProcurementPersistenceError,
)
from claude.clients.merchant.repository import (
    ProjectNotFoundError,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
REVISION_ID = "00000000-0000-0000-0000-000000000003"
PROCUREMENT_1_ID = (
    "00000000-0000-0000-0000-000000000004"
)
PROCUREMENT_2_ID = (
    "00000000-0000-0000-0000-000000000005"
)
TRIGGERED_BY = (
    "00000000-0000-0000-0000-000000000006"
)

SIGNED_AT = datetime(
    2026,
    9,
    5,
    10,
    0,
    tzinfo=timezone.utc,
)
SENSITIVE_EXTERNAL_ID = "JRA-SENSITIVE-12345"


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


def make_procurement_repository():
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

    procurement_repository = (
        MerchantProcurementRepository(repository)
    )

    return (
        procurement_repository,
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


def revision_record(*, signed=True):
    return {
        "id": REVISION_ID,
        "project_id": PROJECT_ID,
        "document_type": "MERCHANT_AGREEMENT",
        "revision_number": 1,
        "content_hash": "sensitive-document-hash",
        "signed": signed,
        "signed_at": (
            SIGNED_AT
            if signed
            else None
        ),
        "effective_date": None,
        "expiry_date": None,
        "superseded_by": None,
        "created_at": None,
        "created_by": TRIGGERED_BY,
    }


def procurement_record(
    *,
    procurement_id=PROCUREMENT_1_ID,
    procurement_type="PURCHASE_REQUEST",
    external_id=SENSITIVE_EXTERNAL_ID,
    status="CREATED",
    version=1,
):
    return {
        "id": procurement_id,
        "project_id": PROJECT_ID,
        "procurement_type": procurement_type,
        "external_id": external_id,
        "status": status,
        "created_at": None,
        "updated_at": None,
        "version": version,
    }


def prepare_snapshot(
    cursor,
    *,
    project=None,
    revisions=(),
    procurement_records=(),
    rowcount=1,
):
    cursor.fetchone.return_value = (
        project
        if project is not None
        else project_record()
    )
    cursor.fetchall.side_effect = [
        list(revisions),
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


class MerchantProcurementRepositoryTests(
    unittest.TestCase
):
    def test_purchase_request_is_inserted_and_audited(self):
        (
            procurement_repository,
            repository,
            connection,
            cursor,
            transaction_context,
        ) = make_procurement_repository()
        prepare_snapshot(cursor)

        result = (
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="purchase_request",
                external_id=SENSITIVE_EXTERNAL_ID,
                status="created",
                triggered_by=TRIGGERED_BY,
                procurement_id=PROCUREMENT_1_ID,
            )
        )

        self.assertIsInstance(
            result,
            ProcurementMutationResult,
        )
        self.assertEqual(result.project_id, PROJECT_ID)
        self.assertEqual(
            result.procurement_id,
            PROCUREMENT_1_ID,
        )
        self.assertEqual(
            result.procurement_type,
            "PURCHASE_REQUEST",
        )
        self.assertEqual(result.status, "CREATED")
        self.assertIsNone(result.previous_version)
        self.assertEqual(result.current_version, 1)
        self.assertEqual(result.operation, "INSERT")
        self.assertEqual(
            result.event_type,
            "PROCUREMENT_CREATED",
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
        self.assertIn(
            "FOR UPDATE OF procurement",
            sql[2],
        )
        self.assertTrue(
            sql[3].startswith(
                "INSERT INTO "
                "merchant_ops.procurement_records"
            )
        )
        self.assertTrue(
            sql[4].startswith(
                "INSERT INTO merchant_ops.project_events"
            )
        )
        self.assertEqual(len(sql), 5)

    def test_insert_persists_complete_record(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            _,
        ) = make_procurement_repository()
        prepare_snapshot(cursor)

        procurement_repository.record_procurement(
            project_id=PROJECT_ID,
            procurement_type="PURCHASE_REQUEST",
            external_id=SENSITIVE_EXTERNAL_ID,
            status="CREATED",
            procurement_id=PROCUREMENT_1_ID,
        )

        insert_call = next(
            call
            for call in cursor.execute.call_args_list
            if (
                "INSERT INTO "
                "merchant_ops.procurement_records"
            )
            in call.args[0]
        )
        self.assertEqual(
            insert_call.args[1],
            (
                uuid.UUID(PROCUREMENT_1_ID),
                uuid.UUID(PROJECT_ID),
                "PURCHASE_REQUEST",
                SENSITIVE_EXTERNAL_ID,
                "CREATED",
            ),
        )

    def test_update_uses_optimistic_version_guards(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            _,
        ) = make_procurement_repository()
        prepare_snapshot(
            cursor,
            procurement_records=[
                procurement_record(version=3)
            ],
        )

        result = (
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_REQUEST",
                external_id="JRA-UPDATED-456",
                status="APPROVED",
                expected_version=3,
                procurement_id=PROCUREMENT_2_ID,
            )
        )

        self.assertEqual(result.operation, "UPDATE")
        self.assertEqual(
            result.procurement_id,
            PROCUREMENT_1_ID,
        )
        self.assertEqual(result.previous_version, 3)
        self.assertEqual(result.current_version, 4)

        update_call = next(
            call
            for call in cursor.execute.call_args_list
            if (
                "UPDATE "
                "merchant_ops.procurement_records"
            )
            in call.args[0]
        )
        sql = " ".join(update_call.args[0].split())
        parameters = update_call.args[1]

        self.assertIn("WHERE id = %s", sql)
        self.assertIn("AND project_id = %s", sql)
        self.assertIn(
            "AND procurement_type = %s",
            sql,
        )
        self.assertIn("AND version = %s", sql)
        self.assertEqual(
            parameters,
            (
                "JRA-UPDATED-456",
                "APPROVED",
                4,
                uuid.UUID(PROCUREMENT_1_ID),
                uuid.UUID(PROJECT_ID),
                "PURCHASE_REQUEST",
                3,
            ),
        )

        executed = executed_sql(cursor)
        update_index = next(
            index
            for index, query in enumerate(executed)
            if query.startswith(
                "UPDATE "
                "merchant_ops.procurement_records"
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

    def test_stale_version_rolls_back_before_mutation(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_procurement_repository()
        prepare_snapshot(
            cursor,
            procurement_records=[
                procurement_record(version=3)
            ],
        )

        with self.assertRaises(
            ProcurementConflictError
        ):
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_REQUEST",
                external_id="JRA-UPDATED-456",
                status="APPROVED",
                expected_version=2,
            )

        self.assertIs(
            transaction_context.exception_type,
            ProcurementConflictError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "UPDATE merchant_ops.procurement_records",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_zero_row_update_rolls_back_without_event(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_procurement_repository()
        prepare_snapshot(
            cursor,
            procurement_records=[
                procurement_record()
            ],
            rowcount=0,
        )

        with self.assertRaisesRegex(
            ProcurementConflictError,
            "changed before",
        ):
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_REQUEST",
                external_id="JRA-UPDATED-456",
                status="APPROVED",
                expected_version=1,
            )

        self.assertIs(
            transaction_context.exception_type,
            ProcurementConflictError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "UPDATE merchant_ops.procurement_records",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_purchase_order_requires_signed_document(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_procurement_repository()
        prepare_snapshot(
            cursor,
            revisions=[revision_record(signed=False)],
        )

        with self.assertRaises(
            ProcurementDependencyError
        ):
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_ORDER",
                external_id="PO-123",
                status="CREATED",
            )

        self.assertIs(
            transaction_context.exception_type,
            ProcurementDependencyError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "INSERT INTO "
            "merchant_ops.procurement_records",
            combined,
        )

    def test_signed_document_allows_purchase_order(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            _,
        ) = make_procurement_repository()
        prepare_snapshot(
            cursor,
            revisions=[revision_record()],
        )

        result = (
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_ORDER",
                external_id="PO-123",
                status="CREATED",
                procurement_id=PROCUREMENT_1_ID,
            )
        )

        self.assertEqual(
            result.procurement_type,
            "PURCHASE_ORDER",
        )
        self.assertEqual(result.current_version, 1)

    def test_required_purchase_order_needs_pr_number(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_procurement_repository()
        prepare_snapshot(
            cursor,
            project=project_record(
                requires_procurement=True
            ),
            revisions=[revision_record()],
        )

        with self.assertRaisesRegex(
            ProcurementDependencyError,
            "Purchase Request number",
        ):
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_ORDER",
                external_id="PO-123",
                status="CREATED",
            )

        self.assertIs(
            transaction_context.exception_type,
            ProcurementDependencyError,
        )

    def test_payment_request_requires_po_number(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_procurement_repository()
        prepare_snapshot(
            cursor,
            revisions=[revision_record()],
        )

        with self.assertRaisesRegex(
            ProcurementDependencyError,
            "Purchase Order number",
        ):
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PAYMENT_REQUEST",
                external_id="PAY-123",
                status="CREATED",
            )

        self.assertIs(
            transaction_context.exception_type,
            ProcurementDependencyError,
        )

    def test_terminal_project_rolls_back(self):
        for status in ("COMPLETED", "CANCELLED"):
            with self.subTest(status=status):
                (
                    procurement_repository,
                    _,
                    _,
                    cursor,
                    transaction_context,
                ) = make_procurement_repository()
                prepare_snapshot(
                    cursor,
                    project=project_record(status=status),
                )

                with self.assertRaises(
                    ProcurementLifecycleClosedError
                ):
                    procurement_repository.record_procurement(
                        project_id=PROJECT_ID,
                        procurement_type=(
                            "PURCHASE_REQUEST"
                        ),
                        external_id=(
                            SENSITIVE_EXTERNAL_ID
                        ),
                    )

                self.assertIs(
                    transaction_context.exception_type,
                    ProcurementLifecycleClosedError,
                )
                combined = "\n".join(
                    executed_sql(cursor)
                )
                self.assertNotIn(
                    "INSERT INTO "
                    "merchant_ops.procurement_records",
                    combined,
                )

    def test_missing_project_stops_before_evidence_locks(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_procurement_repository()
        cursor.fetchone.return_value = None

        with self.assertRaises(ProjectNotFoundError):
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_REQUEST",
                external_id=SENSITIVE_EXTERNAL_ID,
            )

        self.assertIs(
            transaction_context.exception_type,
            ProjectNotFoundError,
        )
        self.assertEqual(
            len(cursor.execute.call_args_list),
            1,
        )

    def test_audit_payload_is_redacted_and_safe(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            _,
        ) = make_procurement_repository()
        prepare_snapshot(cursor)

        procurement_repository.record_procurement(
            project_id=PROJECT_ID,
            procurement_type="PURCHASE_REQUEST",
            external_id=SENSITIVE_EXTERNAL_ID,
            status="CREATED",
            triggered_by=TRIGGERED_BY,
            procurement_id=PROCUREMENT_1_ID,
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

        self.assertNotIn(SENSITIVE_EXTERNAL_ID, encoded)
        self.assertNotIn(
            "sensitive-document-hash",
            encoded,
        )
        self.assertNotIn(TRIGGERED_BY, encoded)
        self.assertNotIn(PROCUREMENT_1_ID, encoded)
        self.assertEqual(
            set(old_values),
            {
                "procurement_type",
                "status",
                "external_id_recorded",
                "version",
            },
        )
        self.assertEqual(set(new_values), set(old_values))
        self.assertEqual(
            parameters[4],
            uuid.UUID(PROCUREMENT_1_ID),
        )
        self.assertEqual(
            parameters[8],
            uuid.UUID(TRIGGERED_BY),
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
        self.assertIn("'PROCUREMENT'", event_sql)

    def test_result_is_json_compatible_and_redacted(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            _,
        ) = make_procurement_repository()
        prepare_snapshot(cursor)

        result = (
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_REQUEST",
                external_id=SENSITIVE_EXTERNAL_ID,
                status="CREATED",
                procurement_id=PROCUREMENT_1_ID,
            )
        )

        payload = result.to_dict()
        self.assertEqual(
            json.loads(json.dumps(payload)),
            payload,
        )
        self.assertNotIn(
            SENSITIVE_EXTERNAL_ID,
            json.dumps(payload),
        )

    def test_invalid_identifier_fails_before_connection(self):
        (
            procurement_repository,
            repository,
            _,
            _,
            _,
        ) = make_procurement_repository()

        invalid_arguments = (
            {
                "project_id": "not-a-uuid",
            },
            {
                "project_id": PROJECT_ID,
                "procurement_id": "not-a-uuid",
            },
            {
                "project_id": PROJECT_ID,
                "triggered_by": "not-a-uuid",
            },
        )

        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(
                    ProcurementPersistenceError
                ):
                    procurement_repository.record_procurement(
                        procurement_type=(
                            "PURCHASE_REQUEST"
                        ),
                        external_id=(
                            SENSITIVE_EXTERNAL_ID
                        ),
                        **arguments,
                    )

        repository.connection.assert_not_called()

    def test_unique_violation_is_translated(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_procurement_repository()
        prepare_snapshot(cursor)

        def execute(query, parameters=None):
            del parameters
            if (
                "INSERT INTO "
                "merchant_ops.procurement_records"
            ) in query:
                raise errors.UniqueViolation(
                    "duplicate procurement"
                )

        cursor.execute.side_effect = execute

        with self.assertRaisesRegex(
            ProcurementConflictError,
            "existing project record",
        ):
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_REQUEST",
                external_id=SENSITIVE_EXTERNAL_ID,
                procurement_id=PROCUREMENT_1_ID,
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

    def test_event_failure_rolls_back_procurement_change(self):
        (
            procurement_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_procurement_repository()
        prepare_snapshot(
            cursor,
            procurement_records=[
                procurement_record()
            ],
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
            procurement_repository.record_procurement(
                project_id=PROJECT_ID,
                procurement_type="PURCHASE_REQUEST",
                external_id="JRA-UPDATED-456",
                status="APPROVED",
                expected_version=1,
            )

        self.assertIs(
            transaction_context.exception_type,
            RuntimeError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "UPDATE merchant_ops.procurement_records",
            combined,
        )
        self.assertIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )


if __name__ == "__main__":
    unittest.main()
