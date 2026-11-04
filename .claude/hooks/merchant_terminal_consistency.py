"""Trusted Direct EXECUTE outcome and terminal report consistency.

The outcome of a ``merchant_execute`` task is derived from trusted team-state
execution evidence, never from the teammate's prose. A teammate's
``TEAM_RESULT_JSON`` is accepted only when it agrees with that evidence:

- its ``database_target`` equals the user-selected target bound to the run;
- a committed write is reported only as EXECUTE_SUCCESS;
- a write that may have committed is never reported as BLOCKED, FAILED,
  REQUIRES_CLARIFICATION or EXECUTE_FAILED;
- EXECUTE_SUCCESS is never accepted without committed evidence.

The check runs before the report reaches the lead (PreToolUse) and again when
the task is settled (TeammateIdle). A report accepted at PreToolUse leaves a
run/task-bound marker that refuses any later execution for the task, so a
no-write report and a write can never both happen.
"""

from __future__ import annotations

from typing import Any, Callable

from claude.hooks.merchant_completion_receipt import (
    NO_WRITE_TERMINAL_OUTCOMES,
    SCOPE_EXECUTION_EXECUTING,
    SCOPE_EXECUTION_FAILED,
    SCOPE_EXECUTION_SUCCEEDED,
    SCOPE_EXECUTION_UNCERTAIN,
    has_direct_write_footprint,
    valid_scope_execution,
)


NO_WRITE = "NO_WRITE"
COMMITTED = "COMMITTED"
NOT_COMMITTED = "NOT_COMMITTED"
UNCERTAIN = "UNCERTAIN"
PENDING_VERIFICATION = "PENDING_VERIFICATION"

EXECUTE_SUCCESS = "EXECUTE_SUCCESS"
EXECUTE_FAILED = "EXECUTE_FAILED"
EXECUTE_UNCERTAIN = "EXECUTE_UNCERTAIN"

EXECUTE_OUTCOMES = frozenset(
    {EXECUTE_SUCCESS, EXECUTE_FAILED, EXECUTE_UNCERTAIN}
)

ALLOWED_OUTCOMES = {
    NO_WRITE: NO_WRITE_TERMINAL_OUTCOMES,
    COMMITTED: frozenset({EXECUTE_SUCCESS}),
    # Reporting uncertainty about a write that did not commit is
    # conservative, never misleading.
    NOT_COMMITTED: frozenset({EXECUTE_FAILED, EXECUTE_UNCERTAIN}),
    UNCERTAIN: frozenset({EXECUTE_UNCERTAIN}),
    PENDING_VERIFICATION: frozenset({EXECUTE_UNCERTAIN}),
}

EXPECTED_OUTCOME = {
    COMMITTED: EXECUTE_SUCCESS,
    NOT_COMMITTED: EXECUTE_FAILED,
    UNCERTAIN: EXECUTE_UNCERTAIN,
    PENDING_VERIFICATION: EXECUTE_UNCERTAIN,
}

TERMINAL_REPORT_MARKER = "direct_terminal_report"

_SCOPE_EVIDENCE = {
    SCOPE_EXECUTION_SUCCEEDED: COMMITTED,
    SCOPE_EXECUTION_FAILED: NOT_COMMITTED,
    SCOPE_EXECUTION_UNCERTAIN: UNCERTAIN,
    SCOPE_EXECUTION_EXECUTING: PENDING_VERIFICATION,
}


def direct_evidence_state(
    record: Any,
    *,
    authority_spent: bool,
) -> str:
    """Classify the current task's write evidence. Malformed is UNCERTAIN."""

    if not isinstance(record, dict):
        return UNCERTAIN

    run_id = record.get("current_run_id")
    task_id = record.get("current_task_id")
    execution = record.get("direct_scope_execution")
    writes = record.get("direct_writes")

    if execution is not None:
        if (
            not valid_scope_execution(execution)
            or execution["run_id"] != run_id
            or execution["task_id"] != task_id
            or writes
        ):
            return UNCERTAIN

        return _SCOPE_EVIDENCE[execution["status"]]

    if writes:
        if not isinstance(writes, dict) or any(
            not isinstance(write, dict)
            or write.get("run_id") != run_id
            or write.get("task_id") != task_id
            for write in writes.values()
        ):
            return UNCERTAIN

        statuses = {write.get("status") for write in writes.values()}

        if statuses == {"VERIFIED"}:
            return COMMITTED

        # The executor persists EXECUTING with an attempt identity before
        # contacting PostgreSQL, so these never reached the database.
        if statuses == {"RESERVED"} and all(
            "execution_attempt_id" not in write for write in writes.values()
        ):
            return NOT_COMMITTED

        return PENDING_VERIFICATION

    if has_direct_write_footprint(record) or authority_spent:
        return UNCERTAIN

    return NO_WRITE


def trusted_scope_binding(
    run_state: Any,
    run_id: Any,
    record: Any,
) -> tuple[str, str | None] | None:
    """Return (database_target, scope command) bound to this run.

    The run state is authoritative while it belongs to this run (Stop keeps
    it while a teammate owns the run). Otherwise only team-state evidence
    can bind: a Create write records its database, and a task without any
    write evidence can only have targeted runtime reads. A scoped write
    without its run state is unverifiable (None).
    """

    if isinstance(run_state, dict) and run_state.get("run_id") == run_id:
        scope = run_state.get("merchant_scope")

        if scope is None:
            from claude.hooks.runtime_state import merchant_database_target

            target = merchant_database_target(run_state)
            return (target, None) if target is not None else None

        if not isinstance(scope, dict) or scope.get("run_id") != run_id:
            return None

        target = scope.get("database_target")
        command = scope.get("command")

        if target not in {"runtime", "test"} or not isinstance(command, str):
            return None

        return target, command

    if not isinstance(record, dict) or "direct_scope_execution" in record:
        return None

    writes = record.get("direct_writes")

    if writes:
        databases = {
            write.get("database")
            for write in writes.values()
            if isinstance(write, dict)
        } if isinstance(writes, dict) else set()

        if len(databases) != 1 or not databases <= {"runtime", "test"}:
            return None

        return databases.pop(), "merchant create"

    return "runtime", None


def terminal_report_violation(
    task_result: Any,
    *,
    evidence: str,
    binding: tuple[str, str | None] | None,
) -> str | None:
    """Return why a terminal report contradicts trusted state, or None."""

    if binding is None:
        return "the run's trusted Merchant authorization is unavailable"

    trusted_target, trusted_command = binding

    if not isinstance(task_result, dict):
        return "it has no valid TEAM_RESULT_JSON block"

    if task_result.get("operation") != "merchant_execute":
        return "its operation is not merchant_execute"

    reported_target = task_result.get("database_target")

    if reported_target != trusted_target:
        return (
            f"its database_target {reported_target!r} differs from the "
            f"authorized target {trusted_target!r}"
        )

    outcome = task_result.get("outcome")

    if outcome not in ALLOWED_OUTCOMES.get(evidence, frozenset()):
        expected = EXPECTED_OUTCOME.get(evidence)
        allowed = (
            f"report {expected}"
            if expected
            else "report REQUIRES_CLARIFICATION, BLOCKED or FAILED"
        )
        return (
            f"its outcome {outcome!r} contradicts trusted execution "
            f"evidence ({evidence}); {allowed}"
        )

    if (
        outcome in EXECUTE_OUTCOMES
        and task_result.get("command") != trusted_command
    ):
        return "its command differs from the authorized scope command"

    return None


def terminal_report_marker_matches(record: Any) -> bool:
    """True when a terminal report was already accepted for this task."""

    if not isinstance(record, dict):
        return False

    marker = record.get(TERMINAL_REPORT_MARKER)

    return (
        isinstance(marker, dict)
        and marker.get("run_id") == record.get("current_run_id")
        and marker.get("task_id") == record.get("current_task_id")
    )


def merchant_terminal_report_decision(
    payload: dict[str, Any],
    deny: Callable[[str], dict[str, Any]],
) -> dict[str, Any] | None:
    """PreToolUse: stop a contradictory Merchant terminal report.

    Only restrictive: it can deny the report, never grant anything. A denied
    report never reaches the lead.
    """

    from claude.hooks.merchant_runtime_handoff_gate import (
        MERCHANT_MANAGER_AGENT,
    )
    from claude.hooks.runtime_state import load_state
    from claude.hooks.team_lifecycle import (
        direct_authority_spent_for_run,
        find_unique_active_teammate_owner,
        locked_team_state,
    )
    from claude.hooks.team_result_contract import (
        TEAM_RESULT_MARKER,
        task_result_candidate_from_message,
    )

    teammate = str(payload.get("agent_type") or "").strip()

    if teammate != MERCHANT_MANAGER_AGENT:
        return None

    if str(payload.get("tool_name") or "") != "SendMessage":
        return None

    tool_input = payload.get("tool_input")
    message = (
        tool_input.get("message") if isinstance(tool_input, dict) else None
    )

    if not isinstance(message, str) or TEAM_RESULT_MARKER not in message:
        return None

    owner_session_id, record, resolution = (
        find_unique_active_teammate_owner(teammate)
    )

    if (
        resolution != "FOUND"
        or not isinstance(record, dict)
        or "merchant_execute" not in (record.get("authorized_operations") or [])
    ):
        return None

    task_result = task_result_candidate_from_message(message)

    with locked_team_state(owner_session_id) as state:
        current = (
            (state or {}).get("teammates", {}).get(teammate)
            if isinstance(state, dict)
            else None
        )

        if not isinstance(current, dict):
            return deny("Blocked: the Merchant task state is unavailable.")

        run_id = current.get("current_run_id")
        evidence = direct_evidence_state(
            current,
            authority_spent=direct_authority_spent_for_run(
                owner_session_id, run_id
            ),
        )
        violation = terminal_report_violation(
            task_result,
            evidence=evidence,
            binding=trusted_scope_binding(
                load_state(owner_session_id), run_id, current
            ),
        )

        if violation is not None:
            return deny(
                "Blocked: this Merchant terminal report was not delivered "
                f"because {violation}. The outcome comes from trusted "
                "execution evidence, not from the report. Do not execute "
                "anything. Send one corrected report with exactly one "
                "TEAM_RESULT_JSON block that states the actual committed "
                "state."
            )

        current[TERMINAL_REPORT_MARKER] = {
            "run_id": run_id,
            "task_id": current.get("current_task_id"),
            "outcome": task_result["outcome"],
        }

    return None


def direct_terminal_report_violation(
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    message: str,
) -> str | None:
    """TeammateIdle: re-check the delivered report against settled evidence."""

    from claude.hooks.runtime_state import load_state
    from claude.hooks.team_lifecycle import (
        direct_authority_spent_for_run,
        load_team_state,
    )
    from claude.hooks.team_result_contract import (
        task_result_candidate_from_message,
    )

    record = (load_team_state(owner_session_id) or {}).get(
        "teammates", {}
    ).get(teammate_name)

    if (
        not isinstance(record, dict)
        or record.get("current_run_id") != run_id
        or record.get("current_task_id") != task_id
    ):
        return "the task binding changed"

    return terminal_report_violation(
        task_result_candidate_from_message(message),
        evidence=direct_evidence_state(
            record,
            authority_spent=direct_authority_spent_for_run(
                owner_session_id, run_id
            ),
        ),
        binding=trusted_scope_binding(
            load_state(owner_session_id), run_id, record
        ),
    )
