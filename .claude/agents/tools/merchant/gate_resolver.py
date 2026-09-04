"""Resolve database-verifiable Merchant workflow gates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from claude.agents.tools.merchant.gates import (
    GateValidationResult,
    evaluate_approval_gate,
    evaluate_signing_gate,
)


APPROVAL_GATE_STEP_TYPE = "APPROVAL_GATE"

PARTNER_APPROVAL_STEP_NAME = "RECORD PARTNER APPROVAL"
SIGNING_GATE_STEP_NAME = "VALIDATE SIGNING GATE"

DATABASE_VERIFIABLE_GATE_NAMES = frozenset(
    {
        PARTNER_APPROVAL_STEP_NAME,
        SIGNING_GATE_STEP_NAME,
    }
)


class DatabaseGateResolutionError(ValueError):
    """Raised when stored gate metadata is invalid."""


def normalize_gate_step_name(value: Any) -> str:
    """Normalize a stored workflow step name."""

    if not isinstance(value, str):
        raise DatabaseGateResolutionError(
            "Workflow gate step name must be a string"
        )

    normalized = " ".join(value.strip().upper().split())

    if not normalized:
        raise DatabaseGateResolutionError(
            "Workflow gate step name cannot be empty"
        )

    return normalized


def is_approval_gate(
    step: Mapping[str, Any],
) -> bool:
    """Return whether trusted template metadata marks a gate."""

    return (
        str(step.get("step_type", "")).strip().upper()
        == APPROVAL_GATE_STEP_TYPE
    )


def database_gate_kind(
    step: Mapping[str, Any],
) -> str | None:
    """Return the database-verifiable gate kind, if any."""

    if not is_approval_gate(step):
        return None

    step_name = normalize_gate_step_name(
        step.get("step_name")
    )

    if step_name in DATABASE_VERIFIABLE_GATE_NAMES:
        return step_name

    return None


def resolve_database_gate(
    *,
    step: Mapping[str, Any],
    project: Mapping[str, Any],
    revisions: Sequence[Mapping[str, Any]],
    approvals: Sequence[Mapping[str, Any]],
    procurement_records: Sequence[Mapping[str, Any]],
    document_type: str | None = None,
) -> GateValidationResult | None:
    """Evaluate a gate from persisted project evidence.

    Returns ``None`` for ordinary steps and approval gates that
    do not yet have a structured database-backed evaluator.
    """

    gate_kind = database_gate_kind(step)

    if gate_kind is None:
        return None

    project_id = project.get("id")

    if project_id is None:
        raise DatabaseGateResolutionError(
            "Project id is required for gate resolution"
        )

    if gate_kind == PARTNER_APPROVAL_STEP_NAME:
        return evaluate_approval_gate(
            str(project_id),
            revisions,
            approvals,
            required_roles=("PARTNER",),
            document_type=document_type,
        )

    if gate_kind == SIGNING_GATE_STEP_NAME:
        return evaluate_signing_gate(
            project,
            revisions,
            approvals,
            procurement_records,
            document_type=document_type,
        )

    raise DatabaseGateResolutionError(
        f"Unsupported database gate kind: {gate_kind}"
    )