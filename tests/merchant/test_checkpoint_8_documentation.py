"""Documentation consistency tests for Merchant Checkpoint 8."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_NAME = "MERCHANT_CHECKPOINT_8_PLAN_2026-09-07.md"
HANDOFF_NAME = "MERCHANT_CHECKPOINT_8_HANDOFF_2026-09-07.md"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_checkpoint_8_handoff_exists_and_is_indexed():
    handoff = PROJECT_ROOT / ".claude" / "documents" / HANDOFF_NAME
    document_index = _read(".claude/documents/README.md")
    root_readme = _read("README.md")
    architecture = _read(".claude/documents/ARCHITECTURE.md")

    assert handoff.is_file()
    assert HANDOFF_NAME in document_index
    assert HANDOFF_NAME in root_readme
    assert HANDOFF_NAME in architecture


def test_plan_and_handoff_record_completed_commit_status():
    plan = _read(f".claude/documents/{PLAN_NAME}")
    handoff = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "Implementation and verification complete; staging review pending" in plan
    assert "**Completion commit:** `efa05fa`" in handoff
    assert "**Status:** Complete, committed, and pushed" in handoff


def test_handoff_records_deadline_policy_and_five_types():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "Asia/Ho_Chi_Minh" in content
    assert "default due-soon window of seven calendar days" in content
    for alert_type in (
        "OVERDUE",
        "DUE_TODAY",
        "DUE_SOON",
        "BLOCKED",
        "MISSING_GATE",
    ):
        assert f"`{alert_type}`" in content
    assert "does not\nadd a sixth alert type" in content


def test_handoff_records_gate_and_parallel_branch_behavior():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "exact `project_step_id`, step name, and `branch_key`" in content
    assert "latest active document revision" in content
    assert "Partner and Legal approval" in content
    assert "signing prerequisites" in content
    assert "Purchase Order cannot\n  satisfy" in content
    assert "reused-document identity" in content


def test_handoff_records_bounded_read_repository_and_filters():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "default is 100 candidate projects" in content
    assert "reviewed maximum is 500" in content
    assert "sentinel row" in content
    assert "merchant id" in content
    assert "project id" in content
    assert "inclusive `business_due_date <= due-date-before`" in content
    assert "existing redaction boundary" in content


def test_handoff_records_cli_compatibility_and_public_limit_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "project alerts <project_id>" in content
    assert "Equivalent positional and flagged ids" in content
    assert "conflicting ids fail before repository dispatch" in content
    assert "`--project-limit` remains deliberately undocumented and rejected" in content


def test_handoff_records_complete_regression_evidence():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "8.5 complete focused regression | 295 passed" in content
    assert "1,374 passed, 120 subtests passed" in content
    assert "8.5 structural validation | 80/80 passed" in content
    assert "explicitly\nexcluded integration tests" in content


def test_handoff_records_live_lifecycle_and_cleanup():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "coding_agent_merchant_test" in content
    assert "user `merchant_test`" in content
    assert "exactly one `OVERDUE`, one `BLOCKED`, and one `DUE_SOON`" in content
    assert "zero project events and zero alert deliveries" in content
    assert "final business counts were\nzero" in content
    assert "HOTFIX_V2_PASSED" in content
    assert "No runtime database was read or mutated" in content


def test_handoff_preserves_read_only_delivery_and_private_data_boundaries():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "may not" in content
    assert "enqueue or claim an alert delivery" in content
    assert "production-ready remains future Checkpoint 10" in content
    assert "migration 3 to the runtime database" in content
    assert "must remain outside Git and RAG ingestion" in content


def test_handoff_defines_checkpoint_9_continuation_order():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "## 12. Next checkpoint — Checkpoint 9" in content
    assert "final currently planned core Phase 4 checkpoint" in content
    assert "private 22-record Merchant catalog contract" in content
    assert "read-only runtime readiness checks" in content
    assert "Apply only after the user separately authorizes" in content
    assert "Checkpoint 10 remains a future alert-delivery extension" in content


def test_handoff_records_completed_commit_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "## 13. Commit record" in content
    assert (
        "efa05fa Complete Checkpoint 8 Merchant deadline and "
        "alert calculation"
    ) in content
    assert "efa05fa10bc32f1fbf2b8c2d5d82c1d5b5ec156e" in content
    assert "exactly the 27 reviewed Checkpoint 8 files" in content
    assert "git show --check efa05fa" in content
    assert "Structural system validation passes 81/81" in content
