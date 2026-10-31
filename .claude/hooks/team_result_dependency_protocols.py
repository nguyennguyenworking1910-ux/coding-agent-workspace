"""Typed callable boundaries for team-result orchestration.

These Protocols describe stable cross-module call contracts only.
They intentionally contain no runtime orchestration logic.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TYPE_CHECKING


if TYPE_CHECKING:
    from claude.agents.tools.merchant.cli import (
        WriteCommandFactory,
    )
    from claude.hooks.merchant_completeness_gate import (
        CompletenessGateDecision,
    )
    from claude.hooks.merchant_runtime_handoff_gate import (
        PreparedRuntimeHandoff,
    )


class FindUniqueActiveTeammateOwnerFn(Protocol):
    def __call__(
        self,
        teammate_name: str,
    ) -> tuple[
        str | None,
        dict[str, Any] | None,
        str,
    ]:
        ...


class LockedStateFn(Protocol):
    def __call__(
        self,
        session_id: Any,
    ) -> AbstractContextManager[
        dict[str, Any] | None
    ]:
        ...


class RecordTeammateResultFn(Protocol):
    def __call__(
        self,
        state: dict[str, Any],
        teammate_name: str,
        task_id: str,
        source: str,
    ) -> bool:
        ...


class ReleaseReportedTeammateToIdleFn(Protocol):
    def __call__(
        self,
        session_id: Any,
        teammate_name: str,
    ) -> tuple[bool, str]:
        ...


class TrustedPostToolSenderFn(Protocol):
    def __call__(
        self,
        payload: dict[str, Any],
    ) -> str:
        ...


class TrustedTeammatePaneSessionMatchesFn(Protocol):
    def __call__(
        self,
        session_id: Any,
        teammate_name: str,
        pane_session_id: Any,
        run_id: str,
        task_id: str,
        *,
        required_operation: str,
    ) -> tuple[bool, str]:
        ...


class ValidateMerchantResolutionResultFn(Protocol):
    def __call__(
        self,
        value: Any,
    ) -> dict[str, Any] | None:
        ...


class StageRuntimeHandoffAttemptFn(Protocol):
    def __call__(
        self,
        state: dict[str, Any],
        *,
        owner_session_id: str,
        teammate_name: str,
        run_id: str,
        task_id: str,
        candidate: Mapping[str, Any],
    ) -> tuple[
        PreparedRuntimeHandoff | None,
        str,
    ]:
        ...


class ValidateCompletenessReceiptForOutcomeFn(Protocol):
    def __call__(
        self,
        outcome: dict[str, Any],
        receipt: dict[str, Any] | None,
    ) -> CompletenessGateDecision:
        ...


class ContainsHandoffMarkerFn(Protocol):
    def __call__(
        self,
        message: Any,
    ) -> bool:
        ...


class PendingMerchantCompletenessMatchesFn(Protocol):
    def __call__(
        self,
        receipt: dict[str, Any],
        *,
        owner_session_id: str,
        teammate_name: str,
        run_id: str,
        task_id: str,
    ) -> bool:
        ...


class MarkReportReceivedFn(Protocol):
    def __call__(
        self,
        session_id: Any,
        teammate_name: str,
        task_id: str,
        source: str,
    ) -> bool:
        ...


class StagePendingResultFn(Protocol):
    def __call__(
        self,
        *,
        session_id: Any,
        message: str,
        tool_use_id: str,
        owner_session_id: Any,
        teammate_name: str,
        run_id: str,
        task_id: str,
        operations: list[str] | None,
        selected_agents: list[str] | None,
    ) -> bool:
        ...


class LoadPendingMerchantCompletenessFn(Protocol):
    def __call__(
        self,
        pane_session_id: str,
    ) -> dict[str, Any] | None:
        ...


class ClearPendingMerchantCompletenessFn(Protocol):
    def __call__(
        self,
        pane_session_id: str,
    ) -> None:
        ...


class ClearPendingReceiptFn(Protocol):
    def __call__(
        self,
        receipt_id: Any,
    ) -> bool:
        ...


class LoadPendingStateFn(Protocol):
    def __call__(
        self,
        session_id: Any,
    ) -> dict[str, Any] | None:
        ...


class MarkBoundReportReceivedFn(Protocol):
    def __call__(
        self,
        session_id: Any,
        teammate_name: str,
        run_id: str,
        task_id: str,
        source: str,
    ) -> bool:
        ...


class MarkRecoverySentFn(Protocol):
    def __call__(
        self,
        state: dict[str, Any],
        teammate_name: str,
        task_id: str,
    ) -> bool:
        ...


class RecordRuntimeHandoffResultFn(Protocol):
    def __call__(
        self,
        state: dict[str, Any],
        attempt: PreparedRuntimeHandoff,
        *,
        succeeded: bool,
        exit_code: int | None,
        runtime_result: Mapping[str, Any] | None,
        failure_type: str | None,
    ) -> bool:
        ...


class CoalescedTextFn(Protocol):
    def __call__(
        self,
        mapping: dict[str, Any],
        *fields: str,
    ) -> str:
        ...


class TrustedTmuxMerchantStageContextFn(Protocol):
    def __call__(
        self,
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
        ...


class ToolResponseCandidateFn(Protocol):
    def __call__(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        ...


class SendMessageBodyFn(Protocol):
    def __call__(
        self,
        tool_input: dict[str, Any],
    ) -> str:
        ...


class ActiveTaskIdFn(Protocol):
    def __call__(
        self,
        session_id: Any,
        teammate_name: str,
    ) -> str:
        ...


class HandoffCandidateFromMessageFn(Protocol):
    def __call__(
        self,
        message: Any,
    ) -> dict[str, Any] | None:
        ...


class MessageCandidateFn(Protocol):
    def __call__(
        self,
        message: str,
    ) -> dict[str, Any] | None:
        ...


class BoundMerchantCompletenessReceiptFn(Protocol):
    def __call__(
        self,
        *,
        pane_session_id: str,
        owner_session_id: str,
        teammate_name: str,
        run_id: str,
        task_id: str,
    ) -> dict[str, Any] | None:
        ...


class MerchantResolutionInvocationQueryFn(Protocol):
    def __call__(
        self,
        payload: dict[str, Any],
    ) -> str:
        ...


class ResolutionStageFn(Protocol):
    def __call__(
        self,
        *,
        payload: dict[str, Any],
        pane_session_id: Any,
        owner_session_id: Any,
        teammate_name: Any,
        run_id: Any,
        task_id: Any,
        authorized_operations: Any,
    ) -> bool:
        ...


class MerchantCompletenessStageFn(Protocol):
    def __call__(
        self,
        payload: dict[str, Any],
        session_id: Any,
        result: dict[str, Any],
    ) -> bool:
        ...


class MerchantResolutionStageFn(Protocol):
    def __call__(
        self,
        payload: dict[str, Any],
        session_id: Any,
        resolution: dict[str, Any],
    ) -> bool:
        ...


class BoundedTerminalResultFailureFn(Protocol):
    def __call__(
        self,
        *,
        owner_session_id: Any,
        pane_session_id: Any,
        teammate_name: str,
        run_id: str,
        task_id: str,
        reason: str,
    ) -> str:
        ...


class ClearMerchantResolutionAfterReleaseFn(Protocol):
    def __call__(
        self,
        session_id: Any,
        teammate_name: str,
    ) -> None:
        ...


class BoundedRuntimeApplyFailureFn(Protocol):
    def __call__(
        self,
        stderr_text: str,
    ) -> str | None:
        ...


class BoundedRuntimeApplyResultFn(Protocol):
    def __call__(
        self,
        stdout_text: Any,
        attempt: PreparedRuntimeHandoff,
    ) -> dict[str, Any] | None:
        ...


class EmitPostToolContextFn(Protocol):
    def __call__(
        self,
        feedback: str,
    ) -> None:
        ...


class HandlePostToolUseFn(Protocol):
    def __call__(
        self,
        state: dict[str, Any] | None,
        payload: dict[str, Any],
        session_id: Any,
    ) -> None:
        ...


class HandleTeammateIdleFn(Protocol):
    def __call__(
        self,
        state: dict[str, Any] | None,
        payload: dict[str, Any],
        session_id: Any,
    ) -> str:
        ...


class PrepareMerchantRuntimeHandoffFn(Protocol):
    def __call__(
        self,
        payload: dict[str, Any],
    ) -> tuple[
        bool,
        PreparedRuntimeHandoff | None,
        str,
    ]:
        ...


class InvokeDirectMerchantExecuteFn(Protocol):
    def __call__(
        self,
        attempt: Any,
    ) -> int: ...


class DirectExecutionEvidenceFn(Protocol):
    def __call__(
        self,
        attempt: Any,
    ) -> str: ...
