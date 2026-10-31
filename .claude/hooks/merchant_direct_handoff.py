"""Execute one staged, user-scoped Merchant Direct EXECUTE request.

Trusted team-state evidence is persisted before the one-use runtime
authorization is spent, so an attempted write always leaves a footprint
that the TeammateIdle gate must settle from trusted evidence:

- ``merchant create``: a durable reservation executed by the protected
  reserved executor and later verified from committed PostgreSQL evidence;
- every other allowlisted write: a ``direct_scope_execution`` record
  executed through the one-use runtime authorization, inside one
  transaction that also commits its execution claim and ledger row; its
  outcome is then settled from that database evidence
  (``merchant_attempt_resolution``).

No identity, command, argument or database target here comes from agent
input. The staged attempt was validated against the user-typed scope, whose
database target (``runtime`` or ``test``) is bound into the scope hash, the
confirmation hash, the staged handoff, the reservation, the spent authority
and the execution receipt.

Before any reservation or spend, the target is checked: runtime execution is
disabled in code, test mode supports only ``merchant create``, and a
read-only preflight verifies the effective database name and user. A
preflight failure leaves no footprint and spends nothing.
"""

from __future__ import annotations

import io
import json
import sys
import uuid
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from claude.hooks.merchant_completion_receipt import (
    SCOPE_EXECUTION_EXECUTING,
    SCOPE_EXECUTION_FAILED,
    SCOPE_EXECUTION_SUCCEEDED,
    SCOPE_EXECUTION_UNCERTAIN,
    has_direct_write_footprint,
)
from claude.hooks.merchant_terminal_consistency import (
    terminal_report_marker_matches,
)
from claude.hooks.merchant_runtime_handoff_gate import (
    PreparedRuntimeHandoff,
    bounded_runtime_apply_failure,
    bounded_runtime_apply_result,
)
from claude.hooks.team_lifecycle import locked_team_state


MERCHANT_CREATE_COMMAND = "merchant create"

# Runtime (production) Direct EXECUTE stays disabled until separately
# approved. This is code, not configuration: no environment variable or
# agent input can enable it.
RUNTIME_DIRECT_EXECUTE_ENABLED = False

# Test mode exists to validate the real Create path end to end.
TEST_MODE_COMMANDS = frozenset({MERCHANT_CREATE_COMMAND})

PREFLIGHT_STAGE = "PREFLIGHT"

# The Merchant CLI reports a class name only for validation and repository
# errors, which are raised before commit and roll the transaction back.
# Anything else (connection loss, an unknown failure) may have committed.
UNCLASSIFIED_CLI_FAILURE = "MerchantCommandError"


class DirectHandoffError(PermissionError):
    """The staged request does not match active lifecycle authority."""


class DirectPreflightRefused(PermissionError):
    """Refused before any reservation or spend; nothing was attempted."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _bound_record(
    state: Any,
    attempt: PreparedRuntimeHandoff,
) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise DirectHandoffError("Team state unavailable")

    record = state.get("teammates", {}).get(attempt.teammate_name)

    if not isinstance(record, dict):
        raise DirectHandoffError("Teammate missing")

    if (
        record.get("canonical_name") != attempt.teammate_name
        or record.get("status") != "RUNNING"
        or record.get("current_run_id") != attempt.run_id
        or record.get("current_task_id") != attempt.task_id
        or record.get("authorized_operations") != ["merchant_execute"]
        or record.get("authorized_selected_agents")
        != [attempt.teammate_name]
        or record.get("result_received") is True
    ):
        raise DirectHandoffError("Lifecycle binding mismatch")

    if not str(record.get("trusted_pane_session_id") or "").strip():
        raise DirectHandoffError("Executing pane is not bound")

    return record


def _begin_scope_execution(
    attempt: PreparedRuntimeHandoff,
) -> dict[str, Any]:
    """Persist EXECUTING before any runtime authorization is spent.

    Returns the persisted record; its fresh execution attempt identity is
    the one the spend and the database evidence are bound to.
    """

    execution_attempt_id = str(uuid.uuid4())

    with locked_team_state(attempt.owner_session_id) as state:
        record = _bound_record(state, attempt)

        # One scoped write per task, never on top of other evidence.
        if has_direct_write_footprint(record):
            raise DirectHandoffError("Task already has write evidence")

        if "direct_no_write_terminal" in record:
            raise DirectHandoffError("Task already finalized without a write")

        if terminal_report_marker_matches(record):
            raise DirectHandoffError("Task already reported a terminal result")

        execution = record["direct_scope_execution"] = {
            "version": 1,
            "run_id": attempt.run_id,
            "task_id": attempt.task_id,
            "command": attempt.command,
            "scope_hash": attempt.scope_hash,
            "confirmation_hash": attempt.confirmation_hash,
            "execution_attempt_id": execution_attempt_id,
            "status": SCOPE_EXECUTION_EXECUTING,
        }

    return dict(execution)


def _finish_scope_execution(
    attempt: PreparedRuntimeHandoff,
    status: str,
) -> bool:
    """Move the exact EXECUTING record to its terminal status."""

    with locked_team_state(attempt.owner_session_id) as state:
        if not isinstance(state, dict):
            return False

        record = state.get("teammates", {}).get(attempt.teammate_name)

        if not isinstance(record, dict):
            return False

        execution = record.get("direct_scope_execution")

        if (
            not isinstance(execution, dict)
            or execution.get("status") != SCOPE_EXECUTION_EXECUTING
            or execution.get("run_id") != attempt.run_id
            or execution.get("task_id") != attempt.task_id
            or execution.get("scope_hash") != attempt.scope_hash
            or execution.get("command") != attempt.command
        ):
            return False

        execution["status"] = status

    return True


def _scope_write_commands(
    database: str,
    repository: Any,
    identity: Any,
) -> Any:
    """Write handlers whose single transaction also commits the evidence."""

    from claude.agents.tools.merchant.write_adapters import (
        build_repository_write_commands,
    )
    from claude.clients.merchant.attempt_evidence import (
        evidence_bound_repository,
    )

    return build_repository_write_commands(
        database,
        repository=evidence_bound_repository(repository, identity),
    )


def _execute_scoped_write(
    attempt: PreparedRuntimeHandoff,
    repository: Any,
) -> int:
    from claude.hooks.merchant_attempt_resolution import (
        scope_attempt_identity,
        settle_scope_execution,
    )
    from claude.system.merchant_runtime_handoff import (
        invoke_authorized_scope_apply,
    )

    execution = _begin_scope_execution(attempt)
    identity = scope_attempt_identity(
        attempt.owner_session_id, attempt.teammate_name, execution
    )

    def settle(fence: bool) -> str | None:
        # The attempt's connection is closed here, so a missing claim can be
        # fenced. Committed evidence decides; a rollback is never inferred.
        return settle_scope_execution(
            owner_session_id=attempt.owner_session_id,
            teammate_name=attempt.teammate_name,
            run_id=attempt.run_id,
            task_id=attempt.task_id,
            database=attempt.database_target,
            repository_factory=lambda database: repository,
            fence=fence,
        )

    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = invoke_authorized_scope_apply(
                attempt.owner_session_id,
                attempt.arguments,
                teammate_name=attempt.teammate_name,
                task_id=attempt.task_id,
                execution_attempt_id=execution["execution_attempt_id"],
                write_command_factory=lambda database: _scope_write_commands(
                    database, repository, identity
                ),
            )
    except BaseException:
        # Settled straight from EXECUTING, so a crash before this point
        # still leaves an attempt TeammateIdle can fence.
        if settle(fence=True) is None:
            _finish_scope_execution(attempt, SCOPE_EXECUTION_UNCERTAIN)
        sys.stdout.write(stdout.getvalue())
        sys.stderr.write(stderr.getvalue())
        raise

    reported = _scope_outcome(
        exit_code, stdout.getvalue(), stderr.getvalue(), attempt
    )
    # The CLI's report only decides whether a fence may be placed: a
    # reported success without its evidence is never fenced.
    settled = settle(fence=reported != SCOPE_EXECUTION_SUCCEEDED)

    if settled is None:
        _finish_scope_execution(attempt, SCOPE_EXECUTION_UNCERTAIN)

    sys.stdout.write(stdout.getvalue())
    sys.stderr.write(stderr.getvalue())

    if settled is None:
        raise DirectHandoffError(
            "Scoped execution outcome could not be recorded"
        )

    return exit_code


def _scope_outcome(
    exit_code: int,
    stdout_text: str,
    stderr_text: str,
    attempt: PreparedRuntimeHandoff,
) -> str:
    """Classify a finished attempt; never infer a rollback.

    Exit 0 means the handler returned, so the write may have committed even
    if its output cannot be verified. A failure is definite only when the
    CLI names a validation or repository error class.
    """

    if exit_code == 0:
        if bounded_runtime_apply_result(stdout_text, attempt) is not None:
            return SCOPE_EXECUTION_SUCCEEDED

        return SCOPE_EXECUTION_UNCERTAIN

    failure = bounded_runtime_apply_failure(stderr_text)

    if failure is None or failure == UNCLASSIFIED_CLI_FAILURE:
        return SCOPE_EXECUTION_UNCERTAIN

    return SCOPE_EXECUTION_FAILED


def _create_payload(argv: tuple[str, ...]) -> dict[str, Any]:
    from claude.agents.tools.merchant.cli import (
        build_argument_parser,
        build_write_payload,
    )

    args = build_argument_parser().parse_args(
        ["--database", "runtime", *argv]
    )

    return build_write_payload(args, MERCHANT_CREATE_COMMAND)


def _execute_reserved_create(
    attempt: PreparedRuntimeHandoff,
    repository: Any,
) -> int:
    from claude.hooks.merchant_direct_write_state import (
        reserve_merchant_create,
    )
    from claude.hooks.merchant_reserved_execution import (
        execute_reserved_merchant_create,
    )
    from claude.system.merchant_runtime_handoff import (
        reserve_direct_scope_authorization,
    )

    with locked_team_state(attempt.owner_session_id) as state:
        record = _bound_record(state, attempt)
        pane_session_id = str(record["trusted_pane_session_id"])

        if "direct_scope_execution" in record:
            raise DirectHandoffError("Task already has write evidence")

        if terminal_report_marker_matches(record):
            raise DirectHandoffError("Task already reported a terminal result")

    database = attempt.database_target
    payload = _create_payload(tuple(attempt.arguments))
    write_id = f"scope-{attempt.scope_hash[:32]}"

    # Durable reservation first: the authority spend below verifies it,
    # and the executor persists EXECUTING with a fresh attempt identity
    # before contacting PostgreSQL.
    reserve_merchant_create(
        owner_session_id=attempt.owner_session_id,
        teammate_name=attempt.teammate_name,
        pane_session_id=pane_session_id,
        run_id=attempt.run_id,
        task_id=attempt.task_id,
        write_id=write_id,
        database=database,
        payload=payload,
    )

    # Spend the one-use user scope for this exact reservation. A failure
    # after this point never restores it, so no second write can happen.
    scope, _ = reserve_direct_scope_authorization(
        attempt.owner_session_id,
        attempt.arguments,
        teammate_name=attempt.teammate_name,
        task_id=attempt.task_id,
        reservation={"kind": "create", "write_id": write_id},
    )

    if scope.get("command") != MERCHANT_CREATE_COMMAND:
        raise DirectHandoffError("Scope is not a Merchant Create")

    result = execute_reserved_merchant_create(
        repository=repository,
        owner_session_id=attempt.owner_session_id,
        teammate_name=attempt.teammate_name,
        pane_session_id=pane_session_id,
        run_id=attempt.run_id,
        task_id=attempt.task_id,
        write_id=write_id,
        database=database,
        payload=payload,
    )

    _verify_committed_create(attempt, repository)

    print(json.dumps(result, default=str))

    return 0


def _verify_committed_create(
    attempt: PreparedRuntimeHandoff,
    repository: Any,
) -> None:
    """Verify committed evidence now so the report can state it.

    Best effort: TeammateIdle verifies again and settles the task.
    """

    from claude.hooks.merchant_direct_completion import (
        reconcile_all_direct_writes,
    )

    try:
        reconcile_all_direct_writes(
            owner_session_id=attempt.owner_session_id,
            teammate_name=attempt.teammate_name,
            run_id=attempt.run_id,
            task_id=attempt.task_id,
            repository_factory=lambda database: repository,
        )
    except Exception:
        pass


def direct_execution_evidence(attempt: PreparedRuntimeHandoff) -> str:
    """Trusted evidence state of the attempt's task (never agent input)."""

    from claude.hooks.merchant_terminal_consistency import (
        UNCERTAIN,
        direct_evidence_state,
    )
    from claude.hooks.team_lifecycle import (
        direct_authority_spent_for_run,
        load_team_state,
    )

    record = (load_team_state(attempt.owner_session_id) or {}).get(
        "teammates", {}
    ).get(attempt.teammate_name)

    if (
        not isinstance(record, dict)
        or record.get("current_run_id") != attempt.run_id
        or record.get("current_task_id") != attempt.task_id
    ):
        return UNCERTAIN

    return direct_evidence_state(
        record,
        authority_spent=direct_authority_spent_for_run(
            attempt.owner_session_id, attempt.run_id
        ),
    )


def _target_repository(target: str) -> Any:
    """Read-only identity check, then the repository the attempt writes to."""

    from claude.hooks.merchant_reserved_execution import (
        preflight_database_identity,
        repository_for_target,
    )

    repository = repository_for_target(target)
    preflight_database_identity(repository, target)

    return repository


def preflight_direct_execute(attempt: PreparedRuntimeHandoff) -> Any:
    """Refuse before any reservation or spend; return the target repository.

    Raises DirectPreflightRefused with RUNTIME_EXECUTION_DISABLED,
    TEST_MODE_COMMAND_UNSUPPORTED, TERMINAL_REPORT_ALREADY_SENT,
    INVALID_CONFIGURATION or DATABASE_UNAVAILABLE. The one-use authority
    stays unspent.
    """

    from claude.hooks.merchant_reserved_execution import (
        DatabasePreflightError,
    )
    from claude.hooks.team_lifecycle import load_team_state

    target = attempt.database_target

    if target == "runtime" and not RUNTIME_DIRECT_EXECUTE_ENABLED:
        raise DirectPreflightRefused("RUNTIME_EXECUTION_DISABLED")

    if target == "test" and attempt.command not in TEST_MODE_COMMANDS:
        raise DirectPreflightRefused("TEST_MODE_COMMAND_UNSUPPORTED")

    # Re-checked under the team-state lock where the footprint is created.
    record = (load_team_state(attempt.owner_session_id) or {}).get(
        "teammates", {}
    ).get(attempt.teammate_name)

    if terminal_report_marker_matches(record):
        raise DirectPreflightRefused("TERMINAL_REPORT_ALREADY_SENT")

    try:
        return _target_repository(target)
    except DatabasePreflightError as exc:
        raise DirectPreflightRefused(exc.reason) from exc


def invoke_direct_merchant_execute(
    attempt: PreparedRuntimeHandoff,
) -> int:
    """Run one staged Direct EXECUTE attempt exactly once."""

    repository = preflight_direct_execute(attempt)

    if attempt.command == MERCHANT_CREATE_COMMAND:
        return _execute_reserved_create(attempt, repository)

    return _execute_scoped_write(attempt, repository)
