"""Pure Merchant teammate-result parsing helpers.

This module parses authenticated report payloads and proposal blocks only.
It performs no state mutation, lifecycle transition, runtime authorization,
or repository access.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from team_result_contract import (
        MERCHANT_PROPOSAL_RESULT_MARKER,
    )
    from team_result_payload import (
        trusted_post_tool_sender,
    )
except ModuleNotFoundError:
    from .team_result_contract import (
        MERCHANT_PROPOSAL_RESULT_MARKER,
    )
    from .team_result_payload import (
        trusted_post_tool_sender,
    )


def merchant_report_sender(
    payload: dict[str, Any],
) -> str:
    """Resolve sender only from harness-authenticated PostToolUse fields."""

    return trusted_post_tool_sender(
        payload
    )


def merchant_proposal_candidate_from_message(
    message: str,
) -> dict[str, Any] | None:
    """Parse the legacy/direct machine-readable proposal block.

    For tmux proposal delivery this is not proposal authority.
    It remains a pure parser for authenticated direct teammate reports.
    """

    report = str(
        message
        or ""
    ).strip()

    if (
        report.count(
            MERCHANT_PROPOSAL_RESULT_MARKER
        )
        != 1
    ):
        return None

    _, encoded = (
        report.split(
            MERCHANT_PROPOSAL_RESULT_MARKER,
            1,
        )
    )

    encoded = encoded.strip()

    if not encoded:
        return None

    try:
        candidate, end = (
            json.JSONDecoder().raw_decode(
                encoded
            )
        )
    except json.JSONDecodeError:
        return None

    if (
        encoded[end:].strip()
    ):
        return None

    if not isinstance(
        candidate,
        dict,
    ):
        return None

    if not str(
        candidate.get(
            "confirmation_token"
        )
        or ""
    ).strip():
        return None

    return candidate
