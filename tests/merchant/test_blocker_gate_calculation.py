"""Checkpoint 8.2 blocker and missing-gate contract tests."""

from __future__ import annotations

from datetime import date

import pytest

from claude.agents.tools.merchant.checker import (
    MerchantProjectChecker,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_PROJECT_ID = "00000000-0000-0000-0000-000000000002"
STEP_ID = "00000000-0000-0000-0000-000000000010"
SECOND_STEP_ID = "00000000-0000-0000-0000-000000000011"
REVISION_ID = "00000000-0000-0000-0000-000000000020"
OLD_REVISION_ID = "00000000-0000-0000-0000-000000000021"


def step(**overrides):
    result = {
        "id": STEP_ID,
        "project_id": PROJECT_ID,
        "branch_key": "document_branch",
        "step_name": "Test step",
        "status": "READY",
        "sequence_number": 1,
        "scheduled_completion": None,
        "step_type": "SEQUENTIAL",
        "condition_key": None,
        "is_optional": False,
    }
    result.update(overrides)
    return result


def revision(**overrides):
    result = {
        "id": REVISION_ID,
        "project_id": PROJECT_ID,
        "document_type": "MERCHANT_AGREEMENT",
        "revision_number": 1,
        "signed": False,
        "signed_at": None,
        "effective_date": None,
        "expiry_date": None,
        "superseded_by": None,
    }
    result.update(overrides)
    return result


def approval(role, **overrides):
    result = {
        "document_revision_id": REVISION_ID,
        "approver_role": role,
        "approval_status": "APPROVED",
        "approved_at": "2026-09-07T02:00:00+00:00",
    }
    result.update(overrides)
    return result


def purchase_request(**overrides):
    result = {
        "project_id": PROJECT_ID,
        "procurement_type": "PURCHASE_REQUEST",
        "external_id": "PR-TEST-001",
    }
    result.update(overrides)
    return result


def snapshot(
    *,
    steps=None,
    dependencies=None,
    revisions=None,
    approvals=None,
    procurement=None,
    project_overrides=None,
):
    project = {
        "id": PROJECT_ID,
        "status": "IN_PROGRESS",
        "requires_procurement": False,
        "payment_period_number": 1,
        "reused_document_revision_id": None,
    }
    project.update(project_overrides or {})

    return {
        "project": project,
        "steps": list(steps or []),
        "dependencies": list(dependencies or []),
        "document_revisions": list(revisions or []),
        "document_approvals": list(approvals or []),
        "procurement_records": list(procurement or []),
    }


def check(candidate):
    return MerchantProjectChecker().check_snapshot(
        candidate,
        business_date=date(2026, 9, 7),
    )


def missing_gate_alerts(candidate):
    return [
        alert
        for alert in check(candidate)
        if alert.alert_type == "MISSING_GATE"
    ]


def test_blocked_and_overdue_facts_coexist_in_stable_order():
    alerts = check(
        snapshot(
            steps=[
                step(
                    status="BLOCKED",
                    scheduled_completion=date(2026, 9, 6),
                )
            ]
        )
    )

    assert [alert.alert_type for alert in alerts] == [
        "OVERDUE",
        "BLOCKED",
    ]
    assert {alert.project_step_id for alert in alerts} == {STEP_ID}
    assert {alert.branch_key for alert in alerts} == {
        "document_branch"
    }


def test_every_parallel_branch_keeps_its_own_blocked_fact():
    alerts = check(
        snapshot(
            steps=[
                step(
                    id=STEP_ID,
                    branch_key="production_branch",
                    status="BLOCKED",
                ),
                step(
                    id=SECOND_STEP_ID,
                    branch_key="uat_branch",
                    status="BLOCKED",
                ),
            ]
        )
    )

    assert len(alerts) == 2
    assert {
        (alert.project_step_id, alert.branch_key)
        for alert in alerts
    } == {
        (STEP_ID, "production_branch"),
        (SECOND_STEP_ID, "uat_branch"),
    }


def test_alert_payload_exposes_branch_key():
    alert = check(
        snapshot(
            steps=[step(status="BLOCKED")]
        )
    )[0]

    assert alert.to_dict()["branch_key"] == "document_branch"


def test_disabled_condition_suppresses_deadline_and_blocker():
    alerts = check(
        snapshot(
            steps=[
                step(
                    branch_key="procurement_branch",
                    condition_key="requires_procurement",
                    is_optional=True,
                    status="BLOCKED",
                    scheduled_completion=date(2026, 9, 6),
                )
            ],
            project_overrides={"requires_procurement": False},
        )
    )

    assert alerts == []


def test_enabled_condition_keeps_procurement_branch_active():
    alerts = check(
        snapshot(
            steps=[
                step(
                    branch_key="procurement_branch",
                    condition_key="requires_procurement",
                    is_optional=True,
                    status="BLOCKED",
                )
            ],
            project_overrides={"requires_procurement": True},
        )
    )

    assert [alert.alert_type for alert in alerts] == [
        "BLOCKED",
        "MISSING_GATE",
    ]
    assert {alert.branch_key for alert in alerts} == {
        "procurement_branch"
    }


def test_unknown_condition_fails_closed():
    candidate = snapshot(
        steps=[step(condition_key="arbitrary_expression")]
    )

    with pytest.raises(ValueError, match="Unsupported workflow condition"):
        check(candidate)


def test_unmet_dependencies_preserve_each_destination_branch():
    source = step(
        id=STEP_ID,
        step_name="Shared prerequisite",
        status="IN_PROGRESS",
        branch_key="document_branch",
    )
    production = step(
        id=SECOND_STEP_ID,
        step_name="Production task",
        status="READY",
        branch_key="production_branch",
    )
    uat_id = "00000000-0000-0000-0000-000000000012"
    uat = step(
        id=uat_id,
        step_name="UAT task",
        status="READY",
        branch_key="uat_branch",
    )
    alerts = check(
        snapshot(
            steps=[source, production, uat],
            dependencies=[
                {
                    "from_step_id": STEP_ID,
                    "to_step_id": SECOND_STEP_ID,
                    "dependency_type": "MUST_COMPLETE_BEFORE",
                },
                {
                    "from_step_id": STEP_ID,
                    "to_step_id": uat_id,
                    "dependency_type": "MUST_COMPLETE_BEFORE",
                },
            ],
        )
    )

    assert {
        (alert.project_step_id, alert.branch_key)
        for alert in alerts
    } == {
        (SECOND_STEP_ID, "production_branch"),
        (uat_id, "uat_branch"),
    }


def test_disabled_dependency_branch_does_not_block():
    alerts = check(
        snapshot(
            steps=[
                step(
                    id=STEP_ID,
                    status="PENDING",
                    condition_key="requires_procurement",
                    is_optional=True,
                ),
                step(
                    id=SECOND_STEP_ID,
                    status="READY",
                ),
            ],
            dependencies=[
                {
                    "from_step_id": STEP_ID,
                    "to_step_id": SECOND_STEP_ID,
                    "dependency_type": "REQUIRES",
                }
            ],
            project_overrides={"requires_procurement": False},
        )
    )

    assert alerts == []


def test_partner_gate_uses_latest_active_revision_only():
    current = revision(revision_number=1)
    superseded = revision(
        id=OLD_REVISION_ID,
        revision_number=2,
        superseded_by=REVISION_ID,
    )
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Record Partner approval",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[current, superseded],
            approvals=[
                approval(
                    "PARTNER",
                    document_revision_id=OLD_REVISION_ID,
                )
            ],
        )
    )

    assert len(alerts) == 1
    assert "MISSING_PARTNER_APPROVAL" in (
        alerts[0].condition_fingerprint
    )


def test_canonical_partner_approval_requires_approved_at():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Record Partner approval",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[revision()],
            approvals=[approval("PARTNER", approved_at=None)],
        )
    )

    assert len(alerts) == 1
    assert "PARTNER approval" in alerts[0].message


def test_rejected_partner_approval_is_a_failed_precondition():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Record Partner approval",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[revision()],
            approvals=[
                approval(
                    "PARTNER",
                    approval_status="REJECTED",
                    approved_at=None,
                )
            ],
        )
    )

    assert len(alerts) == 1
    assert "REJECTED_PARTNER_APPROVAL" in (
        alerts[0].condition_fingerprint
    )
    assert "rejected PARTNER approval" in alerts[0].message


def test_canonical_signing_gate_reports_all_missing_approvals():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Validate signing gate",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[revision()],
            approvals=[],
        )
    )

    assert len(alerts) == 1
    fingerprint = alerts[0].condition_fingerprint
    assert "MISSING_LEGAL_APPROVAL" in fingerprint
    assert "MISSING_ACCOUNTING_APPROVAL" in fingerprint
    assert "MISSING_PARTNER_APPROVAL" in fingerprint


def test_signing_gate_validates_preconditions_before_signing():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Validate signing gate",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[revision(signed=False, signed_at=None)],
            approvals=[
                approval("LEGAL"),
                approval("ACCOUNTING"),
                approval("PARTNER"),
            ],
        )
    )

    assert alerts == []


@pytest.mark.parametrize(
    "procurement",
    [
        [],
        [
            {
                "project_id": PROJECT_ID,
                "procurement_type": "PURCHASE_ORDER",
                "external_id": "PO-TEST-001",
            }
        ],
        [purchase_request(external_id="   ")],
        [purchase_request(project_id=OTHER_PROJECT_ID)],
    ],
)
def test_signing_gate_requires_exact_project_purchase_request(
    procurement,
):
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Validate signing gate",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[revision()],
            approvals=[
                approval("LEGAL"),
                approval("ACCOUNTING"),
                approval("PARTNER"),
            ],
            procurement=procurement,
            project_overrides={"requires_procurement": True},
        )
    )

    assert len(alerts) == 1
    assert "MISSING_PURCHASE_REQUEST" in (
        alerts[0].condition_fingerprint
    )


def test_signing_gate_accepts_exact_project_purchase_request():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Validate signing gate",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[revision()],
            approvals=[
                approval("LEGAL"),
                approval("ACCOUNTING"),
                approval("PARTNER"),
            ],
            procurement=[purchase_request()],
            project_overrides={"requires_procurement": True},
        )
    )

    assert alerts == []


def test_procurement_alert_targets_record_number_step():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    id=STEP_ID,
                    sequence_number=6,
                    branch_key="procurement_branch",
                    step_name="Create Purchase Request",
                ),
                step(
                    id=SECOND_STEP_ID,
                    sequence_number=7,
                    branch_key="procurement_branch",
                    step_name="Record Purchase Request number",
                ),
            ],
            procurement=[
                {
                    "project_id": PROJECT_ID,
                    "procurement_type": "PURCHASE_ORDER",
                    "external_id": "PO-TEST-001",
                }
            ],
            project_overrides={"requires_procurement": True},
        )
    )

    assert len(alerts) == 1
    assert alerts[0].project_step_id == SECOND_STEP_ID
    assert alerts[0].branch_key == "procurement_branch"


def test_existing_document_gate_requires_reused_revision():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Validate existing signed document",
                    step_type="APPROVAL_GATE",
                )
            ],
            project_overrides={"payment_period_number": 2},
        )
    )

    assert len(alerts) == 1
    assert "MISSING_REUSED_DOCUMENT" in (
        alerts[0].condition_fingerprint
    )


def test_existing_document_gate_detects_expired_revision():
    reused = revision(
        project_id=OTHER_PROJECT_ID,
        signed=True,
        signed_at="2026-01-01T00:00:00+00:00",
        effective_date=date(2026, 1, 1),
        expiry_date=date(2026, 9, 6),
    )
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Validate existing signed document",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[reused],
            project_overrides={
                "payment_period_number": 2,
                "reused_document_revision_id": REVISION_ID,
            },
        )
    )

    assert len(alerts) == 1
    assert "EXPIRED_REUSED_DOCUMENT" in (
        alerts[0].condition_fingerprint
    )


def test_valid_existing_document_gate_is_not_missing():
    reused = revision(
        project_id=OTHER_PROJECT_ID,
        signed=True,
        signed_at="2026-01-01T00:00:00+00:00",
        effective_date=date(2026, 1, 1),
        expiry_date=date(2026, 12, 31),
    )
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Validate existing signed document",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[reused],
            project_overrides={
                "payment_period_number": 2,
                "reused_document_revision_id": REVISION_ID,
            },
        )
    )

    assert alerts == []


def test_legacy_approval_name_remains_compatible():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Legal approval gate",
                    step_type="APPROVAL_GATE",
                )
            ],
            revisions=[revision()],
            approvals=[approval("LEGAL", approved_at=None)],
        )
    )

    assert alerts == []


def test_manual_gate_uses_status_fallback():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Complete UAT acceptance",
                    step_type="APPROVAL_GATE",
                    status="READY",
                )
            ]
        )
    )

    assert len(alerts) == 1
    assert "INCOMPLETE_MANUAL_GATE" in (
        alerts[0].condition_fingerprint
    )


def test_future_pending_gate_does_not_alert_early():
    alerts = missing_gate_alerts(
        snapshot(
            steps=[
                step(
                    step_name="Record Partner approval",
                    step_type="APPROVAL_GATE",
                    status="PENDING",
                    scheduled_completion=date(2026, 9, 8),
                )
            ]
        )
    )

    assert alerts == []
