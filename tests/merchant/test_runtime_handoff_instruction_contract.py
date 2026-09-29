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