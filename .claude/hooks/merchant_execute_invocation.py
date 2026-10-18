"""Validate one exact direct Merchant CLI invocation.

Structural validation only. This module does not authenticate
PostToolUse events or establish database commit evidence.
"""

from __future__ import annotations

import shlex
from pathlib import PureWindowsPath
from typing import Any

from claude.agents.tools.merchant.cli import build_argument_parser
from claude.agents.tools.merchant.cli_contract import (
    WRITE_COMMANDS,
    normalize_command,
)


SCRIPT_NAME = "agent_cli.py"
ALLOWED_TOOLS = frozenset({"Bash", "PowerShell"})


def validated_merchant_execute_invocation(
    payload: dict[str, Any],
    execution_result: dict[str, Any],
) -> tuple[str, ...] | None:
    """Validate one simple Merchant CLI invocation against its result."""

    if not isinstance(payload, dict):
        return None

    if not isinstance(execution_result, dict):
        return None

    if payload.get("tool_name") not in ALLOWED_TOOLS:
        return None

    tool_input = payload.get("tool_input")

    if not isinstance(tool_input, dict):
        return None

    command_text = tool_input.get("command")

    if not isinstance(command_text, str):
        return None

    command_text = command_text.strip()

    if not command_text or len(command_text) > 8192:
        return None

    # This validator only supports a single plain CLI invocation.
    # Shell control syntax is deliberately outside its contract.
    if any(
        token in command_text
        for token in ("\n", "\r", ";", "|", "&", "`", "$(", ">", "<")
    ):
        return None

    try:
        tokens = shlex.split(
            command_text,
            posix=False,
        )
    except ValueError:
        return None

    if len(tokens) < 5:
        return None

    tokens = [
        token.strip('"').strip("'")
        for token in tokens
    ]

    # Only permit the repository's canonical Merchant agent CLI path.
    # A different script with the same basename is not equivalent.
    script_path = tokens[1].replace("\\\\", "/").replace("\\", "/")
    script_path = script_path.removeprefix("./")

    if script_path != ".claude/agents/tools/merchant/agent_cli.py":
        return None

    python_name = (
        PureWindowsPath(tokens[0]).name.lower()
    )

    if python_name not in {
        "python",
        "python.exe",
        "python3",
        "python3.exe",
    }:
        return None

    arguments = tuple(tokens[2:])

    forbidden_options = {
        "--apply",
        "--propose",
        "--proposal-hash",
        "--database",
        "--admin-user",
        "--admin-db",
        "--host",
        "--port",
        "--runtime-db",
        "--test-db",
    }

    if any(
        argument.split("=", 1)[0].lower() in forbidden_options
        for argument in arguments
    ):
        return None

    try:
        parser = build_argument_parser()
        parsed = parser.parse_args([
            "--database",
            "runtime",
            *arguments,
        ])
    except (SystemExit, ValueError):
        return None

    command = normalize_command(
        f"{parsed.resource} {parsed.action}"
    )

    if command not in WRITE_COMMANDS:
        return None

    if parsed.mode != "EXECUTE":
        return None

    if execution_result.get("command") != command:
        return None

    if execution_result.get("database") != "runtime":
        return None

    if execution_result.get("mode") != "EXECUTE":
        return None

    if execution_result.get("success") is not True:
        return None

    return arguments
