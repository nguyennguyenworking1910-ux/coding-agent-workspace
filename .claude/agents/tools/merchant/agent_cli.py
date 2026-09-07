#!/usr/bin/env python3
"""Fail-closed operational adapter from Merchant Manager to the CLI.

The adapter deliberately exposes no database selection or credential options.
It fixes the target to ``runtime``, accepts read operations and write proposals,
and rejects every apply request until trusted orchestration supplies the
Checkpoint 7 authorization handoff through a separate in-process boundary.
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


try:
    from claude.agents.tools.merchant.cli import (
        CommandFactory,
        WriteCommandFactory,
        build_argument_parser,
        main as merchant_cli_main,
    )
    from claude.agents.tools.merchant.cli_contract import (
        READ_COMMANDS,
        WRITE_COMMANDS,
        normalize_command,
        render_json,
    )
except ModuleNotFoundError:
    CLAUDE_ROOT = Path(__file__).resolve().parents[3]

    if str(CLAUDE_ROOT) not in sys.path:
        sys.path.insert(0, str(CLAUDE_ROOT))

    from agents.tools.merchant.cli import (  # type: ignore
        CommandFactory,
        WriteCommandFactory,
        build_argument_parser,
        main as merchant_cli_main,
    )
    from agents.tools.merchant.cli_contract import (  # type: ignore
        READ_COMMANDS,
        WRITE_COMMANDS,
        normalize_command,
        render_json,
    )


RUNTIME_DATABASE_TARGET = "runtime"

CREDENTIAL_OR_TARGET_OPTIONS = frozenset(
    {
        "--connection",
        "--connection-string",
        "--credential",
        "--credentials",
        "--database",
        "--database-url",
        "--db",
        "--dsn",
        "--host",
        "--password",
        "--port",
        "--secret",
        "--token",
        "--user",
        "--username",
    }
)


class MerchantAgentCliError(ValueError):
    """Raised when an agent invocation crosses its CLI authority."""


def prepare_agent_cli_argv(
    arguments: Sequence[str],
) -> tuple[str, ...]:
    """Validate agent arguments and prepend the fixed runtime target."""

    values = _normalized_arguments(arguments)
    _reject_target_or_credentials(values)

    parser = build_argument_parser()
    prepared = (
        "--database",
        RUNTIME_DATABASE_TARGET,
        *values,
    )
    args = _parse_without_argparse_output(parser, prepared)
    command = normalize_command(
        f"{args.resource} {args.action}"
    )

    if command in WRITE_COMMANDS:
        if getattr(args, "mode", None) != "PROPOSE":
            raise MerchantAgentCliError(
                "Merchant Manager may propose runtime writes but may not "
                "apply them until trusted Checkpoint 7 authority exists"
            )
    elif command not in READ_COMMANDS:  # pragma: no cover
        raise MerchantAgentCliError(
            "Merchant operation is not allowlisted"
        )

    return prepared


def invoke_agent_cli(
    arguments: Sequence[str],
    *,
    command_factory: CommandFactory | None = None,
    write_command_factory: WriteCommandFactory | None = None,
) -> int:
    """Invoke the Merchant CLI without any runtime-write authority."""

    prepared = prepare_agent_cli_argv(arguments)
    return merchant_cli_main(
        prepared,
        command_factory=command_factory,
        write_command_factory=write_command_factory,
        runtime_authorization=None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one credential-safe Merchant Manager CLI invocation."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)

    try:
        return invoke_agent_cli(arguments)
    except MerchantAgentCliError as error:
        print(
            render_json(
                {
                    "success": False,
                    "error": {
                        "type": error.__class__.__name__,
                        "message": " ".join(str(error).split())[:500],
                    },
                }
            ),
            file=sys.stderr,
        )
        return 2


def _normalized_arguments(
    arguments: Sequence[str],
) -> tuple[str, ...]:
    if isinstance(arguments, (str, bytes, bytearray)):
        raise MerchantAgentCliError(
            "Merchant agent arguments must be a sequence of tokens"
        )

    values = tuple(arguments)

    if not values:
        raise MerchantAgentCliError(
            "Merchant agent command is required"
        )

    if any(not isinstance(value, str) for value in values):
        raise MerchantAgentCliError(
            "Merchant agent arguments must be strings"
        )

    if any(not value or "\x00" in value for value in values):
        raise MerchantAgentCliError(
            "Merchant agent arguments must be non-empty text"
        )

    return values


def _reject_target_or_credentials(
    arguments: Sequence[str],
) -> None:
    for value in arguments:
        option = value.split("=", 1)[0].strip().lower()

        if option in CREDENTIAL_OR_TARGET_OPTIONS:
            raise MerchantAgentCliError(
                "Database target and credential arguments are not accepted "
                "by the Merchant Manager interface"
            )


def _parse_without_argparse_output(
    parser: argparse.ArgumentParser,
    arguments: Sequence[str],
) -> argparse.Namespace:
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            return parser.parse_args(arguments)
    except SystemExit as error:
        raise MerchantAgentCliError(
            "Merchant agent arguments do not match the allowlisted CLI "
            "contract"
        ) from error


if __name__ == "__main__":
    raise SystemExit(main())
