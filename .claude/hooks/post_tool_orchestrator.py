"""PostToolUse orchestration extracted from team_result_hook.

This module preserves the existing ordered Merchant staging, hierarchical
resolution, runtime handoff, and SendMessage result-delivery behavior.

Dependencies are provided by the hook at call time so monkeypatch and test
seams remain compatible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

try:
    from team_result_dependency_protocols import (
        MerchantCompletenessStageFn,
        MerchantProposalStageFn,
        MerchantResolutionStageFn,
        ResolutionStageFn,
        ActiveTaskIdFn,
        CoalescedTextFn,
        SendMessageBodyFn,
        ToolResponseCandidateFn,
        TrustedTmuxMerchantStageContextFn,
        MarkReportReceivedFn,
        StagePendingResultFn,
        FindUniqueActiveTeammateOwnerFn,
        RecordTeammateResultFn,
        TrustedPostToolSenderFn,
    )
except ImportError:
    from .team_result_dependency_protocols import (
        MerchantCompletenessStageFn,
        MerchantProposalStageFn,
        MerchantResolutionStageFn,
        ResolutionStageFn,
        ActiveTaskIdFn,
        CoalescedTextFn,
        SendMessageBodyFn,
        ToolResponseCandidateFn,
        TrustedTmuxMerchantStageContextFn,
        MarkReportReceivedFn,
        StagePendingResultFn,
        FindUniqueActiveTeammateOwnerFn,
        RecordTeammateResultFn,
        TrustedPostToolSenderFn,
    )




ValidatedMerchantExecuteInvocationFn = Callable[
    [dict[str, Any], dict[str, Any]],
    tuple[str, ...] | None,
]

@dataclass(frozen=True)
class PostToolDependencies:
    """Explicit dependencies required by PostToolUse orchestration."""

    MERCHANT_MANAGER_AGENT: str
    MERCHANT_PROPOSE_OPERATION: str
    _coalesced_text: CoalescedTextFn
    _stage_exact_tmux_document_revision_resolution: ResolutionStageFn
    _stage_exact_tmux_merchant_completeness: MerchantCompletenessStageFn
    _stage_exact_tmux_merchant_proposal: MerchantProposalStageFn
    _stage_exact_tmux_merchant_resolution: MerchantResolutionStageFn
    _stage_exact_tmux_project_resolution: ResolutionStageFn
    _stage_exact_tmux_step_resolution: ResolutionStageFn
    _trusted_tmux_merchant_stage_context: TrustedTmuxMerchantStageContextFn
    active_task_id: ActiveTaskIdFn
    find_unique_active_teammate_owner: FindUniqueActiveTeammateOwnerFn
    mark_report_received: MarkReportReceivedFn
    merchant_completeness_from_tool_response: ToolResponseCandidateFn
    merchant_proposal_from_tool_response: ToolResponseCandidateFn
    merchant_execute_from_tool_response: ToolResponseCandidateFn
    validated_merchant_execute_invocation: ValidatedMerchantExecuteInvocationFn
    merchant_resolution_from_tool_response: ToolResponseCandidateFn
    record_teammate_result: RecordTeammateResultFn
    send_message_body: SendMessageBodyFn
    stage_pending_result: StagePendingResultFn
    trusted_post_tool_sender: TrustedPostToolSenderFn



def handle_post_tool_use(
    state: dict[str, Any] | None,
    payload: dict[str, Any],
    session_id: Any = None,
    dependencies: PostToolDependencies | None = None,
) -> None:
    """Handle exact Merchant CLI staging plus canonical SendMessage delivery."""

    if dependencies is None:
        raise RuntimeError(
            "PostToolUse dependencies are required"
        )

    MERCHANT_MANAGER_AGENT = (
        dependencies.MERCHANT_MANAGER_AGENT
    )

    MERCHANT_PROPOSE_OPERATION = (
        dependencies.MERCHANT_PROPOSE_OPERATION
    )

    _coalesced_text = (
        dependencies._coalesced_text
    )

    _stage_exact_tmux_document_revision_resolution = (
        dependencies._stage_exact_tmux_document_revision_resolution
    )

    _stage_exact_tmux_merchant_completeness = (
        dependencies._stage_exact_tmux_merchant_completeness
    )

    _stage_exact_tmux_merchant_proposal = (
        dependencies._stage_exact_tmux_merchant_proposal
    )

    _stage_exact_tmux_merchant_resolution = (
        dependencies._stage_exact_tmux_merchant_resolution
    )

    _stage_exact_tmux_project_resolution = (
        dependencies._stage_exact_tmux_project_resolution
    )

    _stage_exact_tmux_step_resolution = (
        dependencies._stage_exact_tmux_step_resolution
    )

    _trusted_tmux_merchant_stage_context = (
        dependencies._trusted_tmux_merchant_stage_context
    )

    active_task_id = (
        dependencies.active_task_id
    )

    find_unique_active_teammate_owner = (
        dependencies.find_unique_active_teammate_owner
    )

    mark_report_received = (
        dependencies.mark_report_received
    )

    merchant_completeness_from_tool_response = (
        dependencies.merchant_completeness_from_tool_response
    )

    merchant_proposal_from_tool_response = (
        dependencies.merchant_proposal_from_tool_response
    )

    merchant_execute_from_tool_response = (
        dependencies.merchant_execute_from_tool_response
    )

    validated_merchant_execute_invocation = (
        dependencies.validated_merchant_execute_invocation
    )

    merchant_resolution_from_tool_response = (
        dependencies.merchant_resolution_from_tool_response
    )

    record_teammate_result = (
        dependencies.record_teammate_result
    )

    send_message_body = (
        dependencies.send_message_body
    )

    stage_pending_result = (
        dependencies.stage_pending_result
    )

    trusted_post_tool_sender = (
        dependencies.trusted_post_tool_sender
    )

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    completeness = (
        merchant_completeness_from_tool_response(
            payload
        )
    )

    if completeness is not None:
        _stage_exact_tmux_merchant_completeness(
            payload,
            session_id,
            completeness,
        )

    resolution = (
        merchant_resolution_from_tool_response(
            payload
        )
    )

    if resolution is not None:
        _stage_exact_tmux_merchant_resolution(
            payload,
            session_id,
            resolution,
        )

    # ------------------------------------------------------------
    # Exact hierarchical entity-resolution staging.
    #
    # These helpers inspect the exact Bash command themselves and
    # fail closed when the command family does not match.
    #
    # merchant resolve
    #     -> Merchant receipt
    #
    # project resolve
    #     -> requires current-task Merchant receipt
    #     -> Project receipt
    #
    # step resolve
    #     -> requires current-task Merchant + Project receipts
    #     -> Step receipt
    # ------------------------------------------------------------

    if tool_name == "Bash":
        tmux_context = (
            _trusted_tmux_merchant_stage_context(
                payload=payload,
                session_id=session_id,
            )
        )

        if tmux_context is not None:
            (
                pane_session_id,
                owner_session_id,
                teammate_name,
                run_id,
                task_id,
                authorized_operations,
            ) = tmux_context

            _stage_exact_tmux_project_resolution(
                payload=payload,
                pane_session_id=(
                    pane_session_id
                ),
                owner_session_id=(
                    owner_session_id
                ),
                teammate_name=(
                    teammate_name
                ),
                run_id=run_id,
                task_id=task_id,
                authorized_operations=(
                    authorized_operations
                ),
            )

            _stage_exact_tmux_step_resolution(
                payload=payload,
                pane_session_id=(
                    pane_session_id
                ),
                owner_session_id=(
                    owner_session_id
                ),
                teammate_name=(
                    teammate_name
                ),
                run_id=run_id,
                task_id=task_id,
                authorized_operations=(
                    authorized_operations
                ),
            )

            _stage_exact_tmux_document_revision_resolution(
                payload=payload,
                pane_session_id=pane_session_id,
                owner_session_id=owner_session_id,
                teammate_name=teammate_name,
                run_id=run_id,
                task_id=task_id,
                authorized_operations=authorized_operations,
            )

    # ------------------------------------------------------------
    # Gate 11I exact CLI path.
    #
    # This MUST execute before the SendMessage-only return because
    # Merchant CLI proposal output arrives through Bash/PowerShell.
    # ------------------------------------------------------------
    proposal = (
        merchant_proposal_from_tool_response(
            payload
        )
    )

    if proposal is not None:
        _stage_exact_tmux_merchant_proposal(
            payload,
            session_id,
            proposal,
        )

    # Direct Execute observation only.
    # Do not stage trusted evidence or transition lifecycle here.
    execute_result = merchant_execute_from_tool_response(payload)

    if execute_result is not None:
        validated_merchant_execute_invocation(
            payload,
            execute_result,
        )

    # ------------------------------------------------------------
    # SendMessage remains the machine-verifiable result-delivery path.
    # ------------------------------------------------------------
    if (
        tool_name
        != "SendMessage"
    ):
        return

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return

    # recipient/to are true aliases and must agree when both are present.
    to_field = (
        _coalesced_text(
            tool_input,
            "recipient",
            "to",
        )
    )

    if (
        to_field
        != "team-lead"
    ):
        return

    # Gate 11H: prefer full `message`; legacy `content` is fallback only.
    message = (
        send_message_body(
            tool_input
        )
    )

    if not message:
        return

    teammate_name = (
        trusted_post_tool_sender(
            payload
        )
    )

    # ------------------------------------------------------------
    # tmux / pane-backed teammate.
    #
    # No trusted agent_id is available here. `agent_type` is only a role
    # hint used to find exactly one active lifecycle owner. TeammateIdle
    # later supplies trusted teammate_name.
    # ------------------------------------------------------------
    if not teammate_name:
        tmux_role_hint = str(
            payload.get(
                "agent_type"
            )
            or ""
        ).strip()

        if not (
            session_id
            and tmux_role_hint
        ):
            return

        (
            owner_session_id,
            owner_record,
            owner_resolution,
        ) = (
            find_unique_active_teammate_owner(
                tmux_role_hint
            )
        )

        if (
            owner_resolution
            != "FOUND"
            or not owner_session_id
            or not isinstance(
                owner_record,
                dict,
            )
        ):
            return

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
            return

        owner_operations = [
            str(operation)
            for operation in (
                owner_record.get(
                    "authorized_operations"
                )
                or []
            )
        ]

        owner_selected_agents = [
            str(agent)
            for agent in (
                owner_record.get(
                    "authorized_selected_agents"
                )
                or []
            )
        ]

        stage_pending_result(
            session_id=(
                session_id
            ),
            message=(
                message
            ),
            tool_use_id=str(
                payload.get(
                    "tool_use_id"
                )
                or ""
            ).strip(),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                tmux_role_hint
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            operations=(
                owner_operations
            ),
            selected_agents=(
                owner_selected_agents
            ),
        )

        return

    # ------------------------------------------------------------
    # Gate 12C.9A:
    #
    # An authenticated teammate pane may provide both agent_id and
    # agent_type. Authentication proves sender identity, but it does
    # NOT mean a Merchant terminal result is already trustworthy.
    #
    # For an exact merchant-manager / merchant_propose owner binding,
    # defer REPORT_RECEIVED until TeammateIdle validates the staged
    # TEAM_RESULT_JSON against deterministic completeness/proposal
    # evidence.
    #
    # This intentionally mirrors the tmux role-hint staging path.
    # ------------------------------------------------------------
    if (
        teammate_name
        == MERCHANT_MANAGER_AGENT
        and session_id
    ):
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
            owner_resolution == "FOUND"
            and owner_session_id
            and isinstance(
                owner_record,
                dict,
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

            owner_operations = [
                str(operation)
                for operation in (
                    owner_record.get(
                        "authorized_operations"
                    )
                    or []
                )
            ]

            owner_selected_agents = [
                str(agent)
                for agent in (
                    owner_record.get(
                        "authorized_selected_agents"
                    )
                    or []
                )
            ]

            requires_deferred_merchant_result = (
                owner_run_id
                and owner_task_id
                and owner_selected_agents
                == [
                    MERCHANT_MANAGER_AGENT
                ]
                and owner_operations
                in (
                    [
                        MERCHANT_PROPOSE_OPERATION
                    ],
                    [
                        "merchant_apply"
                    ],
                )
            )

            if requires_deferred_merchant_result:
                stage_pending_result(
                    session_id=session_id,
                    message=message,
                    tool_use_id=str(
                        payload.get(
                            "tool_use_id"
                        )
                        or ""
                    ).strip(),
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
                    operations=(
                        owner_operations
                    ),
                    selected_agents=(
                        owner_selected_agents
                    ),
                )

                # Critical Gate 12C invariant:
                # do NOT call record_teammate_result()
                # or mark_report_received() yet.
                #
                # TeammateIdle is responsible for validating
                # completeness/proposal evidence first.
                return

    # ------------------------------------------------------------
    # Authenticated non-tmux teammate path.
    # ------------------------------------------------------------
    task_id = str(
        tool_input.get(
            "task_id"
        )
        or ""
    ).strip()

    if not task_id:
        task_id = str(
            payload.get(
                "task_id"
            )
            or ""
        ).strip()

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
            return

        task_id = (
            current_task_id
        )

    if not (
        teammate_name
        and task_id
    ):
        return

    if state is not None:
        record_teammate_result(
            state,
            teammate_name,
            task_id,
            "sendmessage",
        )

    if session_id:
        mark_report_received(
            session_id,
            teammate_name,
            task_id,
            "sendmessage",
        )

