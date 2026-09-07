"""Repository and plan contracts for Merchant Checkpoint 8 Gate 8.0."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_NAME = "MERCHANT_CHECKPOINT_8_PLAN_2026-09-07.md"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_checkpoint_8_plan_exists_and_is_indexed():
    plan = PROJECT_ROOT / ".claude" / "documents" / PLAN_NAME
    index = _read(".claude/documents/README.md")

    assert plan.is_file()
    assert PLAN_NAME in index


def test_plan_uses_the_pushed_checkpoint_7_commit_as_baseline():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "**Base commit:** `370b0d0`" in content
    assert "Gate 8.0 baseline verified" in content
    assert "clean checkout" in content


def test_plan_reuses_the_existing_checker():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert ".claude/agents/tools/merchant/checker.py" in content
    assert "must not create a duplicate checker" in content
    assert "tests/merchant/test_checker.py" in content
    assert "tests/merchant/test_read_commands.py" in content


def test_plan_preserves_the_five_database_alert_types():
    content = _read(f".claude/documents/{PLAN_NAME}")

    for alert_type in (
        "OVERDUE",
        "DUE_TODAY",
        "DUE_SOON",
        "BLOCKED",
        "MISSING_GATE",
    ):
        assert f"`{alert_type}`" in content

    assert "will not add an undocumented\n`BLOCKED_AND_OVERDUE`" in content


def test_plan_keeps_calculation_read_only_and_delivery_separate():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "deterministic, read-only alert view" in content
    assert "Alert delivery is not part of Checkpoint 8" in content
    assert "cannot enqueue, claim, deliver, or mutate alerts" in content


def test_plan_covers_global_query_filters():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "optional merchant id, project id, alert type" in content
    assert "due-date-before filters" in content
    assert "preserve redaction" in content


def test_plan_defines_all_checkpoint_8_gates():
    content = _read(f".claude/documents/{PLAN_NAME}")

    for gate in range(8):
        assert f"### Gate 8.{gate}" in content


def test_plan_records_the_remaining_roadmap():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "Checkpoint 8 is not the final core checkpoint" in content
    assert "Checkpoint 9 — Private Runtime Initialization" in content
    assert "Checkpoint 10 — Alert Worker (future)" in content
    assert "Checkpoint 9 is the final currently planned core Phase 4 checkpoint" in content
