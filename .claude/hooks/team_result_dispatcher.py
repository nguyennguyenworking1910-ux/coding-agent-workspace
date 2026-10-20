"""Thin event dispatcher extracted from team_result_hook.

This module owns only hook-entrypoint event routing. Domain behavior remains
in the dedicated orchestration, staging, lifecycle, and result modules.

Dependencies are resolved from team_result_hook at call time so historical
test and monkeypatch seams remain compatible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

try:
    from team_result_dependency_protocols import (
        BoundedRuntimeApplyFailureFn,
        BoundedRuntimeApplyResultFn,
        EmitPostToolContextFn,
        HandleMerchantProposalReceiptFn,
        HandlePostToolUseFn,
        HandleTeammateIdleFn,
        PrepareMerchantRuntimeHandoffFn,
        RecordRuntimeHandoffResultFn,
        InvokeConfirmedMerchantSessionApplyFn,
        LockedStateFn,
    )
except ImportError:
    from .team_result_dependency_protocols import (
        BoundedRuntimeApplyFailureFn,
        BoundedRuntimeApplyResultFn,
        EmitPostToolContextFn,
        HandleMerchantProposalReceiptFn,
        HandlePostToolUseFn,
        HandleTeammateIdleFn,
        PrepareMerchantRuntimeHandoffFn,
        RecordRuntimeHandoffResultFn,
        InvokeConfirmedMerchantSessionApplyFn,
        LockedStateFn,
    )




@dataclass(frozen=True)
class DispatcherDependencies:
    """Explicit dependencies required by hook event dispatch."""

    HOOK_EVENT_NAMES: Any
    MerchantRuntimeHandoffStageError: Any
    bounded_runtime_apply_failure: BoundedRuntimeApplyFailureFn
    bounded_runtime_apply_result: BoundedRuntimeApplyResultFn
    emit_post_tool_context: EmitPostToolContextFn
    handle_merchant_proposal_receipt: HandleMerchantProposalReceiptFn
    handle_post_tool_use: HandlePostToolUseFn
    handle_teammate_idle: HandleTeammateIdleFn
    invoke_confirmed_merchant_session_apply: InvokeConfirmedMerchantSessionApplyFn
    io: Any
    json: Any
    locked_state: LockedStateFn
    prepare_merchant_runtime_handoff: PrepareMerchantRuntimeHandoffFn
    record_runtime_handoff_result: RecordRuntimeHandoffResultFn
    redirect_stderr: Callable[..., Any]
    redirect_stdout: Callable[..., Any]
    sys: Any
    invoke_authorized_scope_apply: InvokeConfirmedMerchantSessionApplyFn | None = None
    invoke_trusted_merchant_session_apply: InvokeConfirmedMerchantSessionApplyFn | None = None


def main(
    *,
    dependencies: DispatcherDependencies | None = None,
) -> int:

    if dependencies is None:
        raise RuntimeError(
            "team_result dispatcher dependencies are required"
        )

    HOOK_EVENT_NAMES = (
        dependencies.HOOK_EVENT_NAMES
    )

    MerchantRuntimeHandoffStageError = (
        dependencies.MerchantRuntimeHandoffStageError
    )

    bounded_runtime_apply_failure = (
        dependencies.bounded_runtime_apply_failure
    )

    bounded_runtime_apply_result = (
        dependencies.bounded_runtime_apply_result
    )

    emit_post_tool_context = (
        dependencies.emit_post_tool_context
    )

    handle_merchant_proposal_receipt = (
        dependencies.handle_merchant_proposal_receipt
    )

    handle_post_tool_use = (
        dependencies.handle_post_tool_use
    )

    handle_teammate_idle = (
        dependencies.handle_teammate_idle
    )

    invoke_confirmed_merchant_session_apply = (
        dependencies.invoke_confirmed_merchant_session_apply
    )

    invoke_authorized_scope_apply = (
        dependencies.invoke_authorized_scope_apply
    )

    invoke_trusted_merchant_session_apply = (
        dependencies.invoke_trusted_merchant_session_apply
    )

    io = (
        dependencies.io
    )

    json = (
        dependencies.json
    )

    locked_state = (
        dependencies.locked_state
    )

    prepare_merchant_runtime_handoff = (
        dependencies.prepare_merchant_runtime_handoff
    )

    record_runtime_handoff_result = (
        dependencies.record_runtime_handoff_result
    )

    redirect_stderr = (
        dependencies.redirect_stderr
    )

    redirect_stdout = (
        dependencies.redirect_stdout
    )

    sys = (
        dependencies.sys
    )
    try:
        payload = (
            json.load(
                sys.stdin
            )
        )
    except (
        json.JSONDecodeError,
        ValueError,
    ):
        return 0

    if not isinstance(
        payload,
        dict,
    ):
        return 0

    hook_event = str(
        payload.get(
            "hook_event_name"
        )
        or ""
    ).strip()

    session_id = (
        payload.get(
            "session_id"
        )
    )

    if (
        hook_event
        not in HOOK_EVENT_NAMES
    ):
        return 0

    # ============================================================
    # Gate 12H.1–12H.4
    #
    # Runtime handoff is deliberately handled BEFORE the ordinary
    # PostToolUse run-state lock.
    #
    # prepare_merchant_runtime_handoff() briefly acquires the OWNER
    # session lock only to validate and persist PENDING, then releases it.
    #
    # invoke_confirmed_merchant_session_apply() acquires the same owner
    # lock internally. Calling it from inside the outer locked_state()
    # block below would therefore risk self-deadlock / lock timeout.
    # ============================================================

    if (
        hook_event
        == "PostToolUse"
    ):
        (
            handoff_recognized,
            handoff_attempt,
            handoff_reason,
        ) = (
            prepare_merchant_runtime_handoff(
                payload
            )
        )

        if handoff_recognized:
            if handoff_attempt is None:
                emit_post_tool_context(
                    "Gate 12H runtime handoff was rejected before execution. "
                    f"Reason: {handoff_reason}. "
                    "No Merchant runtime apply was executed. Do not retry this "
                    "message by changing its authority fields."
                )

                return 0

            runtime_stdout = (
                io.StringIO()
            )

            runtime_stderr = (
                io.StringIO()
            )

            exit_code: int | None = None
            succeeded = False
            bounded_runtime_result = None
            runtime_failure_type: str | None = None

            try:
                # merchant_cli_main writes JSON to stdout/stderr.
                #
                # A hook itself must reserve stdout for its hook protocol,
                # therefore runtime CLI output is captured in memory here.
                # Gate 12H.6 will later define the bounded persisted runtime
                # result receipt; 12H.1–12H.4 do not persist raw CLI output.
                with (
                    redirect_stdout(
                        runtime_stdout
                    ),
                    redirect_stderr(
                        runtime_stderr
                    ),
                ):
                    # Production uses one trusted entrypoint. The legacy
                    # dependency-injection path remains temporarily for tests
                    # that have not yet migrated to the unified contract.
                    if callable(invoke_trusted_merchant_session_apply):
                        exit_code = invoke_trusted_merchant_session_apply(
                            handoff_attempt.owner_session_id,
                            handoff_attempt.arguments,
                        )
                    else:
                        # Compatibility-only path. Both handlers acquire the
                        # owner lock; release it before either invocation.
                        with locked_state(
                            handoff_attempt.owner_session_id
                        ) as trusted_owner_state:
                            if trusted_owner_state is None:
                                raise RuntimeError(
                                    "Merchant handoff owner state unavailable"
                                )
                            direct_mode = (
                                trusted_owner_state.get("merchant_scope")
                                is not None
                            )

                        if direct_mode:
                            if not callable(invoke_authorized_scope_apply):
                                raise RuntimeError(
                                    "Direct Merchant handoff is not configured"
                                )
                            exit_code = invoke_authorized_scope_apply(
                                handoff_attempt.owner_session_id,
                                handoff_attempt.arguments,
                            )
                        else:
                            exit_code = invoke_confirmed_merchant_session_apply(
                                handoff_attempt.owner_session_id,
                                handoff_attempt.arguments,
                            )

                if exit_code == 0:
                    bounded_runtime_result = (
                        bounded_runtime_apply_result(
                            runtime_stdout.getvalue(),
                            handoff_attempt,
                        )
                    )

                    succeeded = (
                        bounded_runtime_result
                        is not None
                    )
                else:
                    succeeded = False

                    runtime_failure_type = (
                        bounded_runtime_apply_failure(
                            runtime_stderr.getvalue()
                        )
                    )

            except Exception as exc:
                # The attempt was already staged PENDING before execution.
                # Any exception is therefore an uncertain/failed one-use
                # attempt and must never become replayable.
                #
                # Persist only the exception class name. Do not persist the
                # exception message or traceback because runtime/database
                # exceptions may contain sensitive operational data.
                succeeded = False
                exit_code = None
                if isinstance(
                    exc,
                    MerchantRuntimeHandoffStageError,
                ):
                    runtime_failure_type = (
                        f"MerchantRuntimeHandoffError:{exc.stage}"
                    )
                else:
                    runtime_failure_type = type(exc).__name__

            result_recorded = False

            # The runtime invocation above has completed and released its
            # own run-state lock. Reacquire the owner state only now.
            with locked_state(
                handoff_attempt.owner_session_id
            ) as owner_state:
                if owner_state is not None:
                    result_recorded = (
                        record_runtime_handoff_result(
                            owner_state,
                            handoff_attempt,
                            succeeded=(
                                succeeded
                            ),
                            exit_code=(
                                exit_code
                            ),
                            runtime_result=(
                                bounded_runtime_result
                            ),
                            failure_type=(
                                runtime_failure_type
                            ),
                        )
                    )

            if (
                succeeded
                and result_recorded
            ):
                emit_post_tool_context(
                    "Gate 7.4 trusted runtime handoff succeeded for the exact "
                    "confirmed Merchant apply. The apply attempt is spent and "
                    "must not be executed again. Continue only with allowlisted "
                    "read-only runtime verification. Do not send another "
                    "MERCHANT_APPLY_HANDOFF_REQUEST_JSON for this run/task."
                )

                return 0

            if result_recorded:
                bounded_failure = (
                    runtime_failure_type
                    or "UNKNOWN"
                )

                emit_post_tool_context(
                    "Gate 7.4 trusted runtime handoff was attempted but did "
                    "not complete successfully. "
                    f"Failure: {bounded_failure}. "
                    "The attempt is spent and is not retryable. "
                    "Do not execute Merchant apply through Bash, Python, "
                    "agent_cli --apply, or another handoff request."
                )

                return 0

            # PENDING was persisted before invocation. Failure to persist the
            # final result is an uncertain outcome, therefore fail closed and
            # never retry.
            emit_post_tool_context(
                "Gate 7.4 runtime handoff reached an uncertain terminal state: "
                "the attempt had already been reserved, but the bounded result "
                "could not be persisted. Treat the attempt as spent. Do not "
                "retry or use another runtime mutation path."
            )

            return 0

    # ============================================================
    # Existing result / proposal / entity-receipt lifecycle.
    # ============================================================

    idle_feedback = ""

    with locked_state(
        session_id
    ) as state:
        if (
            hook_event
            == "PostToolUse"
        ):
            handle_post_tool_use(
                state,
                payload,
                session_id,
            )

            # Direct authenticated teammate compatibility path only.
            # tmux Gate 11I does not trust SendMessage as proposal-token
            # authority.
            if (
                state
                is not None
            ):
                handle_merchant_proposal_receipt(
                    state,
                    payload,
                    session_id,
                )

        elif (
            hook_event
            == "TeammateIdle"
        ):
            idle_feedback = (
                handle_teammate_idle(
                    state,
                    payload,
                    session_id,
                )
            )

    if idle_feedback:
        print(
            idle_feedback,
            file=sys.stderr,
        )

        return 2

    return 0

