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
        main as _dispatch_main,
    )
    from teammate_idle_orchestrator import (
        handle_teammate_idle as _teammate_idle_handle,
    )
    from post_tool_orchestrator import (
        handle_post_tool_use as _post_tool_handle,
    )
    from merchant_resolution_tool_contract import (
        _merchant_resolution_invocation_query as _resolution_invocation_query_impl,
        merchant_resolution_from_tool_response as _resolution_from_tool_response_impl,
    )
    from merchant_resolution_cleanup import (
        _clear_merchant_resolution_after_release as _resolution_cleanup_impl,
    )
    from merchant_runtime_orchestration import (
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
        main as _dispatch_main,
    )
    from .teammate_idle_orchestrator import (
        handle_teammate_idle as _teammate_idle_handle,
    )
    from .post_tool_orchestrator import (
        handle_post_tool_use as _post_tool_handle,
    )
    from .merchant_resolution_tool_contract import (
        _merchant_resolution_invocation_query as _resolution_invocation_query_impl,
        merchant_resolution_from_tool_response as _resolution_from_tool_response_impl,
    )
    from .merchant_resolution_cleanup import (
        _clear_merchant_resolution_after_release as _resolution_cleanup_impl,
    )
    from .merchant_runtime_orchestration import (
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



class _ResidualMerchantDependencyView:
    """Resolve residual Merchant dependencies from current hook globals."""

    def __getattr__(
        self,
        name: str,
    ) -> Any:

        try:
            return globals()[name]

        except KeyError as exc:
            raise AttributeError(
                name
            ) from exc


_RESIDUAL_MERCHANT_DEPENDENCIES = (
    _ResidualMerchantDependencyView()
)


def _merchant_resolution_invocation_query(
    payload: dict[str, Any],
) -> str:
    """Compatibility adapter for extracted Merchant helper."""

    return _resolution_invocation_query_impl(
        payload=payload,
        dependencies=(
            _RESIDUAL_MERCHANT_DEPENDENCIES
        ),
    )


def merchant_resolution_from_tool_response(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Compatibility adapter for extracted Merchant helper."""

    return _resolution_from_tool_response_impl(
        payload=payload,
        dependencies=(
            _RESIDUAL_MERCHANT_DEPENDENCIES
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
            _RESIDUAL_MERCHANT_DEPENDENCIES
        ),
    )


class _MerchantRuntimeDependencyView:
    """Resolve extracted runtime dependencies from current hook globals."""

    def __getattr__(
        self,
        name: str,
    ) -> Any:

        try:
            return globals()[
                name
            ]

        except KeyError as exc:
            raise AttributeError(
                name
            ) from exc


_MERCHANT_RUNTIME_DEPENDENCIES = (
    _MerchantRuntimeDependencyView()
)


def _project_resolve_invocation(
    command: Any,
) -> tuple[str, str] | None:
    """Compatibility adapter for extracted Merchant runtime orchestration."""

    return _runtime_project_resolve_invocation(
        command=command,
        dependencies=(
            _MERCHANT_RUNTIME_DEPENDENCIES
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
            _MERCHANT_RUNTIME_DEPENDENCIES
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
            _MERCHANT_RUNTIME_DEPENDENCIES
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
            _MERCHANT_RUNTIME_DEPENDENCIES
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
            _MERCHANT_RUNTIME_DEPENDENCIES
        ),
    )




class _PostToolDependencyView:
    """Resolve PostToolUse dependencies from current hook globals."""

    def __getattr__(
        self,
        name: str,
    ) -> Any:

        try:
            return globals()[
                name
            ]

        except KeyError as exc:
            raise AttributeError(
                name
            ) from exc


_POST_TOOL_DEPENDENCIES = (
    _PostToolDependencyView()
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
            _POST_TOOL_DEPENDENCIES
        ),
    )




class _TeammateIdleDependencyView:
    """Resolve TeammateIdle dependencies from current hook globals."""

    def __getattr__(
        self,
        name: str,
    ) -> Any:

        try:
            return globals()[name]

        except KeyError as exc:
            raise AttributeError(
                name
            ) from exc


_TEAMMATE_IDLE_DEPENDENCIES = (
    _TeammateIdleDependencyView()
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
            _TEAMMATE_IDLE_DEPENDENCIES
        ),
    )



class _DispatcherDependencyView:
    """Resolve dispatcher dependencies from current hook globals."""

    def __getattr__(
        self,
        name: str,
    ) -> Any:

        try:
            return globals()[name]

        except KeyError as exc:
            raise AttributeError(
                name
            ) from exc


_DISPATCHER_DEPENDENCIES = (
    _DispatcherDependencyView()
)


def main() -> None:
    """Compatibility entrypoint for extracted hook dispatcher."""

    return _dispatch_main(
        dependencies=(
            _DISPATCHER_DEPENDENCIES
        ),
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
