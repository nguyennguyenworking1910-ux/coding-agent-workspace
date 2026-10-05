from pathlib import Path

import re


ROOT = Path(__file__).resolve().parents[2]

SOLVE = (
    ROOT
    / ".claude"
    / "commands"
    / "solve.md"
)

MERCHANT_MANAGER = (
    ROOT
    / ".claude"
    / "agents"
    / "merchant-manager.md"
)

CANONICAL_MARKER = (
    "MERCHANT_APPLY_HANDOFF_REQUEST_JSON:"
)


def _read(path: Path) -> str:
    return path.read_text(
        encoding="utf-8",
    )


def test_solve_uses_canonical_runtime_handoff_marker():
    text = _read(SOLVE)

    assert CANONICAL_MARKER in text

    bad = list(
        re.finditer(
            r"MERCHANT_APPLY_HANDOFF_REQUEST_JSON(?!:)",
            text,
        )
    )

    assert bad == []


def test_merchant_manager_uses_canonical_runtime_handoff_marker():
    text = _read(
        MERCHANT_MANAGER
    )

    assert CANONICAL_MARKER in text

    bad = list(
        re.finditer(
            r"MERCHANT_APPLY_HANDOFF_REQUEST_JSON(?!:)",
            text,
        )
    )

    assert bad == []


def test_solve_forbids_model_authored_apply_receipt():
    text = _read(SOLVE)

    assert (
        "Do not model-author"
        in text
    )

    assert (
        "`MERCHANT_APPLY_RECEIPT_JSON`"
        in text
    )

def test_merchant_manager_forbids_model_authored_apply_receipt():
    text = _read(
        MERCHANT_MANAGER
    )

    assert (
        "Do not model-author"
        in text
    )

    assert (
        "`MERCHANT_APPLY_RECEIPT_JSON`"
        in text
    )

def test_solve_requires_exactly_one_handoff_sendmessage():
    text = _read(SOLVE)

    assert (
        "exactly one"
        in text.lower()
    )

    assert (
        "non-terminal"
        in text
    )

    assert (
        "`SendMessage`"
        in text
    )


def test_merchant_manager_requires_exactly_one_handoff_sendmessage():
    text = _read(
        MERCHANT_MANAGER
    )

    assert (
        "exactly one"
        in text.lower()
    )

    assert (
        "non-terminal"
        in text
    )

    assert (
        "`SendMessage`"
        in text
    )


def test_merchant_manager_terminal_apply_sendmessage_is_machine_only():
    text = _read(
        MERCHANT_MANAGER
    )

    assert (
        "`SendMessage` must consist only of exactly one "
        "`TEAM_RESULT_JSON` block."
        in text
    )

    assert (
        "the first non-whitespace content must be "
        "`TEAM_RESULT_JSON:`"
        in text
    )

    assert (
        "after the closing `}` of the JSON object, "
        "the message must end"
        in text
    )

    assert (
        "do not write prose, Markdown, headings, explanations, "
        "failure reports, CLI"
        in text
    )


def test_general_reporting_does_not_override_terminal_apply_contract():
    text = _read(
        MERCHANT_MANAGER
    )

    assert (
        "They do not override the strict terminal"
        in text
    )

    assert re.search(
        r"For terminal `merchant_apply`, send\s+"
        r"only the required `TEAM_RESULT_JSON` block\.",
        text,
    )