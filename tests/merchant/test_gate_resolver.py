"""Tests for database-backed workflow gate resolution."""

from __future__ import annotations

import pytest

from claude.agents.tools.merchant.gate_resolver import (
    DatabaseGateResolutionError,
    database_gate_kind,
    is_approval_gate,
    normalize_gate_step_name,
    resolve_database_gate,
)


PROJECT_ID = "project-1"
REVISION_ID = "revision-1"


def project(*, requires_procurement=False):
    return {
        "id": PROJECT_ID,
        "requires_procurement": requires_procurement,
    }


def gate_step(name):
    return {
        "step_type": "APPROVAL_GATE",
        "step_name": name,
    }


def revision(*, signed=False):
    return {
        "id": REVISION_ID,
        "project_id": PROJECT_ID,
        "document_type": "MASTER_AGREEMENT",
        "revision_number": 1,
        "signed": signed,
        "superseded_by": None,
    }


def approval(role, *, status="APPROVED"):
    return {
        "id": f"approval-{role.lower()}",
        "document_revision_id": REVISION_ID,
        "approver_role": role,
        "approval_status": status,
        "approved_at": (
            "2026-09-04T09:00:00+00:00"
            if status == "APPROVED"
            else None
        ),
    }


def purchase_request():
    return {
        "id": "procurement-1",
        "project_id": PROJECT_ID,
        "procurement_type": "PURCHASE_REQUEST",
        "external_id": "PR-2026-001",
        "status": "CREATED",
    }


def test_normalize_gate_step_name():
    assert normalize_gate_step_name(
        "  Record   Partner approval "
    ) == "RECORD PARTNER APPROVAL"


def test_invalid_gate_step_name_rejected():
    with pytest.raises(DatabaseGateResolutionError):
        normalize_gate_step_name(None)


def test_stored_step_type_identifies_approval_gate():
    assert is_approval_gate(
        gate_step("Record Partner approval")
    )


def test_non_gate_step_has_no_database_gate_kind():
    step = {
        "step_type": "SEQUENTIAL",
        "step_name": "Record Partner approval",
    }

    assert database_gate_kind(step) is None


def test_manual_approval_gate_has_no_database_evaluator():
    assert database_gate_kind(
        gate_step("Complete UAT acceptance")
    ) is None


def test_partner_approval_is_blocked_when_missing():
    result = resolve_database_gate(
        step=gate_step("Record Partner approval"),
        project=project(),
        revisions=[revision()],
        approvals=[],
        procurement_records=[],
    )

    assert result is not None
    assert not result.all_met
    assert result.missing_roles == ("PARTNER",)
    assert result.blocking_codes == (
        "MISSING_REQUIRED_APPROVALS",
    )


def test_partner_approval_passes_from_persisted_evidence():
    result = resolve_database_gate(
        step=gate_step("Record Partner approval"),
        project=project(),
        revisions=[revision()],
        approvals=[approval("PARTNER")],
        procurement_records=[],
    )

    assert result is not None
    assert result.all_met
    assert result.approved_roles == ("PARTNER",)
    assert result.missing_roles == ()


def test_signing_gate_reports_all_missing_approvals():
    result = resolve_database_gate(
        step=gate_step("Validate signing gate"),
        project=project(),
        revisions=[revision()],
        approvals=[],
        procurement_records=[],
    )

    assert result is not None
    assert not result.all_met
    assert result.missing_roles == (
        "LEGAL",
        "ACCOUNTING",
        "PARTNER",
    )


def test_signing_gate_requires_purchase_request():
    result = resolve_database_gate(
        step=gate_step("Validate signing gate"),
        project=project(
            requires_procurement=True
        ),
        revisions=[revision()],
        approvals=[
            approval("LEGAL"),
            approval("ACCOUNTING"),
            approval("PARTNER"),
        ],
        procurement_records=[],
    )

    assert result is not None
    assert not result.all_met
    assert "MISSING_PURCHASE_REQUEST" in (
        result.blocking_codes
    )


def test_signing_gate_passes_with_all_evidence():
    result = resolve_database_gate(
        step=gate_step("Validate signing gate"),
        project=project(
            requires_procurement=True
        ),
        revisions=[revision()],
        approvals=[
            approval("LEGAL"),
            approval("ACCOUNTING"),
            approval("PARTNER"),
        ],
        procurement_records=[
            purchase_request()
        ],
    )

    assert result is not None
    assert result.all_met
    assert result.purchase_request_present


def test_signed_revision_blocks_repeat_signing():
    result = resolve_database_gate(
        step=gate_step("Validate signing gate"),
        project=project(),
        revisions=[revision(signed=True)],
        approvals=[
            approval("LEGAL"),
            approval("ACCOUNTING"),
            approval("PARTNER"),
        ],
        procurement_records=[],
    )

    assert result is not None
    assert not result.all_met
    assert result.already_signed
    assert "DOCUMENT_ALREADY_SIGNED" in (
        result.blocking_codes
    )


def test_ordinary_step_returns_none():
    result = resolve_database_gate(
        step={
            "step_type": "SEQUENTIAL",
            "step_name": "Draft document",
        },
        project=project(),
        revisions=[],
        approvals=[],
        procurement_records=[],
    )

    assert result is None


def test_manual_gate_returns_none():
    result = resolve_database_gate(
        step=gate_step("Complete project"),
        project=project(),
        revisions=[],
        approvals=[],
        procurement_records=[],
    )

    assert result is None