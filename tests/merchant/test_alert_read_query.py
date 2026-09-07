"""Checkpoint 8.3 bounded repository and alert filter tests."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from claude.agents.tools.merchant.checker import ProjectAlert
from claude.agents.tools.merchant.read_commands import (
    MerchantReadCommands,
)
from claude.clients.merchant.read_repository import (
    DEFAULT_ALERT_PROJECT_LIMIT,
    MAX_ALERT_PROJECT_LIMIT,
    AlertCandidateLimitExceededError,
    MerchantReadRepository,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
    TEST_DATABASE,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
SECOND_PROJECT_ID = "00000000-0000-0000-0000-000000000002"
MERCHANT_ID = "00000000-0000-0000-0000-000000000003"
STEP_ID = "00000000-0000-0000-0000-000000000004"


def make_sql_repository():
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    connection.cursor.return_value.__exit__.return_value = None
    connection.transaction.return_value.__enter__.return_value = None
    connection.transaction.return_value.__exit__.return_value = None
    base = MerchantRepository(
        config=RepositoryConfig(
            host="127.0.0.1",
            port=5434,
            database=TEST_DATABASE,
            user="merchant_test",
            password="test-secret",
        ),
        connect_fn=MagicMock(),
    )
    connection_modes = []

    @contextmanager
    def fake_connection(*, read_only=False):
        connection_modes.append(read_only)
        yield connection

    base.connection = fake_connection
    return (
        MerchantReadRepository(base),
        connection,
        cursor,
        connection_modes,
    )


def test_candidate_query_is_bounded_read_only_and_parameterized():
    repository, connection, cursor, modes = make_sql_repository()
    cursor.fetchall.return_value = [
        {"id": uuid.UUID(PROJECT_ID)},
        {"id": uuid.UUID(SECOND_PROJECT_ID)},
    ]

    result = repository.list_alert_candidate_project_ids(
        merchant_id=MERCHANT_ID,
        project_id=PROJECT_ID,
    )

    assert result == [PROJECT_ID, SECOND_PROJECT_ID]
    assert modes == [True]
    query, parameters = cursor.execute.call_args.args
    assert "status NOT IN ('COMPLETED', 'CANCELLED')" in query
    assert "ORDER BY project.created_at, project.id" in query
    assert "LIMIT %s" in query
    assert PROJECT_ID not in query
    assert MERCHANT_ID not in query
    merchant_uuid = uuid.UUID(MERCHANT_ID)
    project_uuid = uuid.UUID(PROJECT_ID)
    assert parameters == (
        merchant_uuid,
        merchant_uuid,
        project_uuid,
        project_uuid,
        DEFAULT_ALERT_PROJECT_LIMIT + 1,
    )
    assert connection.transaction.call_count == 1


def test_unfiltered_candidate_query_still_has_hard_bound():
    repository, connection, cursor, modes = make_sql_repository()
    cursor.fetchall.return_value = []

    assert repository.list_alert_candidate_project_ids() == []

    _, parameters = cursor.execute.call_args.args
    assert parameters == (
        None,
        None,
        None,
        None,
        DEFAULT_ALERT_PROJECT_LIMIT + 1,
    )
    assert modes == [True]


def test_candidate_overflow_fails_instead_of_truncating():
    repository, connection, cursor, modes = make_sql_repository()
    cursor.fetchall.return_value = [
        {"id": uuid.UUID(PROJECT_ID)},
        {"id": uuid.UUID(SECOND_PROJECT_ID)},
    ]

    with pytest.raises(
        AlertCandidateLimitExceededError,
        match="provide merchant_id or project_id",
    ):
        repository.list_alert_candidate_project_ids(limit=1)

    _, parameters = cursor.execute.call_args.args
    assert parameters[-1] == 2
    assert modes == [True]


@pytest.mark.parametrize(
    ("arguments", "message"),
    (
        ({"merchant_id": "not-a-uuid"}, "merchant_id"),
        ({"project_id": "not-a-uuid"}, "project_id"),
        ({"limit": 0}, "project_limit must be between"),
        (
            {"limit": MAX_ALERT_PROJECT_LIMIT + 1},
            "project_limit must be between",
        ),
        ({"limit": True}, "project_limit must be an integer"),
        ({"limit": "100"}, "project_limit must be an integer"),
    ),
)
def test_invalid_candidate_filters_fail_before_database_access(
    arguments,
    message,
):
    repository, connection, cursor, modes = make_sql_repository()

    with pytest.raises(ValueError, match=message):
        repository.list_alert_candidate_project_ids(**arguments)

    assert modes == []
    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()


class FakeGlobalRepository:
    def __init__(self):
        self.calls = []
        self.details = {
            PROJECT_ID: {"project": {"id": PROJECT_ID}},
            SECOND_PROJECT_ID: {
                "project": {"id": SECOND_PROJECT_ID}
            },
        }

    def list_alert_candidate_project_ids(
        self,
        *,
        merchant_id=None,
        project_id=None,
        limit=DEFAULT_ALERT_PROJECT_LIMIT,
    ):
        self.calls.append(
            (
                "candidates",
                merchant_id,
                project_id,
                limit,
            )
        )

        if project_id is not None:
            return [project_id]

        return [PROJECT_ID, SECOND_PROJECT_ID]

    def get_project_detail(self, project_id):
        self.calls.append(("detail", project_id))
        return self.details[project_id]


class FakeGlobalChecker:
    def __init__(self):
        self.calls = []

    def check_snapshot(self, snapshot, *, business_date=None):
        project_id = snapshot["project"]["id"]
        self.calls.append((project_id, business_date))

        if project_id == PROJECT_ID:
            return [
                ProjectAlert(
                    project_id=project_id,
                    project_step_id=STEP_ID,
                    branch_key="document_branch",
                    step_name="Overdue document",
                    alert_type="OVERDUE",
                    severity="CRITICAL",
                    business_due_date=date(2026, 9, 5),
                    message="Document is overdue.",
                ),
                ProjectAlert(
                    project_id=project_id,
                    project_step_id=STEP_ID,
                    branch_key="document_branch",
                    step_name="Approval gate",
                    alert_type="MISSING_GATE",
                    severity="HIGH",
                    condition_fingerprint="gate:partner",
                    message="Partner approval is missing.",
                ),
            ]

        return [
            ProjectAlert(
                project_id=project_id,
                project_step_id=STEP_ID,
                branch_key="uat_branch",
                step_name="UAT",
                alert_type="DUE_SOON",
                severity="MEDIUM",
                business_due_date=date(2026, 9, 12),
                message="UAT is due soon.",
            )
        ]


def make_commands():
    repository = FakeGlobalRepository()
    checker = FakeGlobalChecker()
    commands = MerchantReadCommands(repository, checker=checker)
    return commands, repository, checker


def test_global_alert_query_reads_every_candidate_in_order():
    commands, repository, checker = make_commands()
    business_date = date(2026, 9, 7)

    result = commands.project_alerts(
        business_date=business_date,
    )

    assert [row["project_id"] for row in result] == [
        PROJECT_ID,
        PROJECT_ID,
        SECOND_PROJECT_ID,
    ]
    assert repository.calls == [
        ("candidates", None, None, DEFAULT_ALERT_PROJECT_LIMIT),
        ("detail", PROJECT_ID),
        ("detail", SECOND_PROJECT_ID),
    ]
    assert checker.calls == [
        (PROJECT_ID, business_date),
        (SECOND_PROJECT_ID, business_date),
    ]


def test_merchant_project_and_limit_filters_are_forwarded():
    commands, repository, checker = make_commands()

    commands.project_alerts(
        project_id=PROJECT_ID,
        merchant_id=MERCHANT_ID,
        project_limit=25,
    )

    assert repository.calls[0] == (
        "candidates",
        MERCHANT_ID,
        PROJECT_ID,
        25,
    )
    assert checker.calls == [(PROJECT_ID, None)]


def test_alert_type_filter_is_normalized():
    commands, repository, checker = make_commands()

    result = commands.project_alerts(alert_type=" due_soon ")

    assert [row["alert_type"] for row in result] == ["DUE_SOON"]
    assert len(checker.calls) == 2


def test_due_date_filter_excludes_conditions_without_deadline():
    commands, repository, checker = make_commands()

    result = commands.project_alerts(
        due_date_before=date(2026, 9, 7),
    )

    assert [row["alert_type"] for row in result] == ["OVERDUE"]
    assert result[0]["business_due_date"] == "2026-09-05"


@pytest.mark.parametrize(
    ("arguments", "message"),
    (
        ({"alert_type": "UNKNOWN"}, "alert_type must be one of"),
        ({"alert_type": False}, "alert_type must be one of"),
        ({"due_date_before": "2026-09-07"}, "must be a date"),
        (
            {"due_date_before": datetime(2026, 9, 7, 12, 0)},
            "must be a date",
        ),
    ),
)
def test_invalid_derived_filters_fail_before_repository_access(
    arguments,
    message,
):
    commands, repository, checker = make_commands()

    with pytest.raises(ValueError, match=message):
        commands.project_alerts(**arguments)

    assert repository.calls == []
    assert checker.calls == []


def test_empty_candidate_set_performs_no_detail_reads():
    commands, repository, checker = make_commands()
    repository.list_alert_candidate_project_ids = MagicMock(
        return_value=[]
    )

    assert commands.project_alerts() == []
    repository.list_alert_candidate_project_ids.assert_called_once_with(
        merchant_id=None,
        project_id=None,
        limit=DEFAULT_ALERT_PROJECT_LIMIT,
    )
    assert checker.calls == []
