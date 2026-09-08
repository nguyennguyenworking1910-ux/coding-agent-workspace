"""Checkpoint 9.4 runtime migration deployment-plan tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from claude.clients.merchant.runtime_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS,
    EXPECTED_PENDING_MIGRATIONS,
    MIGRATION_AUTHORIZATION_PHRASE,
    RuntimeMigrationPlanError,
    build_runtime_migration_deployment_plan,
)
from claude.clients.merchant.runtime_readiness import (
    BUSINESS_TABLES,
    RUNTIME_MIGRATIONS_READY,
    RuntimeBackupEvidence,
    RuntimeReadinessReport,
)


BACKUP_SHA256 = "5" * 64
SOURCE_SHA256 = "6" * 64
CATALOG_SHA256 = "7" * 64
TEMPLATE_SHA256 = "8" * 64
EMPTY_TEMPLATE_SHA256 = "9" * 64


def _backup() -> RuntimeBackupEvidence:
    return RuntimeBackupEvidence(
        backup_sha256=BACKUP_SHA256,
        size_bytes=1024,
        created_at_utc=datetime(
            2026,
            9,
            8,
            tzinfo=timezone.utc,
        ),
        format="POSTGRESQL_CUSTOM",
        restore_list_verified=True,
        recovery_procedure_reviewed=True,
        roles_recoverable=True,
    )


def _readiness() -> RuntimeReadinessReport:
    return RuntimeReadinessReport(
        success=True,
        state=RUNTIME_MIGRATIONS_READY,
        checks={"ready": True},
        database="coding_agent_merchant",
        user="merchant_app",
        encoding="UTF8",
        read_only="on",
        schema_owner="merchant_owner",
        applied_versions=(1,),
        pending_versions=(2, 3),
        migration_3_sha256=(
            EXPECTED_PENDING_MIGRATIONS[1].checksum
        ),
        business_counts={name: 0 for name in BUSINESS_TABLES},
        merchant_status_counts={},
        stored_template_count=0,
        expected_template_sha256=TEMPLATE_SHA256,
        stored_template_sha256=EMPTY_TEMPLATE_SHA256,
        source_sha256=SOURCE_SHA256,
        catalog_sha256=CATALOG_SHA256,
        backup=_backup(),
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
                "executed_at": "2026-09-01T00:00:00+00:00",
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


def _build(
    *,
    readiness=None,
    migration_plan=None,
    backup_sha256=BACKUP_SHA256,
):
    return build_runtime_migration_deployment_plan(
        readiness if readiness is not None else _readiness(),
        (
            migration_plan
            if migration_plan is not None
            else _migration_plan()
        ),
        expected_backup_sha256=backup_sha256,
    )


def test_exact_live_evidence_builds_authorization_plan():
    plan = _build()
    summary = plan.safe_summary()

    assert tuple(
        item.version for item in plan.applied_migrations
    ) == (1,)
    assert tuple(
        item.version for item in plan.pending_migrations
    ) == (2, 3)
    assert plan.backup_sha256 == BACKUP_SHA256
    assert plan.requires_authorization is True
    assert len(plan.plan_sha256) == 64
    assert summary["authorization_phrase"] == (
        MIGRATION_AUTHORIZATION_PHRASE
    )


def test_safe_summary_binds_exact_target_roles_and_scope():
    summary = _build().safe_summary()

    assert summary["target"] == {
        "host": "127.0.0.1",
        "port": 5434,
        "database": "coding_agent_merchant",
        "plan_role": "merchant_app",
        "apply_role": "merchant_owner",
    }
    assert summary["execution_contract"] == {
        "runner_sessions": 1,
        "migration_order": [2, 3],
        "transaction_scope": "ONE_PER_MIGRATION",
        "advisory_lock": True,
        "forward_only": True,
        "template_changes": 0,
        "catalog_changes": 0,
    }


def test_summary_and_repr_contain_no_password_or_path():
    plan = _build()
    rendered = json.dumps(plan.safe_summary()) + repr(plan)

    assert "password" not in rendered.lower()
    assert "private_catalog" not in rendered.lower()
    assert "backup_path" not in rendered.lower()
    assert "C:\\" not in rendered


def test_equivalent_evidence_produces_deterministic_hash():
    first = _build()
    second = _build()

    assert first == second
    assert first.plan_sha256 == second.plan_sha256


@pytest.mark.parametrize(
    ("change", "reason_code"),
    (
        ({"success": False}, "PLAN_ENVELOPE_MISMATCH"),
        ({"mode": "apply"}, "PLAN_ENVELOPE_MISMATCH"),
        ({"selected_target": "test"}, "PLAN_ENVELOPE_MISMATCH"),
        ({"errors": ["conflict"]}, "PLAN_ENVELOPE_MISMATCH"),
        (
            {"checksum_conflicts": [2]},
            "PLAN_ENVELOPE_MISMATCH",
        ),
        (
            {"missing_local_versions": [1]},
            "PLAN_ENVELOPE_MISMATCH",
        ),
    ),
)
def test_inexact_plan_envelope_fails_closed(change, reason_code):
    migration_plan = _migration_plan()
    migration_plan.update(change)

    with pytest.raises(RuntimeMigrationPlanError) as error:
        _build(migration_plan=migration_plan)

    assert error.value.reason_code == reason_code


def test_changed_applied_baseline_fails_closed():
    migration_plan = _migration_plan()
    migration_plan["applied_migrations"] = []

    with pytest.raises(RuntimeMigrationPlanError) as error:
        _build(migration_plan=migration_plan)

    assert error.value.reason_code == (
        "APPLIED_BASELINE_MISMATCH"
    )


@pytest.mark.parametrize(
    "pending",
    (
        [],
        [
            EXPECTED_PENDING_MIGRATIONS[1].safe_summary(),
        ],
        [
            item.safe_summary()
            for item in reversed(EXPECTED_PENDING_MIGRATIONS)
        ],
        [
            *(
                item.safe_summary()
                for item in EXPECTED_PENDING_MIGRATIONS
            ),
            {
                "version": 4,
                "description": "unexpected",
                "checksum": "a" * 64,
            },
        ],
    ),
)
def test_pending_set_must_be_exactly_two_then_three(pending):
    migration_plan = _migration_plan()
    migration_plan["pending_migrations"] = pending

    with pytest.raises(RuntimeMigrationPlanError) as error:
        _build(migration_plan=migration_plan)

    assert error.value.reason_code == (
        "PENDING_MIGRATIONS_MISMATCH"
    )


def test_changed_pending_checksum_fails_closed():
    migration_plan = _migration_plan()
    pending = list(migration_plan["pending_migrations"])
    pending[0] = {**pending[0], "checksum": "a" * 64}
    migration_plan["pending_migrations"] = pending

    with pytest.raises(RuntimeMigrationPlanError) as error:
        _build(migration_plan=migration_plan)

    assert error.value.reason_code == (
        "PENDING_MIGRATIONS_MISMATCH"
    )


@pytest.mark.parametrize(
    "readiness",
    (
        replace(_readiness(), state="NOT_READY"),
        replace(_readiness(), pending_versions=(3,)),
        replace(_readiness(), database="coding_agent_merchant_test"),
        replace(_readiness(), user="merchant_owner"),
        replace(_readiness(), read_only="off"),
        replace(_readiness(), stored_template_count=4),
        replace(_readiness(), business_counts={"merchants": 1}),
    ),
)
def test_readiness_must_remain_exact(readiness):
    with pytest.raises(RuntimeMigrationPlanError) as error:
        _build(readiness=readiness)

    assert error.value.reason_code == (
        "READINESS_STATE_MISMATCH"
    )


def test_reviewed_backup_hash_must_match_evidence():
    with pytest.raises(RuntimeMigrationPlanError) as error:
        _build(backup_sha256="a" * 64)

    assert error.value.reason_code == (
        "READINESS_STATE_MISMATCH"
    )


@pytest.mark.parametrize("value", (None, "short", "A" * 64))
def test_reviewed_backup_hash_must_be_lowercase_sha256(value):
    with pytest.raises(RuntimeMigrationPlanError) as error:
        _build(backup_sha256=value)

    assert error.value.reason_code == "INVALID_BACKUP_HASH"


def test_plain_objects_cannot_replace_validated_readiness():
    with pytest.raises(RuntimeMigrationPlanError) as error:
        _build(readiness={"success": True})

    assert error.value.reason_code == (
        "INVALID_READINESS_REPORT"
    )
