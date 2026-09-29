"""Pure trusted-consumption gate for Document Revision resolution receipts."""

from __future__ import annotations

import unicodedata

from dataclasses import dataclass
from typing import Any

try:
    from tmux_document_revision_resolution import (
        document_revision_resolution_receipt_matches,
        validate_document_revision_resolution_result,
    )
except ModuleNotFoundError:
    from .tmux_document_revision_resolution import (
        document_revision_resolution_receipt_matches,
        validate_document_revision_resolution_result,
    )


BOUND = "BOUND"
REQUIRES_CLARIFICATION = "REQUIRES_CLARIFICATION"
REJECTED = "REJECTED"

SCOPE_PROJECT = "PROJECT"
SCOPE_MERCHANT = "MERCHANT"

SCOPES = frozenset(
    {
        SCOPE_PROJECT,
        SCOPE_MERCHANT,
    }
)


@dataclass(frozen=True)
class DocumentRevisionResolutionCandidate:
    revision_id: str
    project_id: str
    merchant_id: str
    document_type: str
    revision_number: int
    signed: bool
    superseded_by: str | None


@dataclass(frozen=True)
class DocumentRevisionResolutionBindingDecision:
    accepted: bool
    outcome: str

    query: str
    scope: str | None

    merchant_id: str | None
    project_id: str | None

    revision_id: str | None
    source_project_id: str | None

    document_type: str | None
    revision_number: int | None
    signed: bool | None
    superseded_by: str | None

    match_kind: str | None

    candidates: tuple[
        DocumentRevisionResolutionCandidate,
        ...,
    ]

    question: str | None


def bind_document_revision_resolution_receipt(
    receipt: Any,
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    trusted_merchant_id: Any,
    expected_scope: Any,
    expected_query: Any,
    trusted_project_id: Any = None,
) -> DocumentRevisionResolutionBindingDecision:
    """Consume one exact staged Document Revision resolver receipt.

    Security model:

    - receipt must belong to the exact pane;
    - receipt must belong to the exact owner + teammate + run + task;
    - receipt must belong to the already-trusted Merchant;
    - PROJECT scope additionally requires the exact trusted Project;
    - MERCHANT scope must not bind to a Project parent;
    - the deterministic resolution schema must validate exactly;
    - the semantic query must match the expected query.

    Outcomes:

    RESOLVED
        -> BOUND

    AMBIGUOUS
        -> REQUIRES_CLARIFICATION

    NOT_FOUND
        -> REQUIRES_CLARIFICATION

    Missing / malformed / wrong-context / wrong-scope evidence
        -> REJECTED

    This function grants no write authority.
    """

    query = _normalize_expected_query(
        expected_query
    )

    if query is None:
        return _rejected()

    scope = _normalize_scope(
        expected_scope
    )

    if scope is None:
        return _rejected(
            query=query
        )

    merchant_id = _clean_text(
        trusted_merchant_id
    )

    if not merchant_id:
        return _rejected(
            query=query
        )

    if scope == SCOPE_PROJECT:
        project_id = _clean_text(
            trusted_project_id
        )

        if not project_id:
            return _rejected(
                query=query
            )

    else:
        if trusted_project_id is not None:
            if _clean_text(
                trusted_project_id
            ):
                return _rejected(
                    query=query
                )

        project_id = None

    if not isinstance(
        receipt,
        dict,
    ):
        return _rejected(
            query=query
        )

    # -------------------------------------------------
    # Exact receipt binding.
    #
    # The receipt primitive performs canonical UUID
    # validation for merchant/project parent identity.
    # -------------------------------------------------

    if not document_revision_resolution_receipt_matches(
        receipt,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        merchant_id=merchant_id,
        project_id=project_id,
        scope=scope,
    ):
        return _rejected(
            query=query
        )

    # -------------------------------------------------
    # Exact deterministic resolver result validation.
    # -------------------------------------------------

    resolution = (
        validate_document_revision_resolution_result(
            receipt.get(
                "resolution"
            )
        )
    )

    if resolution is None:
        return _rejected(
            query=query
        )

    canonical_merchant_id = str(
        resolution.get(
            "merchant_id"
        )
        or ""
    )

    canonical_project_id = (
        resolution.get(
            "project_id"
        )
    )

    # -------------------------------------------------
    # Parent invariants.
    # -------------------------------------------------

    if (
        resolution.get(
            "scope"
        )
        != scope
    ):
        return _rejected(
            query=query
        )

    if (
        canonical_merchant_id
        != merchant_id
    ):
        return _rejected(
            query=query
        )

    if (
        canonical_project_id
        != project_id
    ):
        return _rejected(
            query=query
        )

    # -------------------------------------------------
    # Semantic query binding.
    #
    # NFKC-equivalent forms are accepted.
    # -------------------------------------------------

    resolution_query = (
        _normalize_expected_query(
            resolution.get(
                "query"
            )
        )
    )

    if (
        resolution_query
        != query
    ):
        return _rejected(
            query=query
        )

    candidates = tuple(
        DocumentRevisionResolutionCandidate(
            revision_id=(
                candidate[
                    "revision_id"
                ]
            ),
            project_id=(
                candidate[
                    "project_id"
                ]
            ),
            merchant_id=(
                candidate[
                    "merchant_id"
                ]
            ),
            document_type=(
                candidate[
                    "document_type"
                ]
            ),
            revision_number=(
                candidate[
                    "revision_number"
                ]
            ),
            signed=(
                candidate[
                    "signed"
                ]
            ),
            superseded_by=(
                candidate[
                    "superseded_by"
                ]
            ),
        )
        for candidate in resolution[
            "candidates"
        ]
    )

    status = resolution[
        "status"
    ]

    # -------------------------------------------------
    # RESOLVED -> BOUND
    # -------------------------------------------------

    if status == "RESOLVED":
        return DocumentRevisionResolutionBindingDecision(
            accepted=True,
            outcome=BOUND,
            query=query,
            scope=scope,
            merchant_id=canonical_merchant_id,
            project_id=canonical_project_id,
            revision_id=resolution[
                "revision_id"
            ],
            source_project_id=resolution[
                "source_project_id"
            ],
            document_type=resolution[
                "document_type"
            ],
            revision_number=resolution[
                "revision_number"
            ],
            signed=resolution[
                "signed"
            ],
            superseded_by=resolution[
                "superseded_by"
            ],
            match_kind=resolution[
                "match_kind"
            ],
            candidates=candidates,
            question=None,
        )

    # -------------------------------------------------
    # AMBIGUOUS -> clarification.
    #
    # Never let the LLM choose one candidate.
    # -------------------------------------------------

    if status == "AMBIGUOUS":
        candidate_labels = ", ".join(
            _candidate_label(
                candidate
            )
            for candidate in candidates
        )

        return DocumentRevisionResolutionBindingDecision(
            accepted=False,
            outcome=REQUIRES_CLARIFICATION,
            query=query,
            scope=scope,
            merchant_id=canonical_merchant_id,
            project_id=canonical_project_id,
            revision_id=None,
            source_project_id=None,
            document_type=None,
            revision_number=None,
            signed=None,
            superseded_by=None,
            match_kind=resolution[
                "match_kind"
            ],
            candidates=candidates,
            question=(
                _ambiguous_question(
                    query=query,
                    scope=scope,
                    merchant_id=canonical_merchant_id,
                    project_id=canonical_project_id,
                    candidate_labels=candidate_labels,
                )
            ),
        )

    # -------------------------------------------------
    # NOT_FOUND -> clarification.
    # -------------------------------------------------

    if status == "NOT_FOUND":
        return DocumentRevisionResolutionBindingDecision(
            accepted=False,
            outcome=REQUIRES_CLARIFICATION,
            query=query,
            scope=scope,
            merchant_id=canonical_merchant_id,
            project_id=canonical_project_id,
            revision_id=None,
            source_project_id=None,
            document_type=None,
            revision_number=None,
            signed=None,
            superseded_by=None,
            match_kind=resolution[
                "match_kind"
            ],
            candidates=(),
            question=(
                _not_found_question(
                    query=query,
                    scope=scope,
                    merchant_id=canonical_merchant_id,
                    project_id=canonical_project_id,
                )
            ),
        )

    # Schema validation should already reject unknown
    # statuses. Preserve fail-closed behavior.
    return _rejected(
        query=query
    )


def _candidate_label(
    candidate: DocumentRevisionResolutionCandidate,
) -> str:
    revision_key = (
        f"{candidate.document_type}"
        f"#{candidate.revision_number}"
    )

    return (
        f'"{revision_key}" '
        f"({candidate.revision_id}; "
        f"source project {candidate.project_id})"
    )


def _ambiguous_question(
    *,
    query: str,
    scope: str,
    merchant_id: str,
    project_id: str | None,
    candidate_labels: str,
) -> str:
    if scope == SCOPE_PROJECT:
        return (
            f'Multiple document revisions match "{query}" '
            f"for project {project_id} "
            f"under merchant {merchant_id}: "
            f"{candidate_labels}. "
            "Please specify one revision by exact UUID "
            "or DOCUMENT_TYPE#REVISION_NUMBER."
        )

    return (
        f'Multiple document revisions match "{query}" '
        f"for merchant {merchant_id}: "
        f"{candidate_labels}. "
        "Please specify one revision by exact UUID "
        "or DOCUMENT_TYPE#REVISION_NUMBER."
    )


def _not_found_question(
    *,
    query: str,
    scope: str,
    merchant_id: str,
    project_id: str | None,
) -> str:
    if scope == SCOPE_PROJECT:
        return (
            f'No document revision matched "{query}" '
            f"for project {project_id} "
            f"under merchant {merchant_id}. "
            "Please provide an exact revision UUID "
            "or DOCUMENT_TYPE#REVISION_NUMBER."
        )

    return (
        f'No document revision matched "{query}" '
        f"for merchant {merchant_id}. "
        "Please provide an exact revision UUID "
        "or DOCUMENT_TYPE#REVISION_NUMBER."
    )


def _rejected(
    *,
    query: str = "",
) -> DocumentRevisionResolutionBindingDecision:
    return DocumentRevisionResolutionBindingDecision(
        accepted=False,
        outcome=REJECTED,
        query=query,
        scope=None,
        merchant_id=None,
        project_id=None,
        revision_id=None,
        source_project_id=None,
        document_type=None,
        revision_number=None,
        signed=None,
        superseded_by=None,
        match_kind=None,
        candidates=(),
        question=None,
    )


def _normalize_scope(
    value: Any,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    normalized = value.strip().upper()

    if normalized not in SCOPES:
        return None

    return normalized


def _normalize_expected_query(
    value: Any,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    normalized = (
        unicodedata.normalize(
            "NFKC",
            value,
        )
        .strip()
    )

    if not normalized:
        return None

    return normalized


def _clean_text(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip()
