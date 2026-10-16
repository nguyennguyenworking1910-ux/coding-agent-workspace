"""Pure trusted-consumption gate for Step resolution receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from resolution_gate_base import (
        BOUND,
        REJECTED,
        REQUIRES_CLARIFICATION,
        build_candidates_tuple,
        clean_text,
        normalize_expected_query,
        validate_pane_id,
        validate_receipt_dict,
        validate_resolution_query,
    )
except ModuleNotFoundError:
    from .resolution_gate_base import (
        BOUND,
        REJECTED,
        REQUIRES_CLARIFICATION,
        build_candidates_tuple,
        clean_text,
        normalize_expected_query,
        validate_pane_id,
        validate_receipt_dict,
        validate_resolution_query,
    )

try:
    from tmux_step_resolution import (
        step_resolution_receipt_matches,
        validate_step_resolution_result,
    )
except ModuleNotFoundError:
    from .tmux_step_resolution import (
        step_resolution_receipt_matches,
        validate_step_resolution_result,
    )


@dataclass(frozen=True)
class StepResolutionCandidate:
    step_id: str
    project_id: str
    template_step_id: str

    branch_key: str | None
    step_name: str
    step_type: str | None

    status: str | None
    sequence_number: int
    version: int

    condition_key: str | None
    is_optional: bool | None


@dataclass(frozen=True)
class StepResolutionBindingDecision:
    accepted: bool
    outcome: str

    query: str

    merchant_id: str | None
    project_id: str | None
    step_id: str | None

    template_step_id: str | None

    branch_key: str | None
    step_name: str | None
    step_type: str | None

    step_status: str | None
    sequence_number: int | None
    version: int | None

    condition_key: str | None
    is_optional: bool | None

    match_kind: str | None

    candidates: tuple[
        StepResolutionCandidate,
        ...,
    ]

    question: str | None


def bind_step_resolution_receipt(
    receipt: Any,
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    trusted_merchant_id: Any,
    trusted_project_id: Any,
    expected_query: Any,
) -> StepResolutionBindingDecision:
    """Consume one exact staged Step resolver receipt.

    Security model:

    - receipt belongs to exact pane;
    - exact owner + teammate + run + task;
    - exact already-trusted Merchant;
    - exact already-trusted Project;
    - deterministic Step resolver schema is valid;
    - resolver project_id remains inside trusted Project;
    - semantic query matches expected query.

    This function grants no write authority.
    """
    query = normalize_expected_query(expected_query)
    if query is None:
        return _rejected()

    merchant_id = clean_text(trusted_merchant_id)
    project_id = clean_text(trusted_project_id)
    if not merchant_id or not project_id:
        return _rejected(query=query)

    if not validate_receipt_dict(receipt):
        return _rejected(query=query)

    if not step_resolution_receipt_matches(
        receipt,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        merchant_id=merchant_id,
        project_id=project_id,
    ):
        return _rejected(query=query)

    resolution = validate_step_resolution_result(receipt.get("resolution"))
    if resolution is None:
        return _rejected(query=query)

    if resolution.get("project_id") != project_id:
        return _rejected(query=query)

    if receipt.get("merchant_id") != merchant_id or receipt.get("project_id") != project_id:
        return _rejected(query=query)

    if not validate_resolution_query(resolution.get("query"), query):
        return _rejected(query=query)

    candidates = build_candidates_tuple(
        resolution["candidates"],
        lambda c: StepResolutionCandidate(
            step_id=c["step_id"],
            project_id=c["project_id"],
            template_step_id=c["template_step_id"],
            branch_key=c["branch_key"],
            step_name=c["step_name"],
            step_type=c["step_type"],
            status=c["status"],
            sequence_number=c["sequence_number"],
            version=c["version"],
            condition_key=c["condition_key"],
            is_optional=c["is_optional"],
        ),
    )

    status = resolution[
        "status"
    ]

    # -------------------------------------------------
    # RESOLVED
    # -------------------------------------------------

    if status == "RESOLVED":
        return (
            StepResolutionBindingDecision(
                accepted=True,
                outcome=BOUND,
                query=query,
                merchant_id=merchant_id,
                project_id=project_id,
                step_id=resolution[
                    "step_id"
                ],
                template_step_id=(
                    resolution[
                        "template_step_id"
                    ]
                ),
                branch_key=resolution[
                    "branch_key"
                ],
                step_name=resolution[
                    "step_name"
                ],
                step_type=resolution[
                    "step_type"
                ],
                step_status=resolution[
                    "step_status"
                ],
                sequence_number=(
                    resolution[
                        "sequence_number"
                    ]
                ),
                version=resolution[
                    "version"
                ],
                condition_key=(
                    resolution[
                        "condition_key"
                    ]
                ),
                is_optional=(
                    resolution[
                        "is_optional"
                    ]
                ),
                match_kind=resolution[
                    "match_kind"
                ],
                candidates=candidates,
                question=None,
            )
        )

    # -------------------------------------------------
    # AMBIGUOUS
    #
    # Never let the LLM select a candidate.
    # branch_key is display/disambiguation context only.
    # -------------------------------------------------

    if status == "AMBIGUOUS":
        candidate_labels = ", ".join(
            _candidate_label(
                candidate
            )
            for candidate
            in candidates
        )

        return (
            StepResolutionBindingDecision(
                accepted=False,
                outcome=(
                    REQUIRES_CLARIFICATION
                ),
                query=query,
                merchant_id=merchant_id,
                project_id=project_id,
                step_id=None,
                template_step_id=None,
                branch_key=None,
                step_name=None,
                step_type=None,
                step_status=None,
                sequence_number=None,
                version=None,
                condition_key=None,
                is_optional=None,
                match_kind=resolution[
                    "match_kind"
                ],
                candidates=candidates,
                question=(
                    f'Multiple workflow steps match '
                    f'"{query}" for project '
                    f"{project_id}: "
                    f"{candidate_labels}. "
                    "Please specify one Step by "
                    "exact UUID."
                ),
            )
        )

    # -------------------------------------------------
    # NOT_FOUND
    # -------------------------------------------------

    if status == "NOT_FOUND":
        return (
            StepResolutionBindingDecision(
                accepted=False,
                outcome=(
                    REQUIRES_CLARIFICATION
                ),
                query=query,
                merchant_id=merchant_id,
                project_id=project_id,
                step_id=None,
                template_step_id=None,
                branch_key=None,
                step_name=None,
                step_type=None,
                step_status=None,
                sequence_number=None,
                version=None,
                condition_key=None,
                is_optional=None,
                match_kind=resolution[
                    "match_kind"
                ],
                candidates=(),
                question=(
                    f'No workflow step matched '
                    f'"{query}" for project '
                    f"{project_id}. "
                    "Please provide an exact Step UUID "
                    "or full Step name."
                ),
            )
        )

    return _rejected(
        query=query
    )


def _candidate_label(
    candidate: StepResolutionCandidate,
) -> str:
    """Return deterministic human-readable Step identity."""

    branch = (
        candidate.branch_key
        or "no-branch"
    )

    return (
        f'"{candidate.step_name}" '
        f"[{branch}, sequence "
        f"{candidate.sequence_number}] "
        f"({candidate.step_id})"
    )


def _rejected(
    *,
    query: str = "",
) -> StepResolutionBindingDecision:
    return (
        StepResolutionBindingDecision(
            accepted=False,
            outcome=REJECTED,
            query=query,
            merchant_id=None,
            project_id=None,
            step_id=None,
            template_step_id=None,
            branch_key=None,
            step_name=None,
            step_type=None,
            step_status=None,
            sequence_number=None,
            version=None,
            condition_key=None,
            is_optional=None,
            match_kind=None,
            candidates=(),
            question=None,
        )
    )
