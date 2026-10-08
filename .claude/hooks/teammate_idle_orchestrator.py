"""TeammateIdle orchestration extracted from team_result_hook.

This module preserves trusted result reconciliation, Merchant
proposal/completeness enforcement, runtime apply verification,
lifecycle release, cleanup, and reusable-teammate behavior.

Dependencies are supplied dynamically by the hook so existing
monkeypatch and dependency-injection seams remain compatible.
"""

from __future__ import annotations

from typing import Any


def handle_teammate_idle(
    state: dict[str, Any] | None,
    payload: dict[str, Any],
    session_id: Any = None,
    dependencies: Any = None,
) -> str:
    """Handle TeammateIdle as the trusted delivery/lifecycle gate."""

    if dependencies is None:
        raise RuntimeError(
            "TeammateIdle dependencies are required"
        )

    MERCHANT_APPLY_FAILED_OUTCOME = (
        dependencies.MERCHANT_APPLY_FAILED_OUTCOME
    )

    MERCHANT_APPLY_SUCCESS_OUTCOME = (
        dependencies.MERCHANT_APPLY_SUCCESS_OUTCOME
    )

    MERCHANT_MANAGER_AGENT = (
        dependencies.MERCHANT_MANAGER_AGENT
    )

    MERCHANT_PROPOSAL_READY_OUTCOME = (
        dependencies.MERCHANT_PROPOSAL_READY_OUTCOME
    )

    MERCHANT_PROPOSE_OPERATION = (
        dependencies.MERCHANT_PROPOSE_OPERATION
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

    bind_reported_teammate_pane_session = (
        dependencies.bind_reported_teammate_pane_session
    )

    bound_merchant_completeness_receipt = (
        dependencies.bound_merchant_completeness_receipt
    )

    bounded_terminal_result_failure = (
        dependencies.bounded_terminal_result_failure
    )

    capture_proposal_receipt = (
        dependencies.capture_proposal_receipt
    )

    clear_pending_merchant_completeness = (
        dependencies.clear_pending_merchant_completeness
    )

    clear_pending_merchant_proposal = (
        dependencies.clear_pending_merchant_proposal
    )

    clear_pending_result = (
        dependencies.clear_pending_result
    )

    failed_runtime_handoff_matches = (
        dependencies.failed_runtime_handoff_matches
    )

    find_unique_active_teammate_owner = (
        dependencies.find_unique_active_teammate_owner
    )

    load_pending_merchant_proposal = (
        dependencies.load_pending_merchant_proposal
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

    pending_merchant_proposal_matches = (
        dependencies.pending_merchant_proposal_matches
    )

    record_teammate_result = (
        dependencies.record_teammate_result
    )

    release_reported_teammate_to_idle = (
        dependencies.release_reported_teammate_to_idle
    )

    successful_runtime_handoff_matches = (
        dependencies.successful_runtime_handoff_matches
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

            # --------------------------------------------------------
            # Gate 11I:
            # Merchant proposal authority comes from the exact staged CLI
            # output, not from the model-copied SendMessage JSON.
            #
            # Missing/mismatched proposal state does not invent authority.
            # It also does not undo a valid report delivery.
            # --------------------------------------------------------
            merchant_proposal_captured = False

            owner_authorized_operations = [
                str(operation)
                for operation in (
                    owner_record.get(
                        "authorized_operations"
                    )
                    or []
                )
            ]

            owner_authorized_agents = [
                str(agent)
                for agent in (
                    owner_record.get(
                        "authorized_selected_agents"
                    )
                    or []
                )
            ]

            requires_exact_merchant_apply = (
                teammate_name
                == MERCHANT_MANAGER_AGENT
                and owner_authorized_operations
                == [
                    "merchant_apply"
                ]
                and owner_authorized_agents
                == [
                    MERCHANT_MANAGER_AGENT
                ]
            )

            if requires_exact_merchant_apply:
                apply_task_result = (
                    task_result_candidate_from_message(
                        str(
                            pending_result.get(
                                "message"
                            )
                            or ""
                        )
                    )
                )

                if (
                    apply_task_result
                    is None
                    or str(
                        apply_task_result.get(
                            "operation"
                        )
                        or ""
                    ).strip()
                    != "merchant_apply"
                    or str(
                        apply_task_result.get(
                            "database_target"
                        )
                        or ""
                    ).strip()
                    != "runtime"
                ):
                    return (
                        bounded_terminal_result_failure(
                            owner_session_id=(
                                owner_session_id
                            ),
                            pane_session_id=(
                                session_id
                            ),
                            teammate_name=(
                                teammate_name
                            ),
                            run_id=(
                                owner_run_id
                            ),
                            task_id=(
                                owner_task_id
                            ),
                            reason=(
                                "Merchant apply terminal result is "
                                "missing or malformed"
                            ),
                        )
                    )

                apply_outcome = str(
                    apply_task_result.get(
                        "outcome"
                    )
                    or ""
                ).strip()

                apply_confirmation_hash = str(
                    apply_task_result.get(
                        "confirmation_hash"
                    )
                    or ""
                ).strip()

                with locked_state(
                    owner_session_id
                ) as owner_state:
                    if owner_state is None:
                        return (
                            PENDING_RESULT_FEEDBACK
                        )

                    if (
                        apply_outcome
                        == MERCHANT_APPLY_SUCCESS_OUTCOME
                    ):
                        trusted_apply_result = (
                            successful_runtime_handoff_matches(
                                owner_state,
                                owner_session_id=(
                                    owner_session_id
                                ),
                                teammate_name=(
                                    teammate_name
                                ),
                                run_id=(
                                    owner_run_id
                                ),
                                task_id=(
                                    owner_task_id
                                ),
                                confirmation_hash=(
                                    apply_confirmation_hash
                                ),
                            )
                        )

                        if not trusted_apply_result:
                            return (
                                bounded_terminal_result_failure(
                                    owner_session_id=(
                                        owner_session_id
                                    ),
                                    pane_session_id=(
                                        session_id
                                    ),
                                    teammate_name=(
                                        teammate_name
                                    ),
                                    run_id=(
                                        owner_run_id
                                    ),
                                    task_id=(
                                        owner_task_id
                                    ),
                                    reason=(
                                        "APPLY_SUCCESS has no matching "
                                        "trusted Gate 7.4 SUCCESS receipt"
                                    ),
                                )
                            )

                    elif (
                        apply_outcome
                        == MERCHANT_APPLY_FAILED_OUTCOME
                    ):
                        trusted_failure = (
                            failed_runtime_handoff_matches(
                                owner_state,
                                owner_session_id=(
                                    owner_session_id
                                ),
                                teammate_name=(
                                    teammate_name
                                ),
                                run_id=(
                                    owner_run_id
                                ),
                                task_id=(
                                    owner_task_id
                                ),
                                confirmation_hash=(
                                    apply_confirmation_hash
                                ),
                            )
                        )

                        if not trusted_failure:
                            return (
                                bounded_terminal_result_failure(
                                    owner_session_id=(
                                        owner_session_id
                                    ),
                                    pane_session_id=(
                                        session_id
                                    ),
                                    teammate_name=(
                                        teammate_name
                                    ),
                                    run_id=(
                                        owner_run_id
                                    ),
                                    task_id=(
                                        owner_task_id
                                    ),
                                    reason=(
                                        "APPLY_FAILED has no matching "
                                        "trusted Gate 7.4 FAILED receipt"
                                    ),
                                )
                            )

                    elif (
                        apply_outcome
                        not in {
                            "BLOCKED",
                            "FAILED",
                        }
                    ):
                        return (
                            bounded_terminal_result_failure(
                                owner_session_id=(
                                    owner_session_id
                                ),
                                pane_session_id=(
                                    session_id
                                ),
                                teammate_name=(
                                    teammate_name
                                ),
                                run_id=(
                                    owner_run_id
                                ),
                                task_id=(
                                    owner_task_id
                                ),
                                reason=(
                                    "Merchant apply terminal outcome is "
                                    "not allowed"
                                ),
                            )
                        )

            requires_exact_merchant_proposal = (
                teammate_name
                == MERCHANT_MANAGER_AGENT
                and owner_authorized_operations
                == [
                    MERCHANT_PROPOSE_OPERATION
                ]
                and owner_authorized_agents
                == [
                    MERCHANT_MANAGER_AGENT
                ]
            )

            # --------------------------------------------------------
            # Gate 12A:
            #
            # Authorization tells us what the teammate was allowed
            # to attempt. The structured task outcome tells us what
            # actually happened.
            #
            # Only PROPOSAL_READY requires exact Merchant proposal
            # evidence. Clarification/failure/block are valid terminal
            # results without proposal authority.
            #
            # Missing or malformed TEAM_RESULT_JSON deliberately falls
            # back to Gate 11 behavior and therefore remains fail-closed.
            # --------------------------------------------------------
            if requires_exact_merchant_proposal:
                task_result = (
                    task_result_candidate_from_message(
                        str(
                            pending_result.get(
                                "message"
                            )
                            or ""
                        )
                    )
                )

                if (task_result is not None and str(task_result.get("operation") or "").strip() == MERCHANT_PROPOSE_OPERATION and str(task_result.get("database_target") or "").strip() == "runtime"):
                    bound_completeness = (
                        bound_merchant_completeness_receipt(
                            pane_session_id=str(
                                session_id
                                or ""
                            ).strip(),
                            owner_session_id=str(
                                owner_session_id
                            ).strip(),
                            teammate_name=teammate_name,
                            run_id=owner_run_id,
                            task_id=owner_task_id,
                        )
                    )

                    completeness_decision = (
                        validate_completeness_receipt_for_outcome(
                            task_result,
                            bound_completeness,
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

                    task_outcome = str(
                        task_result.get(
                            "outcome"
                        )
                        or ""
                    ).strip()

                    if (
                        task_outcome
                        in MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES
                    ):
                        # A non-proposal terminal outcome must not coexist
                        # with staged proposal authority. Preserve evidence
                        # and fail closed if the two disagree.
                        unexpected_proposal = (
                            load_pending_merchant_proposal(
                                session_id
                            )
                        )

                        if (
                            unexpected_proposal
                            is not None
                        ):
                            return (
                                PENDING_RESULT_FEEDBACK
                            )

                        requires_exact_merchant_proposal = (
                            False
                        )

            if requires_exact_merchant_proposal:
                pending_proposal = (
                    load_pending_merchant_proposal(
                        session_id
                    )
                )

                # A merchant_propose run MUST have an exact
                # CLI-staged proposal before the teammate can
                # become reusable.
                if pending_proposal is None:
                    return bounded_terminal_result_failure(
                        owner_session_id=owner_session_id,
                        pane_session_id=session_id,
                        teammate_name=teammate_name,
                        run_id=owner_run_id,
                        task_id=owner_task_id,
                        reason=(
                            "Merchant terminal report did not establish "
                            "a valid non-proposal outcome and no exact "
                            "CLI proposal was staged."
                        ),
                    )

                if not pending_merchant_proposal_matches(
                    pending_proposal,
                    owner_session_id=(
                        owner_session_id
                    ),
                    teammate_name=(
                        teammate_name
                    ),
                    run_id=(
                        owner_run_id
                    ),
                    task_id=(
                        owner_task_id
                    ),
                ):
                    return PENDING_RESULT_FEEDBACK

                proposal = (
                    pending_proposal.get(
                        "proposal"
                    )
                )

                if not isinstance(
                    proposal,
                    dict,
                ):
                    return PENDING_RESULT_FEEDBACK

                if (
                    task_result is not None
                    and str(
                        task_result.get(
                            "outcome"
                        )
                        or ""
                    ).strip()
                    == MERCHANT_PROPOSAL_READY_OUTCOME
                ):
                    if not isinstance(
                        bound_completeness,
                        dict,
                    ):
                        return bounded_terminal_result_failure(
                            owner_session_id=owner_session_id,
                            pane_session_id=session_id,
                            teammate_name=teammate_name,
                            run_id=owner_run_id,
                            task_id=owner_task_id,
                            reason=(
                                "PROPOSAL_READY has no exact "
                                "completeness receipt"
                            ),
                        )

                    completeness_result = (
                        bound_completeness.get(
                            "result"
                        )
                    )

                    if not isinstance(
                        completeness_result,
                        dict,
                    ):
                        return PENDING_RESULT_FEEDBACK

                    completeness_command = str(
                        completeness_result.get(
                            "command"
                        )
                        or ""
                    ).strip()

                    proposal_command = str(
                        proposal.get(
                            "command"
                        )
                        or ""
                    ).strip()

                    if (
                        not completeness_command
                        or completeness_command
                        != proposal_command
                    ):
                        return bounded_terminal_result_failure(
                            owner_session_id=owner_session_id,
                            pane_session_id=session_id,
                            teammate_name=teammate_name,
                            run_id=owner_run_id,
                            task_id=owner_task_id,
                            reason=(
                                "Merchant proposal command does not match "
                                "the exact completeness command"
                            ),
                        )

                pane_bound, _ = (
                    bind_reported_teammate_pane_session(
                        owner_session_id,
                        teammate_name,
                        session_id,
                        owner_run_id,
                        owner_task_id,
                        required_operation=(
                            MERCHANT_PROPOSE_OPERATION
                        ),
                    )
                )

                if not pane_bound:
                    return (
                        PENDING_RESULT_FEEDBACK
                    )

                capture_outcome = (
                    capture_proposal_receipt(
                        owner_session_id,
                        proposal,
                    )
                )

                # Critical Gate 11I fail-closed boundary:
                # do not release the teammate and do not delete
                # transient evidence when receipt capture fails.
                if not capture_outcome.accepted:
                    return PENDING_RESULT_FEEDBACK

                merchant_proposal_captured = True

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

            # Clear transient raw-token proposal only after successful
            # lifecycle reconciliation. SendMessage receipt is cleared in
            # the same successful path.
            if session_id:
                if merchant_proposal_captured:
                    clear_pending_merchant_proposal(
                        session_id
                    )

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

