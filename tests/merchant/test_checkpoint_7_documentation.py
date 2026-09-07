"""Documentation consistency tests for Merchant Checkpoint 7."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HANDOFF_NAME = "MERCHANT_CHECKPOINT_7_HANDOFF_2026-09-07.md"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_checkpoint_7_handoff_exists_and_is_indexed():
    handoff = PROJECT_ROOT / ".claude" / "documents" / HANDOFF_NAME
    index = _read(".claude/documents/README.md")
    root_readme = _read("README.md")

    assert handoff.is_file()
    assert HANDOFF_NAME in index
    assert HANDOFF_NAME in root_readme


def test_top_level_docs_record_the_completed_runtime_boundary():
    claude = _read("CLAUDE.md")
    root_readme = _read("README.md")
    architecture = _read(".claude/documents/ARCHITECTURE.md")

    assert "invoke_confirmed_merchant_session_apply" in claude
    assert "The ordinary CLI remains read/propose-only" in root_readme
    assert "merchant_runtime_handoff.py" in architecture
    assert "One-use in-process confirmed Merchant apply bridge" in architecture
    assert "Merchant Manager      (Merchant reads/proposals; trusted apply)" in architecture


def test_agent_frontmatter_matches_checkpoint_7_role():
    agent = _read(".claude/agents/merchant-manager.md")

    assert "participates in exact confirmed applies" in agent
    assert "The ordinary CLI remains read/propose-only" in agent
    assert "invoke_confirmed_merchant_session_apply" in agent


def test_handoff_records_all_three_merchant_operations():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "`merchant_read`" in content
    assert "`merchant_propose`" in content
    assert "`merchant_apply`" in content
    assert "exclusive routing of every Merchant operation" in content


def test_handoff_records_exact_confirmation_and_dispatch():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "dedicated `--merchant-confirmation` input" in content
    assert "MERCHANT_DISPATCH_AUTHORIZATION_JSON" in content
    assert "token and raw proposal payload are deliberately absent" in content
    assert "consumes the dispatch binding" in content


def test_handoff_records_one_use_persisted_runtime_authority():
    content = _read(f".claude/documents/{HANDOFF_NAME}")
    normalized = " ".join(content.split())

    assert "invoke_confirmed_merchant_session_apply" in content
    assert "opaque, expiring, non-serializable capability" in content
    assert "provides at-most-once execution" in content
    assert "reservation is saved before capability issuance" in content
    assert "environment variable" in content
    assert "fresh proposal, confirmation, envelope, and dispatch" in normalized


def test_handoff_records_complete_non_live_regression():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "1,223 passed, 8 deselected, 120 subtests passed" in content
    assert "system 80/80" in content
    assert "explicitly excluded all\nintegration tests" in content


def test_handoff_records_safe_live_lifecycle_and_cleanup():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "coding_agent_merchant_test" in content
    assert "user `merchant_test`" in content
    assert "test connection is read-only" in content
    assert "cleanup restored the empty business state" in content
    assert "No\nruntime database was read or mutated" in content


def test_handoff_preserves_runtime_migration_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "Migration 3 remains unapplied to the runtime database" in content
    assert "fresh read-only plan" in content
    assert "Real Merchant data remains outside Git" in content


def test_handoff_defines_checkpoint_8_goal_and_order():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "## 12. Next checkpoint — Checkpoint 8" in content
    assert "overdue, due-today, and due-soon" in content
    assert "blocked-and-overdue" in content
    assert "Keep alert calculation read-only" in content
    assert "does not send email" in content


def test_handoff_stays_pending_until_user_commits():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "**Completion commit:** Pending staging review" in content
    assert "**Status:** Implementation and verification complete; staging review pending" in content
    assert "## 13. Staging and commit boundary" in content
