"""Documentation contract for Checkpoint 10 worker operations."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCUMENT_NAME = "MERCHANT_ALERT_OPERATIONS.md"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_operations_runbook_exists_and_is_indexed():
    document = PROJECT_ROOT / ".claude" / "documents" / DOCUMENT_NAME

    assert document.is_file()
    assert DOCUMENT_NAME in _read(".claude/documents/README.md")
    assert DOCUMENT_NAME in _read("README.md")


def test_operations_runbook_requires_one_explicit_mode():
    content = _read(f".claude/documents/{DOCUMENT_NAME}")

    for mode in (
        "--dry-run",
        "--enqueue-only",
        "--deliver",
        "--status",
        "--health-check",
    ):
        assert mode in content

    assert "Exactly one mode is required" in content
    assert "There is no default delivery mode" in content
    assert "one-shot" in content


def test_operations_runbook_records_safety_and_recovery_contracts():
    content = _read(f".claude/documents/{DOCUMENT_NAME}")

    for required_text in (
        "at least once",
        "DEAD_LETTER",
        "IgnoreNew",
        "Do not reset attempt counts or claim tokens manually",
        "Expired claims",
        "Exit code",
        "MERCHANT_ALERT_PROJECT_LIMIT",
        "never command-line arguments",
        "does not create or manage a scheduler",
        "never applies a migration",
    ):
        assert required_text in content


def test_operations_runbook_does_not_claim_exactly_once_delivery():
    content = _read(f".claude/documents/{DOCUMENT_NAME}")

    assert "not exactly once" in content
    assert "at least once" in content
