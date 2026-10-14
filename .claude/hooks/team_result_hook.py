#!/usr/bin/env python3
"""PostToolUse and TeammateIdle hooks: exact teammate result delivery.

`SendMessage` to `team-lead` is the single machine-verifiable result path.
`TeammateIdle` is only a lifecycle signal: it never invents a result. If a
teammate tries to become idle before sending its report, the hook exits with
code 2 and asks it to send the existing report without repeating the task.

Uses deduplication key: run_id + task_id + canonical_teammate_name.
- Repeated SendMessage delivery is one logical result
- TaskUpdate and TeammateIdle do not count as complete results
- Once result_received is true, no recovery request is allowed
- recovery_sent records that delivery recovery was initiated

Updates both run state (result ledger) and team state (lifecycle status).
When result is received, marks team state REPORT_RECEIVED.
When TeammateIdle fires after result received, marks team state IDLE_REUSABLE.

Gate 11I:
- exact Merchant proposal JSON is taken from the Merchant CLI PostToolUse
  response, never reconstructed from the teammate's SendMessage;
- exact CLI output is staged only after the current lead run authorizes
  exactly merchant_propose + merchant-manager;
- tmux PostToolUse role information is only a hint;
- TeammateIdle supplies the trusted canonical teammate identity;
- owner session + teammate + run + task must match before proposal capture;
- the raw confirmation token exists only in transient pending proposal state
  and is cleared after successful lifecycle reconciliation.

Stop hook clears run state only.
SessionEnd hook clears run state and session team state.
"""

from __future__ import annotations

import io
import json
import sys
import shlex
import unicodedata

from contextlib import (
    redirect_stderr,
    redirect_stdout,
)
from pathlib import Path
from typing import Any
from claude.system.merchant_runtime_handoff import (
    MerchantRuntimeHandoffStageError,
    invoke_confirmed_merchant_session_apply,
)

if __package__ in (None, ""):
    sys.path.insert(
        0,
        str(
            Path(__file__).resolve().parent
        ),
    )

    from runtime_state import (
        load_state,
        locked_state,
    )
    from team_result_payload import (
        coalesced_text as _coalesced_text,
        embedded_json_objects,
        send_message_body,
        trusted_post_tool_sender,
    )
    from team_result_ledger import (
        mark_recovery_sent,
        record_teammate_result,
    )
    from team_result_context import (
        INVALID_TERMINAL_RESULT_FEEDBACK,
        MISSING_RESULT_FEEDBACK,
        PENDING_RESULT_FEEDBACK,
        active_task_id,
        bounded_terminal_result_failure,
        emit_post_tool_context,
    )
    from resolution_staging_context import (
        resolution_stage_context,
    )
    from resolution_cli_invocation import (
        parse_resolution_cli_invocation,
    )
    from team_result_dispatcher import (
        DispatcherDependencies,
        main as _dispatch_main,
    )
    from teammate_idle_orchestrator import (
        TeammateIdleDependencies,
        handle_teammate_idle as _teammate_idle_handle,
    )
    from post_tool_orchestrator import (
        PostToolDependencies,
        handle_post_tool_use as _post_tool_handle,
    )
    from merchant_resolution_tool_contract import (
        ResidualMerchantDependencies,
        _merchant_resolution_invocation_query as _resolution_invocation_query_impl,
        merchant_resolution_from_tool_response as _resolution_from_tool_response_impl,
    )
    from merchant_resolution_cleanup import (
        _clear_merchant_resolution_after_release as _resolution_cleanup_impl,
    )
    from merchant_runtime_orchestration import (
        MerchantRuntimeDependencies,
        _project_resolve_invocation as _runtime_project_resolve_invocation,
        bound_merchant_completeness_receipt as _runtime_bound_merchant_completeness_receipt,
        capture_merchant_proposal_from_message as _runtime_capture_merchant_proposal_from_message,
        handle_merchant_proposal_receipt as _runtime_handle_merchant_proposal_receipt,
        prepare_merchant_runtime_handoff as _runtime_prepare_merchant_runtime_handoff,
    )
    from merchant_staging import (
        MerchantStagingDependencies,
        _stage_exact_tmux_merchant_completeness as _merchant_stage_completeness,
        _stage_exact_tmux_merchant_proposal as _merchant_stage_proposal,
        _stage_exact_tmux_merchant_resolution as _merchant_stage_resolution,
        _trusted_tmux_merchant_stage_context as _merchant_stage_context,
    )
    from resolution_staging import (
        ResolutionStagingDependencies,
        _stage_exact_tmux_document_revision_resolution as _resolution_stage_document,
        _stage_exact_tmux_project_resolution as _resolution_stage_project,
        _stage_exact_tmux_step_resolution as _resolution_stage_step,
    )
    from team_result_contract import (
        MERCHANT_APPLY_FAILED_OUTCOME,
        MERCHANT_APPLY_SUCCESS_OUTCOME,
        MERCHANT_PROPOSAL_READY_OUTCOME,
        MERCHANT_PROPOSAL_RESULT_MARKER,
        MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES,
        TEAM_RESULT_CONTRACT_VERSION,
        TEAM_RESULT_MARKER,
        task_result_candidate_from_message,
    )
    from merchant_result_contract import (
        merchant_proposal_candidate_from_message,
        merchant_report_sender,
    )
    from merchant_tool_result_contract import (
        merchant_completeness_from_tool_response,
        merchant_proposal_from_tool_response,
    )
    from team_lifecycle import (
        claim_terminal_recovery,
        find_unique_active_teammate_owner,
        load_team_state,
        mark_bound_report_received,
        mark_report_received,
        mark_teammate_failed,
        release_reported_teammate_to_idle,
        bind_reported_teammate_pane_session,
        trusted_teammate_pane_session_matches,
    )
    from merchant_confirmation_preferences import (
        MERCHANT_MANAGER_AGENT,
        MERCHANT_PROPOSE_OPERATION,
        capture_proposal_receipt,
        validate_proposal_result,
        proposal_requires_local_auto_receipt,
    )
    from tmux_result_receipt import (
        clear_pending_result,
        load_pending_result,
        stage_pending_result,
    )
    from tmux_merchant_proposal import (
        clear_pending_merchant_proposal,
        load_pending_merchant_proposal,
        pending_merchant_proposal_matches,
        stage_pending_merchant_proposal,
    )
    from tmux_merchant_completeness import (
        clear_pending_merchant_completeness,
        load_pending_merchant_completeness,
        pending_merchant_completeness_matches,
        stage_pending_merchant_completeness,
        validate_completeness_result,
    )
    from merchant_completeness_gate import (
        validate_completeness_receipt_for_outcome,
    )
    from tmux_merchant_resolution import (  # noqa: E402
        stage_pending_merchant_resolution,
        validate_merchant_resolution_result,
        clear_pending_merchant_resolution,
    )
    from tmux_merchant_resolution import (
        load_pending_merchant_resolution,
        pending_merchant_resolution_matches,
    )
    from tmux_project_resolution import (
        clear_pending_project_resolution,
        load_pending_project_resolution,
        pending_project_resolution_matches,
        project_resolution_receipt_matches,
        stage_pending_project_resolution,
    )
    from tmux_step_resolution import (
        stage_pending_step_resolution,
        clear_pending_step_resolution,
        load_pending_step_resolution,
    )
    from step_resolution_gate import (
        BOUND as STEP_BOUND,
        bind_step_resolution_receipt,
    )
    from tmux_document_revision_resolution import (
        stage_pending_document_revision_resolution,
        clear_pending_document_revision_resolution,
    )
    from merchant_runtime_handoff_gate import (
        MERCHANT_APPLY_HANDOFF_MARKER,
        PreparedRuntimeHandoff,
        contains_handoff_marker,
        handoff_candidate_from_message,
        record_runtime_handoff_result,
        stage_runtime_handoff_attempt,
        bounded_runtime_apply_result,
        failed_runtime_handoff_matches,
        successful_runtime_handoff_matches,
        bounded_runtime_apply_failure,
    )

else:
    from .runtime_state import (
        load_state,
        locked_state,
    )
    from .team_result_payload import (
        coalesced_text as _coalesced_text,
        embedded_json_objects,
        send_message_body,
        trusted_post_tool_sender,
    )
    from .team_result_ledger import (
        mark_recovery_sent,
        record_teammate_result,
    )
    from .team_result_context import (
        INVALID_TERMINAL_RESULT_FEEDBACK,
        MISSING_RESULT_FEEDBACK,
        PENDING_RESULT_FEEDBACK,
        active_task_id,
        bounded_terminal_result_failure,
        emit_post_tool_context,
    )
    from .resolution_staging_context import (
        resolution_stage_context,
    )
    from .resolution_cli_invocation import (
        parse_resolution_cli_invocation,
    )
    from .team_result_dispatcher import (
        DispatcherDependencies,
        main as _dispatch_main,
    )
    from .teammate_idle_orchestrator import (
        TeammateIdleDependencies,
        handle_teammate_idle as _teammate_idle_handle,
    )
    from .post_tool_orchestrator import (
        PostToolDependencies,
        handle_post_tool_use as _post_tool_handle,
    )
    from .merchant_resolution_tool_contract import (
        ResidualMerchantDependencies,
        _merchant_resolution_invocation_query as _resolution_invocation_query_impl,
        merchant_resolution_from_tool_response as _resolution_from_tool_response_impl,
    )
    from .merchant_resolution_cleanup import (
        _clear_merchant_resolution_after_release as _resolution_cleanup_impl,
    )
    from .merchant_runtime_orchestration import (
        MerchantRuntimeDependencies,
        _project_resolve_invocation as _runtime_project_resolve_invocation,
        bound_merchant_completeness_receipt as _runtime_bound_merchant_completeness_receipt,
        capture_merchant_proposal_from_message as _runtime_capture_merchant_proposal_from_message,
        handle_merchant_proposal_receipt as _runtime_handle_merchant_proposal_receipt,
        prepare_merchant_runtime_handoff as _runtime_prepare_merchant_runtime_handoff,
    )
    from .merchant_staging import (
        MerchantStagingDependencies,
        _stage_exact_tmux_merchant_completeness as _merchant_stage_completeness,
        _stage_exact_tmux_merchant_proposal as _merchant_stage_proposal,
        _stage_exact_tmux_merchant_resolution as _merchant_stage_resolution,
        _trusted_tmux_merchant_stage_context as _merchant_stage_context,
    )
    from .resolution_staging import (
        ResolutionStagingDependencies,
        _stage_exact_tmux_document_revision_resolution as _resolution_stage_document,
        _stage_exact_tmux_project_resolution as _resolution_stage_project,
        _stage_exact_tmux_step_resolution as _resolution_stage_step,
    )
    from .team_result_contract import (
        MERCHANT_APPLY_FAILED_OUTCOME,
        MERCHANT_APPLY_SUCCESS_OUTCOME,
        MERCHANT_PROPOSAL_READY_OUTCOME,
        MERCHANT_PROPOSAL_RESULT_MARKER,
        MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES,
        TEAM_RESULT_CONTRACT_VERSION,
        TEAM_RESULT_MARKER,
        task_result_candidate_from_message,
    )
    from .merchant_result_contract import (
        merchant_proposal_candidate_from_message,
        merchant_report_sender,
    )
    from .merchant_tool_result_contract import (
        merchant_completeness_from_tool_response,
        merchant_proposal_from_tool_response,
    )
    from .team_lifecycle import (
        claim_terminal_recovery,
        find_unique_active_teammate_owner,
        load_team_state,
        mark_bound_report_received,
        mark_report_received,
        mark_teammate_failed,
        release_reported_teammate_to_idle,
        bind_reported_teammate_pane_session,
        trusted_teammate_pane_session_matches,
    )
    from .merchant_confirmation_preferences import (
        MERCHANT_MANAGER_AGENT,
        MERCHANT_PROPOSE_OPERATION,
        capture_proposal_receipt,
        validate_proposal_result,
        proposal_requires_local_auto_receipt,
    )
    from .tmux_result_receipt import (
        clear_pending_result,
        load_pending_result,
        stage_pending_result,
    )
    from .tmux_merchant_proposal import (
        clear_pending_merchant_proposal,
        load_pending_merchant_proposal,
        pending_merchant_proposal_matches,
        stage_pending_merchant_proposal,
    )
    from .tmux_merchant_completeness import (
        clear_pending_merchant_completeness,
        load_pending_merchant_completeness,
        pending_merchant_completeness_matches,
        stage_pending_merchant_completeness,
        validate_completeness_result,
    )
    from .merchant_completeness_gate import (
        validate_completeness_receipt_for_outcome,
    )
    from .tmux_merchant_resolution import (
        stage_pending_merchant_resolution,
        validate_merchant_resolution_result,
        clear_pending_merchant_resolution,
    )
    from .tmux_merchant_resolution import (
        load_pending_merchant_resolution,
        pending_merchant_resolution_matches,
    )
    from .tmux_project_resolution import (
        clear_pending_project_resolution,
        load_pending_project_resolution,
        pending_project_resolution_matches,
        project_resolution_receipt_matches,
        stage_pending_project_resolution,
    )
    from .tmux_step_resolution import (
        clear_pending_step_resolution,
        stage_pending_step_resolution,
    )
    from .step_resolution_gate import (
        BOUND as STEP_BOUND,
        bind_step_resolution_receipt,
    )
    from .tmux_document_revision_resolution import (
        stage_pending_document_revision_resolution,
        clear_pending_document_revision_resolution,
    )
    from .merchant_runtime_handoff_gate import (
        MERCHANT_APPLY_HANDOFF_MARKER,
        PreparedRuntimeHandoff,
        contains_handoff_marker,
        handoff_candidate_from_message,
        record_runtime_handoff_result,
        stage_runtime_handoff_attempt,
        bounded_runtime_apply_result,
        failed_runtime_handoff_matches,
        successful_runtime_handoff_matches,
        bounded_runtime_apply_failure,
    )

HOOK_EVENT_NAMES = (
    "PostToolUse",
    "TeammateIdle",
)

MERCHANT_RESOLUTION_OPERATIONS = frozenset(
    {
        "merchant_read",
        "merchant_propose",
        "merchant_apply",
    }
)




def _residual_merchant_dependencies(
) -> ResidualMerchantDependencies:
    """Bind current hook symbols to residual Merchant dependencies."""

    return ResidualMerchantDependencies(
        MERCHANT_MANAGER_AGENT=(
            MERCHANT_MANAGER_AGENT
        ),
        _merchant_resolution_invocation_query=(
            _merchant_resolution_invocation_query
        ),
        clear_pending_document_revision_resolution=(
            clear_pending_document_revision_resolution
        ),
        clear_pending_merchant_resolution=(
            clear_pending_merchant_resolution
        ),
        clear_pending_project_resolution=(
            clear_pending_project_resolution
        ),
        clear_pending_step_resolution=(
            clear_pending_step_resolution
        ),
        json=(
            json
        ),
        shlex=(
            shlex
        ),
        unicodedata=(
            unicodedata
        ),
        validate_merchant_resolution_result=(
            validate_merchant_resolution_result
        ),
    )



def _merchant_resolution_invocation_query(
    payload: dict[str, Any],
) -> str:
    """Compatibility adapter for extracted Merchant helper."""

    return _resolution_invocation_query_impl(
        payload=payload,
        dependencies=(
            _residual_merchant_dependencies()
        ),
    )


def merchant_resolution_from_tool_response(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Compatibility adapter for extracted Merchant helper."""

    return _resolution_from_tool_response_impl(
        payload=payload,
        dependencies=(
            _residual_merchant_dependencies()
        ),
    )


def _resolution_staging_dependencies(
) -> ResolutionStagingDependencies:
    """Bind current hook dependencies for resolution staging.

    Keeping this adapter in the hook preserves the existing dependency
    injection / monkeypatch seam while entity staging lives in its own module.
    """

    return ResolutionStagingDependencies(
        load_pending_merchant_resolution=(
            load_pending_merchant_resolution
        ),
        pending_merchant_resolution_matches=(
            pending_merchant_resolution_matches
        ),
        load_pending_project_resolution=(
            load_pending_project_resolution
        ),
        pending_project_resolution_matches=(
            pending_project_resolution_matches
        ),
        project_resolution_receipt_matches=(
            project_resolution_receipt_matches
        ),
        stage_pending_project_resolution=(
            stage_pending_project_resolution
        ),
        stage_pending_document_revision_resolution=(
            stage_pending_document_revision_resolution
        ),
        stage_pending_step_resolution=(
            stage_pending_step_resolution
        ),
    )


def _stage_exact_tmux_project_resolution(
    *,
    payload: dict[str, Any],
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    authorized_operations: Any,
) -> bool:
    """Compatibility adapter for Project resolution staging."""

    return _resolution_stage_project(
        payload=payload,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        authorized_operations=authorized_operations,
        dependencies=(
            _resolution_staging_dependencies()
        ),
    )


def _stage_exact_tmux_document_revision_resolution(
    *,
    payload: dict[str, Any],
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    authorized_operations: Any,
) -> bool:
    """Compatibility adapter for Document Revision staging."""

    return _resolution_stage_document(
        payload=payload,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        authorized_operations=authorized_operations,
        dependencies=(
            _resolution_staging_dependencies()
        ),
    )


def _stage_exact_tmux_step_resolution(
    *,
    payload: dict[str, Any],
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    authorized_operations: Any,
) -> bool:
    """Compatibility adapter for Step resolution staging."""

    return _resolution_stage_step(
        payload=payload,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        authorized_operations=authorized_operations,
        dependencies=(
            _resolution_staging_dependencies()
        ),
    )




def _merchant_staging_dependencies(
) -> MerchantStagingDependencies:
    """Bind current hook dependencies for Merchant staging."""

    return MerchantStagingDependencies(
        trusted_post_tool_sender=(
            trusted_post_tool_sender
        ),
        find_unique_active_teammate_owner=(
            find_unique_active_teammate_owner
        ),
        stage_pending_merchant_resolution=(
            stage_pending_merchant_resolution
        ),
        stage_pending_merchant_proposal=(
            stage_pending_merchant_proposal
        ),
        stage_pending_merchant_completeness=(
            stage_pending_merchant_completeness
        ),
    )


def _stage_exact_tmux_merchant_resolution(
    payload: dict[str, Any],
    session_id: Any,
    resolution: dict[str, Any],
) -> bool:
    """Compatibility adapter for Merchant resolution staging."""

    return _merchant_stage_resolution(
        payload,
        session_id,
        resolution,
        dependencies=(
            _merchant_staging_dependencies()
        ),
    )


def _trusted_tmux_merchant_stage_context(
    *,
    payload: dict[str, Any],
    session_id: Any,
) -> tuple[
    str,
    str,
    str,
    str,
    str,
    list[str],
] | None:
    """Compatibility adapter for trusted Merchant task context."""

    return _merchant_stage_context(
        payload=payload,
        session_id=session_id,
        dependencies=(
            _merchant_staging_dependencies()
        ),
    )


def _stage_exact_tmux_merchant_proposal(
    payload: dict[str, Any],
    session_id: Any,
    proposal: dict[str, Any],
) -> bool:
    """Compatibility adapter for Merchant proposal staging."""

    return _merchant_stage_proposal(
        payload,
        session_id,
        proposal,
        dependencies=(
            _merchant_staging_dependencies()
        ),
    )


def _stage_exact_tmux_merchant_completeness(
    payload: dict[str, Any],
    session_id: Any,
    result: dict[str, Any],
) -> bool:
    """Compatibility adapter for Merchant completeness staging."""

    return _merchant_stage_completeness(
        payload,
        session_id,
        result,
        dependencies=(
            _merchant_staging_dependencies()
        ),
    )



def _clear_merchant_resolution_after_release(
    session_id: Any,
    teammate_name: str,
) -> None:
    """Compatibility adapter for extracted Merchant helper."""

    return _resolution_cleanup_impl(
        session_id=session_id,
        teammate_name=teammate_name,
        dependencies=(
            _residual_merchant_dependencies()
        ),
    )



def _merchant_runtime_dependencies(
) -> MerchantRuntimeDependencies:
    """Bind current hook symbols to Merchant runtime dependencies."""

    return MerchantRuntimeDependencies(
        MERCHANT_MANAGER_AGENT=(
            MERCHANT_MANAGER_AGENT
        ),
        MERCHANT_PROPOSE_OPERATION=(
            MERCHANT_PROPOSE_OPERATION
        ),
        _coalesced_text=(
            _coalesced_text
        ),
        capture_merchant_proposal_from_message=(
            capture_merchant_proposal_from_message
        ),
        capture_proposal_receipt=(
            capture_proposal_receipt
        ),
        contains_handoff_marker=(
            contains_handoff_marker
        ),
        find_unique_active_teammate_owner=(
            find_unique_active_teammate_owner
        ),
        handoff_candidate_from_message=(
            handoff_candidate_from_message
        ),
        load_pending_merchant_completeness=(
            load_pending_merchant_completeness
        ),
        locked_state=(
            locked_state
        ),
        merchant_proposal_candidate_from_message=(
            merchant_proposal_candidate_from_message
        ),
        merchant_report_sender=(
            merchant_report_sender
        ),
        pending_merchant_completeness_matches=(
            pending_merchant_completeness_matches
        ),
        send_message_body=(
            send_message_body
        ),
        shlex=(
            shlex
        ),
        stage_runtime_handoff_attempt=(
            stage_runtime_handoff_attempt
        ),
        trusted_post_tool_sender=(
            trusted_post_tool_sender
        ),
        trusted_teammate_pane_session_matches=(
            trusted_teammate_pane_session_matches
        ),
    )



def _project_resolve_invocation(
    command: Any,
) -> tuple[str, str] | None:
    """Compatibility adapter for extracted Merchant runtime orchestration."""

    return _runtime_project_resolve_invocation(
        command=command,
        dependencies=(
            _merchant_runtime_dependencies()
        ),
    )


def prepare_merchant_runtime_handoff(
    payload: dict[str, Any],
) -> tuple[
    bool,
    PreparedRuntimeHandoff | None,
    str,
]:
    """Compatibility adapter for extracted Merchant runtime orchestration."""

    return _runtime_prepare_merchant_runtime_handoff(
        payload=payload,
        dependencies=(
            _merchant_runtime_dependencies()
        ),
    )


def bound_merchant_completeness_receipt(
    *,
    pane_session_id: str,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Compatibility adapter for extracted Merchant runtime orchestration."""

    return _runtime_bound_merchant_completeness_receipt(
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        dependencies=(
            _merchant_runtime_dependencies()
        ),
    )


def capture_merchant_proposal_from_message(
    state: dict[str, Any],
    session_id: Any,
    teammate_name: str,
    message: str,
) -> bool:
    """Compatibility adapter for extracted Merchant runtime orchestration."""

    return _runtime_capture_merchant_proposal_from_message(
        state=state,
        session_id=session_id,
        teammate_name=teammate_name,
        message=message,
        dependencies=(
            _merchant_runtime_dependencies()
        ),
    )


def handle_merchant_proposal_receipt(
    state: dict[str, Any],
    payload: dict[str, Any],
    session_id: Any = None,
) -> bool:
    """Compatibility adapter for extracted Merchant runtime orchestration."""

    return _runtime_handle_merchant_proposal_receipt(
        state=state,
        payload=payload,
        session_id=session_id,
        dependencies=(
            _merchant_runtime_dependencies()
        ),
    )






from claude.hooks.merchant_tool_result_contract import (
    merchant_execute_from_tool_response,
)
from claude.hooks.merchant_execute_invocation import (
    validated_merchant_execute_invocation,
)

def _post_tool_dependencies(
) -> PostToolDependencies:
    """Bind current hook symbols to the explicit PostTool contract."""

    return PostToolDependencies(
        MERCHANT_MANAGER_AGENT=(
            MERCHANT_MANAGER_AGENT
        ),
        MERCHANT_PROPOSE_OPERATION=(
            MERCHANT_PROPOSE_OPERATION
        ),
        _coalesced_text=(
            _coalesced_text
        ),
        _stage_exact_tmux_document_revision_resolution=(
            _stage_exact_tmux_document_revision_resolution
        ),
        _stage_exact_tmux_merchant_completeness=(
            _stage_exact_tmux_merchant_completeness
        ),
        _stage_exact_tmux_merchant_proposal=(
            _stage_exact_tmux_merchant_proposal
        ),
        _stage_exact_tmux_merchant_resolution=(
            _stage_exact_tmux_merchant_resolution
        ),
        _stage_exact_tmux_project_resolution=(
            _stage_exact_tmux_project_resolution
        ),
        _stage_exact_tmux_step_resolution=(
            _stage_exact_tmux_step_resolution
        ),
        _trusted_tmux_merchant_stage_context=(
            _trusted_tmux_merchant_stage_context
        ),
        active_task_id=(
            active_task_id
        ),
        find_unique_active_teammate_owner=(
            find_unique_active_teammate_owner
        ),
        mark_report_received=(
            mark_report_received
        ),
        merchant_completeness_from_tool_response=(
            merchant_completeness_from_tool_response
        ),
        merchant_proposal_from_tool_response=(
            merchant_proposal_from_tool_response
        ),
        merchant_execute_from_tool_response=(
            merchant_execute_from_tool_response
        ),
        validated_merchant_execute_invocation=(
            validated_merchant_execute_invocation
        ),
        merchant_resolution_from_tool_response=(
            merchant_resolution_from_tool_response
        ),
        record_teammate_result=(
            record_teammate_result
        ),
        send_message_body=(
            send_message_body
        ),
        stage_pending_result=(
            stage_pending_result
        ),
        trusted_post_tool_sender=(
            trusted_post_tool_sender
        ),
    )



def handle_post_tool_use(
    state: dict[str, Any] | None,
    payload: dict[str, Any],
    session_id: Any = None,
) -> None:
    """Compatibility adapter for extracted PostToolUse orchestration."""

    return _post_tool_handle(
        state=state,
        payload=payload,
        session_id=session_id,
        dependencies=(
            _post_tool_dependencies()
        ),
    )






def _reconcile_direct_merchant_writes(
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
) -> bool:
    """Trusted database reconciliation, never agent-provided data."""
    from claude.clients.merchant.repository import MerchantRepository
    from claude.hooks.merchant_direct_completion import (
        reconcile_all_direct_writes,
    )

    def repository_factory(database: str):
        if database not in {"test", "runtime"}:
            raise ValueError("Unapproved database target")
        return MerchantRepository(role=database)

    return reconcile_all_direct_writes(
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        repository_factory=repository_factory,
    )


def _teammate_idle_dependencies(
) -> TeammateIdleDependencies:
    """Bind current hook symbols to TeammateIdle dependencies."""

    return TeammateIdleDependencies(
        reconcile_direct_writes=(
            _reconcile_direct_merchant_writes
        ),
        MERCHANT_APPLY_FAILED_OUTCOME=(
            MERCHANT_APPLY_FAILED_OUTCOME
        ),
        MERCHANT_APPLY_SUCCESS_OUTCOME=(
            MERCHANT_APPLY_SUCCESS_OUTCOME
        ),
        MERCHANT_MANAGER_AGENT=(
            MERCHANT_MANAGER_AGENT
        ),
        MERCHANT_PROPOSAL_READY_OUTCOME=(
            MERCHANT_PROPOSAL_READY_OUTCOME
        ),
        MERCHANT_PROPOSE_OPERATION=(
            MERCHANT_PROPOSE_OPERATION
        ),
        MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES=(
            MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES
        ),
        MISSING_RESULT_FEEDBACK=(
            MISSING_RESULT_FEEDBACK
        ),
        PENDING_RESULT_FEEDBACK=(
            PENDING_RESULT_FEEDBACK
        ),
        _clear_merchant_resolution_after_release=(
            _clear_merchant_resolution_after_release
        ),
        active_task_id=(
            active_task_id
        ),
        bind_reported_teammate_pane_session=(
            bind_reported_teammate_pane_session
        ),
        bound_merchant_completeness_receipt=(
            bound_merchant_completeness_receipt
        ),
        bounded_terminal_result_failure=(
            bounded_terminal_result_failure
        ),
        capture_proposal_receipt=(
            capture_proposal_receipt
        ),
        clear_pending_merchant_completeness=(
            clear_pending_merchant_completeness
        ),
        clear_pending_merchant_proposal=(
            clear_pending_merchant_proposal
        ),
        clear_pending_result=(
            clear_pending_result
        ),
        failed_runtime_handoff_matches=(
            failed_runtime_handoff_matches
        ),
        find_unique_active_teammate_owner=(
            find_unique_active_teammate_owner
        ),
        load_pending_merchant_proposal=(
            load_pending_merchant_proposal
        ),
        load_pending_result=(
            load_pending_result
        ),
        load_team_state=(
            load_team_state
        ),
        locked_state=(
            locked_state
        ),
        mark_bound_report_received=(
            mark_bound_report_received
        ),
        mark_recovery_sent=(
            mark_recovery_sent
        ),
        mark_report_received=(
            mark_report_received
        ),
        pending_merchant_proposal_matches=(
            pending_merchant_proposal_matches
        ),
        record_teammate_result=(
            record_teammate_result
        ),
        release_reported_teammate_to_idle=(
            release_reported_teammate_to_idle
        ),
        successful_runtime_handoff_matches=(
            successful_runtime_handoff_matches
        ),
        task_result_candidate_from_message=(
            task_result_candidate_from_message
        ),
        validate_completeness_receipt_for_outcome=(
            validate_completeness_receipt_for_outcome
        ),
        proposal_requires_local_auto_receipt=(
            proposal_requires_local_auto_receipt
        ),
    )



def handle_teammate_idle(
    state: dict[str, Any] | None,
    payload: dict[str, Any],
    session_id: Any = None,
) -> str:
    """Compatibility adapter for extracted TeammateIdle orchestration."""

    return _teammate_idle_handle(
        state=state,
        payload=payload,
        session_id=session_id,
        dependencies=(
            _teammate_idle_dependencies()
        ),
    )




def _dispatcher_dependencies(
) -> DispatcherDependencies:
    """Bind current hook symbols to dispatcher dependencies."""

    return DispatcherDependencies(
        HOOK_EVENT_NAMES=(
            HOOK_EVENT_NAMES
        ),
        MerchantRuntimeHandoffStageError=(
            MerchantRuntimeHandoffStageError
        ),
        bounded_runtime_apply_failure=(
            bounded_runtime_apply_failure
        ),
        bounded_runtime_apply_result=(
            bounded_runtime_apply_result
        ),
        emit_post_tool_context=(
            emit_post_tool_context
        ),
        handle_merchant_proposal_receipt=(
            handle_merchant_proposal_receipt
        ),
        handle_post_tool_use=(
            handle_post_tool_use
        ),
        handle_teammate_idle=(
            handle_teammate_idle
        ),
        invoke_confirmed_merchant_session_apply=(
            invoke_confirmed_merchant_session_apply
        ),
        io=(
            io
        ),
        json=(
            json
        ),
        locked_state=(
            locked_state
        ),
        prepare_merchant_runtime_handoff=(
            prepare_merchant_runtime_handoff
        ),
        record_runtime_handoff_result=(
            record_runtime_handoff_result
        ),
        redirect_stderr=(
            redirect_stderr
        ),
        redirect_stdout=(
            redirect_stdout
        ),
        sys=(
            sys
        ),
    )

def reconcile_reported_merchant_for_reuse(
    owner_session_id: Any,
    teammate_name: str,
) -> bool:
    """Replay trusted idle reconciliation for one completed Merchant report.

    This is a narrow recovery path for a missed live TeammateIdle event.
    REPORT_RECEIVED is not made reusable by status alone: the existing
    TeammateIdle orchestration must successfully validate and settle the
    exact persisted Merchant evidence first.
    """

    owner_id = str(
        owner_session_id
        or ""
    ).strip()

    teammate = str(
        teammate_name
        or ""
    ).strip()

    if (
        not owner_id
        or teammate
        != MERCHANT_MANAGER_AGENT
    ):
        return False

    team_state = load_team_state(
        owner_id
    )

    if not isinstance(
        team_state,
        dict,
    ):
        return False

    record = (
        team_state.get(
            "teammates",
            {},
        ).get(
            teammate
        )
    )

    if not isinstance(
        record,
        dict,
    ):
        return False

    if (
        record.get("status")
        != "REPORT_RECEIVED"
        or record.get(
            "result_received"
        )
        is not True
        or record.get(
            "report_source"
        )
        != "sendmessage"
    ):
        return False

    run_id = str(
        record.get(
            "current_run_id"
        )
        or ""
    ).strip()

    task_id = str(
        record.get(
            "current_task_id"
        )
        or ""
    ).strip()

    pane_session_id = str(
        record.get(
            "trusted_pane_session_id"
        )
        or ""
    ).strip()

    if (
        not run_id
        or not task_id
        or not pane_session_id
    ):
        return False

    feedback = handle_teammate_idle(
        None,
        {
            "hook_event_name": "TeammateIdle",
            "session_id": pane_session_id,
            "agent_type": teammate,
            "teammate_name": teammate,
        },
        pane_session_id,
    )

    if feedback:
        return False

    settled_state = load_team_state(
        owner_id
    )

    if not isinstance(
        settled_state,
        dict,
    ):
        return False

    settled_record = (
        settled_state.get(
            "teammates",
            {},
        ).get(
            teammate
        )
    )

    return (
        isinstance(
            settled_record,
            dict,
        )
        and settled_record.get(
            "status"
        )
        == "IDLE_REUSABLE"
        and settled_record.get(
            "last_completed_task_id"
        )
        == task_id
        and settled_record.get(
            "current_run_id"
        )
        is None
        and settled_record.get(
            "current_task_id"
        )
        is None
    )

def main() -> None:
    """Compatibility entrypoint for extracted hook dispatcher."""

    return _dispatch_main(
        dependencies=(
            _dispatcher_dependencies()
        ),
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
