from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOLVE_COMMAND = (
    PROJECT_ROOT
    / ".claude"
    / "commands"
    / "solve.md"
)


def test_solve_propagates_machine_readable_merchant_proposal_contract():
    text = SOLVE_COMMAND.read_text(
        encoding="utf-8",
    )

    assert "MERCHANT_PROPOSAL_RESULT_JSON:" in text

    assert (
        "IDLE_REUSABLE"
        in text
    )

    assert (
        "confirmation_token"
        in text
    )

    assert (
        "do not replace the token with `[REDACTED]`"
        in text
    )

    assert (
        "newly created teammate"
        in text
    )

    assert (
        "receiving its next task through `SendMessage`"
        in text
    )