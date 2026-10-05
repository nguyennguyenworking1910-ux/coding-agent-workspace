"""Shared resolution gate validation logic for Merchant, Project, Step, and Document Revision.

All four gates follow identical validation flow, differing only in:
- Trusted parent boundaries (merchant_id for Project/Step/Document)
- Candidate/decision dataclass fields
- Question formatting for AMBIGUOUS/NOT_FOUND outcomes

This module consolidates ~1,800 lines of duplication into reusable primitives.
"""

from __future__ import annotations

import unicodedata
from typing import Any


BOUND = "BOUND"
REQUIRES_CLARIFICATION = "REQUIRES_CLARIFICATION"
REJECTED = "REJECTED"


def normalize_expected_query(value: Any) -> str | None:
    """Normalize and validate query string (NFKC + strip)."""
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value).strip()
    return normalized if normalized else None


def clean_text(value: Any) -> str:
    """Safely convert value to string."""
    return str(value or "").strip()


def validate_pane_id(pane_session_id: Any, receipt_pane_id: Any, query: str) -> bool:
    """Verify receipt pane_session_id matches expected pane."""
    pane_id = clean_text(pane_session_id)
    if not pane_id or clean_text(receipt_pane_id) != pane_id:
        return False
    return True


def validate_receipt_dict(receipt: Any, query: str) -> bool:
    """Verify receipt is a dict."""
    return isinstance(receipt, dict)


def validate_resolution_query(
    resolution_query: Any,
    expected_query: str,
) -> bool:
    """Verify resolution's query matches expected query (normalized)."""
    resolved_q = normalize_expected_query(resolution_query)
    return resolved_q == expected_query


def build_candidates_tuple(
    resolution_candidates: list[dict[str, Any]],
    candidate_factory,
) -> tuple:
    """Build candidate tuple using provided factory function."""
    return tuple(
        candidate_factory(candidate) for candidate in resolution_candidates
    )
