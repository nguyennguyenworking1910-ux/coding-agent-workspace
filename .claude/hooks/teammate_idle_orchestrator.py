"""TeammateIdle orchestration extracted from team_result_hook.

This module preserves trusted result reconciliation, Merchant Direct
EXECUTE terminal verification (committed writes or a trusted no-write
outcome), lifecycle release, cleanup, and reusable-teammate behavior.

Dependencies are supplied dynamically by the hook so existing
monkeypatch and dependency-injection seams remain compatible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from typing import Any

try:
    from team_result_dependency_protocols import (
        BoundedTerminalResultFailureFn,
        ClearMerchantResolutionAfterReleaseFn,
        ActiveTaskIdFn,
        BoundMerchantCompletenessReceiptFn,
        MessageCandidateFn,
        ClearPendingMerchantCompletenessFn,
        ClearPendingReceiptFn,
        LoadPendingStateFn,
        MarkBoundReportReceivedFn,
        MarkRecoverySentFn,
        MarkReportReceivedFn,
        ValidateCompletenessReceiptForOutcomeFn,
        FindUniqueActiveTeammateOwnerFn,
        LockedStateFn,
        RecordTeammateResultFn,
        ReleaseReportedTeammateToIdleFn,
    )
except ImportError:
    from .team_result_dependency_protocols import (
        BoundedTerminalResultFailureFn,
        ClearMerchantResolutionAfterReleaseFn,
        ActiveTaskIdFn,
        BoundMerchantCompletenessReceiptFn,
        MessageCandidateFn,
        ClearPendingMerchantCompletenessFn,
        ClearPendingReceiptFn,
        LoadPendingStateFn,
        MarkBoundReportReceivedFn,
        MarkRecoverySentFn,
        MarkReportReceivedFn,
        ValidateCompletenessReceiptForOutcomeFn,
        FindUniqueActiveTeammateOwnerFn,
        LockedStateFn,
        RecordTeammateResultFn,
        ReleaseReportedTeammateToIdleFn,
    )


class ReconcileDirectWritesFn(Protocol):
    def __call__(
        self,
        *,
        owner_session_id: str,
        teammate_name: str,
        run_id: str,
        task_id: str,
    ) -> bool: ...


class EstablishNoWriteTerminalFn(Protocol):
    def __call__(
        self,
        *,
        owner_session_id: str,
        teammate_name: str,
        run_id: str,
        task_id: str,
        outcome: Any,
    ) -> bool: ...


class TerminateDirectTaskFn(Protocol):
    def __call__(
        self,
        session_id: Any,
        teammate_name: str,
        run_id: str,
        task_id: str,
    ) -> tuple[bool, str]: ...


class DirectPaneIdentityStatusFn(Protocol):
    def __call__(
        self,
        session_id: Any,
        teammate_name: str,
        pane_session_id: Any,
        run_id: str,
        task_id: str,
    ) -> str: ...


LEGACY_MERCHANT_OPERATIONS = frozenset(
    {"merchant_propose", "merchant_apply"}
)


def _has_legacy_merchant_operation(record: dict[str, Any]) -> bool:
    return any(
        str(operation) in LEGACY_MERCHANT_OPERATIONS
        for operation in (record.get("authorized_operations") or [])
    )


@dataclass(frozen=True)
class TeammateIdleDependencies:
    """Explicit dependencies required by TeammateIdle orchestration."""

    reconcile_direct_writes: ReconcileDirectWritesFn
    direct_task_is_write_free: ReconcileDirectWritesFn
    establish_no_write_terminal: EstablishNoWriteTerminalFn
    terminate_legacy_merchant_task: TerminateDirectTaskFn
    fail_spent_direct_execution: TerminateDirectTaskFn
    direct_pane_identity_status: DirectPaneIdentityStatusFn
    MERCHANT_MANAGER_AGENT: str
    MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES: Any
    MISSING_RESULT_FEEDBACK: str
    PENDING_RESULT_FEEDBACK: str
    _clear_merchant_resolution_after_release: ClearMerchantResolutionAfterReleaseFn
    active_task_id: ActiveTaskIdFn
    bound_merchant_completeness_receipt: BoundMerchantCompletenessReceiptFn
    bounded_terminal_result_failure: BoundedTerminalResultFailureFn
    clear_pending_merchant_completeness: ClearPendingMerchantCompletenessFn
    clear_pending_result: ClearPendingReceiptFn
    find_unique_active_teammate_owner: FindUniqueActiveTeammateOwnerFn
    load_pending_result: LoadPendingStateFn
    load_team_state: LoadPendingStateFn
    locked_state: LockedStateFn
    mark_bound_report_received: MarkBoundReportReceivedFn
    mark_recovery_sent: MarkRecoverySentFn
    mark_report_received: MarkReportReceivedFn
    record_teammate_result: RecordTeammateResultFn
    release_reported_teammate_to_idle: ReleaseReportedTeammateToIdleFn
    task_result_candidate_from_message: MessageCandidateFn
    validate_completeness_receipt_for_outcome: ValidateCompletenessReceiptForOutcomeFn


def handle_teammate_idle(
    state: dict[str, Any] | None,
    payload: dict[str, Any],
    session_id: Any = None,
    dependencies: TeammateIdleDependencies | None = None,
) -> str:
    """Handle TeammateIdle as the trusted delivery/lifecycle gate."""

    if dependencies is None:
        raise RuntimeError(
            "TeammateIdle dependencies are required"
        )

    MERCHANT_MANAGER_AGENT = (
        dependencies.MERCHANT_MANAGER_AGENT
    )

    MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES = (
        dependencies.MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES
    )

    MISSING_RESULT_FEEDBACK = (
        dependencies.MISSING_RESULT_FEEDBACK
    )

    PENDING_RESULT_FEEDBACK = (
        dependencies.PENDING_RESULT_FEEDBACK
    )

    _clear_merchant_resolution_after_release = (
        dependencies._clear_merchant_resolution_after_release
    )

    active_task_id = (
        dependencies.active_task_id
    )

    bound_merchant_completeness_receipt = (
        dependencies.bound_merchant_completeness_receipt
    )

    bounded_terminal_result_failure = (
        dependencies.bounded_terminal_result_failure
    )

    clear_pending_merchant_completeness = (
        dependencies.clear_pending_merchant_completeness
    )

    clear_pending_result = (
        dependencies.clear_pending_result
    )

    find_unique_active_teammate_owner = (
        dependencies.find_unique_active_teammate_owner
    )

    load_pending_result = (
        dependencies.load_pending_result
    )

    load_team_state = (
        dependencies.load_team_state
    )

    locked_state = (
        dependencies.locked_state
    )

    mark_bound_report_received = (
        dependencies.mark_bound_report_received
    )

    mark_recovery_sent = (
        dependencies.mark_recovery_sent
    )

    mark_report_received = (
        dependencies.mark_report_received
    )

    record_teammate_result = (
        dependencies.record_teammate_result
    )

    release_reported_teammate_to_idle = (
        dependencies.release_reported_teammate_to_idle
    )

    task_result_candidate_from_message = (
        dependencies.task_result_candidate_from_message
    )

    validate_completeness_receipt_for_outcome = (
        dependencies.validate_completeness_receipt_for_outcome
    )

    teammate_name = str(
        payload.get(
            "teammate_name"
        )
        or ""
    ).strip()

    task_id = str(
        payload.get(
            "task_id"
        )
        or ""
    ).strip()

    if not teammate_name:
        return ""

    if session_id:
        direct_team_state = (
            load_team_state(
                session_id
            )
        )

        if (
            direct_team_state
            is not None
        ):
            direct_record = (
                direct_team_state.get("teammates") or {}
            ).get(teammate_name)

            if (
                isinstance(direct_record, dict)
                and _has_legacy_merchant_operation(direct_record)
            ):
                terminated, _ = dependencies.terminate_legacy_merchant_task(
                    session_id,
                    teammate_name,
                    str(direct_record.get("current_run_id") or ""),
                    str(direct_record.get("current_task_id") or ""),
                )

                if terminated:
                    clear_pending_result(session_id)
                    return ""

            released, _ = (
                release_reported_teammate_to_idle(
                    session_id,
                    teammate_name,
                )
            )

            if released:
                _clear_merchant_resolution_after_release(
                    session_id,
                    teammate_name,
                )

                return ""

        # tmux fallback:
        # TeammateIdle provides trusted teammate_name. Its session_id belongs
        # to the pane, so find the unique lead session that currently owns it.
        (
            owner_session_id,
            owner_record,
            owner_resolution,
        ) = (
            find_unique_active_teammate_owner(
                teammate_name
            )
        )

        if (
            owner_resolution
            == "AMBIGUOUS"
        ):
            return (
                "Cannot safely reconcile this teammate because more than "
                "one active lead session owns the same canonical teammate. "
                "Do not start new work."
            )

        if (
            owner_resolution
            == "FOUND"
            and owner_session_id
            and isinstance(
                owner_record,
                dict,
            )
            and str(
                owner_session_id
            )
            != str(
                session_id
            )
        ):
            owner_run_id = str(
                owner_record.get(
                    "current_run_id"
                )
                or ""
            ).strip()

            owner_task_id = str(
                owner_record.get(
                    "current_task_id"
                )
                or ""
            ).strip()

            if not (
                owner_run_id
                and owner_task_id
            ):
                return (
                    PENDING_RESULT_FEEDBACK
                )

            # A stale task from a removed Merchant workflow ends here, with
            # or without a delivered report: FAILED, no write, no new turn.
            if _has_legacy_merchant_operation(owner_record):
                terminated, _ = dependencies.terminate_legacy_merchant_task(
                    owner_session_id,
                    teammate_name,
                    owner_run_id,
                    owner_task_id,
                )

                if not terminated:
                    return PENDING_RESULT_FEEDBACK

                clear_pending_result(session_id)

                return ""

            # Once bound, only the verified executing pane may settle a
            # direct task. A foreign pane is ignored without feedback, and a
            # binding conflict ends the task: neither can loop.
            if "merchant_execute" in (
                owner_record.get("authorized_operations") or []
            ):
                pane_status = dependencies.direct_pane_identity_status(
                    owner_session_id,
                    teammate_name,
                    session_id,
                    owner_run_id,
                    owner_task_id,
                )

                if pane_status != "MATCH":
                    if pane_status == "CONFLICT":
                        clear_pending_result(session_id)

                    return ""

            pending_result = (
                load_pending_result(
                    session_id
                )
                if session_id
                else None
            )

            if (
                pending_result
                is None
            ):
                return (
                    MISSING_RESULT_FEEDBACK
                )

            receipt_matches_owner = (
                str(
                    pending_result.get(
                        "owner_session_id"
                    )
                    or ""
                ).strip()
                == str(
                    owner_session_id
                ).strip()
                and str(
                    pending_result.get(
                        "teammate_name"
                    )
                    or ""
                ).strip()
                == teammate_name
                and str(
                    pending_result.get(
                        "run_id"
                    )
                    or ""
                ).strip()
                == owner_run_id
                and str(
                    pending_result.get(
                        "task_id"
                    )
                    or ""
                ).strip()
                == owner_task_id
            )

            if not (
                receipt_matches_owner
            ):
                return (
                    MISSING_RESULT_FEEDBACK
                )

            # Direct Execute: committed PostgreSQL evidence must
            # be reconciled before accepting SendMessage.
            # Never derive write identity from message content.
            owner_direct_operations = (
                owner_record.get("authorized_operations")
            )

            # No merchant_execute task may fall through to the
            # legacy report/release path because its teammate
            # or selected-agent binding is malformed.
            if "merchant_execute" in (
                owner_direct_operations or []
            ):
                if (
                    teammate_name != MERCHANT_MANAGER_AGENT
                    or owner_direct_operations
                    != ["merchant_execute"]
                    or owner_record.get(
                        "authorized_selected_agents"
                    )
                    != [MERCHANT_MANAGER_AGENT]
                ):
                    return PENDING_RESULT_FEEDBACK

                # Trusted state, never message content, selects the
                # path. Any reservation, receipt, or same-task history
                # requires committed-evidence reconciliation.
                write_free = dependencies.direct_task_is_write_free(
                    owner_session_id=owner_session_id,
                    teammate_name=teammate_name,
                    run_id=owner_run_id,
                    task_id=owner_task_id,
                )

                if write_free is True:
                    task_result = task_result_candidate_from_message(
                        str(pending_result.get("message") or "")
                    )

                    outcome = str(
                        (task_result or {}).get("outcome") or ""
                    ).strip()

                    # An execution outcome without a trusted reservation
                    # is malformed, as is any non-direct operation.
                    if (
                        task_result is None
                        or outcome
                        not in MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES
                        or str(
                            task_result.get("operation") or ""
                        ).strip()
                        != "merchant_execute"
                        or str(
                            task_result.get("database_target") or ""
                        ).strip()
                        != "runtime"
                    ):
                        return bounded_terminal_result_failure(
                            owner_session_id=owner_session_id,
                            pane_session_id=session_id,
                            teammate_name=teammate_name,
                            run_id=owner_run_id,
                            task_id=owner_task_id,
                            reason=(
                                "Direct Merchant task without a write "
                                "has no valid no-write terminal result"
                            ),
                        )

                    completeness_decision = (
                        validate_completeness_receipt_for_outcome(
                            task_result,
                            bound_merchant_completeness_receipt(
                                pane_session_id=str(
                                    session_id or ""
                                ).strip(),
                                owner_session_id=str(
                                    owner_session_id
                                ).strip(),
                                teammate_name=teammate_name,
                                run_id=owner_run_id,
                                task_id=owner_task_id,
                            ),
                        )
                    )

                    if not completeness_decision.accepted:
                        return bounded_terminal_result_failure(
                            owner_session_id=owner_session_id,
                            pane_session_id=session_id,
                            teammate_name=teammate_name,
                            run_id=owner_run_id,
                            task_id=owner_task_id,
                            reason=(
                                "Merchant completeness evidence did not "
                                "match the structured task outcome: "
                                f"{completeness_decision.reason}"
                            ),
                        )

                    # Re-verified under the team-state lock. The report
                    # and release boundaries verify the marker again.
                    if not dependencies.establish_no_write_terminal(
                        owner_session_id=owner_session_id,
                        teammate_name=teammate_name,
                        run_id=owner_run_id,
                        task_id=owner_task_id,
                        outcome=outcome,
                    ):
                        return PENDING_RESULT_FEEDBACK

                elif "direct_scope_execution" in owner_record:
                    execution = owner_record.get("direct_scope_execution")

                    # A spent scoped write that did not succeed is never
                    # retried or released: the task ends FAILED and the
                    # execution record stays for audit. The report and
                    # release boundaries re-verify SUCCEEDED under lock.
                    if (
                        not isinstance(execution, dict)
                        or execution.get("status") != "SUCCEEDED"
                    ):
                        failed, _ = dependencies.fail_spent_direct_execution(
                            owner_session_id,
                            teammate_name,
                            owner_run_id,
                            owner_task_id,
                        )

                        if not failed:
                            return PENDING_RESULT_FEEDBACK

                        clear_pending_result(session_id)

                        return ""

                else:
                    # Spent authority without trusted evidence, or Create
                    # reservations never claimed, end the task (bounded).
                    failed, _ = dependencies.fail_spent_direct_execution(
                        owner_session_id,
                        teammate_name,
                        owner_run_id,
                        owner_task_id,
                    )

                    if failed:
                        clear_pending_result(session_id)
                        return ""

                    try:
                        direct_verified = (
                            dependencies.reconcile_direct_writes(
                                owner_session_id=owner_session_id,
                                teammate_name=teammate_name,
                                run_id=owner_run_id,
                                task_id=owner_task_id,
                            )
                        )
                    except Exception:
                        return PENDING_RESULT_FEEDBACK

                    if direct_verified is not True:
                        return PENDING_RESULT_FEEDBACK

            marked = (
                mark_bound_report_received(
                    owner_session_id,
                    teammate_name,
                    owner_run_id,
                    owner_task_id,
                    "sendmessage",
                )
            )

            if not marked:
                return (
                    PENDING_RESULT_FEEDBACK
                )
            # Update the lead run ledger when it still exists.
            # Stop may already have removed it; team state remains the
            # authoritative lifecycle completion record in that case.
            if (
                str(
                    owner_session_id
                )
                == str(
                    session_id
                )
            ):
                if (
                    state
                    is not None
                ):
                    record_teammate_result(
                        state,
                        teammate_name,
                        owner_task_id,
                        "sendmessage",
                    )
            else:
                with locked_state(
                    owner_session_id
                ) as owner_state:
                    if (
                        owner_state
                        is not None
                    ):
                        record_teammate_result(
                            owner_state,
                            teammate_name,
                            owner_task_id,
                            "sendmessage",
                        )

            released, _ = (
                release_reported_teammate_to_idle(
                    owner_session_id,
                    teammate_name,
                )
            )

            if not released:
                return (
                    PENDING_RESULT_FEEDBACK
                )

            _clear_merchant_resolution_after_release(
                session_id,
                teammate_name,
            )

            # Clear transient result evidence after successful release.
            if session_id:
                clear_pending_merchant_completeness(
                    session_id
                )

                clear_pending_result(
                    session_id
                )
            return ""

    current_task_id = (
        active_task_id(
            session_id,
            teammate_name,
        )
    )

    if current_task_id:
        if (
            task_id
            and task_id
            != current_task_id
        ):
            return ""

        task_id = (
            current_task_id
        )

    if not (
        teammate_name
        and task_id
    ):
        return ""

    if state is None:
        return (
            MISSING_RESULT_FEEDBACK
        )

    run_id = state.get(
        "run_id",
        "",
    )

    ledger = state.get(
        "result_ledger",
        {},
    )

    dedup_key = (
        f"{run_id}:"
        f"{task_id}:"
        f"{teammate_name}"
    )

    result_already_received = (
        dedup_key in ledger
        and ledger[
            dedup_key
        ].get(
            "result_received"
        )
    )

    if result_already_received:
        if session_id:
            mark_report_received(
                session_id,
                teammate_name,
                task_id,
                "sendmessage",
            )

            released, _ = (
                release_reported_teammate_to_idle(
                    session_id,
                    teammate_name,
                )
            )

            if released:
                _clear_merchant_resolution_after_release(
                    session_id,
                    teammate_name,
                )

            if not released:
                team_state = (
                    load_team_state(
                        session_id
                    )
                )

                teammate_record = None

                if isinstance(
                    team_state,
                    dict,
                ):
                    teammate_record = (
                        team_state.get(
                            "teammates",
                            {},
                        )
                    ).get(
                        teammate_name
                    )

                if isinstance(
                    teammate_record,
                    dict,
                ):
                    return (
                        PENDING_RESULT_FEEDBACK
                    )

        return ""

    recovery_is_new = (
        mark_recovery_sent(
            state,
            teammate_name,
            task_id,
        )
    )

    return (
        MISSING_RESULT_FEEDBACK
        if recovery_is_new
        else PENDING_RESULT_FEEDBACK
    )

