from __future__ import annotations

import sys

from pathlib import Path


HOOKS = (
    Path(__file__)
    .resolve()
    .parents[1]
    / ".claude"
    / "hooks"
)

if str(HOOKS) not in sys.path:
    sys.path.insert(
        0,
        str(HOOKS),
    )


from resolution_cli_invocation import (  # noqa: E402
    parse_resolution_cli_invocation,
)


def payload(
    command: str,
    *,
    tool_name: str = "Bash",
):
    return {
        "tool_name": tool_name,
        "tool_input": {
            "command": command,
        },
    }


CLI = (
    "python "
    ".claude/agents/tools/merchant/agent_cli.py "
)


def test_project_resolution_invocation():
    result = parse_resolution_cli_invocation(
        payload(
            CLI
            + "project resolve "
            "--merchant-id merchant-1 "
            "--query alpha"
        ),
        entity="project",
    )

    assert result is not None
    assert result.merchant_id == "merchant-1"
    assert result.project_id is None
    assert result.query == "alpha"


def test_step_resolution_invocation():
    result = parse_resolution_cli_invocation(
        payload(
            CLI
            + "step resolve "
            "--project-id project-1 "
            "--query alpha"
        ),
        entity="step",
    )

    assert result is not None
    assert result.project_id == "project-1"
    assert result.merchant_id is None


def test_document_merchant_scope():
    result = parse_resolution_cli_invocation(
        payload(
            CLI
            + "document resolve "
            "--merchant-id merchant-1 "
            "--query alpha"
        ),
        entity="document",
    )

    assert result is not None
    assert result.merchant_id == "merchant-1"
    assert result.project_id is None


def test_document_project_scope():
    result = parse_resolution_cli_invocation(
        payload(
            CLI
            + "document resolve "
            "--project-id project-1 "
            "--query alpha"
        ),
        entity="document",
    )

    assert result is not None
    assert result.project_id == "project-1"
    assert result.merchant_id is None


def test_document_rejects_two_scopes():
    assert (
        parse_resolution_cli_invocation(
            payload(
                CLI
                + "document resolve "
                "--merchant-id merchant-1 "
                "--project-id project-1 "
                "--query alpha"
            ),
            entity="document",
        )
        is None
    )


def test_rejects_shell_chaining():
    assert (
        parse_resolution_cli_invocation(
            payload(
                CLI
                + "project resolve "
                "--merchant-id merchant-1 "
                "--query alpha "
                "&& echo forged"
            ),
            entity="project",
        )
        is None
    )


def test_rejects_wrong_tool():
    assert (
        parse_resolution_cli_invocation(
            payload(
                CLI
                + "project resolve "
                "--merchant-id merchant-1 "
                "--query alpha",
                tool_name="PowerShell",
            ),
            entity="project",
        )
        is None
    )


def test_rejects_duplicate_flag():
    assert (
        parse_resolution_cli_invocation(
            payload(
                CLI
                + "project resolve "
                "--merchant-id merchant-1 "
                "--merchant-id merchant-2 "
                "--query alpha"
            ),
            entity="project",
        )
        is None
    )


def test_rejects_unknown_flag():
    assert (
        parse_resolution_cli_invocation(
            payload(
                CLI
                + "step resolve "
                "--project-id project-1 "
                "--query alpha "
                "--unexpected value"
            ),
            entity="step",
        )
        is None
    )


def test_supports_equals_form():
    result = parse_resolution_cli_invocation(
        payload(
            CLI
            + "project resolve "
            "--merchant-id=merchant-1 "
            "--query=alpha"
        ),
        entity="project",
    )

    assert result is not None
    assert result.merchant_id == "merchant-1"
    assert result.query == "alpha"
