from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOLVE_PATH = (
    PROJECT_ROOT
    / ".claude"
    / "commands"
    / "solve.md"
)


def test_solve_keeps_completed_teammates_idle_reusable():
    content = SOLVE_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "Request graceful shutdown of every teammate created by this run."
        not in content
    )

    assert (
        "IDLE_REUSABLE` means the teammate pane must remain alive"
        in content
    )

    assert (
        "The lead must not acknowledge the completed result back through "
        "`SendMessage`."
        in content
    )

    assert (
        "Session-scoped teammate cleanup belongs to `SessionEnd`"
        in content
    )