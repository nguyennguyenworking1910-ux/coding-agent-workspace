"""Pure trusted-consumption gate for Project resolution receipts."""

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
        validate_receipt_dict,
        validate_resolution_query,
    )

try:
    from tmux_project_resolution import (
        project_resolution_receipt_matches,
        validate_project_resolution_result,
    )
except ModuleNotFoundError:
    from .tmux_project_resolution import (
        project_resolution_receipt_matches,
        validate_project_resolution_result,
    )


@dataclass(frozen=True)
class ProjectResolutionCandidate:
    project_id: str
    merchant_id: str
    title: str | None
    project_type: str | None
    workflow_variant: str | None
    status: str | None
    version: int | None


@dataclass(frozen=True)
class ProjectResolutionBindingDecision:
    accepted: bool
    outcome: str

    query: str

    merchant_id: str | None
    project_id: str | None

    title: str | None
    project_type: str | None
    workflow_variant: str | None
    project_status: str | None
    version: int | None

    match_kind: str | None

    candidates: tuple[
        ProjectResolutionCandidate,
        ...,
    ]

    question: str | None


def bind_project_resolution_receipt(
    receipt: Any,
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    trusted_merchant_id: Any,
    expected_query: Any,
) -> ProjectResolutionBindingDecision:
    """Consume one exact staged Project resolver receipt.

    Security model:

    - the Project receipt must belong to the exact pane;
    - it must belong to the exact owner + teammate + run + task;
    - it must belong to the already-trusted Merchant binding;
    - its resolution must satisfy the deterministic Project resolver schema;
    - its semantic query must match the expected query.

    Outcomes:

    RESOLVED
        -> BOUND

    AMBIGUOUS
        -> REQUIRES_CLARIFICATION

    NOT_FOUND
        -> REQUIRES_CLARIFICATION

    Missing / malformed / wrong-context / cross-merchant evidence
        -> REJECTED

    This function grants no write authority.
    """
    query = normalize_expected_query(expected_query)
    if query is None:
        return _rejected()

    merchant_id = clean_text(trusted_merchant_id)
    if not merchant_id:
        return _rejected(query=query)

    if not validate_receipt_dict(receipt, query):
        return _rejected(query=query)

    if not project_resolution_receipt_matches(
        receipt,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        merchant_id=merchant_id,
    ):
        return _rejected(query=query)

    resolution = validate_project_resolution_result(receipt.get("resolution"))
    if resolution is None:
        return _rejected(query=query)

    if resolution.get("merchant_id") != merchant_id:
        return _rejected(query=query)

    if not validate_resolution_query(resolution.get("query"), query):
        return _rejected(query=query)

    candidates = build_candidates_tuple(
        resolution["candidates"],
        lambda c: ProjectResolutionCandidate(
            project_id=c["project_id"],
            merchant_id=c["merchant_id"],
            title=c["title"],
            project_type=c["project_type"],
            workflow_variant=c["workflow_variant"],
            status=c["status"],
            version=c["version"],
        ),
    )

    status = resolution[
        "status"
    ]

    # -------------------------------------------------
    # RESOLVED
    # -------------------------------------------------

    if status == "RESOLVED":
        return ProjectResolutionBindingDecision(
            accepted=True,
            outcome=BOUND,
            query=query,
            merchant_id=merchant_id,
            project_id=resolution[
                "project_id"
            ],
            title=resolution[
                "title"
            ],
            project_type=resolution[
                "project_type"
            ],
            workflow_variant=resolution[
                "workflow_variant"
            ],
            project_status=resolution[
                "project_status"
            ],
            version=resolution[
                "version"
            ],
            match_kind=resolution[
                "match_kind"
            ],
            candidates=candidates,
            question=None,
        )

    # -------------------------------------------------
    # AMBIGUOUS
    #
    # This is authoritative evidence that multiple
    # projects match. Do not let the LLM choose one.
    # -------------------------------------------------

    if status == "AMBIGUOUS":
        candidate_labels = ", ".join(
            _candidate_label(
                candidate
            )
            for candidate in candidates
        )

        return ProjectResolutionBindingDecision(
            accepted=False,
            outcome=REQUIRES_CLARIFICATION,
            query=query,
            merchant_id=merchant_id,
            project_id=None,
            title=None,
            project_type=None,
            workflow_variant=None,
            project_status=None,
            version=None,
            match_kind=resolution[
                "match_kind"
            ],
            candidates=candidates,
            question=(
                f'Multiple projects match "{query}" '
                f"for merchant {merchant_id}: "
                f"{candidate_labels}. "
                "Please specify one project by exact UUID "
                "or full title."
            ),
        )

    # -------------------------------------------------
    # NOT_FOUND
    # -------------------------------------------------

    if status == "NOT_FOUND":
        return ProjectResolutionBindingDecision(
            accepted=False,
            outcome=REQUIRES_CLARIFICATION,
            query=query,
            merchant_id=merchant_id,
            project_id=None,
            title=None,
            project_type=None,
            workflow_variant=None,
            project_status=None,
            version=None,
            match_kind=resolution[
                "match_kind"
            ],
            candidates=(),
            question=(
                f'No project matched "{query}" '
                f"for merchant {merchant_id}. "
                "Please provide an exact project UUID "
                "or full project title."
            ),
        )

    # validate_project_resolution_result() should already
    # reject unknown statuses. Preserve fail-closed behavior.
    return _rejected(
        query=query
    )


def _candidate_label(
    candidate: ProjectResolutionCandidate,
) -> str:
    """Return deterministic human-readable candidate identity."""

    if candidate.title:
        return (
            f'"{candidate.title}" '
            f"({candidate.project_id})"
        )

    return candidate.project_id


def _rejected(
    *,
    query: str = "",
) -> ProjectResolutionBindingDecision:
    return ProjectResolutionBindingDecision(
        accepted=False,
        outcome=REJECTED,
        query=query,
        merchant_id=None,
        project_id=None,
        title=None,
        project_type=None,
        workflow_variant=None,
        project_status=None,
        version=None,
        match_kind=None,
        candidates=(),
        question=None,
    )