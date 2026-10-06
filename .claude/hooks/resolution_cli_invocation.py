"""Strict Merchant CLI resolution invocation parsing.

This module validates only the direct CLI command boundary used by entity
resolution staging. It grants no authority, loads no receipts, mutates no
state, and performs no staging.
"""

from __future__ import annotations

import shlex

from dataclasses import dataclass
from typing import Any


FORBIDDEN_SHELL_TOKENS = (
    "&&",
    "||",
    "|",
    ";",
    ">>",
    ">",
    "<",
    "2>&1",
    "2>>",
    "2>",
)

MERCHANT_AGENT_CLI_SUFFIX = (
    ".claude/agents/tools/merchant/agent_cli.py"
)


@dataclass(frozen=True)
class ResolutionCliInvocation:
    entity: str
    query: str
    merchant_id: str | None = None
    project_id: str | None = None


def _flag_values(
    tokens: list[str],
    allowed_flags: frozenset[str],
) -> dict[str, str] | None:
    """Parse strict --flag value / --flag=value pairs.

    Duplicate, unknown, missing, and empty values fail closed.
    """

    values: dict[str, str] = {}

    index = 0

    while index < len(tokens):
        token = tokens[index]

        if not token.startswith("--"):
            return None

        if "=" in token:
            flag, value = token.split(
                "=",
                1,
            )

            value = value.strip()

            if (
                flag not in allowed_flags
                or flag in values
                or not value
            ):
                return None

            values[flag] = value

            index += 1
            continue

        flag = token

        if (
            flag not in allowed_flags
            or flag in values
            or index + 1 >= len(tokens)
        ):
            return None

        value = str(
            tokens[index + 1]
        ).strip()

        if not value:
            return None

        values[flag] = value

        index += 2

    return values


def _direct_resolution_tokens(
    payload: Any,
) -> list[str] | None:
    """Return exact Merchant agent CLI tokens from one direct Bash command."""

    if not isinstance(
        payload,
        dict,
    ):
        return None

    if (
        str(
            payload.get(
                "tool_name"
            )
            or ""
        ).strip()
        != "Bash"
    ):
        return None

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return None

    command = tool_input.get(
        "command"
    )

    if not isinstance(
        command,
        str,
    ):
        return None

    command = command.strip()

    if not command:
        return None

    if any(
        token in command
        for token in FORBIDDEN_SHELL_TOKENS
    ):
        return None

    try:
        tokens = shlex.split(
            command,
            posix=True,
        )
    except ValueError:
        return None

    if len(
        tokens
    ) < 4:
        return None

    executable = (
        tokens[0]
        .replace(
            "\\",
            "/",
        )
        .lower()
    )

    if executable not in {
        "python",
        "python.exe",
    }:
        return None

    script = (
        tokens[1]
        .replace(
            "\\",
            "/",
        )
    )

    if not script.endswith(
        MERCHANT_AGENT_CLI_SUFFIX
    ):
        return None

    return tokens[2:]


def parse_resolution_cli_invocation(
    payload: Any,
    *,
    entity: str,
) -> ResolutionCliInvocation | None:
    """Parse one strict entity resolution invocation.

    Supported forms:

      project resolve
          --merchant-id <id>
          --query <query>

      document resolve
          (--merchant-id <id> | --project-id <id>)
          --query <query>

      step resolve
          --project-id <id>
          --query <query>
    """

    cli_tokens = (
        _direct_resolution_tokens(
            payload
        )
    )

    if cli_tokens is None:
        return None

    normalized_entity = str(
        entity
        or ""
    ).strip()

    if normalized_entity not in {
        "project",
        "document",
        "step",
    }:
        return None

    if (
        len(cli_tokens) < 2
        or cli_tokens[0]
        != normalized_entity
        or cli_tokens[1]
        != "resolve"
    ):
        return None

    if normalized_entity == "project":
        allowed_flags = frozenset(
            {
                "--merchant-id",
                "--query",
            }
        )

    elif normalized_entity == "document":
        allowed_flags = frozenset(
            {
                "--merchant-id",
                "--project-id",
                "--query",
            }
        )

    else:
        allowed_flags = frozenset(
            {
                "--project-id",
                "--query",
            }
        )

    values = _flag_values(
        cli_tokens[2:],
        allowed_flags,
    )

    if values is None:
        return None

    query = values.get(
        "--query"
    )

    if not query:
        return None

    merchant_id = values.get(
        "--merchant-id"
    )

    project_id = values.get(
        "--project-id"
    )

    if normalized_entity == "project":
        if (
            not merchant_id
            or project_id is not None
            or set(values)
            != {
                "--merchant-id",
                "--query",
            }
        ):
            return None

    elif normalized_entity == "step":
        if (
            not project_id
            or merchant_id is not None
            or set(values)
            != {
                "--project-id",
                "--query",
            }
        ):
            return None

    else:
        # Document resolution requires exactly one scope.
        if (
            bool(merchant_id)
            == bool(project_id)
        ):
            return None

        expected = {
            "--query",
            (
                "--merchant-id"
                if merchant_id
                else "--project-id"
            ),
        }

        if set(values) != expected:
            return None

    return ResolutionCliInvocation(
        entity=normalized_entity,
        query=query,
        merchant_id=merchant_id,
        project_id=project_id,
    )
