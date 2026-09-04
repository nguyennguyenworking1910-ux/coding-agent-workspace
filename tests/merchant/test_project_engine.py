"""Tests for pure Merchant project-transition planning."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from claude.agents.tools.merchant.engine import (
    WorkflowVersionConflictError,
)
from claude.agents.tools.merchant.project_engine import (
    ProjectCompletionBlockedError,
    ProjectEngineError,
    ProjectTransitionPlan,
    propose_project_transition,
)
from claude.agents.tools.merchant.state_machine import (
    InvalidProjectTransitionError,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
STEP_ID = "00000000-0000-0000-0000-000000000003"
SECOND_STEP_ID = "00000000-0000-0000-0000-000000000004"

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
        "status": status,
        "version": version,
        "started_at": started_at,
        "completed_at": completed_at,
    }


def step_record(
    *,
    step_id=STEP_ID,
    project_id=PROJECT_ID,
    status="COMPLETED",
):
    return {
        "id": step_id,
        "project_id": project_id,
        "status": status,
    }


def snapshot(
    *,
    project=None,
    steps=(),
):
    return {
        "project": (
            project
            if project is not None
            else project_record()
        ),
        "steps": list(steps),
    }


def test_planned_project_starts():
    plan = propose_project_transition(
        snapshot(),
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert isinstance(plan, ProjectTransitionPlan)
    assert plan.merchant_id == MERCHANT_ID
    assert plan.project_id == PROJECT_ID
    assert plan.current_status == "PLANNED"
    assert plan.target_status == "IN_PROGRESS"
    assert plan.expected_version == 1
    assert plan.new_version == 2
    assert plan.started_at == OCCURRED_AT
    assert plan.completed_at is None
    assert not plan.is_reopen
    assert plan.event_type == "PROJECT_STARTED"


def test_existing_started_at_is_preserved():
    plan = propose_project_transition(
        snapshot(
            project=project_record(
                status="PLANNED",
                started_at=EARLIER,
            )
        ),
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert plan.started_at == EARLIER


def test_naive_occurred_at_is_interpreted_as_utc():
    naive = datetime(2026, 9, 4, 9, 0)

    plan = propose_project_transition(
        snapshot(),
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=naive,
    )

    assert plan.started_at == OCCURRED_AT
    assert plan.started_at.tzinfo == timezone.utc


def test_occurred_at_is_normalized_to_utc():
    local_timezone = timezone(timedelta(hours=7))
    local_time = datetime(
        2026,
        9,
        4,
        16,
        0,
        tzinfo=local_timezone,
    )

    plan = propose_project_transition(
        snapshot(),
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=local_time,
    )

    assert plan.started_at == OCCURRED_AT


def test_missing_project_record_is_rejected():
    with pytest.raises(
        ProjectEngineError,
        match="no project record",
    ):
        propose_project_transition(
            {"project": None, "steps": []},
            "IN_PROGRESS",
            expected_version=1,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", None),
        ("id", "  "),
        ("merchant_id", None),
        ("merchant_id", ""),
    ],
)
def test_required_project_identifiers_are_validated(
    field,
    value,
):
    project = project_record()
    project[field] = value

    with pytest.raises(ProjectEngineError):
        propose_project_transition(
            snapshot(project=project),
            "IN_PROGRESS",
            expected_version=1,
        )


@pytest.mark.parametrize(
    "version",
    [None, 0, -1, True, "1"],
)
def test_invalid_project_version_is_rejected(version):
    with pytest.raises(
        ProjectEngineError,
        match="project.version must be a positive integer",
    ):
        propose_project_transition(
            snapshot(
                project=project_record(version=version)
            ),
            "IN_PROGRESS",
            expected_version=1,
        )


@pytest.mark.parametrize(
    "expected_version",
    [None, 0, -1, True, "1"],
)
def test_invalid_expected_version_is_rejected(
    expected_version,
):
    with pytest.raises(
        ProjectEngineError,
        match="expected_version must be a positive integer",
    ):
        propose_project_transition(
            snapshot(),
            "IN_PROGRESS",
            expected_version=expected_version,
        )


def test_stale_expected_version_is_rejected():
    with pytest.raises(
        WorkflowVersionConflictError,
        match="expected 1, current 2",
    ):
        propose_project_transition(
            snapshot(
                project=project_record(version=2)
            ),
            "IN_PROGRESS",
            expected_version=1,
        )


def test_same_status_transition_is_rejected():
    with pytest.raises(InvalidProjectTransitionError):
        propose_project_transition(
            snapshot(),
            "PLANNED",
            expected_version=1,
        )


@pytest.mark.parametrize(
    ("target_status", "event_type"),
    [
        ("BLOCKED", "PROJECT_BLOCKED"),
        ("ON_HOLD", "PROJECT_ON_HOLD"),
        ("CANCELLED", "PROJECT_CANCELLED"),
    ],
)
def test_active_project_status_event_types(
    target_status,
    event_type,
):
    plan = propose_project_transition(
        snapshot(
            project=project_record(
                status="IN_PROGRESS",
                started_at=EARLIER,
            )
        ),
        target_status,
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert plan.target_status == target_status
    assert plan.event_type == event_type
    assert plan.started_at == EARLIER
    assert plan.completed_at is None


def test_project_cannot_complete_without_steps():
    with pytest.raises(
        ProjectCompletionBlockedError,
        match="without workflow steps",
    ):
        propose_project_transition(
            snapshot(
                project=project_record(
                    status="IN_PROGRESS",
                    started_at=EARLIER,
                )
            ),
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


@pytest.mark.parametrize(
    "unfinished_status",
    ["PENDING", "READY", "IN_PROGRESS", "BLOCKED"],
)
def test_unfinished_step_blocks_project_completion(
    unfinished_status,
):
    with pytest.raises(
        ProjectCompletionBlockedError,
        match=STEP_ID,
    ):
        propose_project_transition(
            snapshot(
                project=project_record(
                    status="IN_PROGRESS",
                    started_at=EARLIER,
                ),
                steps=[
                    step_record(status=unfinished_status)
                ],
            ),
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_unfinished_step_ids_are_reported_stably():
    with pytest.raises(
        ProjectCompletionBlockedError,
    ) as captured:
        propose_project_transition(
            snapshot(
                project=project_record(
                    status="IN_PROGRESS",
                    started_at=EARLIER,
                ),
                steps=[
                    step_record(
                        step_id=SECOND_STEP_ID,
                        status="READY",
                    ),
                    step_record(
                        step_id=STEP_ID,
                        status="PENDING",
                    ),
                ],
            ),
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )

    message = str(captured.value)
    assert message.index(STEP_ID) < message.index(
        SECOND_STEP_ID
    )


def test_foreign_project_step_is_rejected():
    with pytest.raises(
        ProjectEngineError,
        match="step from another project",
    ):
        propose_project_transition(
            snapshot(
                project=project_record(
                    status="IN_PROGRESS",
                    started_at=EARLIER,
                ),
                steps=[
                    step_record(
                        project_id="another-project",
                    )
                ],
            ),
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_terminal_step_statuses_allow_completion():
    plan = propose_project_transition(
        snapshot(
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
                        "000000000005"
                    ),
                    status="SUPERSEDED",
                ),
            ],
        ),
        "COMPLETED",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert plan.current_status == "IN_PROGRESS"
    assert plan.target_status == "COMPLETED"
    assert plan.started_at == EARLIER
    assert plan.completed_at == OCCURRED_AT
    assert plan.new_version == 2
    assert plan.event_type == "PROJECT_COMPLETED"


def test_completion_audit_values_are_safe_and_complete():
    plan = propose_project_transition(
        snapshot(
            project=project_record(
                status="IN_PROGRESS",
                started_at=EARLIER,
            ),
            steps=[step_record()],
        ),
        "COMPLETED",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert plan.old_values == {
        "status": "IN_PROGRESS",
        "version": 1,
        "started_at": EARLIER.isoformat(),
        "completed_at": None,
    }
    assert plan.new_values == {
        "status": "COMPLETED",
        "version": 2,
        "started_at": EARLIER.isoformat(),
        "completed_at": OCCURRED_AT.isoformat(),
    }

    serialized_values = json.dumps(
        {
            "old_values": plan.old_values,
            "new_values": plan.new_values,
        }
    )

    assert "Sensitive project title" not in serialized_values
    assert "title" not in serialized_values


def test_completed_project_reopen_requires_explicit_flag():
    with pytest.raises(InvalidProjectTransitionError):
        propose_project_transition(
            snapshot(
                project=project_record(
                    status="COMPLETED",
                    started_at=EARLIER,
                    completed_at=OCCURRED_AT,
                )
            ),
            "IN_PROGRESS",
            expected_version=1,
        )


def test_explicit_reopen_clears_completion_timestamp():
    plan = propose_project_transition(
        snapshot(
            project=project_record(
                status="COMPLETED",
                started_at=EARLIER,
                completed_at=OCCURRED_AT,
            )
        ),
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=(
            OCCURRED_AT + timedelta(hours=1)
        ),
        allow_reopen=True,
    )

    assert plan.current_status == "COMPLETED"
    assert plan.target_status == "IN_PROGRESS"
    assert plan.is_reopen
    assert plan.event_type == "PROJECT_REOPENED"
    assert plan.started_at == EARLIER
    assert plan.completed_at is None
    assert plan.old_values["completed_at"] == (
        OCCURRED_AT.isoformat()
    )
    assert plan.new_values["completed_at"] is None


def test_invalid_datetime_fields_are_rejected():
    with pytest.raises(
        ProjectEngineError,
        match="project.started_at must be a datetime or None",
    ):
        propose_project_transition(
            snapshot(
                project=project_record(
                    started_at="2026-09-04",
                )
            ),
            "IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_invalid_occurred_at_is_rejected():
    with pytest.raises(
        ProjectEngineError,
        match="occurred_at must be a datetime",
    ):
        propose_project_transition(
            snapshot(),
            "IN_PROGRESS",
            expected_version=1,
            occurred_at="2026-09-04",
        )


def test_transition_plan_is_frozen():
    plan = propose_project_transition(
        snapshot(),
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    with pytest.raises(FrozenInstanceError):
        plan.target_status = "BLOCKED"


def test_transition_plan_to_dict_is_json_compatible():
    plan = propose_project_transition(
        snapshot(),
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    payload = plan.to_dict()
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)

    assert decoded["project_id"] == PROJECT_ID
    assert decoded["target_status"] == "IN_PROGRESS"
    assert decoded["started_at"] == OCCURRED_AT.isoformat()
    assert decoded["completed_at"] is None