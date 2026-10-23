"""Bounded, side-effect-free diagnostic event contract.

No filesystem writes, external calls, or business state mutations.
"""

from __future__ import annotations

import json
import re
from typing import Any

SCHEMA_VERSION = 1

EVENT_TYPES = frozenset({
    "merchant.execution",
    "merchant.recovery",
    "merchant.completion",
    "merchant.report",
    "merchant.archive",
})

STAGES = frozenset({
    "reservation",
    "execution",
    "evidence_verification",
    "state_persistence",
    "completion_receipt",
    "report_transition",
    "archive_transition",
    "idle_release",
})

OUTCOMES = frozenset({
    "started",
    "verified",
    "completed",
    "blocked",
    "failed",
})

ERROR_CODES = frozenset({
    "INVALID_IDENTITY",
    "AUTHORITY_DENIED",
    "STATE_MISMATCH",
    "EVIDENCE_MISSING",
    "EVIDENCE_INVALID",
    "GENERATION_MISMATCH",
    "PERSISTENCE_FAILED",
    "LOCK_UNAVAILABLE",
    "UNKNOWN_FAILURE",
})

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

ALLOWED_FIELDS = frozenset({
    "event_type",
    "stage",
    "outcome",
    "run_id",
    "task_id",
    "write_id",
    "claim_generation",
    "error_code",
})


class DiagnosticContractError(ValueError):
    """Diagnostic event rejected without exposing its input."""


def build_diagnostic_event(
    *,
    event_type: str,
    stage: str,
    outcome: str,
    run_id: str,
    task_id: str,
    write_id: str,
    claim_generation: int | None = None,
    error_code: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Return an explicitly allowlisted diagnostic event.

    Does not log, persist, or publish anything.
    """
    if extra:
        raise DiagnosticContractError(
            "Unsupported diagnostic fields"
        )

    if (
        type(event_type) is not str
        or event_type not in EVENT_TYPES
        or type(stage) is not str
        or stage not in STAGES
        or type(outcome) is not str
        or outcome not in OUTCOMES
    ):
        raise DiagnosticContractError(
            "Invalid diagnostic classification"
        )

    identifiers = (run_id, task_id, write_id)

    if any(
        type(value) is not str
        or IDENTIFIER_PATTERN.fullmatch(value) is None
        for value in identifiers
    ):
        raise DiagnosticContractError(
            "Invalid diagnostic identity"
        )

    if claim_generation is not None and (
        type(claim_generation) is not int
        or claim_generation < 1
    ):
        raise DiagnosticContractError(
            "Invalid claim generation"
        )

    if error_code is not None and (
        type(error_code) is not str
        or error_code not in ERROR_CODES
    ):
        raise DiagnosticContractError(
            "Invalid diagnostic error code"
        )

    if outcome == "failed" and error_code is None:
        raise DiagnosticContractError(
            "Failed event requires error code"
        )

    if outcome != "failed" and error_code is not None:
        raise DiagnosticContractError(
            "Error code requires failed outcome"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "stage": stage,
        "outcome": outcome,
        "run_id": run_id,
        "task_id": task_id,
        "write_id": write_id,
        "claim_generation": claim_generation,
        "error_code": error_code,
    }


def serialize_diagnostic_event(
    event: dict[str, Any],
) -> str:
    """Serialize only a valid, canonical event."""
    if type(event) is not dict:
        raise DiagnosticContractError(
            "Invalid diagnostic event"
        )

    if set(event) != ALLOWED_FIELDS | {"schema_version"}:
        raise DiagnosticContractError(
            "Invalid diagnostic schema"
        )

    if type(event.get("schema_version")) is not int or (
        event["schema_version"] != SCHEMA_VERSION
    ):
        raise DiagnosticContractError(
            "Invalid diagnostic schema version"
        )

    try:
        expected = build_diagnostic_event(
            **{
                key: event[key]
                for key in ALLOWED_FIELDS
            }
        )
    except (TypeError, KeyError) as exc:
        raise DiagnosticContractError(
            "Invalid diagnostic event"
        ) from None

    if event != expected:
        raise DiagnosticContractError(
            "Non-canonical diagnostic event"
        )

    return json.dumps(
        expected,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )



def emit_diagnostic_event(
    event: dict[str, Any],
    sink: Any = None,
) -> bool:
    """Best-effort delivery of validated JSON to an injected sink.

    A failed diagnostic must never change business execution results.
    """
    if sink is None:
        return False

    try:
        encoded = serialize_diagnostic_event(event)
        sink(encoded)
    except Exception:
        return False

    return True
