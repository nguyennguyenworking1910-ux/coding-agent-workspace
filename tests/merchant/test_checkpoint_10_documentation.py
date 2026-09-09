"""Final documentation contracts for Merchant Checkpoint 10."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_NAME = "MERCHANT_CHECKPOINT_10_PLAN_2026-09-09.md"
HANDOFF_NAME = "MERCHANT_CHECKPOINT_10_HANDOFF_2026-09-09.md"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_checkpoint_10_handoff_exists_and_is_indexed():
    handoff = PROJECT_ROOT / ".claude" / "documents" / HANDOFF_NAME

    assert handoff.is_file()
    assert HANDOFF_NAME in _read(".claude/documents/README.md")
    assert HANDOFF_NAME in _read("README.md")
    assert HANDOFF_NAME in _read(".claude/documents/ARCHITECTURE.md")


def test_plan_records_runtime_rollout_and_final_closeout_state():
    content = _read(f".claude/documents/{PLAN_NAME}")

    assert "Gate 10.7 runtime rollout verified" in content
    assert "Gate 10.8 final closeout in progress" in content


def test_handoff_records_final_checkpoint_and_execution_modes():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "final planned Merchant Project Manager implementation" in content
    for mode in (
        "`--dry-run`",
        "`--enqueue-only`",
        "`--deliver`",
        "`--status`",
        "`--health-check`",
    ):
        assert mode in content
    assert "There is no implicit delivery mode" in content


def test_handoff_records_honest_delivery_and_lease_contract():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "**at least\nonce**, not exactly once" in content
    assert "fresh opaque token" in content
    assert "stale worker cannot complete a newer claim" in content
    assert "bounded exponential backoff" in content
    assert "becomes `DEAD_LETTER`" in content


def test_handoff_records_channels_and_private_payload_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    for channel in ("`INTERNAL`", "`EMAIL`", "`SLACK`"):
        assert channel in content
    assert "No live external message was sent" in content
    assert "Merchant names, contacts, document content" in content
    assert "arbitrary exceptions, and private paths are excluded" in content


def test_handoff_records_migration_backup_and_authorization():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    for value in (
        "5d305951e7970d982f3d839bc0bb1363d96beb16312445b07cdbde777109e110",
        "7745c7855d6fb0549c1e81c58af5e67a9c7da4289af0c8980ffff784045068be",
        "d230a81f7af0fa54efd10a02a700ccc89d07ed7dea20d62845055b4d032bfd9b",
        "ALERT_LEASE_MIGRATION_4_AUTHORIZED",
    ):
        assert value in content
    assert "only migration 4 pending" in content
    assert "forward-only runner and advisory lock" in content


def test_handoff_records_exact_redacted_runtime_state():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    for row in (
        "| Merchant records | 22 |",
        "| `ONBOARDING` | 22 |",
        "| `ACTIVE` | 0 |",
        "| Workflow templates | 4 |",
        "| Template steps | 64 |",
        "| Template dependencies | 68 |",
        "| Projects | 0 |",
        "| Alert deliveries | 0 |",
    ):
        assert row in content
    assert "No catalog row, credential, environment file" in content


def test_handoff_records_runtime_hashes_and_role_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "c0c48cf58a0cd55a25a78abc35922114a36c42b92d29d6c1c58d97898733a501" in content
    assert "d657f977a384b4747882017ef77163bf4e268a38f6092dfbdd8dfc4ebb609354" in content
    assert "worker uses `merchant_alert`" in content
    assert "no authority to mutate merchants, contacts, projects" in content
    assert "Runtime schema application remains owned by\n`merchant_owner`" in content


def test_handoff_records_test_lifecycle_and_cleanup():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "separate-connection concurrent claim exclusion" in content
    assert "claim-token rotation and stale-token rejection" in content
    assert "cleanup of every generated row in `finally`" in content
    assert "restored the test business tables" in content


def test_handoff_records_operations_and_activation_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "MERCHANT_ALERT_OPERATIONS.md" in content
    assert "Windows Task Scheduler with `IgnoreNew`" in content
    assert "worker never creates a scheduled task" in content
    assert "INTERNAL is the safe initial operational channel" in content
    assert "EMAIL or Slack activation requires a separate" in content


def test_handoff_records_gate_markers_and_final_staging_scope():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    for marker in (
        "CHECKPOINT_10_GATE_1_DELIVERY_CONFIGURATION_AND_PAYLOAD_PASSED",
        "CHECKPOINT_10_GATE_4_WORKER_OPERATIONS_PASSED",
        "CHECKPOINT_10_GATE_5_COMPLETE_NON_LIVE_REGRESSION_PASSED",
        "CHECKPOINT_10_GATE_6_SAFE_TEST_DATABASE_DELIVERY_LIFECYCLE_PASSED",
        "CHECKPOINT_10_GATE_7A_RUNTIME_BACKUP_AND_PREFLIGHT_PASSED",
        "CHECKPOINT_10_GATE_7B_RUNTIME_MIGRATION_4_APPLY_AND_VERIFY_PASSED",
    ):
        assert marker in content
    assert "boundary contains 31 files" in content
    assert "excluded from staging" in content


def test_handoff_defines_ready_for_use_and_debugging_boundary():
    content = _read(f".claude/documents/{HANDOFF_NAME}")

    assert "ready\nfor ordinary use, observation, and issue-driven debugging" in content
    assert "does not authorize a\nreal Merchant workflow mutation" in content
    assert "run `--health-check` with `INTERNAL`" in content
    assert "preserve private-data\nisolation" in content
