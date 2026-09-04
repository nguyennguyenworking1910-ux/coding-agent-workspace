"""Tests for Merchant workflow state transitions."""

from __future__ import annotations

import json

import pytest

from claude.agents.tools.merchant.state_machine import (
    PROJECT_REOPEN_TRANSITIONS,
    PROJECT_STATUSES,
    PROJECT_TRANSITIONS,
    STEP_REOPEN_TRANSITIONS,
    STEP_STATUSES,
    STEP_TRANSITIONS,
    InvalidProjectTransitionError,
    InvalidStepTransitionError,
    UnknownProjectStatusError,
    UnknownStepStatusError,
    can_transition_project,
    can_transition_step,
    normalize_project_status,
    normalize_step_status,
    validate_project_transition,
    validate_step_transition,
)


PROJECT_ALLOWED_TRANSITIONS = (
    ("PLANNED", "IN_PROGRESS"),
    ("PLANNED", "CANCELLED"),
    ("IN_PROGRESS", "BLOCKED"),
    ("IN_PROGRESS", "ON_HOLD"),
    ("IN_PROGRESS", "COMPLETED"),
    ("IN_PROGRESS", "CANCELLED"),
    ("BLOCKED", "IN_PROGRESS"),
    ("BLOCKED", "ON_HOLD"),
    ("BLOCKED", "CANCELLED"),
    ("ON_HOLD", "IN_PROGRESS"),
    ("ON_HOLD", "CANCELLED"),
)

STEP_ALLOWED_TRANSITIONS = (
    ("PENDING", "READY"),
    ("PENDING", "BLOCKED"),
    ("PENDING", "SKIPPED"),
    ("PENDING", "SUPERSEDED"),
    ("READY", "IN_PROGRESS"),
    ("READY", "BLOCKED"),
    ("READY", "SKIPPED"),
    ("READY", "SUPERSEDED"),
    ("IN_PROGRESS", "BLOCKED"),
    ("IN_PROGRESS", "COMPLETED"),
    ("IN_PROGRESS", "SUPERSEDED"),
    ("BLOCKED", "READY"),
    ("BLOCKED", "SUPERSEDED"),
    ("COMPLETED", "SUPERSEDED"),
)


def test_project_status_set_matches_database_contract():
    assert PROJECT_STATUSES == {
        "PLANNED",
        "IN_PROGRESS",
        "BLOCKED",
        "ON_HOLD",
        "COMPLETED",
        "CANCELLED",
    }


def test_step_status_set_matches_database_contract():
    assert STEP_STATUSES == {
        "PENDING",
        "READY",
        "IN_PROGRESS",
        "BLOCKED",
        "COMPLETED",
        "SKIPPED",
        "SUPERSEDED",
    }


def test_project_transition_map_is_complete():
    flattened = {
        (current, target)
        for current, targets in PROJECT_TRANSITIONS.items()
        for target in targets
    }

    assert flattened == set(PROJECT_ALLOWED_TRANSITIONS)
    assert set(PROJECT_TRANSITIONS) == PROJECT_STATUSES


def test_step_transition_map_is_complete():
    flattened = {
        (current, target)
        for current, targets in STEP_TRANSITIONS.items()
        for target in targets
    }

    assert flattened == set(STEP_ALLOWED_TRANSITIONS)
    assert set(STEP_TRANSITIONS) == STEP_STATUSES


@pytest.mark.parametrize(
    ("current", "target"),
    PROJECT_ALLOWED_TRANSITIONS,
)
def test_every_normal_project_transition_is_allowed(
    current,
    target,
):
    assert can_transition_project(current, target)

    decision = validate_project_transition(
        current,
        target,
    )

    assert decision.entity_type == "PROJECT"
    assert decision.current_status == current
    assert decision.target_status == target
    assert not decision.is_reopen


@pytest.mark.parametrize(
    ("current", "target"),
    STEP_ALLOWED_TRANSITIONS,
)
def test_every_normal_step_transition_is_allowed(
    current,
    target,
):
    assert can_transition_step(current, target)

    decision = validate_step_transition(
        current,
        target,
    )

    assert decision.entity_type == "STEP"
    assert decision.current_status == current
    assert decision.target_status == target
    assert not decision.is_reopen


def test_all_unlisted_project_transitions_are_rejected():
    allowed = set(PROJECT_ALLOWED_TRANSITIONS)

    for current in PROJECT_STATUSES:
        for target in PROJECT_STATUSES:
            if (current, target) in allowed:
                continue

            assert not can_transition_project(
                current,
                target,
            )

            with pytest.raises(
                InvalidProjectTransitionError
            ):
                validate_project_transition(
                    current,
                    target,
                )


def test_all_unlisted_step_transitions_are_rejected():
    allowed = set(STEP_ALLOWED_TRANSITIONS)

    for current in STEP_STATUSES:
        for target in STEP_STATUSES:
            if (current, target) in allowed:
                continue

            assert not can_transition_step(
                current,
                target,
            )

            with pytest.raises(
                InvalidStepTransitionError
            ):
                validate_step_transition(
                    current,
                    target,
                )


@pytest.mark.parametrize(
    ("current", "target"),
    (
        ("COMPLETED", "READY"),
        ("SKIPPED", "READY"),
    ),
)
def test_step_reopen_requires_explicit_permission(
    current,
    target,
):
    assert (current, target) in STEP_REOPEN_TRANSITIONS

    assert not can_transition_step(current, target)

    with pytest.raises(InvalidStepTransitionError):
        validate_step_transition(current, target)

    assert can_transition_step(
        current,
        target,
        allow_reopen=True,
    )

    decision = validate_step_transition(
        current,
        target,
        allow_reopen=True,
    )

    assert decision.is_reopen
    assert decision.clears_actual_completion


def test_project_reopen_requires_explicit_permission():
    transition = ("COMPLETED", "IN_PROGRESS")

    assert transition in PROJECT_REOPEN_TRANSITIONS
    assert not can_transition_project(*transition)

    with pytest.raises(InvalidProjectTransitionError):
        validate_project_transition(*transition)

    assert can_transition_project(
        *transition,
        allow_reopen=True,
    )

    decision = validate_project_transition(
        *transition,
        allow_reopen=True,
    )

    assert decision.is_reopen
    assert decision.clears_actual_completion


def test_superseded_step_cannot_be_reopened():
    for target in STEP_STATUSES:
        assert not can_transition_step(
            "SUPERSEDED",
            target,
            allow_reopen=True,
        )


def test_cancelled_project_cannot_be_reopened():
    for target in PROJECT_STATUSES:
        assert not can_transition_project(
            "CANCELLED",
            target,
            allow_reopen=True,
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("planned", "PLANNED"),
        (" in_progress ", "IN_PROGRESS"),
        ("Blocked", "BLOCKED"),
    ),
)
def test_project_status_normalization(value, expected):
    assert normalize_project_status(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("pending", "PENDING"),
        (" ready ", "READY"),
        ("In_Progress", "IN_PROGRESS"),
    ),
)
def test_step_status_normalization(value, expected):
    assert normalize_step_status(value) == expected


@pytest.mark.parametrize(
    "value",
    (
        "",
        "UNKNOWN",
        "READY",
    ),
)
def test_unknown_project_status_is_rejected(value):
    with pytest.raises(UnknownProjectStatusError):
        normalize_project_status(value)


@pytest.mark.parametrize(
    "value",
    (
        "",
        "UNKNOWN",
        "ON_HOLD",
    ),
)
def test_unknown_step_status_is_rejected(value):
    with pytest.raises(UnknownStepStatusError):
        normalize_step_status(value)


def test_non_string_status_is_rejected():
    with pytest.raises(UnknownProjectStatusError):
        normalize_project_status(None)

    with pytest.raises(UnknownStepStatusError):
        normalize_step_status(123)


def test_same_project_status_is_not_a_transition():
    assert not can_transition_project(
        "IN_PROGRESS",
        "IN_PROGRESS",
    )

    with pytest.raises(
        InvalidProjectTransitionError,
        match="no state change requested",
    ):
        validate_project_transition(
            "IN_PROGRESS",
            "IN_PROGRESS",
        )


def test_same_step_status_is_not_a_transition():
    assert not can_transition_step("READY", "READY")

    with pytest.raises(
        InvalidStepTransitionError,
        match="no state change requested",
    ):
        validate_step_transition("READY", "READY")


def test_step_start_requires_actual_start():
    decision = validate_step_transition(
        "READY",
        "IN_PROGRESS",
    )

    assert decision.requires_actual_start
    assert not decision.requires_actual_completion
    assert not decision.clears_actual_completion


def test_step_completion_requires_actual_completion():
    decision = validate_step_transition(
        "IN_PROGRESS",
        "COMPLETED",
    )

    assert not decision.requires_actual_start
    assert decision.requires_actual_completion
    assert not decision.clears_actual_completion


def test_project_completion_requires_completion_timestamp():
    decision = validate_project_transition(
        "IN_PROGRESS",
        "COMPLETED",
    )

    assert decision.requires_actual_completion


def test_transition_decision_is_json_compatible():
    decision = validate_step_transition(
        "READY",
        "IN_PROGRESS",
    )

    encoded = json.dumps(decision.to_dict())
    decoded = json.loads(encoded)

    assert decoded == {
        "entity_type": "STEP",
        "current_status": "READY",
        "target_status": "IN_PROGRESS",
        "is_reopen": False,
        "requires_actual_start": True,
        "requires_actual_completion": False,
        "clears_actual_completion": False,
    }