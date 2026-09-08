"""Repository and plan contracts for Merchant Checkpoint 9 Gate 9.0."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_NAME = "MERCHANT_CHECKPOINT_9_PLAN_2026-09-07.md"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_checkpoint_9_plan_exists_and_is_indexed():
    plan = PROJECT_ROOT / ".claude" / "documents" / PLAN_NAME
    index = _read(".claude/documents/README.md")

    assert plan.is_file()
    assert PLAN_NAME in index


def test_plan_uses_the_pushed_checkpoint_8_commit_as_baseline():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "**Base commit:** `efa05fa`" in content
    assert "efa05fa10bc32f1fbf2b8c2d5d82c1d5b5ec156e" in content
    assert "exactly 27 reviewed Checkpoint 8 files" in content
    assert "structural validation passes 81/81" in content


def test_plan_defines_exact_private_catalog_boundary():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "exactly 22 Merchant records" in content
    assert "required UTF-8 `code` and `name`" in content
    assert "`ONBOARDING` or `ACTIVE`" in content
    assert "unknown-field validation" in content
    assert "fictitious fixtures" in content


def test_plan_keeps_real_values_out_of_repository_and_rag():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "never be added to Git" in content
    assert "test fixtures" in content
    assert "generated\narchives" in content
    assert "ordinary logs" in content
    assert "RAG ingestion" in content
    assert "without printing the private\nvalue" in content


def test_plan_separates_runtime_authority_gates():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "Runtime readiness is read-only" in content
    assert (
        "Applying runtime migrations 2 and 3 requires explicit authorization"
        in content
    )
    assert "separate explicit authorization" in content
    assert "Checkpoint 7 proposal, exact confirmation" in content
    assert "No `--force`" in content


def test_plan_requires_atomic_idempotent_conflict_safe_import():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "one database transaction and be all-or-nothing" in content
    assert "identical source must produce a verified no-op" in content
    assert "fail closed" in content
    assert "source hash that differs from the reviewed plan" in content


def test_plan_defines_all_checkpoint_9_gates():
    content = _read(f".claude/documents/{PLAN_NAME}")

    for gate in range(8):
        assert f"### Gate 9.{gate}" in content


def test_plan_defines_runtime_verification_without_private_rows():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "expected status distribution without exposing rows" in content
    assert "UTF-8 preservation through private hash-based checks" in content
    assert "ordinary redacted reads" in content
    assert "workflow preconditions" in content


def test_plan_records_final_core_and_future_worker_boundaries():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "final currently planned core Phase 4 checkpoint" in content
    assert "Checkpoint 10 remains an optional Phase 4B" in content
    assert "not required for the core Merchant Project Manager" in content
