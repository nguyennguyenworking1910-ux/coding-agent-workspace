"""Preserve CLI identity parser contracts during structural refactoring."""

import pytest

from claude.hooks import policy_gate


def cli(*arguments):
    return ("python", "agent_cli.py", *arguments)


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (cli("merchant", "resolve"), ("merchant resolve", None)),
        (cli("merchant", "show", "--merchant-id", "M1"), ("merchant show", "M1")),
        (cli("merchant", "show", "--merchant-id=M1"), ("merchant show", "M1")),
        (cli("merchant", "show", "--merchant-id"), ("merchant show", "")),
        (cli("integration", "identifier-set", "M1"), ("integration identifier-set", "M1")),
        (cli("integration", "identifier-set", "--scope", "X"), ("integration identifier-set", "")),
    ],
)
def test_merchant_parser_contract(tokens, expected):
    assert policy_gate._merchant_id_from_cli_tokens(tokens) == expected


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (cli("project", "show", "P1"), ("project show", "P1")),
        (cli("project", "update"), ("project update", "")),
        (cli("step", "resolve", "--project-id", "P1"), ("step resolve", "P1")),
        (cli("step", "resolve", "--project-id=P1"), ("step resolve", "P1")),
        (cli("step", "resolve"), ("step resolve", "")),
        (cli("step", "resolve", "--project-id", "P1", "--project-id", "P2"), ("step resolve", "")),
        (cli("project", "alerts"), ("project alerts", None)),
        (cli("project", "alerts", "P1"), ("project alerts", "P1")),
        (cli("project", "alerts", "--project-id=P1"), ("project alerts", "P1")),
        (cli("project", "alerts", "P1", "--project-id=P2"), ("project alerts", "")),
        (cli("integration", "identifier-set", "M1"), ("integration identifier-set", None)),
        (cli("integration", "identifier-set", "M1", "P1"), ("integration identifier-set", "P1")),
    ],
)
def test_project_parser_contract(tokens, expected):
    assert policy_gate._project_id_from_cli_tokens(tokens) == expected


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (cli("step", "update", "S1"), ("step update", "S1")),
        (cli("step", "update"), ("step update", "")),
        (cli("step", "update", "--unknown"), ("step update", "")),
        (cli("step", "resolve", "--query", "test"), ("step resolve", None)),
    ],
)
def test_step_parser_contract(tokens, expected):
    assert policy_gate._step_id_from_cli_tokens(tokens) == expected


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (cli("document", "approve", "R1"), ("document approve", "R1", "PROJECT")),
        (cli("document", "approve"), ("document approve", "", "PROJECT")),
        (cli("document", "resolve"), ("document resolve", None, None)),
        (
            cli("project", "create", "--reused-document-revision-id", "R1"),
            ("project create", "R1", "MERCHANT"),
        ),
        (
            cli("project", "create", "--reused-document-revision-id=R1"),
            ("project create", "R1", "MERCHANT"),
        ),
        (cli("project", "create"), ("project create", None, None)),
        (
            cli("project", "create", "--reused-document-revision-id"),
            ("project create", "", "MERCHANT"),
        ),
        (
            cli(
                "project", "create",
                "--reused-document-revision-id=R1",
                "--reused-document-revision-id=R2",
            ),
            ("project create", "", "MERCHANT"),
        ),
    ],
)
def test_revision_parser_contract(tokens, expected):
    assert (
        policy_gate._document_revision_id_from_cli_tokens(tokens)
        == expected
    )



@pytest.mark.parametrize(
    "tokens,expected",
    [
        (
            cli("step", "resolve", "--project-id"),
            ("step resolve", ""),
        ),
        (
            cli("step", "resolve", "--project-id="),
            ("step resolve", ""),
        ),
        (
            cli("step", "resolve", "--project-id", "--query"),
            ("step resolve", ""),
        ),
        (
            cli(
                "step", "resolve",
                "--project-id=P1",
                "--project-id=P1",
            ),
            ("step resolve", ""),
        ),
        (
            cli("project", "alerts", "--project-id"),
            ("project alerts", ""),
        ),
        (
            cli("project", "alerts", "--project-id="),
            ("project alerts", ""),
        ),
        (
            cli("project", "alerts", "--project-id", "--merchant-id"),
            ("project alerts", ""),
        ),
        (
            cli(
                "project", "alerts", "P1",
                "--project-id=P1",
            ),
            ("project alerts", "P1"),
        ),
        (
            cli(
                "project", "alerts", "P1",
                "--project-id=P2",
            ),
            ("project alerts", ""),
        ),
    ],
)
def test_project_flag_negative_contract(tokens, expected):
    assert policy_gate._project_id_from_cli_tokens(tokens) == expected



@pytest.mark.parametrize(
    "arguments,expected",
    [
        ((), None),
        (("--query", "example"), None),
        (("--project-id", "P1"), "P1"),
        (("--project-id=P1",), "P1"),
        (("--project-id",), ""),
        (("--project-id=",), ""),
        (("--project-id", "--query"), ""),
        (("--project-id=P1", "--project-id=P1"), ""),
        (("--project-id", "P1", "--project-id=P2"), ""),
        (("--project-id", " P1 "), "P1"),
        (("--project-id=P1", "--merchant-id", "M1"), "P1"),
    ],
)
def test_shared_project_id_scanner(arguments, expected):
    assert (
        policy_gate._scan_unique_project_id_flag(arguments)
        == expected
    )
