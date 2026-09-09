"""Checkpoint 10 post-migration runtime verification tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from claude.clients.merchant.runtime_alert_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS,
    EXPECTED_PENDING_MIGRATIONS,
)
from claude.clients.merchant.runtime_alert_migration_verification import (
    RuntimeAlertMigrationVerificationError,
    verify_runtime_alert_migration,
)
from claude.clients.merchant.runtime_readiness import (
    RuntimeBackupEvidence,
)
from claude.clients.merchant.runtime_verification import (
    RuntimeVerificationReport,
)


BACKUP_HASH = "5" * 64
SOURCE_HASH = "6" * 64
CATALOG_HASH = "7" * 64


def _checkpoint9_report() -> RuntimeVerificationReport:
    checks = {
        "runtime_database_exact": True,
        "migration_history_exact": False,
        "catalog_target_identical": True,
        "noncatalog_business_state_empty": True,
        "verification_made_no_runtime_change": True,
    }
    return RuntimeVerificationReport(
        success=False,
        checks=checks,
        record_count=22,
        status_counts={"ACTIVE": 0, "ONBOARDING": 22},
        ordinary_reads={
            "all_merchants": 22,
            "onboarding_merchants": 22,
            "active_merchants": 0,
            "projects": 0,
            "alerts": 0,
        },
        workflow_preconditions={"runtime_projects_created": 0},
        migration_versions=(1, 2, 3, 4),
        template_count=4,
        template_step_count=64,
        template_dependency_count=68,
        catalog_event_count=22,
        source_sha256=SOURCE_HASH,
        catalog_sha256=CATALOG_HASH,
        stored_catalog_sha256=CATALOG_HASH,
    )


def _status() -> dict[str, object]:
    migrations = (
        *EXPECTED_APPLIED_MIGRATIONS,
        *EXPECTED_PENDING_MIGRATIONS,
    )
    return {
        "success": True,
        "mode": "status",
        "selected_target": "runtime",
        "redacted_connection": (
            "postgresql://merchant_app@127.0.0.1:5434/"
            "coding_agent_merchant"
        ),
        "applied_migrations": [
            {
                **item.safe_summary(),
                "executed_at": "2026-09-09T00:00:00+00:00",
            }
            for item in migrations
        ],
        "pending_migrations": [],
        "checksum_conflicts": [],
        "missing_local_versions": [],
        "errors": [],
    }


def _health() -> dict[str, object]:
    return {
        "success": True,
        "mode": "health_check",
        "checks": {"migration_4_exact": True},
        "failed_checks": [],
        "database": {
            "database": "coding_agent_merchant",
            "user": "merchant_alert",
            "read_only": "on",
            "encoding": "UTF8",
        },
        "queues": [],
    }


def _backup() -> RuntimeBackupEvidence:
    return RuntimeBackupEvidence(
        backup_sha256=BACKUP_HASH,
        size_bytes=4096,
        created_at_utc=datetime(
            2026, 9, 9, tzinfo=timezone.utc
        ),
        format="POSTGRESQL_CUSTOM",
        restore_list_verified=True,
        recovery_procedure_reviewed=True,
        roles_recoverable=True,
    )


def _verify(**changes):
    return verify_runtime_alert_migration(
        changes.get("checkpoint9", _checkpoint9_report()),
        changes.get("status", _status()),
        changes.get("health", _health()),
        changes.get("backup", _backup()),
        expected_backup_sha256=changes.get(
            "backup_hash", BACKUP_HASH
        ),
    )


def test_exact_post_migration_state_is_accepted_and_redacted():
    report = _verify()
    summary = report.safe_summary()

    assert report.success is True
    assert report.failed_checks == ()
    assert summary["migration_versions"] == [1, 2, 3, 4]
    assert summary["runtime_state"]["merchant_count"] == 22
    rendered = json.dumps(summary) + repr(report)
    assert "password" not in rendered.lower()
    assert "catalog_path" not in rendered.lower()
    assert "backup_path" not in rendered.lower()


def test_changed_catalog_or_business_state_fails_closed():
    checkpoint9 = _checkpoint9_report()
    checks = dict(checkpoint9.checks)
    checks["noncatalog_business_state_empty"] = False
    report = _verify(
        checkpoint9=replace(checkpoint9, checks=checks)
    )

    assert report.success is False
    assert "checkpoint_9_catalog_state_preserved" in (
        report.failed_checks
    )


def test_inexact_migration_history_fails_closed():
    status = _status()
    status["applied_migrations"] = status["applied_migrations"][:-1]

    report = _verify(status=status)

    assert report.success is False
    assert "migration_history_exact" in report.failed_checks


def test_wrong_role_or_nonempty_queue_fails_closed():
    health = _health()
    health["database"] = {
        **health["database"],
        "user": "merchant_app",
    }
    health["queues"] = [{"total_count": 1}]

    report = _verify(health=health)

    assert report.success is False
    assert "runtime_alert_role_healthy" in report.failed_checks
    assert "runtime_alert_queue_empty" in report.failed_checks


def test_backup_binding_is_exact():
    report = _verify(backup_hash="8" * 64)
    assert report.success is False
    assert "fresh_backup_still_bound" in report.failed_checks

    with pytest.raises(
        RuntimeAlertMigrationVerificationError
    ) as error:
        _verify(backup_hash="invalid")
    assert error.value.reason_code == "INVALID_BACKUP_HASH"
