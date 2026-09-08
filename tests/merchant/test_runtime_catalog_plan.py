"""Checkpoint 9.5 private runtime catalog binding tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from claude.agents.tools.merchant.catalog_contract import (
    PrivateMerchantCatalog,
    validate_private_catalog_bytes,
)
from claude.agents.tools.merchant.catalog_plan import (
    CatalogTargetConflictError,
)
from claude.clients.merchant.runtime_catalog_plan import (
    CATALOG_AUDIT_EVENT_TYPE,
    RuntimeCatalogPlanError,
    build_runtime_catalog_initialization_plan,
)
from claude.clients.merchant.runtime_readiness import (
    BUSINESS_TABLES,
    CATALOG_INITIALIZATION_READY,
    RuntimeBackupEvidence,
    RuntimeReadinessReport,
)
from claude.clients.merchant.runtime_template_plan import (
    EXPECTED_READINESS_TEMPLATE_SHA256,
)


BACKUP_SHA256 = "5" * 64


def _catalog() -> PrivateMerchantCatalog:
    records = [
        {
            "code": f"PRIVATE_{number:02d}",
            "name": f"Đối Tác Riêng {number:02d}",
            "account_status": (
                "ONBOARDING" if number <= 5 else "ACTIVE"
            ),
        }
        for number in range(1, 23)
    ]
    return validate_private_catalog_bytes(
        json.dumps(records, ensure_ascii=False).encode("utf-8")
    )


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
        state=CATALOG_INITIALIZATION_READY,
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
        stored_template_count=4,
        expected_template_sha256=(
            EXPECTED_READINESS_TEMPLATE_SHA256
        ),
        stored_template_sha256=(
            EXPECTED_READINESS_TEMPLATE_SHA256
        ),
        source_sha256="6" * 64,
        catalog_sha256="7" * 64,
        backup=_backup(),
    )


def _build(
    *,
    readiness=None,
    catalog=None,
    existing_records=(),
    backup_sha256=BACKUP_SHA256,
):
    selected_catalog = catalog or _catalog()
    return build_runtime_catalog_initialization_plan(
        readiness if readiness is not None else _readiness(),
        selected_catalog,
        existing_records=existing_records,
        expected_source_sha256=selected_catalog.source_sha256,
        expected_catalog_sha256=selected_catalog.catalog_sha256,
        expected_backup_sha256=backup_sha256,
    )


def test_empty_runtime_builds_exact_atomic_insert_plan():
    plan = _build()
    summary = plan.safe_summary()

    assert summary["action"] == "INSERT"
    assert summary["record_count"] == 22
    assert summary["target_count_before"] == 0
    assert summary["target_count_after"] == 22
    assert summary["status_counts"] == {
        "ACTIVE": 17,
        "ONBOARDING": 5,
    }
    assert len(summary["runtime_plan_sha256"]) == 64


def test_plan_binds_least_privilege_role_and_audit_scope():
    summary = _build().safe_summary()

    assert summary["target"] == {
        "host": "127.0.0.1",
        "port": 5434,
        "database": "coding_agent_merchant",
        "write_role": "merchant_app",
    }
    assert summary["authorization_phrase"] == (
        "PRIVATE_CATALOG_22_AUTHORIZED"
    )
    assert summary["execution_contract"] == {
        "transaction_mode": "SINGLE_ATOMIC_TRANSACTION",
        "idempotency": "IDENTICAL_SOURCE_NO_OP",
        "conflict_behavior": "FAIL_CLOSED",
        "merchant_inserts": 22,
        "audit_event_inserts": 22,
        "audit_event_type": CATALOG_AUDIT_EVENT_TYPE,
        "contact_inserts": 0,
        "project_inserts": 0,
    }


def test_plan_summary_and_repr_do_not_expose_private_rows():
    catalog = _catalog()
    plan = _build(catalog=catalog)
    rendered = json.dumps(plan.safe_summary()) + repr(plan)

    for record in catalog.records:
        assert record.code not in rendered
        assert record.name not in rendered
        assert record.merchant_id not in rendered


def test_equivalent_evidence_produces_deterministic_plan():
    first = _build()
    second = _build()

    assert first == second
    assert first.runtime_plan_sha256 == (
        second.runtime_plan_sha256
    )


@pytest.mark.parametrize(
    "readiness",
    (
        replace(_readiness(), state="TEMPLATE_INITIALIZATION_READY"),
        replace(_readiness(), applied_versions=(1, 2)),
        replace(_readiness(), pending_versions=(3,)),
        replace(_readiness(), database="coding_agent_merchant_test"),
        replace(_readiness(), user="merchant_owner"),
        replace(_readiness(), read_only="off"),
        replace(_readiness(), stored_template_count=3),
        replace(_readiness(), stored_template_sha256="a" * 64),
        replace(_readiness(), business_counts={"merchants": 1}),
    ),
)
def test_runtime_readiness_must_remain_exact(readiness):
    with pytest.raises(RuntimeCatalogPlanError) as error:
        _build(readiness=readiness)

    assert error.value.reason_code == "READINESS_STATE_MISMATCH"


def test_nonempty_runtime_target_fails_without_private_output():
    catalog = _catalog()
    record = catalog.records[0]
    existing = [
        {
            "merchant_id": record.merchant_id,
            "code": record.code,
            "name": record.name,
            "region_code": record.region_code,
            "account_status": record.account_status,
            "version": 1,
        }
    ]

    with pytest.raises(CatalogTargetConflictError) as error:
        _build(catalog=catalog, existing_records=existing)

    rendered = str(error.value)
    assert record.code not in rendered
    assert record.name not in rendered
    assert record.merchant_id not in rendered


def test_backup_hash_must_match_readiness_evidence():
    with pytest.raises(RuntimeCatalogPlanError) as error:
        _build(backup_sha256="a" * 64)

    assert error.value.reason_code == "READINESS_STATE_MISMATCH"


@pytest.mark.parametrize("value", (None, "short", "A" * 64))
def test_backup_hash_must_be_lowercase_sha256(value):
    with pytest.raises(RuntimeCatalogPlanError) as error:
        _build(backup_sha256=value)

    assert error.value.reason_code == "INVALID_BACKUP_HASH"


def test_plain_mapping_cannot_replace_validated_readiness():
    with pytest.raises(RuntimeCatalogPlanError) as error:
        _build(readiness={"success": True})

    assert error.value.reason_code == "INVALID_READINESS_REPORT"
