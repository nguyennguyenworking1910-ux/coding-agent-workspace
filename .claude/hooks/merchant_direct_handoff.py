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
disabled in code, test mode supports only ``merchant create``,
``project create`` and ``step update``, and a read-only preflight verifies
the effective database name and user. ``project create`` must carry the
confirmed preview's Project ID and basis, which are recomputed from current
state here and again inside the write transaction. ``step update`` must be
the user's own confirmation of a verified preview, spent for this exact run
(CP12H.NL4C2A), and is re-judged the same way. A preflight failure leaves no
footprint and spends nothing.
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
PROJECT_CREATE_COMMAND = "project create"

# Runtime (production) Direct EXECUTE stays disabled until separately
# approved. This is code, not configuration: no environment variable or
# agent input can enable it.
RUNTIME_DIRECT_EXECUTE_ENABLED = False

# CP12H.NL4C1/NL4C2A: a Step Update runs only from the user's confirmation
# of a verified preview (never a typed or model-built scope) and is re-judged
# against its basis before any spend and in the write transaction.
STEP_UPDATE_COMMAND = "step update"

# Test mode validates the real write paths end to end: the reserved
# Merchant Create, Project creation from a confirmed preview and (NL4C2A)
# a confirmed Step Update. Runtime stays disabled above.
TEST_MODE_COMMANDS = frozenset(
    {MERCHANT_CREATE_COMMAND, PROJECT_CREATE_COMMAND, STEP_UPDATE_COMMAND}
)

# Run-state key of the reconciled durable receipt of a Step Update.
STEP_RECEIPT_STATE_KEY = "merchant_step_update_receipt"


def direct_execute_enabled(command: str, target: str) -> bool:
    """Whether Direct EXECUTE of ``command`` on ``target`` can run at all."""

    if target == "runtime":
        return RUNTIME_DIRECT_EXECUTE_ENABLED
    return target == "test" and command in TEST_MODE_COMMANDS

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

    if (
        settled == SCOPE_EXECUTION_SUCCEEDED
        and attempt.command == STEP_UPDATE_COMMAND
    ):
        _record_step_receipt(attempt, repository, identity)

    sys.stdout.write(stdout.getvalue())
    sys.stderr.write(stderr.getvalue())

    if settled is None:
        raise DirectHandoffError(
            "Scoped execution outcome could not be recorded"
        )

    return exit_code


def _record_step_receipt(
    attempt: PreparedRuntimeHandoff,
    repository: Any,
    identity: Any,
) -> dict[str, Any]:
    """CP12H.NL4C2A: persist the reconciled receipt of a SUCCEEDED Step Update.

    Built only from durable evidence (ledger, claim and STEP event of one
    transaction) and checked against the confirmed operation; never from
    the CLI's or a teammate's report. An unreconciled receipt is recorded as
    such: it never changes the settled outcome, which committed evidence
    already decided.
    """

    from claude.clients.merchant.attempt_evidence import step_update_receipt
    from claude.hooks.merchant_pending_confirmation import confirmed_step_record
    from claude.hooks.runtime_state import locked_state

    try:
        operation = confirmed_step_record(
            attempt.owner_session_id, attempt.run_id
        )["operation"]
        receipt = step_update_receipt(repository, identity, operation["step_id"])
        confirmed = (
            operation["merchant_id"], operation["project_id"],
            operation["step_id"], operation["step_sequence"],
            operation["current_status"], operation["target_status"],
            operation["step_version"],
        )
        if confirmed != (
            receipt["merchant_id"], receipt["project_id"],
            receipt["step_id"], receipt["step_sequence"],
            receipt["previous_status"], receipt["new_status"],
            receipt["previous_version"],
        ):
            raise ValueError("receipt differs from the confirmed operation")
        receipt["status"] = "RECONCILED"
    except Exception as exc:  # noqa: BLE001 - recorded, never inferred
        receipt = {"status": "UNRECONCILED", "error": type(exc).__name__}

    receipt.update(
        run_id=attempt.run_id,
        task_id=attempt.task_id,
        database_target=attempt.database_target,
    )

    with locked_state(attempt.owner_session_id) as state:
        if isinstance(state, dict) and state.get("run_id") == attempt.run_id:
            state[STEP_RECEIPT_STATE_KEY] = receipt

    return receipt


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


def _create_payload(
    argv: tuple[str, ...],
    command: str = MERCHANT_CREATE_COMMAND,
) -> dict[str, Any]:
    from claude.agents.tools.merchant.cli import (
        build_argument_parser,
        build_write_payload,
    )

    args = build_argument_parser().parse_args(
        ["--database", "runtime", *argv]
    )

    return build_write_payload(args, command)


def _verify_project_preview(
    attempt: PreparedRuntimeHandoff,
    repository: Any,
) -> None:
    """Recompute the confirmed preview read-only; refuse before any spend."""

    from claude.agents.tools.merchant.project_preview import (
        ProjectPreviewMismatch,
        verify_project_create,
    )
    from claude.clients.merchant.read_repository import (
        MerchantReadRepository,
    )

    payload = _create_payload(tuple(attempt.arguments), PROJECT_CREATE_COMMAND)

    try:
        verify_project_create(MerchantReadRepository(repository), payload)
    except ProjectPreviewMismatch as exc:
        raise DirectPreflightRefused(exc.reason) from exc


def _confirmed_step_operation(attempt: PreparedRuntimeHandoff) -> dict[str, Any]:
    """CP12H.NL4C2A: the trusted pending Step Update this run confirmed.

    A Step Update executes only as the exact operation of one verified
    preview that the owner confirmed with their own prompt for this run, on
    the same database target. Anything else (a typed or model-built scope,
    another run's confirmation, an edited argv) is refused unspent.
    """

    from claude.agents.tools.merchant.step_preview import validate_step_operation
    from claude.hooks.merchant_pending_confirmation import confirmed_step_record

    try:
        record = confirmed_step_record(attempt.owner_session_id, attempt.run_id)
        operation = (record or {}).get("operation")
        validate_step_operation(operation)
    except Exception as exc:  # noqa: BLE001 - no trusted confirmation, no write
        raise DirectPreflightRefused("STEP_CONFIRMATION_REQUIRED") from exc

    if (
        list(attempt.arguments) != operation["argv"]
        or attempt.database_target != operation["database_target"]
        or record.get("database_target") != operation["database_target"]
        or record.get("step_id") != operation["step_id"]
    ):
        raise DirectPreflightRefused("STEP_CONFIRMATION_MISMATCH")

    return operation


def _verify_step_preview(
    attempt: PreparedRuntimeHandoff,
    repository: Any,
) -> None:
    """CP12H.NL4C1: re-judge the confirmed Step preview; refuse before any spend.

    A Step Update scope without a preview basis is refused too, so no Step
    write can skip the Project-version, dependency and gate re-check.
    """

    from claude.agents.tools.merchant.step_preview import (
        StepPreviewMismatch,
        verify_step_update,
    )
    from claude.clients.merchant.read_repository import (
        MerchantReadRepository,
    )

    payload = _create_payload(tuple(attempt.arguments), STEP_UPDATE_COMMAND)

    try:
        verify_step_update(MerchantReadRepository(repository), payload)
    except StepPreviewMismatch as exc:
        raise DirectPreflightRefused(exc.reason) from exc
    except Exception as exc:  # noqa: BLE001 - an unjudgeable step never runs
        raise DirectPreflightRefused("STEP_PREVIEW_UNVERIFIABLE") from exc


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
    INVALID_CONFIGURATION, DATABASE_UNAVAILABLE or, for ``project create``,
    a preview reason (PREVIEW_BASIS_REQUIRED, PREVIEW_BASIS_CHANGED,
    PROJECT_NOT_READY, PROJECT_ID_MISMATCH); for ``step update``,
    STEP_CONFIRMATION_REQUIRED, STEP_CONFIRMATION_MISMATCH or a re-judgement
    reason (STEP_BASIS_CHANGED, STEP_VERSION_CHANGED, STEP_NOT_READY, ...).
    The one-use authority stays unspent.
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

    if attempt.command == STEP_UPDATE_COMMAND:
        _confirmed_step_operation(attempt)

    try:
        repository = _target_repository(target)
    except DatabasePreflightError as exc:
        raise DirectPreflightRefused(exc.reason) from exc

    if attempt.command == PROJECT_CREATE_COMMAND:
        _verify_project_preview(attempt, repository)

    if attempt.command == STEP_UPDATE_COMMAND:
        _verify_step_preview(attempt, repository)

    return repository


def invoke_direct_merchant_execute(
    attempt: PreparedRuntimeHandoff,
) -> int:
    """Run one staged Direct EXECUTE attempt exactly once."""

    repository = preflight_direct_execute(attempt)

    if attempt.command == MERCHANT_CREATE_COMMAND:
        return _execute_reserved_create(attempt, repository)

    return _execute_scoped_write(attempt, repository)
