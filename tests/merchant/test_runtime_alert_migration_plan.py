"""Checkpoint 10 runtime alert migration plan tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from claude.clients.merchant.runtime_alert_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS,
    EXPECTED_PENDING_MIGRATIONS,
    MIGRATION_AUTHORIZATION_PHRASE,
    RuntimeAlertMigrationPlanError,
    build_runtime_alert_migration_deployment_plan,
)
from claude.clients.merchant.runtime_readiness import (
    RuntimeBackupEvidence,
)
from claude.clients.merchant.runtime_verification import (
    RuntimeVerificationReport,
)


BACKUP_SHA256 = "5" * 64
SOURCE_SHA256 = "6" * 64
CATALOG_SHA256 = "7" * 64


def _backup() -> RuntimeBackupEvidence:
    return RuntimeBackupEvidence(
        backup_sha256=BACKUP_SHA256,
        size_bytes=4096,
        created_at_utc=datetime(
            2026, 9, 9, tzinfo=timezone.utc
        ),
        format="POSTGRESQL_CUSTOM",
        restore_list_verified=True,
        recovery_procedure_reviewed=True,
        roles_recoverable=True,
    )


def _verification() -> RuntimeVerificationReport:
    return RuntimeVerificationReport(
        success=True,
        checks={"verified": True},
        record_count=22,
        status_counts={"ACTIVE": 0, "ONBOARDING": 22},
        ordinary_reads={
            "all_merchants": 22,
            "onboarding_merchants": 22,
            "active_merchants": 0,
            "projects": 0,
            "alerts": 0,
        },
        workflow_preconditions={
            "runtime_projects_created": 0,
        },
        migration_versions=(1, 2, 3),
        template_count=4,
        template_step_count=64,
        template_dependency_count=68,
        catalog_event_count=22,
        source_sha256=SOURCE_SHA256,
        catalog_sha256=CATALOG_SHA256,
        stored_catalog_sha256=CATALOG_SHA256,
    )


def _migration_plan() -> dict[str, object]:
    return {
        "success": True,
        "mode": "plan",
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
            for item in EXPECTED_APPLIED_MIGRATIONS
        ],
        "pending_migrations": [
            item.safe_summary()
            for item in EXPECTED_PENDING_MIGRATIONS
        ],
        "checksum_conflicts": [],
        "missing_local_versions": [],
        "errors": [],
    }


def _build(**changes):
    return build_runtime_alert_migration_deployment_plan(
        changes.get("verification", _verification()),
        changes.get("migration_plan", _migration_plan()),
        changes.get("backup", _backup()),
        expected_backup_sha256=changes.get(
            "backup_sha256", BACKUP_SHA256
        ),
    )


def test_exact_evidence_builds_migration_4_authorization_plan():
    plan = _build()
    summary = plan.safe_summary()

    assert tuple(
        item.version for item in plan.applied_migrations
    ) == (1, 2, 3)
    assert tuple(
        item.version for item in plan.pending_migrations
    ) == (4,)
    assert plan.requires_authorization is True
    assert summary["authorization_phrase"] == (
        MIGRATION_AUTHORIZATION_PHRASE
    )
    assert summary["execution_contract"]["migration_order"] == [4]
    assert len(plan.plan_sha256) == 64


def test_safe_summary_binds_runtime_without_private_values():
    plan = _build()
    summary = plan.safe_summary()

    assert summary["target"] == {
        "host": "127.0.0.1",
        "port": 5434,
        "database": "coding_agent_merchant",
        "plan_role": "merchant_app",
        "apply_role": "merchant_owner",
    }
    assert summary["runtime_state"]["merchant_count"] == 22
    rendered = json.dumps(summary) + repr(plan)
    assert "password" not in rendered.lower()
    assert "catalog_path" not in rendered.lower()
    assert "backup_path" not in rendered.lower()


def test_plan_hash_is_deterministic_and_backup_bound():
    first = _build()
    second = _build()
    different = _build(
        backup=replace(
            _backup(), backup_sha256="8" * 64
        ),
        backup_sha256="8" * 64,
    )

    assert first == second
    assert first.plan_sha256 != different.plan_sha256


@pytest.mark.parametrize(
    "change",
    (
        {"success": False},
        {"mode": "apply"},
        {"selected_target": "test"},
        {"errors": ["unsafe"]},
        {"checksum_conflicts": [4]},
        {"missing_local_versions": [1]},
    ),
)
def test_inexact_plan_envelope_fails_closed(change):
    migration_plan = _migration_plan()
    migration_plan.update(change)

    with pytest.raises(RuntimeAlertMigrationPlanError) as error:
        _build(migration_plan=migration_plan)

    assert error.value.reason_code == "PLAN_ENVELOPE_MISMATCH"


def test_changed_migration_sets_fail_closed():
    migration_plan = _migration_plan()
    migration_plan["pending_migrations"] = []

    with pytest.raises(RuntimeAlertMigrationPlanError) as error:
        _build(migration_plan=migration_plan)

    assert error.value.reason_code == (
        "PENDING_MIGRATIONS_MISMATCH"
    )

    migration_plan = _migration_plan()
    migration_plan["applied_migrations"] = []

    with pytest.raises(RuntimeAlertMigrationPlanError) as error:
        _build(migration_plan=migration_plan)

    assert error.value.reason_code == "APPLIED_BASELINE_MISMATCH"


@pytest.mark.parametrize(
    "verification",
    (
        replace(_verification(), success=False),
        replace(_verification(), record_count=21),
        replace(_verification(), migration_versions=(1, 2, 3, 4)),
        replace(_verification(), stored_catalog_sha256="8" * 64),
        replace(_verification(), template_count=3),
    ),
)
def test_changed_runtime_verification_fails_closed(verification):
    with pytest.raises(RuntimeAlertMigrationPlanError) as error:
        _build(verification=verification)

    assert error.value.reason_code == "RUNTIME_STATE_MISMATCH"


def test_missing_or_changed_backup_fails_closed():
    with pytest.raises(RuntimeAlertMigrationPlanError) as error:
        _build(backup_sha256="9" * 64)

    assert error.value.reason_code == "BACKUP_EVIDENCE_MISMATCH"

    with pytest.raises(RuntimeAlertMigrationPlanError) as error:
        _build(backup_sha256="not-a-hash")

    assert error.value.reason_code == "INVALID_BACKUP_HASH"
