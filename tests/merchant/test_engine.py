"""Tests for Merchant workflow transition planning."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from claude.agents.tools.merchant.engine import (
    WorkflowDependencyNotMetError,
    WorkflowEngineError,
    WorkflowGateNotMetError,
    WorkflowStepNotFoundError,
    WorkflowVersionConflictError,
    propose_step_transition,
)
from claude.agents.tools.merchant.gates import (
    GateValidationResult,
)
from claude.agents.tools.merchant.state_machine import (
    InvalidStepTransitionError,
)


OCCURRED_AT = datetime(
    2026,
    9,
    4,
    8,
    0,
    tzinfo=timezone.utc,
)
EARLIER = datetime(
    2026,
    9,
    3,
    8,
    0,
    tzinfo=timezone.utc,
)


def step(
    step_id,
    *,
    status="PENDING",
    version=1,
    project_id="project-1",
    actual_start=None,
    actual_completion=None,
    notes=None,
):
    return {
        "id": step_id,
        "project_id": project_id,
        "status": status,
        "version": version,
        "actual_start": actual_start,
        "actual_completion": actual_completion,
        "notes": notes,
    }


def dependency(from_step_id, to_step_id):
    return {
        "from_step_id": from_step_id,
        "to_step_id": to_step_id,
        "dependency_type": "MUST_COMPLETE_BEFORE",
    }


def snapshot(
    steps,
    dependencies=(),
    *,
    project_id="project-1",
    merchant_id="merchant-1",
):
    return {
        "project": {
            "id": project_id,
            "merchant_id": merchant_id,
        },
        "steps": list(steps),
        "dependencies": list(dependencies),
    }


def gate_result(
    *,
    project_id="project-1",
    all_met=True,
    blocking_codes=(),
):
    return GateValidationResult(
        gate_name="TEST_GATE",
        project_id=project_id,
        document_revision_id="revision-1",
        all_met=all_met,
        blocking_codes=tuple(blocking_codes),
        approved_roles=(),
        missing_roles=(),
        requires_procurement=False,
        purchase_request_present=False,
        already_signed=False,
    )


def test_ready_step_can_start():
    plan = propose_step_transition(
        snapshot(
            [
                step(
                    "target",
                    status="READY",
                )
            ]
        ),
        "target",
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert plan.actual_start == OCCURRED_AT
    assert plan.actual_completion is None
    assert plan.new_version == 2
    assert plan.event_type == "STEP_STARTED"


def test_in_progress_step_can_complete():
    plan = propose_step_transition(
        snapshot(
            [
                step(
                    "target",
                    status="IN_PROGRESS",
                    actual_start=EARLIER,
                )
            ]
        ),
        "target",
        "COMPLETED",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert plan.actual_start == EARLIER
    assert plan.actual_completion == OCCURRED_AT
    assert plan.event_type == "STEP_COMPLETED"


def test_blocked_step_can_become_ready_when_dependencies_met():
    plan = propose_step_transition(
        snapshot(
            [
                step(
                    "source",
                    status="COMPLETED",
                    actual_completion=EARLIER,
                ),
                step(
                    "target",
                    status="BLOCKED",
                ),
            ],
            [
                dependency("source", "target"),
            ],
        ),
        "target",
        "READY",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert plan.target_status == "READY"
    assert plan.event_type == "STEP_READY"


def test_unmet_direct_dependency_blocks_ready():
    with pytest.raises(
        WorkflowDependencyNotMetError,
        match="source",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "source",
                        status="IN_PROGRESS",
                    ),
                    step(
                        "target",
                        status="PENDING",
                    ),
                ],
                [
                    dependency(
                        "source",
                        "target",
                    )
                ],
            ),
            "target",
            "READY",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_unmet_transitive_dependency_blocks_completion():
    with pytest.raises(
        WorkflowDependencyNotMetError,
        match="root",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "root",
                        status="IN_PROGRESS",
                    ),
                    step(
                        "middle",
                        status="COMPLETED",
                        actual_completion=EARLIER,
                    ),
                    step(
                        "target",
                        status="IN_PROGRESS",
                        actual_start=EARLIER,
                    ),
                ],
                [
                    dependency("root", "middle"),
                    dependency("middle", "target"),
                ],
            ),
            "target",
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


@pytest.mark.parametrize(
    "source_status",
    (
        "SKIPPED",
        "SUPERSEDED",
    ),
)
def test_noncompleted_terminal_dependency_does_not_satisfy(
    source_status,
):
    with pytest.raises(
        WorkflowDependencyNotMetError
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "source",
                        status=source_status,
                    ),
                    step(
                        "target",
                        status="PENDING",
                    ),
                ],
                [
                    dependency("source", "target"),
                ],
            ),
            "target",
            "READY",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_version_conflict_is_rejected():
    with pytest.raises(
        WorkflowVersionConflictError,
        match="expected 1, current 2",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "target",
                        status="READY",
                        version=2,
                    )
                ]
            ),
            "target",
            "IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


@pytest.mark.parametrize(
    "invalid_version",
    (
        None,
        0,
        -1,
        True,
        "1",
    ),
)
def test_invalid_expected_version_is_rejected(
    invalid_version,
):
    with pytest.raises(
        WorkflowEngineError,
        match="positive integer",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "target",
                        status="READY",
                    )
                ]
            ),
            "target",
            "IN_PROGRESS",
            expected_version=invalid_version,
            occurred_at=OCCURRED_AT,
        )


def test_missing_step_is_rejected():
    with pytest.raises(
        WorkflowStepNotFoundError,
        match="missing",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "known",
                        status="READY",
                    )
                ]
            ),
            "missing",
            "IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_duplicate_snapshot_step_is_rejected():
    with pytest.raises(
        WorkflowEngineError,
        match="duplicate step id",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "duplicate",
                        status="READY",
                    ),
                    step(
                        "duplicate",
                        status="READY",
                    ),
                ]
            ),
            "duplicate",
            "IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_step_from_another_project_is_rejected():
    with pytest.raises(
        WorkflowEngineError,
        match="does not belong",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "target",
                        status="READY",
                        project_id="other-project",
                    )
                ]
            ),
            "target",
            "IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_missing_project_record_is_rejected():
    with pytest.raises(
        WorkflowEngineError,
        match="no project record",
    ):
        propose_step_transition(
            {
                "project": None,
                "steps": [],
                "dependencies": [],
            },
            "target",
            "READY",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_invalid_state_transition_is_rejected():
    with pytest.raises(
        InvalidStepTransitionError
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "target",
                        status="PENDING",
                    )
                ]
            ),
            "target",
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


def test_required_gate_must_be_supplied():
    with pytest.raises(
        WorkflowGateNotMetError,
        match="required",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "target",
                        status="IN_PROGRESS",
                    )
                ]
            ),
            "target",
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            gate_required=True,
        )


def test_failed_gate_blocks_transition():
    with pytest.raises(
        WorkflowGateNotMetError,
        match="MISSING_APPROVAL",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "target",
                        status="IN_PROGRESS",
                    )
                ]
            ),
            "target",
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            gate_required=True,
            gate_result=gate_result(
                all_met=False,
                blocking_codes=(
                    "MISSING_APPROVAL",
                ),
            ),
        )


def test_gate_from_another_project_is_rejected():
    with pytest.raises(
        WorkflowGateNotMetError,
        match="another project",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "target",
                        status="IN_PROGRESS",
                    )
                ]
            ),
            "target",
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            gate_required=True,
            gate_result=gate_result(
                project_id="other-project"
            ),
        )


def test_successful_gate_allows_completion():
    plan = propose_step_transition(
        snapshot(
            [
                step(
                    "target",
                    status="IN_PROGRESS",
                    actual_start=EARLIER,
                )
            ]
        ),
        "target",
        "COMPLETED",
        expected_version=1,
        occurred_at=OCCURRED_AT,
        gate_required=True,
        gate_result=gate_result(),
    )

    assert plan.target_status == "COMPLETED"
    assert plan.actual_completion == OCCURRED_AT


def test_completed_step_reopen_requires_permission():
    source_snapshot = snapshot(
        [
            step(
                "target",
                status="COMPLETED",
                actual_start=EARLIER,
                actual_completion=OCCURRED_AT,
            )
        ]
    )

    with pytest.raises(InvalidStepTransitionError):
        propose_step_transition(
            source_snapshot,
            "target",
            "READY",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )

    plan = propose_step_transition(
        source_snapshot,
        "target",
        "READY",
        expected_version=1,
        occurred_at=OCCURRED_AT,
        allow_reopen=True,
    )

    assert plan.is_reopen
    assert plan.actual_start is None
    assert plan.actual_completion is None
    assert plan.event_type == "STEP_REOPENED"


def test_naive_occurred_at_is_rejected():
    with pytest.raises(
        WorkflowEngineError,
        match="timezone-aware",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "target",
                        status="READY",
                    )
                ]
            ),
            "target",
            "IN_PROGRESS",
            expected_version=1,
            occurred_at=datetime(2026, 9, 4, 8, 0),
        )


def test_naive_existing_timestamp_is_rejected():
    with pytest.raises(
        WorkflowEngineError,
        match="timezone-aware",
    ):
        propose_step_transition(
            snapshot(
                [
                    step(
                        "target",
                        status="IN_PROGRESS",
                        actual_start=datetime(
                            2026,
                            9,
                            3,
                            8,
                            0,
                        ),
                    )
                ]
            ),
            "target",
            "COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )


@pytest.mark.parametrize(
    ("current", "target", "event_type"),
    (
        ("PENDING", "BLOCKED", "STEP_BLOCKED"),
        ("PENDING", "SKIPPED", "STEP_SKIPPED"),
        (
            "PENDING",
            "SUPERSEDED",
            "STEP_SUPERSEDED",
        ),
        ("PENDING", "READY", "STEP_READY"),
        (
            "READY",
            "IN_PROGRESS",
            "STEP_STARTED",
        ),
        (
            "IN_PROGRESS",
            "COMPLETED",
            "STEP_COMPLETED",
        ),
    ),
)
def test_transition_event_types(
    current,
    target,
    event_type,
):
    plan = propose_step_transition(
        snapshot(
            [
                step(
                    "target",
                    status=current,
                    actual_start=(
                        EARLIER
                        if current == "IN_PROGRESS"
                        else None
                    ),
                )
            ]
        ),
        "target",
        target,
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert plan.event_type == event_type


def test_audit_values_only_contain_safe_fields():
    sensitive_notes = "secret partner information"

    plan = propose_step_transition(
        snapshot(
            [
                step(
                    "target",
                    status="READY",
                    notes=sensitive_notes,
                )
            ]
        ),
        "target",
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    encoded = json.dumps(
        {
            "old_values": plan.old_values,
            "new_values": plan.new_values,
        }
    )

    assert sensitive_notes not in encoded
    assert set(plan.old_values) == {
        "status",
        "version",
        "actual_start",
        "actual_completion",
    }
    assert set(plan.new_values) == set(
        plan.old_values
    )


def test_plan_is_json_compatible():
    plan = propose_step_transition(
        snapshot(
            [
                step(
                    "target",
                    status="READY",
                )
            ]
        ),
        "target",
        "IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    decoded = json.loads(
        json.dumps(plan.to_dict())
    )

    assert decoded["new_version"] == 2
    assert decoded["actual_start"] == (
        "2026-09-04T08:00:00+00:00"
    )
    assert decoded["new_values"]["status"] == (
        "IN_PROGRESS"
    )