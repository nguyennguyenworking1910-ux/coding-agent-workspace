#!/usr/bin/env python3
"""Command-line entry point for the local RAG search tool."""

from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path
from typing import Sequence


CLAUDE_DIR = Path(__file__).resolve().parent


def _load_claude_package() -> None:
    """Expose `.claude` through its importable package name."""
    if "claude" in sys.modules:
        return

    package = types.ModuleType("claude")
    package.__path__ = [str(CLAUDE_DIR)]
    package.__package__ = "claude"
    sys.modules["claude"] = package


_load_claude_package()

from claude.agents.tools.rag import (  # noqa: E402
    ready as tool_ready,
    search as tool_search,
)
from claude.clients import RagClientError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Search the private local coding-agent-workspace "
            "RAG service."
        )
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Knowledge-base query text",
    )
    parser.add_argument(
        "--ready",
        action="store_true",
        help="Check RAG readiness instead of searching",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of final results (default: 5)",
    )
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=40,
        help="Candidates considered before ranking (default: 40)",
    )
    parser.add_argument(
        "--source-type",
        action="append",
        default=[],
        help=(
            "Restrict source type; repeat for multiple values"
        ),
    )
    parser.add_argument(
        "--source-key",
        action="append",
        default=[],
        help=(
            "Restrict source key; repeat for multiple values"
        ),
    )
    return parser


def _write_json(payload: object, *, stream) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        file=stream,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.ready and args.query:
        parser.error("query cannot be used with --ready")
    if not args.ready and not args.query:
        parser.error("query is required unless --ready is used")

    try:
        if args.ready:
            response = tool_ready()
        else:
            response = tool_search(
                args.query,
                top_k=args.top_k,
                candidate_k=args.candidate_k,
                source_types=args.source_type,
                source_keys=args.source_key,
            )
    except (RagClientError, ValueError) as exc:
        _write_json(
            {
                "status": "error",
                "message": str(exc),
            },
            stream=sys.stderr,
        )
        return 1

    _write_json(response, stream=sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )
        sys.stderr.reconfigure(
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        pass

    raise SystemExit(main())