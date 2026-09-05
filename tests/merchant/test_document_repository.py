"""Tests for atomic Merchant document revision persistence."""

from __future__ import annotations

import json
import unittest
import uuid
from datetime import date
from unittest.mock import MagicMock

from psycopg import errors

from claude.agents.tools.merchant.document_engine import (
    DocumentLifecycleClosedError,
    DocumentRevisionConflictError,
)
from claude.clients.merchant.document_repository import (
    DocumentPersistenceError,
    DocumentRevisionResult,
    MerchantDocumentRepository,
)
from claude.clients.merchant.repository import (
    ProjectNotFoundError,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
REVISION_1_ID = (
    "00000000-0000-0000-0000-000000000003"
)
REVISION_2_ID = (
    "00000000-0000-0000-0000-000000000004"
)
CREATED_BY = "00000000-0000-0000-0000-000000000005"

EFFECTIVE_DATE = date(2026, 9, 4)
EXPIRY_DATE = date(2027, 9, 4)
CONTENT_HASH = "sha256:document-revision-one"


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


def make_document_repository():
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

    document_repository = MerchantDocumentRepository(
        repository
    )

    return (
        document_repository,
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
    document_type="MERCHANT_AGREEMENT",
    revision_number=1,
    content_hash=CONTENT_HASH,
    signed=False,
    superseded_by=None,
):
    return {
        "id": revision_id,
        "project_id": PROJECT_ID,
        "document_type": document_type,
        "revision_number": revision_number,
        "content_hash": content_hash,
        "signed": signed,
        "signed_at": None,
        "effective_date": EFFECTIVE_DATE,
        "expiry_date": EXPIRY_DATE,
        "superseded_by": superseded_by,
        "created_at": None,
        "created_by": CREATED_BY,
    }


def prepare_snapshot(
    cursor,
    *,
    project=None,
    revisions=(),
    rowcount=1,
):
    cursor.fetchone.return_value = (
        project
        if project is not None
        else project_record()
    )
    cursor.fetchall.return_value = list(revisions)
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


class MerchantDocumentRepositoryTests(
    unittest.TestCase
):
    def test_initial_revision_is_created_and_audited(self):
        (
            document_repository,
            repository,
            connection,
            cursor,
            transaction_context,
        ) = make_document_repository()

        prepare_snapshot(cursor)

        result = document_repository.create_revision(
            project_id=PROJECT_ID,
            document_type="merchant_agreement",
            content_hash=CONTENT_HASH,
            effective_date=EFFECTIVE_DATE,
            expiry_date=EXPIRY_DATE,
            created_by=CREATED_BY,
            revision_id=REVISION_1_ID,
        )

        self.assertIsInstance(
            result,
            DocumentRevisionResult,
        )
        self.assertEqual(result.project_id, PROJECT_ID)
        self.assertEqual(
            result.revision_id,
            REVISION_1_ID,
        )
        self.assertEqual(
            result.document_type,
            "MERCHANT_AGREEMENT",
        )
        self.assertEqual(result.revision_number, 1)
        self.assertIsNone(result.previous_revision_id)
        self.assertEqual(
            result.event_type,
            "DOCUMENT_REVISION_CREATED",
        )

        repository.connection.assert_called_once_with()
        connection.transaction.assert_called_once_with()
        self.assertTrue(transaction_context.entered)
        self.assertIsNone(
            transaction_context.exception_type
        )

        combined = "\n".join(executed_sql(cursor))
        self.assertIn("FOR UPDATE OF project", combined)
        self.assertIn("FOR UPDATE OF revision", combined)
        self.assertEqual(
            combined.count(
                "INSERT INTO merchant_ops.document_revisions"
            ),
            1,
        )
        self.assertNotIn(
            "UPDATE merchant_ops.document_revisions",
            combined,
        )
        self.assertEqual(
            combined.count(
                "INSERT INTO merchant_ops.project_events"
            ),
            1,
        )

    def test_next_revision_supersedes_previous_atomically(self):
        (
            document_repository,
            _,
            _,
            cursor,
            _,
        ) = make_document_repository()

        prepare_snapshot(
            cursor,
            revisions=[revision_record()],
        )

        result = document_repository.create_revision(
            project_id=PROJECT_ID,
            document_type="MERCHANT_AGREEMENT",
            content_hash="sha256:document-revision-two",
            created_by=CREATED_BY,
            revision_id=REVISION_2_ID,
        )

        self.assertEqual(result.revision_number, 2)
        self.assertEqual(
            result.previous_revision_id,
            REVISION_1_ID,
        )

        sql = executed_sql(cursor)
        insert_index = next(
            index
            for index, query in enumerate(sql)
            if query.startswith(
                "INSERT INTO merchant_ops.document_revisions"
            )
        )
        supersede_index = next(
            index
            for index, query in enumerate(sql)
            if query.startswith(
                "UPDATE merchant_ops.document_revisions"
            )
        )
        event_index = next(
            index
            for index, query in enumerate(sql)
            if query.startswith(
                "INSERT INTO merchant_ops.project_events"
            )
        )

        self.assertEqual(
            supersede_index,
            insert_index + 1,
        )
        self.assertEqual(event_index, supersede_index + 1)
        self.assertEqual(event_index, len(sql) - 1)

    def test_supersede_update_uses_active_revision_guards(self):
        (
            document_repository,
            _,
            _,
            cursor,
            _,
        ) = make_document_repository()

        prepare_snapshot(
            cursor,
            revisions=[revision_record()],
        )

        document_repository.create_revision(
            project_id=PROJECT_ID,
            document_type="MERCHANT_AGREEMENT",
            content_hash="sha256:document-revision-two",
            revision_id=REVISION_2_ID,
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
        self.assertIn("AND superseded_by IS NULL", sql)
        self.assertEqual(
            parameters,
            (
                uuid.UUID(REVISION_2_ID),
                uuid.UUID(REVISION_1_ID),
                uuid.UUID(PROJECT_ID),
                "MERCHANT_AGREEMENT",
                1,
            ),
        )

    def test_different_document_type_starts_new_sequence(self):
        (
            document_repository,
            _,
            _,
            cursor,
            _,
        ) = make_document_repository()

        prepare_snapshot(
            cursor,
            revisions=[revision_record()],
        )

        result = document_repository.create_revision(
            project_id=PROJECT_ID,
            document_type="DATA_PROCESSING_ADDENDUM",
            content_hash="sha256:dpa-revision-one",
            revision_id=REVISION_2_ID,
        )

        self.assertEqual(result.revision_number, 1)
        self.assertIsNone(result.previous_revision_id)
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "UPDATE merchant_ops.document_revisions",
            combined,
        )

    def test_supersede_conflict_rolls_back_without_event(self):
        (
            document_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_document_repository()

        prepare_snapshot(
            cursor,
            revisions=[revision_record()],
            rowcount=0,
        )

        with self.assertRaisesRegex(
            DocumentRevisionConflictError,
            "changed before",
        ):
            document_repository.create_revision(
                project_id=PROJECT_ID,
                document_type="MERCHANT_AGREEMENT",
                content_hash="sha256:document-revision-two",
                revision_id=REVISION_2_ID,
            )

        self.assertIs(
            transaction_context.exception_type,
            DocumentRevisionConflictError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "INSERT INTO merchant_ops.document_revisions",
            combined,
        )
        self.assertIn(
            "UPDATE merchant_ops.document_revisions",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_terminal_project_rolls_back_before_insert(self):
        for status in ("COMPLETED", "CANCELLED"):
            with self.subTest(status=status):
                (
                    document_repository,
                    _,
                    _,
                    cursor,
                    transaction_context,
                ) = make_document_repository()

                prepare_snapshot(
                    cursor,
                    project=project_record(status=status),
                )

                with self.assertRaises(
                    DocumentLifecycleClosedError
                ):
                    document_repository.create_revision(
                        project_id=PROJECT_ID,
                        document_type=(
                            "MERCHANT_AGREEMENT"
                        ),
                        content_hash=CONTENT_HASH,
                        revision_id=REVISION_1_ID,
                    )

                self.assertIs(
                    transaction_context.exception_type,
                    DocumentLifecycleClosedError,
                )
                combined = "\n".join(
                    executed_sql(cursor)
                )
                self.assertNotIn(
                    "INSERT INTO merchant_ops.document_revisions",
                    combined,
                )
                self.assertNotIn(
                    "INSERT INTO merchant_ops.project_events",
                    combined,
                )

    def test_multiple_active_revisions_roll_back(self):
        (
            document_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_document_repository()

        prepare_snapshot(
            cursor,
            revisions=[
                revision_record(),
                revision_record(
                    revision_id=REVISION_2_ID,
                    revision_number=2,
                ),
            ],
        )

        with self.assertRaises(
            DocumentRevisionConflictError
        ):
            document_repository.create_revision(
                project_id=PROJECT_ID,
                document_type="MERCHANT_AGREEMENT",
                content_hash="sha256:document-revision-three",
            )

        self.assertIs(
            transaction_context.exception_type,
            DocumentRevisionConflictError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "INSERT INTO merchant_ops.document_revisions",
            combined,
        )

    def test_missing_project_rolls_back_before_revision_lock(self):
        (
            document_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_document_repository()

        cursor.fetchone.return_value = None

        with self.assertRaises(ProjectNotFoundError):
            document_repository.create_revision(
                project_id=PROJECT_ID,
                document_type="MERCHANT_AGREEMENT",
                content_hash=CONTENT_HASH,
                revision_id=REVISION_1_ID,
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
            document_repository,
            _,
            _,
            cursor,
            _,
        ) = make_document_repository()

        prepare_snapshot(
            cursor,
            revisions=[revision_record()],
        )

        document_repository.create_revision(
            project_id=PROJECT_ID,
            document_type="MERCHANT_AGREEMENT",
            content_hash="sensitive-content-fingerprint",
            created_by=CREATED_BY,
            revision_id=REVISION_2_ID,
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

        self.assertNotIn(
            "sensitive-content-fingerprint",
            encoded,
        )
        self.assertNotIn("Sensitive project title", encoded)
        self.assertNotIn(REVISION_1_ID, encoded)
        self.assertNotIn(REVISION_2_ID, encoded)
        self.assertEqual(
            parameters[4],
            uuid.UUID(REVISION_2_ID),
        )
        self.assertEqual(
            parameters[8],
            uuid.UUID(CREATED_BY),
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

    def test_result_is_json_compatible(self):
        (
            document_repository,
            _,
            _,
            cursor,
            _,
        ) = make_document_repository()

        prepare_snapshot(cursor)

        result = document_repository.create_revision(
            project_id=PROJECT_ID,
            document_type="MERCHANT_AGREEMENT",
            content_hash=CONTENT_HASH,
            revision_id=REVISION_1_ID,
        )

        payload = result.to_dict()
        self.assertEqual(
            json.loads(json.dumps(payload)),
            payload,
        )
        self.assertEqual(
            payload,
            {
                "project_id": PROJECT_ID,
                "revision_id": REVISION_1_ID,
                "document_type": (
                    "MERCHANT_AGREEMENT"
                ),
                "revision_number": 1,
                "previous_revision_id": None,
                "event_id": result.event_id,
                "event_type": (
                    "DOCUMENT_REVISION_CREATED"
                ),
            },
        )

    def test_invalid_identifier_fails_before_connection(self):
        (
            document_repository,
            repository,
            _,
            _,
            _,
        ) = make_document_repository()

        with self.assertRaises(DocumentPersistenceError):
            document_repository.create_revision(
                project_id="not-a-uuid",
                document_type="MERCHANT_AGREEMENT",
                content_hash=CONTENT_HASH,
            )

        repository.connection.assert_not_called()

    def test_unique_violation_is_translated(self):
        (
            document_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_document_repository()

        prepare_snapshot(cursor)

        def execute(query, parameters=None):
            del parameters
            if (
                "INSERT INTO merchant_ops.document_revisions"
                in query
            ):
                raise errors.UniqueViolation(
                    "duplicate revision"
                )

        cursor.execute.side_effect = execute

        with self.assertRaisesRegex(
            DocumentRevisionConflictError,
            "existing immutable record",
        ):
            document_repository.create_revision(
                project_id=PROJECT_ID,
                document_type="MERCHANT_AGREEMENT",
                content_hash=CONTENT_HASH,
                revision_id=REVISION_1_ID,
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

    def test_event_failure_rolls_back_revision_changes(self):
        (
            document_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_document_repository()

        prepare_snapshot(
            cursor,
            revisions=[revision_record()],
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
            document_repository.create_revision(
                project_id=PROJECT_ID,
                document_type="MERCHANT_AGREEMENT",
                content_hash="sha256:document-revision-two",
                revision_id=REVISION_2_ID,
            )

        self.assertIs(
            transaction_context.exception_type,
            RuntimeError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "INSERT INTO merchant_ops.document_revisions",
            combined,
        )
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
