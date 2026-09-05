"""Opt-in live lifecycle for Merchant project transitions."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from psycopg.rows import dict_row

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
    MerchantRepository,
    RepositoryConfig,
    TEST_DATABASE,
)
from claude.clients.merchant.transition_repository import (
    MerchantProjectTransitionRepository,
)


LIVE_TESTS_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_LIVE_TESTS",
        "",
    ).strip()
    == "1"
)

STARTED_AT = datetime(
    2026,
    9,
    4,
    9,
    0,
    tzinfo=timezone.utc,
)
BLOCKED_AT = STARTED_AT + timedelta(minutes=1)
RESUMED_AT = STARTED_AT + timedelta(minutes=2)
COMPLETED_AT = STARTED_AT + timedelta(minutes=3)
REOPENED_AT = STARTED_AT + timedelta(minutes=4)

SAFE_AUDIT_KEYS = {
    "status",
    "version",
    "started_at",
    "completed_at",
}
SENSITIVE_MARKER = "DO_NOT_AUDIT_PROJECT_TITLE"


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_LIVE_TESTS=1 to run the "
        "Merchant test-database lifecycle"
    ),
)
def test_project_transition_live_lifecycle():
    """Prove start, block, resume, complete, and reopen."""

    config = RepositoryConfig.from_env("test")
    assert config.database == TEST_DATABASE
    assert config.database.endswith("_test")
    assert config.user == "merchant_test"

    repository = MerchantRepository(config)
    transition_repository = (
        MerchantProjectTransitionRepository(repository)
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

        started = transition_repository.transition_project(
            project_id=str(identifiers["project_id"]),
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=STARTED_AT,
        )
        assert started.previous_status == "PLANNED"
        assert started.current_status == "IN_PROGRESS"
        assert started.previous_version == 1
        assert started.current_version == 2
        assert started.event_type == "PROJECT_STARTED"

        state = _project_state(
            repository,
            identifiers["project_id"],
        )
        assert state["status"] == "IN_PROGRESS"
        assert state["version"] == 2
        assert state["started_at"] == STARTED_AT
        assert state["completed_at"] is None
        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 1

        with pytest.raises(
            WorkflowVersionConflictError
        ):
            transition_repository.transition_project(
                project_id=str(
                    identifiers["project_id"]
                ),
                target_status="BLOCKED",
                expected_version=1,
                occurred_at=BLOCKED_AT,
            )

        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 1

        blocked = transition_repository.transition_project(
            project_id=str(identifiers["project_id"]),
            target_status="BLOCKED",
            expected_version=2,
            occurred_at=BLOCKED_AT,
        )
        assert blocked.current_status == "BLOCKED"
        assert blocked.current_version == 3
        assert blocked.event_type == "PROJECT_BLOCKED"

        resumed = transition_repository.transition_project(
            project_id=str(identifiers["project_id"]),
            target_status="IN_PROGRESS",
            expected_version=3,
            occurred_at=RESUMED_AT,
        )
        assert resumed.current_status == "IN_PROGRESS"
        assert resumed.current_version == 4
        assert resumed.event_type == "PROJECT_STARTED"

        with pytest.raises(
            ProjectCompletionBlockedError
        ):
            transition_repository.transition_project(
                project_id=str(
                    identifiers["project_id"]
                ),
                target_status="COMPLETED",
                expected_version=4,
                occurred_at=COMPLETED_AT,
            )

        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 3

        _complete_temporary_step(
            repository,
            identifiers["step_id"],
        )

        completed = (
            transition_repository.transition_project(
                project_id=str(
                    identifiers["project_id"]
                ),
                target_status="COMPLETED",
                expected_version=4,
                occurred_at=COMPLETED_AT,
            )
        )
        assert completed.current_status == "COMPLETED"
        assert completed.current_version == 5
        assert completed.event_type == "PROJECT_COMPLETED"

        completed_state = _project_state(
            repository,
            identifiers["project_id"],
        )
        assert completed_state["status"] == "COMPLETED"
        assert completed_state["version"] == 5
        assert completed_state["started_at"] == STARTED_AT
        assert (
            completed_state["completed_at"]
            == COMPLETED_AT
        )

        with pytest.raises(
            InvalidProjectTransitionError
        ):
            transition_repository.transition_project(
                project_id=str(
                    identifiers["project_id"]
                ),
                target_status="IN_PROGRESS",
                expected_version=5,
                occurred_at=REOPENED_AT,
            )

        assert _event_count(
            repository,
            identifiers["project_id"],
        ) == 4

        reopened = transition_repository.transition_project(
            project_id=str(identifiers["project_id"]),
            target_status="IN_PROGRESS",
            expected_version=5,
            occurred_at=REOPENED_AT,
            allow_reopen=True,
        )
        assert reopened.current_status == "IN_PROGRESS"
        assert reopened.current_version == 6
        assert reopened.event_type == "PROJECT_REOPENED"

        final_state = _project_state(
            repository,
            identifiers["project_id"],
        )
        assert final_state["status"] == "IN_PROGRESS"
        assert final_state["version"] == 6
        assert final_state["started_at"] == STARTED_AT
        assert final_state["completed_at"] is None

        events = _project_events(
            repository,
            identifiers["project_id"],
        )
        assert [
            event["event_type"]
            for event in events
        ] == [
            "PROJECT_STARTED",
            "PROJECT_BLOCKED",
            "PROJECT_STARTED",
            "PROJECT_COMPLETED",
            "PROJECT_REOPENED",
        ]

        for event in events:
            assert event["entity_type"] == "PROJECT"
            assert (
                event["entity_id"]
                == identifiers["project_id"]
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
            assert SENSITIVE_MARKER not in encoded

    finally:
        cleanup_counts = _cleanup_temporary_records(
            repository,
            identifiers,
        )

    assert cleanup_counts == {
        "project_events": 5,
        "project_steps": 1,
        "projects": 1,
        "workflow_template_steps": 1,
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
        "template_step_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "step_id": uuid.uuid4(),
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
        "LIVE_PROJECT_"
        + identifiers["merchant_id"].hex[:12]
    )
    template_name = (
        "LIVE_PROJECT_TRANSITION_"
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
                        "Temporary lifecycle merchant",
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
                        "Temporary lifecycle template",
                        "LIVE_PROJECT_TRANSITION",
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO
                        merchant_ops.workflow_template_steps (
                            id,
                            template_id,
                            sequence_number,
                            step_type,
                            name,
                            is_optional
                        )
                    VALUES (%s, %s, 1, 'SEQUENTIAL', %s, FALSE)
                    """,
                    (
                        identifiers["template_step_id"],
                        identifiers["template_id"],
                        "Temporary lifecycle step",
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
                        version,
                        payment_period_number
                    )
                    VALUES (
                        %s, %s, 'OPENING_NEW_CINEMA',
                        %s, %s, %s, 'PLANNED', FALSE,
                        1, NULL
                    )
                    """,
                    (
                        identifiers["project_id"],
                        identifiers["merchant_id"],
                        "LIVE_PROJECT_TRANSITION",
                        identifiers["template_id"],
                        SENSITIVE_MARKER,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.project_steps (
                        id,
                        project_id,
                        template_step_id,
                        step_name,
                        status,
                        sequence_number,
                        version
                    )
                    VALUES (%s, %s, %s, %s, 'READY', 1, 1)
                    """,
                    (
                        identifiers["step_id"],
                        identifiers["project_id"],
                        identifiers["template_step_id"],
                        "Temporary lifecycle step",
                    ),
                )


def _complete_temporary_step(
    repository,
    step_id,
):
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE merchant_ops.project_steps
                    SET
                        status = 'COMPLETED',
                        actual_start = %s,
                        actual_completion = %s,
                        updated_at = CURRENT_TIMESTAMP,
                        version = version + 1
                    WHERE id = %s
                      AND status = 'READY'
                    """,
                    (
                        STARTED_AT,
                        COMPLETED_AT,
                        step_id,
                    ),
                )
                assert cursor.rowcount == 1


def _project_state(repository, project_id):
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
                        status,
                        version,
                        started_at,
                        completed_at
                    FROM merchant_ops.projects
                    WHERE id = %s
                    """,
                    (project_id,),
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


def _project_events(repository, project_id):
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
                    ORDER BY
                        (new_values ->> 'version')::INTEGER,
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
    targets = (
        (
            "project_events",
            "project_id",
            identifiers["project_id"],
        ),
        (
            "project_steps",
            "project_id",
            identifiers["project_id"],
        ),
        (
            "projects",
            "id",
            identifiers["project_id"],
        ),
        (
            "workflow_template_steps",
            "template_id",
            identifiers["template_id"],
        ),
        (
            "workflow_templates",
            "id",
            identifiers["template_id"],
        ),
        (
            "merchants",
            "id",
            identifiers["merchant_id"],
        ),
    )
    deleted = {}

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                for table, column, value in targets:
                    cursor.execute(
                        (
                            "DELETE FROM merchant_ops."
                            f"{table} WHERE {column} = %s"
                        ),
                        (value,),
                    )
                    deleted[table] = cursor.rowcount

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
                            FROM merchant_ops.project_steps
                            WHERE id = %s
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
                        identifiers["step_id"],
                        identifiers["project_id"],
                    ),
                )
                return cursor.fetchone()["record_count"]
