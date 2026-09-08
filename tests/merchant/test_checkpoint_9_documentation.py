"""Documentation contracts for Merchant Checkpoint 9."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_NAME = "MERCHANT_CHECKPOINT_9_PLAN_2026-09-07.md"
HANDOFF_NAME = "MERCHANT_CHECKPOINT_9_HANDOFF_2026-09-08.md"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_checkpoint_9_handoff_exists_and_is_indexed():
    handoff = PROJECT_ROOT / ".claude" / "documents" / HANDOFF_NAME
    document_index = _read(".claude/documents/README.md")
    root_readme = _read("README.md")
    architecture = _read(".claude/documents/ARCHITECTURE.md")

    assert handoff.is_file()
    assert HANDOFF_NAME in document_index
    assert HANDOFF_NAME in root_readme
    assert HANDOFF_NAME in architecture


def test_plan_and_handoff_record_staging_review_status():
    plan = _read(f".claude/documents/{PLAN_NAME}")
    handoff = _read(f".claude/documents/{HANDOFF_NAME}")

    assert (
        "Implementation and runtime verification complete; "
        "final staging review pending"
    ) in plan
    assert "**Completion commit:** Pending commit and push verification" in handoff
    assert "**Status:** Implementation and runtime verification complete" in handoff


def test_handoff_records_exact_redacted_runtime_state():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "| Merchant records | 22 |" in content
    assert "| `ONBOARDING` | 22 |" in content
    assert "| `ACTIVE` | 0 |" in content
    assert "| Catalog initialization events | 22 |" in content
    assert "No Merchant id, code, name, contact, identifier" in content


def test_handoff_records_catalog_hash_and_privacy_contract():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert (
        "c0c48cf58a0cd55a25a78abc35922114"
        "a36c42b92d29d6c1c58d97898733a501"
    ) in content
    assert (
        "d657f977a384b4747882017ef77163bf4"
        "e268a38f6092dfbdd8dfc4ebb609354"
    ) in content
    assert "UTF-8 without a byte\norder mark" in content
    assert "errors containing only\na record position and reason code" in content
    assert "Test fixtures use fictitious values only" in content


def test_handoff_records_separate_authorizations_and_backup():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "MIGRATIONS_2_3_AUTHORIZED" in content
    assert "STANDARD_TEMPLATES_AUTHORIZED" in content
    assert "PRIVATE_CATALOG_22_AUTHORIZED" in content
    assert "PostgreSQL custom-format backup" in content
    assert (
        "5567a6ac9508490085382b58a6b8395e"
        "37814a698c0eb024577e94abaab2e145"
    ) in content
    assert "not reusable runtime capabilities" in content


def test_handoff_records_migrations_and_templates():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    for version in (1, 2, 3):
        assert f"| {version} |" in content
    assert "4 templates" in content
    assert "64 workflow steps" in content
    assert "68 dependencies" in content
    assert (
        "71e6570aef9eac09b0707d487388059bc"
        "8f26249c1aa4c08c36a99cd6203842f"
    ) in content
    assert "identical retry\ninserted nothing" in content


def test_handoff_records_atomic_catalog_and_rollback_correction():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "one connection, one transaction" in content
    assert "22 deterministic `MERCHANT_CATALOG_INITIALIZED` events" in content
    assert "transaction context rolled back all inserts" in content
    assert "target was still empty" in content
    assert "all-`ONBOARDING` case" in content
    assert "immediate identical retry returned\n`NO_OP`" in content


def test_handoff_records_read_only_workflow_compatibility():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "collects two read-only snapshots" in content
    assert "stored catalog hash equal" in content
    assert "ordinary project and global alert reads returned zero" in content
    assert "actual initialized `ONBOARDING` identity" in content
    assert "three ACTIVE-only workflow planner contracts" in content
    assert "`runtime_projects_created` remains 0" in content


def test_handoff_records_privacy_scan_and_safe_staging_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "scanned every modified and untracked text file" in content
    assert "private codes and names and found no match" in content
    assert "environment files, spreadsheets, archives, dumps" in content
    assert "private source, backup, credentials" in content


def test_handoff_records_final_regression_markers():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    for marker in (
        "CHECKPOINT_9_GATE_7_FOCUSED_REGRESSION_PASSED",
        "CHECKPOINT_9_GATE_7_ALL_NON_LIVE_TESTS_PASSED",
        "CHECKPOINT_9_GATE_7_STRUCTURAL_VALIDATION_PASSED",
        "CHECKPOINT_9_GATE_7_PRIVATE_DATA_ISOLATION_PASSED",
        "CHECKPOINT_9_GATE_7_FINAL_RUNTIME_VERIFICATION_PASSED",
        "CHECKPOINT_9_GATE_7A_COMPLETE_REGRESSION_PASSED",
    ):
        assert marker in content
    assert "All 80 structural checks passed" in content


def test_handoff_records_final_core_and_future_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "completes the core Phase 4A" in content
    assert "Checkpoint 10 remains the optional Phase 4B" in content
    assert "not required for the\ncompleted core Merchant Project Manager" in content


def test_handoff_defines_post_commit_finalization():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "## 15. Commit boundary" in content
    assert "Stage only the reviewed Checkpoint 9 files" in content
    assert "documentation-only finalization" in content
    assert "real commit SHA" in content
    assert "remote and clean-checkout evidence" in content
