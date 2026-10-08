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


def test_solve_requires_fresh_primary_inputs_for_reused_teammates():
    solve = (
        Path(".claude/commands/solve.md")
        .read_text(
            encoding="utf-8-sig"
        )
    )

    assert (
        "Treat the assignment as a fresh work unit."
        in solve
    )

    assert (
        "Re-read every primary input file"
        in solve
    )

    normalized = " ".join(
        line.lstrip("> ").strip()
        for line in solve.splitlines()
    )

    assert (
        "Prior-run file contents"
        in normalized
    )

    assert (
        "read the current file during this assignment"
        in normalized
    )
