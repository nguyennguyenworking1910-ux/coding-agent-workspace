"""Exact Merchant resolution invocation/result contract.

Extracted from team_result_hook without changing validation semantics.
External validation dependencies remain dynamically bound through the
compatibility layer.
"""

from __future__ import annotations

from typing import Any


def _merchant_resolution_invocation_query(
    payload: dict[str, Any],
    dependencies: Any = None,
) -> str:
    """Return query only for one direct allowlisted resolver invocation.

    Resolution JSON is easy to fabricate with shell output, so exact stdout
    alone is insufficient authority. The PostToolUse command must also be one
    direct Merchant agent CLI resolver invocation with no pipeline, redirect,
    command chaining, or wrapper script.
    """

    if dependencies is None:
        raise RuntimeError(
            "Merchant resolution dependencies are required"
        )

    shlex = (
        dependencies.shlex
    )

    unicodedata = (
        dependencies.unicodedata
    )

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
        return ""

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return ""

    command = tool_input.get(
        "command"
    )

    if not isinstance(
        command,
        str,
    ):
        return ""

    command = command.strip()

    if not command:
        return ""

    try:
        tokens = shlex.split(
            command,
            posix=True,
        )
    except ValueError:
        return ""

    if len(
        tokens
    ) != 6:
        return ""

    (
        executable,
        script,
        resource,
        action,
        query_flag,
        query,
    ) = tokens

    normalized_executable = (
        executable
        .replace(
            "\\",
            "/",
        )
        .lower()
    )

    allowed_executables = {
        "python",
        "python.exe",
        "py",
        "py.exe",
        ".venv/scripts/python.exe",
        "./.venv/scripts/python.exe",
    }

    if (
        normalized_executable
        not in allowed_executables
    ):
        return ""

    normalized_script = (
        script
        .replace(
            "\\",
            "/",
        )
    )

    if normalized_script.startswith(
        "./"
    ):
        normalized_script = (
            normalized_script[
                2:
            ]
        )

    if (
        normalized_script
        != (
            ".claude/agents/tools/"
            "merchant/agent_cli.py"
        )
    ):
        return ""

    if (
        resource
        != "merchant"
        or action
        != "resolve"
        or query_flag
        != "--query"
    ):
        return ""

    normalized_query = (
        unicodedata.normalize(
            "NFKC",
            query,
        )
        .strip()
    )

    return normalized_query


def merchant_resolution_from_tool_response(
    payload: dict[str, Any],
    dependencies: Any = None,
) -> dict[str, Any] | None:
    """Extract one exact validated Merchant resolver CLI result."""

    if dependencies is None:
        raise RuntimeError(
            "Merchant resolution dependencies are required"
        )

    _merchant_resolution_invocation_query = (
        dependencies._merchant_resolution_invocation_query
    )

    json = (
        dependencies.json
    )

    validate_merchant_resolution_result = (
        dependencies.validate_merchant_resolution_result
    )

    invocation_query = (
        _merchant_resolution_invocation_query(
            payload
        )
    )

    if not invocation_query:
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

        if (
            candidate_response
            is not None
        ):
            response = (
                candidate_response
            )
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

    text = stdout.strip()

    if not text:
        return None

    try:
        candidate = json.loads(
            text
        )
    except json.JSONDecodeError:
        return None

    validated = (
        validate_merchant_resolution_result(
            candidate
        )
    )

    if validated is None:
        return None

    if (
        validated.get(
            "query"
        )
        != invocation_query
    ):
        return None

    return validated
