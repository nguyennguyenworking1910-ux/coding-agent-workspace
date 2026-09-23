"""Pure trusted-consumption gate for Merchant resolution receipts."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

try:
    from tmux_merchant_resolution import (
        pending_merchant_resolution_matches,
        validate_merchant_resolution_result,
    )
except ModuleNotFoundError:
    from .tmux_merchant_resolution import (
        pending_merchant_resolution_matches,
        validate_merchant_resolution_result,
    )


BOUND = "BOUND"
REQUIRES_CLARIFICATION = "REQUIRES_CLARIFICATION"
REJECTED = "REJECTED"


@dataclass(frozen=True)
class MerchantResolutionCandidate:
    merchant_id: str
    code: str
    name: str


@dataclass(frozen=True)
class MerchantResolutionBindingDecision:
    accepted: bool
    outcome: str
    query: str
    merchant_id: str | None
    code: str | None
    name: str | None
    match_kind: str | None
    candidates: tuple[
        MerchantResolutionCandidate,
        ...,
    ]
    question: str | None


def bind_merchant_resolution_receipt(
    receipt: Any,
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    expected_query: Any,
) -> MerchantResolutionBindingDecision:
    """Consume one exact staged resolver receipt.

    A valid RESOLVED receipt returns one trusted Merchant binding.

    Valid AMBIGUOUS / NOT_FOUND receipts return deterministic user
    clarification.

    Missing, malformed, stale-context, wrong-task, or wrong-query evidence
    is REJECTED and must never become a Merchant binding.
    """

    query = _normalize_expected_query(
        expected_query
    )

    if query is None:
        return _rejected()

    if not isinstance(
        receipt,
        dict,
    ):
        return _rejected(
            query=query
        )

    pane_id = _clean_text(
        pane_session_id
    )

    if (
        not pane_id
        or _clean_text(
            receipt.get(
                "pane_session_id"
            )
        )
        != pane_id
    ):
        return _rejected(
            query=query
        )

    if not pending_merchant_resolution_matches(
        receipt,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
    ):
        return _rejected(
            query=query
        )

    resolution = (
        validate_merchant_resolution_result(
            receipt.get(
                "resolution"
            )
        )
    )

    if resolution is None:
        return _rejected(
            query=query
        )

    if (
        _normalize_expected_query(
            resolution.get(
                "query"
            )
        )
        != query
    ):
        return _rejected(
            query=query
        )

    candidates = tuple(
        MerchantResolutionCandidate(
            merchant_id=(
                candidate[
                    "merchant_id"
                ]
            ),
            code=(
                candidate[
                    "code"
                ]
            ),
            name=(
                candidate[
                    "name"
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

    if status == "RESOLVED":
        return MerchantResolutionBindingDecision(
            accepted=True,
            outcome=BOUND,
            query=query,
            merchant_id=resolution[
                "merchant_id"
            ],
            code=resolution[
                "code"
            ],
            name=resolution[
                "name"
            ],
            match_kind=resolution[
                "match_kind"
            ],
            candidates=candidates,
            question=None,
        )

    if status == "AMBIGUOUS":
        codes = ", ".join(
            candidate.code
            for candidate in candidates
        )

        return MerchantResolutionBindingDecision(
            accepted=False,
            outcome=REQUIRES_CLARIFICATION,
            query=query,
            merchant_id=None,
            code=None,
            name=None,
            match_kind=resolution[
                "match_kind"
            ],
            candidates=candidates,
            question=(
                f'Multiple merchants match "{query}": '
                f"{codes}. "
                "Please specify one merchant by exact code or UUID."
            ),
        )

    if status == "NOT_FOUND":
        return MerchantResolutionBindingDecision(
            accepted=False,
            outcome=REQUIRES_CLARIFICATION,
            query=query,
            merchant_id=None,
            code=None,
            name=None,
            match_kind=resolution[
                "match_kind"
            ],
            candidates=(),
            question=(
                f'No merchant matched "{query}". '
                "Please provide an exact merchant code, name, or UUID."
            ),
        )

    return _rejected(
        query=query
    )


def _rejected(
    *,
    query: str = "",
) -> MerchantResolutionBindingDecision:
    return MerchantResolutionBindingDecision(
        accepted=False,
        outcome=REJECTED,
        query=query,
        merchant_id=None,
        code=None,
        name=None,
        match_kind=None,
        candidates=(),
        question=None,
    )


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