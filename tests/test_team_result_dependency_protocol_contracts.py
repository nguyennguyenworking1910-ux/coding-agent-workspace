from __future__ import annotations

import ast
from pathlib import Path


DEPENDENCY_MODULES = {
    Path(
        ".claude/hooks/post_tool_orchestrator.py"
    ): {
        "find_unique_active_teammate_owner":
            "FindUniqueActiveTeammateOwnerFn",
        "record_teammate_result":
            "RecordTeammateResultFn",
        "trusted_post_tool_sender":
            "TrustedPostToolSenderFn",
        "mark_report_received":
            "MarkReportReceivedFn",
        "stage_pending_result":
            "StagePendingResultFn",
        "_coalesced_text":
            "CoalescedTextFn",
        "_trusted_tmux_merchant_stage_context":
            "TrustedTmuxMerchantStageContextFn",
        "merchant_completeness_from_tool_response":
            "ToolResponseCandidateFn",
        "merchant_proposal_from_tool_response":
            "ToolResponseCandidateFn",
        "merchant_resolution_from_tool_response":
            "ToolResponseCandidateFn",
        "send_message_body":
            "SendMessageBodyFn",
        "active_task_id":
            "ActiveTaskIdFn",
        "_stage_exact_tmux_document_revision_resolution":
            "ResolutionStageFn",
        "_stage_exact_tmux_merchant_completeness":
            "MerchantCompletenessStageFn",
        "_stage_exact_tmux_merchant_proposal":
            "MerchantProposalStageFn",
        "_stage_exact_tmux_merchant_resolution":
            "MerchantResolutionStageFn",
        "_stage_exact_tmux_project_resolution":
            "ResolutionStageFn",
        "_stage_exact_tmux_step_resolution":
            "ResolutionStageFn",
    },

    Path(
        ".claude/hooks/merchant_runtime_orchestration.py"
    ): {
        "find_unique_active_teammate_owner":
            "FindUniqueActiveTeammateOwnerFn",
        "locked_state":
            "LockedStateFn",
        "trusted_post_tool_sender":
            "TrustedPostToolSenderFn",
        "trusted_teammate_pane_session_matches":
            "TrustedTeammatePaneSessionMatchesFn",
        "capture_proposal_receipt":
            "CaptureProposalReceiptFn",
        "stage_runtime_handoff_attempt":
            "StageRuntimeHandoffAttemptFn",
        "contains_handoff_marker":
            "ContainsHandoffMarkerFn",
        "pending_merchant_completeness_matches":
            "PendingMerchantCompletenessMatchesFn",
        "capture_merchant_proposal_from_message":
            "CaptureMerchantProposalFromMessageFn",
        "load_pending_merchant_completeness":
            "LoadPendingMerchantCompletenessFn",
        "_coalesced_text":
            "CoalescedTextFn",
        "handoff_candidate_from_message":
            "HandoffCandidateFromMessageFn",
        "merchant_proposal_candidate_from_message":
            "MessageCandidateFn",
        "merchant_report_sender":
            "MerchantReportSenderFn",
        "send_message_body":
            "SendMessageBodyFn",
    },

    Path(
        ".claude/hooks/teammate_idle_orchestrator.py"
    ): {
        "find_unique_active_teammate_owner":
            "FindUniqueActiveTeammateOwnerFn",
        "locked_state":
            "LockedStateFn",
        "record_teammate_result":
            "RecordTeammateResultFn",
        "release_reported_teammate_to_idle":
            "ReleaseReportedTeammateToIdleFn",
        "capture_proposal_receipt":
            "CaptureProposalReceiptFn",
        "validate_completeness_receipt_for_outcome":
            "ValidateCompletenessReceiptForOutcomeFn",
        "failed_runtime_handoff_matches":
            "RuntimeHandoffMatchesFn",
        "pending_merchant_proposal_matches":
            "PendingMerchantProposalMatchesFn",
        "successful_runtime_handoff_matches":
            "RuntimeHandoffMatchesFn",
        "bind_reported_teammate_pane_session":
            "BindReportedTeammatePaneSessionFn",
        "clear_pending_merchant_completeness":
            "ClearPendingMerchantCompletenessFn",
        "clear_pending_merchant_proposal":
            "ClearPendingReceiptFn",
        "clear_pending_result":
            "ClearPendingReceiptFn",
        "load_pending_merchant_proposal":
            "LoadPendingStateFn",
        "load_pending_result":
            "LoadPendingStateFn",
        "load_team_state":
            "LoadPendingStateFn",
        "mark_bound_report_received":
            "MarkBoundReportReceivedFn",
        "mark_recovery_sent":
            "MarkRecoverySentFn",
        "mark_report_received":
            "MarkReportReceivedFn",
        "active_task_id":
            "ActiveTaskIdFn",
        "bound_merchant_completeness_receipt":
            "BoundMerchantCompletenessReceiptFn",
        "task_result_candidate_from_message":
            "MessageCandidateFn",
        "bounded_terminal_result_failure":
            "BoundedTerminalResultFailureFn",
        "_clear_merchant_resolution_after_release":
            "ClearMerchantResolutionAfterReleaseFn",
    },

    Path(
        ".claude/hooks/merchant_resolution_tool_contract.py"
    ): {
        "validate_merchant_resolution_result":
            "ValidateMerchantResolutionResultFn",
        "clear_pending_document_revision_resolution":
            "ClearPendingReceiptFn",
        "clear_pending_merchant_resolution":
            "ClearPendingReceiptFn",
        "clear_pending_project_resolution":
            "ClearPendingReceiptFn",
        "clear_pending_step_resolution":
            "ClearPendingReceiptFn",
        "_merchant_resolution_invocation_query":
            "MerchantResolutionInvocationQueryFn",
    },

    Path(
        ".claude/hooks/team_result_dispatcher.py"
    ): {
        "locked_state":
            "LockedStateFn",
        "invoke_confirmed_merchant_session_apply":
            "InvokeConfirmedMerchantSessionApplyFn",
        "record_runtime_handoff_result":
            "RecordRuntimeHandoffResultFn",
        "bounded_runtime_apply_failure":
            "BoundedRuntimeApplyFailureFn",
        "bounded_runtime_apply_result":
            "BoundedRuntimeApplyResultFn",
        "emit_post_tool_context":
            "EmitPostToolContextFn",
        "handle_merchant_proposal_receipt":
            "HandleMerchantProposalReceiptFn",
        "handle_post_tool_use":
            "HandlePostToolUseFn",
        "handle_teammate_idle":
            "HandleTeammateIdleFn",
        "prepare_merchant_runtime_handoff":
            "PrepareMerchantRuntimeHandoffFn",
    },
}


PROTOCOL_FILE = Path(
    ".claude/hooks/team_result_dependency_protocols.py"
)


def _dependency_annotations(
    path: Path,
) -> dict[str, str]:

    tree = ast.parse(
        path.read_text(
            encoding="utf-8-sig"
        )
    )

    contract = next(
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.ClassDef,
            )
            and node.name.endswith(
                "Dependencies"
            )
        )
    )

    return {
        node.target.id:
            ast.unparse(
                node.annotation
            )
        for node in contract.body
        if (
            isinstance(
                node,
                ast.AnnAssign,
            )
            and isinstance(
                node.target,
                ast.Name,
            )
        )
    }


def _protocol_names() -> set[str]:

    tree = ast.parse(
        PROTOCOL_FILE.read_text(
            encoding="utf-8-sig"
        )
    )

    return {
        node.name
        for node in tree.body
        if isinstance(
            node,
            ast.ClassDef,
        )
    }


def test_dependency_fields_use_expected_protocol_types():
    violations = []

    for (
        path,
        expected_fields,
    ) in DEPENDENCY_MODULES.items():

        actual = (
            _dependency_annotations(
                path
            )
        )

        for (
            field,
            expected_type,
        ) in expected_fields.items():

            actual_type = actual.get(
                field
            )

            if actual_type != expected_type:

                violations.append(
                    (
                        path.name,
                        field,
                        expected_type,
                        actual_type,
                    )
                )

    assert violations == [], (
        "Dependency Protocol mapping changed: "
        f"{violations}"
    )


def test_all_expected_protocol_types_exist():
    protocol_names = (
        _protocol_names()
    )

    expected = {
        protocol
        for fields
        in DEPENDENCY_MODULES.values()
        for protocol
        in fields.values()
    }

    missing = (
        expected
        - protocol_names
    )

    assert missing == set(), (
        "Dependency contracts reference missing "
        f"Protocol types: {sorted(missing)}"
    )


def test_protocol_module_contains_protocol_classes_only_for_callable_contracts():
    tree = ast.parse(
        PROTOCOL_FILE.read_text(
            encoding="utf-8-sig"
        )
    )

    invalid = []

    for node in tree.body:

        if not isinstance(
            node,
            ast.ClassDef,
        ):
            continue

        call_methods = [
            item
            for item in node.body
            if (
                isinstance(
                    item,
                    ast.FunctionDef,
                )
                and item.name
                == "__call__"
            )
        ]

        if len(call_methods) != 1:
            invalid.append(
                node.name
            )

    assert invalid == [], (
        "Callable dependency Protocols must define "
        f"exactly one __call__: {invalid}"
    )


def test_security_critical_protocols_have_precise_return_annotations():
    security_protocols = {
        "FindUniqueActiveTeammateOwnerFn",
        "LockedStateFn",
        "TrustedPostToolSenderFn",
        "TrustedTeammatePaneSessionMatchesFn",
        "ValidateMerchantResolutionResultFn",
        "CaptureProposalReceiptFn",
        "StageRuntimeHandoffAttemptFn",
        "ValidateCompletenessReceiptForOutcomeFn",
        "InvokeConfirmedMerchantSessionApplyFn",
        "ContainsHandoffMarkerFn",
        "PendingMerchantCompletenessMatchesFn",
        "PendingMerchantProposalMatchesFn",
        "RuntimeHandoffMatchesFn",
    }

    tree = ast.parse(
        PROTOCOL_FILE.read_text(
            encoding="utf-8-sig"
        )
    )

    classes = {
        node.name: node
        for node in tree.body
        if isinstance(
            node,
            ast.ClassDef,
        )
    }

    violations = []

    for name in security_protocols:

        protocol = classes.get(
            name
        )

        if protocol is None:
            violations.append(
                (
                    name,
                    "missing",
                )
            )
            continue

        call = next(
            (
                node
                for node in protocol.body
                if (
                    isinstance(
                        node,
                        ast.FunctionDef,
                    )
                    and node.name
                    == "__call__"
                )
            ),
            None,
        )

        if (
            call is None
            or call.returns is None
        ):
            violations.append(
                (
                    name,
                    "missing return annotation",
                )
            )
            continue

        return_type = ast.unparse(
            call.returns
        )

        if return_type == "Any":
            violations.append(
                (
                    name,
                    "Any",
                )
            )

    assert violations == [], (
        "Security-critical Protocol return types "
        f"must remain precise: {violations}"
    )
