"""Tests for atomic Merchant project-transition persistence."""

from __future__ import annotations

import json
import uuid
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from claude.agents.tools.merchant.engine import (
    WorkflowVersionConflictError,
)
from claude.agents.tools.merchant.project_engine import (
    ProjectCompletionBlockedError,
)
from claude.agents.tools.merchant.state_machine import (
    InvalidProjectTransitionError,
)
from claude.clients.merchant.repository import (
    ProjectNotFoundError,
)
from claude.clients.merchant.transition_repository import (
    MerchantProjectTransitionRepository,
    ProjectTransitionResult,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
STEP_ID = "00000000-0000-0000-0000-000000000003"
SECOND_STEP_ID = "00000000-0000-0000-0000-000000000004"
TRIGGERED_BY = "00000000-0000-0000-0000-000000000005"

OCCURRED_AT = datetime(
    2026,
    9,
    4,
    9,
    0,
    tzinfo=timezone.utc,
)
EARLIER = datetime(
    2026,
    9,
    4,
    8,
    0,
    tzinfo=timezone.utc,
)


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


def make_transition_repository():
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

    transition_repository = (
        MerchantProjectTransitionRepository(repository)
    )

    return (
        transition_repository,
        repository,
        connection,
        cursor,
        transaction_context,
    )


def project_record(
    *,
    status="PLANNED",
    version=1,
    started_at=None,
    completed_at=None,
):
    return {
        "id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "title": "Sensitive project title",
        "contact_email": "private@example.com",
        "integration_identifier": "secret-mid",
        "status": status,
        "version": version,
        "started_at": started_at,
        "completed_at": completed_at,
    }


def step_record(
    *,
    step_id=STEP_ID,
    status="COMPLETED",
):
    return {
        "id": step_id,
        "project_id": PROJECT_ID,
        "status": status,
    }


def prepare_snapshot(
    cursor,
    *,
    project=None,
    steps=(),
    rowcount=1,
):
    cursor.fetchone.return_value = (
        project
        if project is not None
        else project_record()
    )
    cursor.fetchall.return_value = list(steps)
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


class MerchantProjectTransitionRepositoryTests(
    unittest.TestCase
):
    def test_planned_project_is_started_and_audited(self):
        (
            transition_repository,
            repository,
            connection,
            cursor,
            transaction_context,
        ) = make_transition_repository()

        prepare_snapshot(cursor)

        result = transition_repository.transition_project(
            project_id=PROJECT_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            triggered_by=TRIGGERED_BY,
        )

        self.assertIsInstance(
            result,
            ProjectTransitionResult,
        )
        self.assertEqual(result.project_id, PROJECT_ID)
        self.assertEqual(result.previous_status, "PLANNED")
        self.assertEqual(
            result.current_status,
            "IN_PROGRESS",
        )
        self.assertEqual(result.previous_version, 1)
        self.assertEqual(result.current_version, 2)
        self.assertEqual(
            result.event_type,
            "PROJECT_STARTED",
        )

        repository.connection.assert_called_once_with()
        connection.transaction.assert_called_once_with()
        self.assertTrue(transaction_context.entered)
        self.assertIsNone(
            transaction_context.exception_type
        )

        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "FROM merchant_ops.projects AS project",
            combined,
        )
        self.assertIn("FOR UPDATE OF project", combined)
        self.assertIn(
            "FROM merchant_ops.project_steps AS step",
            combined,
        )
        self.assertIn("FOR UPDATE OF step", combined)
        self.assertEqual(
            combined.count(
                "UPDATE merchant_ops.projects"
            ),
            1,
        )
        self.assertEqual(
            combined.count(
                "INSERT INTO merchant_ops.project_events"
            ),
            1,
        )

    def test_event_is_inserted_after_project_update(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            _,
        ) = make_transition_repository()

        prepare_snapshot(cursor)

        transition_repository.transition_project(
            project_id=PROJECT_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )

        sql = executed_sql(cursor)
        update_index = next(
            index
            for index, query in enumerate(sql)
            if query.startswith(
                "UPDATE merchant_ops.projects"
            )
        )
        event_index = next(
            index
            for index, query in enumerate(sql)
            if query.startswith(
                "INSERT INTO merchant_ops.project_events"
            )
        )

        self.assertEqual(event_index, update_index + 1)
        self.assertEqual(event_index, len(sql) - 1)

    def test_block_and_resume_transitions_are_persisted(self):
        cases = (
            (
                "IN_PROGRESS",
                "BLOCKED",
                "PROJECT_BLOCKED",
            ),
            (
                "BLOCKED",
                "IN_PROGRESS",
                "PROJECT_STARTED",
            ),
            (
                "ON_HOLD",
                "IN_PROGRESS",
                "PROJECT_STARTED",
            ),
        )

        for current, target, event_type in cases:
            with self.subTest(
                current=current,
                target=target,
            ):
                (
                    transition_repository,
                    _,
                    _,
                    cursor,
                    transaction_context,
                ) = make_transition_repository()

                prepare_snapshot(
                    cursor,
                    project=project_record(
                        status=current,
                        started_at=EARLIER,
                    ),
                )

                result = (
                    transition_repository
                    .transition_project(
                        project_id=PROJECT_ID,
                        target_status=target,
                        expected_version=1,
                        occurred_at=OCCURRED_AT,
                    )
                )

                self.assertEqual(
                    result.previous_status,
                    current,
                )
                self.assertEqual(
                    result.current_status,
                    target,
                )
                self.assertEqual(
                    result.event_type,
                    event_type,
                )
                self.assertIsNone(
                    transaction_context.exception_type
                )

    def test_all_terminal_steps_allow_completion(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            _,
        ) = make_transition_repository()

        prepare_snapshot(
            cursor,
            project=project_record(
                status="IN_PROGRESS",
                started_at=EARLIER,
            ),
            steps=[
                step_record(status="COMPLETED"),
                step_record(
                    step_id=SECOND_STEP_ID,
                    status="SKIPPED",
                ),
                step_record(
                    step_id=(
                        "00000000-0000-0000-0000-"
                        "000000000006"
                    ),
                    status="SUPERSEDED",
                ),
            ],
        )

        result = transition_repository.transition_project(
            project_id=PROJECT_ID,
            target_status="COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )

        self.assertEqual(
            result.current_status,
            "COMPLETED",
        )
        self.assertEqual(
            result.event_type,
            "PROJECT_COMPLETED",
        )

        update_call = next(
            call
            for call in cursor.execute.call_args_list
            if "UPDATE merchant_ops.projects"
            in call.args[0]
        )
        self.assertEqual(
            update_call.args[1][2],
            OCCURRED_AT,
        )

    def test_unfinished_step_rolls_back_without_update(self):
        for status in (
            "PENDING",
            "READY",
            "IN_PROGRESS",
            "BLOCKED",
        ):
            with self.subTest(status=status):
                (
                    transition_repository,
                    _,
                    _,
                    cursor,
                    transaction_context,
                ) = make_transition_repository()

                prepare_snapshot(
                    cursor,
                    project=project_record(
                        status="IN_PROGRESS",
                        started_at=EARLIER,
                    ),
                    steps=[step_record(status=status)],
                )

                with self.assertRaises(
                    ProjectCompletionBlockedError
                ):
                    (
                        transition_repository
                        .transition_project(
                            project_id=PROJECT_ID,
                            target_status="COMPLETED",
                            expected_version=1,
                            occurred_at=OCCURRED_AT,
                        )
                    )

                self.assertIs(
                    transaction_context.exception_type,
                    ProjectCompletionBlockedError,
                )
                combined = "\n".join(
                    executed_sql(cursor)
                )
                self.assertNotIn(
                    "UPDATE merchant_ops.projects",
                    combined,
                )
                self.assertNotIn(
                    "INSERT INTO merchant_ops.project_events",
                    combined,
                )

    def test_reopen_requires_explicit_permission(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_transition_repository()

        prepare_snapshot(
            cursor,
            project=project_record(
                status="COMPLETED",
                version=3,
                started_at=EARLIER,
                completed_at=OCCURRED_AT,
            ),
            steps=[step_record()],
        )

        with self.assertRaises(
            InvalidProjectTransitionError
        ):
            transition_repository.transition_project(
                project_id=PROJECT_ID,
                target_status="IN_PROGRESS",
                expected_version=3,
                occurred_at=OCCURRED_AT,
            )

        self.assertIs(
            transaction_context.exception_type,
            InvalidProjectTransitionError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "UPDATE merchant_ops.projects",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_explicit_reopen_clears_completion_timestamp(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            _,
        ) = make_transition_repository()

        prepare_snapshot(
            cursor,
            project=project_record(
                status="COMPLETED",
                version=3,
                started_at=EARLIER,
                completed_at=OCCURRED_AT,
            ),
            steps=[step_record()],
        )

        result = transition_repository.transition_project(
            project_id=PROJECT_ID,
            target_status="IN_PROGRESS",
            expected_version=3,
            occurred_at=OCCURRED_AT,
            allow_reopen=True,
        )

        self.assertEqual(
            result.event_type,
            "PROJECT_REOPENED",
        )
        self.assertEqual(result.current_version, 4)

        update_call = next(
            call
            for call in cursor.execute.call_args_list
            if "UPDATE merchant_ops.projects"
            in call.args[0]
        )
        self.assertIsNone(update_call.args[1][2])

    def test_stale_version_rolls_back_before_update(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_transition_repository()

        prepare_snapshot(
            cursor,
            project=project_record(version=2),
        )

        with self.assertRaises(
            WorkflowVersionConflictError
        ):
            transition_repository.transition_project(
                project_id=PROJECT_ID,
                target_status="IN_PROGRESS",
                expected_version=1,
                occurred_at=OCCURRED_AT,
            )

        self.assertIs(
            transaction_context.exception_type,
            WorkflowVersionConflictError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertNotIn(
            "UPDATE merchant_ops.projects",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_zero_update_rowcount_rolls_back_without_event(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_transition_repository()

        prepare_snapshot(cursor, rowcount=0)

        with self.assertRaisesRegex(
            WorkflowVersionConflictError,
            "changed before",
        ):
            transition_repository.transition_project(
                project_id=PROJECT_ID,
                target_status="IN_PROGRESS",
                expected_version=1,
                occurred_at=OCCURRED_AT,
            )

        self.assertIs(
            transaction_context.exception_type,
            WorkflowVersionConflictError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "UPDATE merchant_ops.projects",
            combined,
        )
        self.assertNotIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )

    def test_project_update_uses_status_and_version_guards(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            _,
        ) = make_transition_repository()

        prepare_snapshot(cursor)

        transition_repository.transition_project(
            project_id=PROJECT_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )

        update_call = next(
            call
            for call in cursor.execute.call_args_list
            if "UPDATE merchant_ops.projects"
            in call.args[0]
        )
        sql = " ".join(update_call.args[0].split())
        parameters = update_call.args[1]

        self.assertIn("AND merchant_id = %s", sql)
        self.assertIn("AND status = %s", sql)
        self.assertIn("AND version = %s", sql)
        self.assertEqual(parameters[-2], "PLANNED")
        self.assertEqual(parameters[-1], 1)

    def test_audit_payload_contains_only_safe_fields(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            _,
        ) = make_transition_repository()

        prepare_snapshot(cursor)

        transition_repository.transition_project(
            project_id=PROJECT_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            triggered_by=TRIGGERED_BY,
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

        safe_keys = {
            "status",
            "version",
            "started_at",
            "completed_at",
        }
        self.assertEqual(set(old_values), safe_keys)
        self.assertEqual(set(new_values), safe_keys)
        self.assertNotIn("Sensitive project title", encoded)
        self.assertNotIn("private@example.com", encoded)
        self.assertNotIn("secret-mid", encoded)
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
        self.assertIn("'PROJECT'", event_sql)
        self.assertEqual(
            parameters[4],
            uuid.UUID(PROJECT_ID),
        )

    def test_result_is_json_compatible(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            _,
        ) = make_transition_repository()

        prepare_snapshot(cursor)

        result = transition_repository.transition_project(
            project_id=PROJECT_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
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
                "previous_status": "PLANNED",
                "current_status": "IN_PROGRESS",
                "previous_version": 1,
                "current_version": 2,
                "event_id": result.event_id,
                "event_type": "PROJECT_STARTED",
            },
        )

    def test_missing_project_rolls_back_before_step_lock(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_transition_repository()

        cursor.fetchone.return_value = None

        with self.assertRaises(ProjectNotFoundError):
            transition_repository.transition_project(
                project_id=PROJECT_ID,
                target_status="IN_PROGRESS",
                expected_version=1,
                occurred_at=OCCURRED_AT,
            )

        self.assertIs(
            transaction_context.exception_type,
            ProjectNotFoundError,
        )
        self.assertEqual(
            len(cursor.execute.call_args_list),
            1,
        )

    def test_event_failure_rolls_back_project_update(self):
        (
            transition_repository,
            _,
            _,
            cursor,
            transaction_context,
        ) = make_transition_repository()

        prepare_snapshot(cursor)

        def execute(query, parameters):
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
            transition_repository.transition_project(
                project_id=PROJECT_ID,
                target_status="IN_PROGRESS",
                expected_version=1,
                occurred_at=OCCURRED_AT,
            )

        self.assertIs(
            transaction_context.exception_type,
            RuntimeError,
        )
        combined = "\n".join(executed_sql(cursor))
        self.assertIn(
            "UPDATE merchant_ops.projects",
            combined,
        )
        self.assertIn(
            "INSERT INTO merchant_ops.project_events",
            combined,
        )


if __name__ == "__main__":
    unittest.main()
