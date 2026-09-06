"""Documentation consistency tests for Merchant Checkpoint 6."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HANDOFF_NAME = "MERCHANT_CHECKPOINT_6_HANDOFF_2026-09-06.md"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_root_readme_describes_eight_agents():
    content = _read("README.md")

    assert "eight specialists" in content
    assert "| `merchant-manager` |" in content
    assert "tools/merchant/" in content


def test_claude_instructions_include_merchant_boundary():
    content = _read("CLAUDE.md")

    assert "eight reusable specialist agent definitions" in content
    assert "## Merchant Manager boundary" in content
    assert "agent_cli.py" in content
    assert "Checkpoint 6 deliberately denies runtime `--apply`" in content
    assert "only through the teammate's final `SendMessage`" in content


def test_architecture_lists_merchant_agent_and_adapter():
    content = _read(".claude/documents/ARCHITECTURE.md")

    assert "Merchant operations" in content
    assert "merchant-manager.md" in content
    assert "agent_cli.py" in content
    assert "Credential-safe operational agent adapter" in content


def test_checkpoint_6_handoff_exists_and_is_indexed():
    handoff = (
        PROJECT_ROOT / ".claude" / "documents" / HANDOFF_NAME
    )
    index = _read(".claude/documents/README.md")

    assert handoff.is_file()
    assert HANDOFF_NAME in index
    assert "The eight specialists" in index


def test_handoff_records_fail_closed_checkpoint_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "runtime_authorized=False" in content
    assert "rejects every runtime apply" in content
    assert "intent parser does not select `merchant-manager`" in content
    assert "No live Merchant write" in content


def test_handoff_records_final_regression_evidence():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "Implementation and verification complete" in content
    assert "Final Checkpoint 6 focused regression | 102 passed" in content
    assert "1,036 passed, 8 deselected, 97 subtests passed" in content
    assert "1,107 passed, 8 deselected, 118 subtests passed" in content
    assert "Final structural system validation | 80/80 passed" in content
    assert "explicitly targeted\nthe root `tests` directory" in content


def test_handoff_defines_checkpoint_7_continuation_order():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "## 11. Next checkpoint — Checkpoint 7" in content
    assert "Merchant read, proposal, and confirmed-apply operations" in content
    assert "trusted in-process runtime-authorization handoff" in content
    assert "one-time confirmed apply behavior" in content


def test_handoff_preserves_runtime_migration_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "Migration 3 remains unapplied to the runtime database" in content
    assert "fresh read-only plan" in content
    assert "explicit authorization" in content
