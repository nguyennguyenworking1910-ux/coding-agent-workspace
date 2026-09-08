"""Checkpoint 9.5 standard runtime template plan tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from claude.clients.merchant.runtime_readiness import (
    BUSINESS_TABLES,
    TEMPLATE_INITIALIZATION_READY,
    RuntimeBackupEvidence,
    RuntimeReadinessReport,
)
from claude.clients.merchant.runtime_template_plan import (
    EXPECTED_FULL_TEMPLATE_SHA256,
    EXPECTED_READINESS_TEMPLATE_SHA256,
    RuntimeTemplatePlanError,
    build_runtime_template_initialization_plan,
)


BACKUP_SHA256 = "5" * 64


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
        state=TEMPLATE_INITIALIZATION_READY,
        checks={"ready": True},
        database="coding_agent_merchant",
        user="merchant_app",
        encoding="UTF8",
        read_only="on",
        schema_owner="merchant_owner",
        applied_versions=(1, 2, 3),
        pending_versions=(),
        migration_3_sha256="2" * 64,
        business_counts={name: 0 for name in BUSINESS_TABLES},
        merchant_status_counts={},
        stored_template_count=0,
        expected_template_sha256=(
            EXPECTED_READINESS_TEMPLATE_SHA256
        ),
        stored_template_sha256="4" * 64,
        source_sha256="6" * 64,
        catalog_sha256="7" * 64,
        backup=_backup(),
    )


def _build(*, readiness=None, backup_sha256=BACKUP_SHA256):
    return build_runtime_template_initialization_plan(
        readiness if readiness is not None else _readiness(),
        expected_backup_sha256=backup_sha256,
    )


def test_exact_readiness_builds_four_template_plan():
    plan = _build()

    assert plan.template_count == 4
    assert plan.step_count == 64
    assert plan.dependency_count == 68
    assert plan.manifest_sha256 == EXPECTED_FULL_TEMPLATE_SHA256
    assert len(plan.plan_sha256) == 64


def test_plan_contains_frozen_template_identities_and_fingerprints():
    summary = _build().safe_summary()

    assert [item["template_id"] for item in summary["templates"]] == [
        "f48689c2-67a7-58cf-9a12-0bcdec07477b",
        "8099202a-6449-52e6-8eca-c8012767c883",
        "a3cc7546-6b0f-58a7-b78d-8e7a3289dc10",
        "4ce4df94-da4e-55b5-968b-ca24d4ecc3d3",
    ]
    assert all(
        len(item["fingerprint"]) == 64
        for item in summary["templates"]
    )


def test_safe_summary_binds_separate_authority_and_zero_catalog_scope():
    summary = _build().safe_summary()

    assert summary["target"] == {
        "host": "127.0.0.1",
        "port": 5434,
        "database": "coding_agent_merchant",
        "read_role": "merchant_app",
        "write_role": "merchant_owner",
    }
    assert summary["authorization_phrase"] == (
        "STANDARD_TEMPLATES_AUTHORIZED"
    )
    assert summary["execution_contract"] == {
        "transaction_mode": "SINGLE_ATOMIC_TRANSACTION",
        "idempotency": "IDENTICAL_ONLY",
        "conflict_behavior": "FAIL_CLOSED",
        "catalog_changes": 0,
        "business_record_changes": 0,
    }


def test_summary_and_repr_expose_no_password_or_private_catalog():
    plan = _build()
    rendered = json.dumps(plan.safe_summary()) + repr(plan)

    assert "password" not in rendered.lower()
    assert "merchant_catalog_private" not in rendered.lower()
    assert "backup_path" not in rendered.lower()


def test_equivalent_readiness_produces_deterministic_plan():
    first = _build()
    second = _build()

    assert first == second
    assert first.plan_sha256 == second.plan_sha256


@pytest.mark.parametrize(
    "readiness",
    (
        replace(_readiness(), state="RUNTIME_MIGRATIONS_READY"),
        replace(_readiness(), applied_versions=(1, 2)),
        replace(_readiness(), pending_versions=(3,)),
        replace(_readiness(), database="coding_agent_merchant_test"),
        replace(_readiness(), user="merchant_owner"),
        replace(_readiness(), read_only="off"),
        replace(_readiness(), stored_template_count=1),
        replace(_readiness(), business_counts={"merchants": 1}),
        replace(
            _readiness(),
            expected_template_sha256="a" * 64,
        ),
    ),
)
def test_runtime_readiness_must_remain_exact(readiness):
    with pytest.raises(RuntimeTemplatePlanError) as error:
        _build(readiness=readiness)

    assert error.value.reason_code == "READINESS_STATE_MISMATCH"


def test_backup_hash_must_match_readiness_evidence():
    with pytest.raises(RuntimeTemplatePlanError) as error:
        _build(backup_sha256="a" * 64)

    assert error.value.reason_code == "READINESS_STATE_MISMATCH"


@pytest.mark.parametrize("value", (None, "short", "A" * 64))
def test_backup_hash_must_be_lowercase_sha256(value):
    with pytest.raises(RuntimeTemplatePlanError) as error:
        _build(backup_sha256=value)

    assert error.value.reason_code == "INVALID_BACKUP_HASH"


def test_plain_mapping_cannot_replace_validated_readiness():
    with pytest.raises(RuntimeTemplatePlanError) as error:
        _build(readiness={"success": True})

    assert error.value.reason_code == "INVALID_READINESS_REPORT"


def test_changed_standard_manifest_fails_closed():
    changed = (
        {
            "name": "CHANGED",
            "variant": "CHANGED",
            "version": 1,
            "project_type": "MEDIA_TOP_UP",
            "template_id": (
                "00000000-0000-0000-0000-000000000001"
            ),
            "fingerprint": "a" * 64,
            "step_count": 1,
            "dependency_count": 1,
        },
    )

    with patch(
        "claude.clients.merchant.runtime_template_plan"
        ".standard_template_manifest",
        return_value=changed,
    ):
        with pytest.raises(RuntimeTemplatePlanError) as error:
            _build()

    assert error.value.reason_code == "TEMPLATE_MANIFEST_MISMATCH"
