"""Contracts for read-only initialized-runtime verification."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from claude.agents.tools.merchant.catalog_contract import (
    validate_private_catalog_bytes,
)
from claude.agents.tools.merchant.workflow_templates import (
    standard_template_manifest,
)
from claude.clients.merchant.catalog_initializer import _event_id
from claude.clients.merchant.runtime_migration_plan import (
    EXPECTED_APPLIED_MIGRATIONS,
    EXPECTED_PENDING_MIGRATIONS,
)
from claude.clients.merchant.runtime_readiness import BUSINESS_TABLES
from claude.clients.merchant.runtime_verification import (
    EXPECTED_STATUS_COUNTS,
    RuntimeVerificationError,
    _exercise_ordinary_reads,
    _stored_catalog_hash,
    _workflow_precondition_checks,
    verify_initialized_runtime,
)


def _catalog():
    payload = [
        {
            "code": f"PRIVATE_{number:02d}",
            "name": f"Đối Tác Riêng {number:02d}",
            "account_status": "ONBOARDING",
        }
        for number in range(1, 23)
    ]
    return validate_private_catalog_bytes(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )


def _merchant_rows(catalog):
    return tuple(
        {
            "merchant_id": record.merchant_id,
            "code": record.code,
            "name": record.name,
            "region_code": record.region_code,
            "account_status": record.account_status,
            "version": 1,
        }
        for record in catalog.records
    )


def _migration_rows():
    return tuple(
        {
            "version": item.version,
            "description": item.description,
            "checksum": item.checksum,
        }
        for item in (
            *EXPECTED_APPLIED_MIGRATIONS,
            *EXPECTED_PENDING_MIGRATIONS,
        )
    )


def _template_rows():
    return tuple(
        sorted(
            (
                {
                    "template_id": str(item["template_id"]),
                    "name": str(item["name"]),
                    "version": int(item["version"]),
                    "variant": str(item["variant"]),
                    "step_count": int(item["step_count"]),
                    "dependency_count": int(
                        item["dependency_count"]
                    ),
                }
                for item in standard_template_manifest()
            ),
            key=lambda item: (item["name"], item["version"]),
        )
    )


def _event_rows(catalog):
    return tuple(
        {
            "id": str(
                _event_id(
                    catalog.catalog_sha256,
                    record.merchant_id,
                )
            ),
            "merchant_id": record.merchant_id,
            "project_id": None,
            "entity_type": "MERCHANT",
            "entity_id": record.merchant_id,
            "change_summary": (
                "Merchant initialized from reviewed private catalog"
            ),
            "old_values": {},
            "new_values": {
                "account_status": record.account_status,
                "catalog_sha256": catalog.catalog_sha256,
                "version": 1,
            },
            "triggered_by": None,
        }
        for record in catalog.records
    )


def _snapshot(catalog):
    counts = {name: 0 for name in BUSINESS_TABLES}
    counts["merchants"] = 22
    counts["project_events"] = 22
    return {
        "identity": {
            "database": "coding_agent_merchant",
            "user": "merchant_app",
            "read_only": "on",
            "encoding": "UTF8",
        },
        "merchants": _merchant_rows(catalog),
        "migrations": _migration_rows(),
        "templates": _template_rows(),
        "catalog_events": _event_rows(catalog),
        "counts": counts,
    }


def _ordinary_evidence():
    return {
        "merchant_reads_exact": True,
        "status_filters_exact": True,
        "sensitive_fields_absent": True,
        "project_reads_empty": True,
        "all_count": 22,
        "onboarding_count": 22,
        "active_count": 0,
        "project_count": 0,
        "alert_count": 0,
    }


def _repository():
    repository = MagicMock()
    repository.config = SimpleNamespace(
        host="127.0.0.1",
        port=5434,
        database="coding_agent_merchant",
        user="merchant_app",
    )
    return repository


def _verify(catalog, snapshots):
    with (
        patch(
            "claude.clients.merchant.runtime_verification"
            "._collect_runtime_snapshot",
            side_effect=snapshots,
        ),
        patch(
            "claude.clients.merchant.runtime_verification"
            "._exercise_ordinary_reads",
            return_value=_ordinary_evidence(),
        ),
    ):
        return verify_initialized_runtime(
            _repository(),
            catalog,
            expected_source_sha256=catalog.source_sha256,
            expected_catalog_sha256=catalog.catalog_sha256,
        )


def test_exact_initialized_runtime_is_verified():
    catalog = _catalog()
    snapshot = _snapshot(catalog)

    report = _verify(catalog, [snapshot, snapshot])

    assert report.success is True
    assert report.failed_checks == ()
    assert report.record_count == 22
    assert dict(report.status_counts) == EXPECTED_STATUS_COUNTS
    assert report.migration_versions == (1, 2, 3)
    assert report.template_count == 4
    assert report.template_step_count == 64
    assert report.template_dependency_count == 68
    assert report.catalog_event_count == 22
    assert report.stored_catalog_sha256 == catalog.catalog_sha256


def test_report_never_contains_private_catalog_values():
    catalog = _catalog()
    snapshot = _snapshot(catalog)
    report = _verify(catalog, [snapshot, snapshot])
    rendered = json.dumps(
        report.safe_summary(),
        ensure_ascii=False,
    ) + repr(report)

    for record in catalog.records:
        assert record.code not in rendered
        assert record.name not in rendered
        assert record.merchant_id not in rendered


def test_catalog_drift_fails_hash_and_identity_checks():
    catalog = _catalog()
    snapshot = _snapshot(catalog)
    changed = dict(snapshot)
    changed_rows = [dict(row) for row in snapshot["merchants"]]
    changed_rows[0]["name"] = "Changed Private Name"
    changed["merchants"] = tuple(changed_rows)

    report = _verify(catalog, [changed, changed])

    assert report.success is False
    assert report.checks["catalog_target_identical"] is False
    assert report.checks["stored_catalog_hash_exact"] is False


def test_change_during_verification_fails_no_mutation_check():
    catalog = _catalog()
    before = _snapshot(catalog)
    after = dict(before)
    after_counts = dict(before["counts"])
    after_counts["projects"] = 1
    after["counts"] = after_counts

    report = _verify(catalog, [before, after])

    assert report.success is False
    assert report.checks[
        "verification_made_no_runtime_change"
    ] is False


def test_wrong_runtime_target_fails_before_query():
    catalog = _catalog()
    repository = _repository()
    repository.config.database = "coding_agent_merchant_test"

    with pytest.raises(RuntimeVerificationError) as error:
        verify_initialized_runtime(
            repository,
            catalog,
            expected_source_sha256=catalog.source_sha256,
            expected_catalog_sha256=catalog.catalog_sha256,
        )

    assert error.value.reason_code == "UNSAFE_RUNTIME_CONFIG"
    repository.connection.assert_not_called()


def test_workflow_preconditions_cover_both_status_contracts():
    catalog = _catalog()
    evidence = _workflow_precondition_checks(
        _merchant_rows(catalog)
    )

    assert evidence["onboarding_integration_allowed"] is True
    assert evidence["onboarding_active_workflows_denied"] is True
    assert evidence["active_workflow_contracts_available"] is True
    assert evidence["active_integration_denied"] is True
    assert evidence["onboarding_runtime_records"] == 22
    assert evidence["active_runtime_records"] == 0
    assert evidence["integration_preview_steps"] == 26
    assert evidence["active_preview_variants"] == 3


def test_stored_catalog_hash_is_utf8_and_order_sensitive():
    catalog = _catalog()
    rows = _merchant_rows(catalog)

    assert _stored_catalog_hash(rows) == catalog.catalog_sha256
    assert _stored_catalog_hash(tuple(reversed(rows))) != (
        catalog.catalog_sha256
    )


def test_ordinary_reads_are_summarized_without_private_rows():
    catalog = _catalog()
    rows = _merchant_rows(catalog)
    all_rows = [
        {
            "id": row["merchant_id"],
            "code": row["code"],
            "name": row["name"],
            "region_code": row["region_code"],
            "account_status": row["account_status"],
            "created_at": "2026-09-08T00:00:00+00:00",
            "updated_at": "2026-09-08T00:00:00+00:00",
            "version": row["version"],
            "contact_count": 0,
        }
        for row in rows
    ]
    commands = MagicMock()
    commands.merchant_list.side_effect = [all_rows, all_rows, []]
    commands.project_list.return_value = []
    commands.project_alerts.return_value = []

    with (
        patch(
            "claude.clients.merchant.runtime_verification"
            ".MerchantReadRepository"
        ),
        patch(
            "claude.clients.merchant.runtime_verification"
            ".MerchantReadCommands",
            return_value=commands,
        ),
    ):
        evidence = _exercise_ordinary_reads(
            _repository(),
            rows,
        )

    assert evidence["merchant_reads_exact"] is True
    assert evidence["status_filters_exact"] is True
    assert evidence["sensitive_fields_absent"] is True
    assert evidence["project_reads_empty"] is True


def test_runtime_verifier_contains_only_read_only_sql():
    source = Path(
        ".claude/clients/merchant/runtime_verification.py"
    ).read_text(encoding="utf-8")
    normalized = " ".join(source.upper().split())

    assert "REPOSITORY.CONNECTION(READ_ONLY=TRUE)" in normalized
    assert "INSERT INTO " not in normalized
    assert "UPDATE MERCHANT_OPS." not in normalized
    assert "DELETE FROM " not in normalized
    assert "TRUNCATE " not in normalized
