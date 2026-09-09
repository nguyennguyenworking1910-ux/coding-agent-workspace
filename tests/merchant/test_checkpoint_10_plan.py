"""Repository and delivery contracts for Merchant Checkpoint 10 Gate 10.0."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_NAME = "MERCHANT_CHECKPOINT_10_PLAN_2026-09-09.md"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_checkpoint_10_plan_exists_and_is_indexed():
    plan = PROJECT_ROOT / ".claude" / "documents" / PLAN_NAME
    document_index = _read(".claude/documents/README.md")
    root_readme = _read("README.md")
    architecture = _read(".claude/documents/ARCHITECTURE.md")

    assert plan.is_file()
    assert PLAN_NAME in document_index
    assert PLAN_NAME in root_readme
    assert PLAN_NAME in architecture


def test_plan_uses_final_checkpoint_9_remote_boundary():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert (
        "**Base commit:** "
        "`ef2ee1d695ca1f0e63472f881d95449cf1db2f02`"
    ) in content
    assert "2ac90c0a57ac857da8d537b8aeeea7b04fc97cb9" in content
    assert "detached checkout is clean" in content
    assert "structural validation passes 81/81" in content


def test_plan_preserves_private_runtime_state():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "migrations 1–3" in content
    assert "4 templates, 64 template steps, and 68 dependencies" in content
    assert "22 `ONBOARDING` records" in content
    assert "no real projects, contacts, identifiers, or\n  alert deliveries" in content
    assert "no private catalog row, credential" in content


def test_plan_extends_existing_worker_instead_of_rebuilding_checker():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "extends the deterministic Checkpoint 8 calculator" in content
    assert "does not rebuild deadline or blocker logic" in content
    assert "uses the isolated `merchant_alert` PostgreSQL role" in content
    assert "claims candidates with `FOR UPDATE SKIP LOCKED`" in content
    assert "writes only `merchant_ops.alert_deliveries`" in content


def test_plan_defines_honest_lease_and_delivery_semantics():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "claim token and expiring lease" in content
    assert "prevent a stale worker from marking a newer attempt" in content
    assert "External notification delivery is **at least once**" in content
    assert "never makes a false exactly-once claim" in content


def test_plan_defines_migration_4_state_and_retry_contract():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "explicit `CLAIMED` and `DEAD_LETTER` statuses" in content
    assert "opaque claim token" in content
    assert "next-attempt time" in content
    assert "Attempt count increments\nonce per successful claim" in content
    assert "bounded exponential backoff" in content


def test_plan_defines_all_three_fail_closed_channels():
    content = _read(f".claude/documents/{PLAN_NAME}")

    for channel in ("`INTERNAL`", "`EMAIL`", "`SLACK`"):
        assert channel in content
    assert "EMAIL and SLACK remain unavailable" in content
    assert "Secrets are accepted\nonly from the repository-root environment" in content
    assert "Tests use fake transports and\nfictitious recipients" in content


def test_plan_requires_explicit_bounded_execution_mode():
    content = _read(f".claude/documents/{PLAN_NAME}")

    for mode in ("`--dry-run`", "`--enqueue-only`", "`--deliver`"):
        assert mode in content
    assert "There is no implicit live delivery mode" in content
    assert "worker remains one-shot" in content
    assert "Invalid or conflicting values\nfail before" in content


def test_plan_defines_redacted_operational_visibility():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "bounded aggregate metrics" in content
    assert "expired leases" in content
    assert "dead-letter count" in content
    assert "never returns a Merchant row" in content
    assert "stable reason codes" in content


def test_plan_preserves_alert_role_and_requires_migration_authorization():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "restricted by the `merchant_alert` database role" in content
    assert "unable to mutate merchants, contacts, projects" in content
    assert "fresh verified PostgreSQL custom-format runtime backup" in content
    assert "`ALERT_LEASE_MIGRATION_4_AUTHORIZED`" in content
    assert "forward-only application by `merchant_owner`" in content


def test_plan_defines_every_checkpoint_10_gate():
    content = _read(f".claude/documents/{PLAN_NAME}")

    for gate in range(9):
        assert f"### Gate 10.{gate}" in content


def test_plan_defines_final_pre_use_completion_boundary():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "final planned Merchant Project Manager checkpoint" in content
    assert "Checkpoint 10 is complete only when" in content
    assert "initialized 22-record catalog and four templates remain unchanged" in content
    assert "ready for ordinary use, observation, and issue-driven debugging" in content
    assert "never performed automatically" in content
