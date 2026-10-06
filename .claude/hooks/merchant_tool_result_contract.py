"""Pure parsing of exact Merchant CLI tool responses.

This module extracts and validates exact machine-readable Merchant CLI
responses. It performs no state mutation, staging, lifecycle transition,
runtime authorization, or repository access.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from merchant_confirmation_preferences import (
        validate_proposal_result,
    )
    from tmux_merchant_completeness import (
        validate_completeness_result,
    )
except ModuleNotFoundError:
    from .merchant_confirmation_preferences import (
        validate_proposal_result,
    )
    from .tmux_merchant_completeness import (
        validate_completeness_result,
    )


def _exact_tool_stdout(
    payload: dict[str, Any],
) -> str | None:
    """Return exact stdout from one supported CLI tool response."""

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    if tool_name not in {
        "Bash",
        "PowerShell",
    }:
        return None

    response: Any = None

    for field in (
        "tool_response",
        "tool_result",
        "toolUseResult",
    ):
        candidate_response = (
            payload.get(
                field
            )
        )

        if candidate_response is not None:
            response = candidate_response
            break

    stdout: Any = None

    if isinstance(
        response,
        dict,
    ):
        stdout = response.get(
            "stdout"
        )

    elif isinstance(
        response,
        str,
    ):
        stdout = response

    if not isinstance(
        stdout,
        str,
    ):
        return None

    stdout = stdout.strip()

    if not stdout:
        return None

    return stdout


def _exact_json_object(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Parse one exact JSON object from supported CLI stdout."""

    stdout = _exact_tool_stdout(
        payload
    )

    if stdout is None:
        return None

    try:
        candidate = json.loads(
            stdout
        )
    except json.JSONDecodeError:
        return None

    if not isinstance(
        candidate,
        dict,
    ):
        return None

    return candidate


def merchant_proposal_from_tool_response(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract one fully validated exact Merchant CLI proposal."""

    candidate = _exact_json_object(
        payload
    )

    if candidate is None:
        return None

    if (
        validate_proposal_result(
            candidate
        )
        is None
    ):
        return None

    return candidate


def merchant_completeness_from_tool_response(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract one exact validated Merchant completeness CLI result."""

    candidate = _exact_json_object(
        payload
    )

    if candidate is None:
        return None

    if (
        validate_completeness_result(
            candidate
        )
        is None
    ):
        return None

    return candidate
