"""Shared pure primitives for entity resolution."""

from __future__ import annotations

import uuid
from typing import Any


def _whole_token_sequence_match(
    query: str,
    candidate: str,
) -> bool:
    query_tokens = query.split()
    candidate_tokens = candidate.split()

    if not query_tokens:
        return False

    if len(query_tokens) > len(candidate_tokens):
        return False

    window_size = len(query_tokens)

    return any(
        candidate_tokens[
            index:index + window_size
        ]
        == query_tokens
        for index in range(
            len(candidate_tokens)
            - window_size
            + 1
        )
    )


def _canonical_uuid_or_none(
    value: Any,
) -> str | None:
    try:
        return str(
            uuid.UUID(str(value).strip())
        )
    except (ValueError, AttributeError, TypeError):
        return None


def _optional_text(
    value: Any,
) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text or None
