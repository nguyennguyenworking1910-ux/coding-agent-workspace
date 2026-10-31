"""Settle finished Direct EXECUTE attempts from committed database evidence.

A scoped (non-Create) write runs inside one transaction that also commits its
execution claim and ledger row (``attempt_evidence``). After the attempt has
returned, raised or its process has ended, its outcome is read from that
evidence; a missing claim is fenced so a late commit becomes impossible. A
fence that cannot be placed leaves the attempt UNCERTAIN. Nothing here ever
infers a rollback from a terminated caller.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Callable

from claude.hooks.merchant_completion_receipt import (
    SCOPE_EXECUTION_EXECUTING,
    SCOPE_EXECUTION_FAILED,
    SCOPE_EXECUTION_SUCCEEDED,
    SCOPE_EXECUTION_UNCERTAIN,
    valid_scope_execution,
)
from claude.hooks.team_lifecycle import load_team_state, locked_team_state


SCOPE_OPERATION_KEY_PREFIX = "merchant-scope:v1:"

_UNSETTLED = frozenset({SCOPE_EXECUTION_EXECUTING, SCOPE_EXECUTION_UNCERTAIN})


def scope_attempt_identity(
    owner_session_id: str,
    teammate_name: str,
    execution: dict[str, Any],
) -> Any:
    """Bind the operation to owner, teammate, run, task, command and scope.

    The key excludes the attempt id, so a second attempt for the same scoped
    operation collides in the database before any mutation.
    """

    from claude.clients.merchant.attempt_evidence import AttemptIdentity

    identity = json.dumps(
        {
            "owner_session_id": owner_session_id,
            "teammate_name": teammate_name,
            "run_id": execution["run_id"],
            "task_id": execution["task_id"],
            "command": execution["command"],
            "scope_hash": execution["scope_hash"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return AttemptIdentity(
        operation_key=(
            SCOPE_OPERATION_KEY_PREFIX
            + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        ),
        payload_hash=execution["scope_hash"],
        execution_attempt_id=uuid.UUID(execution["execution_attempt_id"]),
        command=execution["command"],
    )


def _resolve(repository_factory: Callable[[str], Any], database: str,
             identity: Any, *, fence: bool) -> str:
    from claude.clients.merchant.attempt_evidence import (
        UNCERTAIN,
        resolve_attempt,
    )
    from claude.hooks import merchant_direct_handoff

    # A fence is a database write: never on runtime while runtime Direct
    # EXECUTE is disabled, even for an attempt left by an earlier version.
    if (
        database != "test"
        and not merchant_direct_handoff.RUNTIME_DIRECT_EXECUTE_ENABLED
    ):
        return UNCERTAIN

    try:
        return resolve_attempt(
            repository_factory(database), identity, fence=fence
        )
    except Exception:
        return UNCERTAIN


def settle_scope_execution(
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    database: str,
    repository_factory: Callable[[str], Any],
    fence: bool | None = None,
) -> str | None:
    """Move an unsettled scoped execution to its evidenced status.

    ``fence`` places a fence over a missing claim. The executor passes it
    only when the CLI did not report success. None (TeammateIdle) fences
    only an attempt still EXECUTING, whose result was never learned; an
    UNCERTAIN attempt is re-read but never fenced, because it may stand
    for a reported success whose evidence is missing.
    Returns the persisted status, or None when the record does not match.
    """

    from claude.clients.merchant.attempt_evidence import (
        COMMITTED,
        NOT_COMMITTED,
    )

    record = (load_team_state(owner_session_id) or {}).get(
        "teammates", {}
    ).get(teammate_name)
    execution = (
        record.get("direct_scope_execution")
        if isinstance(record, dict)
        else None
    )

    if (
        not valid_scope_execution(execution)
        or execution["run_id"] != run_id
        or execution["task_id"] != task_id
    ):
        return None

    if execution["status"] not in _UNSETTLED:
        return execution["status"]

    outcome = _resolve(
        repository_factory,
        database,
        scope_attempt_identity(owner_session_id, teammate_name, execution),
        fence=(
            execution["status"] == SCOPE_EXECUTION_EXECUTING
            if fence is None
            else fence
        ),
    )
    status = {
        COMMITTED: SCOPE_EXECUTION_SUCCEEDED,
        NOT_COMMITTED: SCOPE_EXECUTION_FAILED,
    }.get(outcome, SCOPE_EXECUTION_UNCERTAIN)

    with locked_team_state(owner_session_id) as state:
        current = (state or {}).get("teammates", {}).get(teammate_name)
        locked = (
            current.get("direct_scope_execution")
            if isinstance(current, dict)
            else None
        )

        if (
            not isinstance(locked, dict)
            or locked.get("execution_attempt_id")
            != execution["execution_attempt_id"]
            or locked.get("run_id") != run_id
            or locked.get("task_id") != task_id
            or locked.get("status") not in _UNSETTLED
        ):
            return None

        locked["status"] = status

    return status


def unverified_create_outcome(
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    repository_factory: Callable[[str], Any],
) -> str | None:
    """Fence Create writes that reconciliation could not verify.

    Returns DIRECT_WRITE_NOT_COMMITTED when every executed write is fenced,
    DIRECT_WRITE_UNCERTAIN otherwise, and None when nothing was executed.
    """

    from claude.clients.merchant.attempt_evidence import (
        NOT_COMMITTED,
        AttemptIdentity,
    )

    record = (load_team_state(owner_session_id) or {}).get(
        "teammates", {}
    ).get(teammate_name)
    writes = record.get("direct_writes") if isinstance(record, dict) else None

    if not isinstance(writes, dict) or not writes:
        return None

    outcomes = []

    for write in writes.values():
        if (
            not isinstance(write, dict)
            or write.get("run_id") != run_id
            or write.get("task_id") != task_id
        ):
            return "DIRECT_WRITE_UNCERTAIN"

        if write.get("status") != "EXECUTING":
            continue

        try:
            identity = AttemptIdentity(
                operation_key=write["operation_key"],
                payload_hash=write["payload_hash"],
                execution_attempt_id=uuid.UUID(write["execution_attempt_id"]),
                command="merchant create",
            )
        except (KeyError, TypeError, ValueError):
            return "DIRECT_WRITE_UNCERTAIN"

        outcomes.append(
            _resolve(
                repository_factory,
                write.get("database"),
                identity,
                fence=True,
            )
        )

    if not outcomes:
        return None

    if all(outcome == NOT_COMMITTED for outcome in outcomes):
        return "DIRECT_WRITE_NOT_COMMITTED"

    return "DIRECT_WRITE_UNCERTAIN"


def _bound_target(owner_session_id: str, run_id: str) -> str | None:
    from claude.hooks.merchant_terminal_consistency import (
        trusted_scope_binding,
    )
    from claude.hooks.runtime_state import load_state

    # A scoped write is bound only by its run state; without it the target
    # is unverifiable and the attempt stays as recorded.
    binding = trusted_scope_binding(load_state(owner_session_id), run_id, None)

    return None if binding is None else binding[0]


def settle_scope_execution_at_idle(
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
) -> None:
    """Settle an EXECUTING (crashed) or UNCERTAIN scoped attempt.

    The teammate's turn has ended, so no execution is in flight for it.
    """

    from claude.hooks.merchant_reserved_execution import repository_for_target

    database = _bound_target(owner_session_id, run_id)

    if database is None:
        return

    settle_scope_execution(
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        database=database,
        repository_factory=repository_for_target,
    )


def end_unverified_direct_create(
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
) -> bool:
    """End a Create task whose executed write reconciliation never verified."""

    from claude.hooks.merchant_reserved_execution import repository_for_target
    from claude.hooks.team_lifecycle import (
        end_unverified_direct_create as end_task,
    )

    reason = unverified_create_outcome(
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        repository_factory=repository_for_target,
    )

    return reason is not None and end_task(
        owner_session_id, teammate_name, run_id, task_id, reason
    )
