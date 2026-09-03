"""Unit tests for deterministic Merchant project checking."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from claude.agents.tools.merchant.checker import (
    MerchantProjectChecker,
    ProjectAlert,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
STEP_ID = "00000000-0000-0000-0000-000000000002"
SECOND_STEP_ID = "00000000-0000-0000-0000-000000000003"
REVISION_ID = "00000000-0000-0000-0000-000000000004"


def make_step(**overrides):
    step = {
        "id": STEP_ID,
        "project_id": PROJECT_ID,
        "template_step_id": (
            "00000000-0000-0000-0000-000000000010"
        ),
        "branch_key": None,
        "step_name": "Test step",
        "status": "READY",
        "sequence_number": 1,
        "scheduled_start": None,
        "scheduled_completion": None,
        "actual_start": None,
        "actual_completion": None,
        "notes": None,
        "version": 1,
        "step_type": "SEQUENTIAL",
        "condition_key": None,
        "is_optional": False,
    }
    step.update(overrides)
    return step


def make_snapshot(
    *,
    project_status="IN_PROGRESS",
    requires_procurement=False,
    steps=None,
    dependencies=None,
    revisions=None,
    approvals=None,
    procurement=None,
):
    return {
        "project": {
            "id": PROJECT_ID,
            "merchant_id": (
                "00000000-0000-0000-0000-000000000020"
            ),
            "merchant_code": "TEST_MERCHANT",
            "merchant_name": "Test Merchant",
            "project_type": "MEDIA_TOP_UP",
            "workflow_variant": "TEST_WORKFLOW",
            "title": "Test Project",
            "status": project_status,
            "requires_procurement": requires_procurement,
            "version": 1,
        },
        "steps": (
            steps
            if steps is not None
            else [make_step()]
        ),
        "dependencies": dependencies or [],
        "document_revisions": revisions or [],
        "document_approvals": approvals or [],
        "procurement_records": procurement or [],
    }


@pytest.mark.parametrize(
    "project_status",
    ["COMPLETED", "CANCELLED"],
)
def test_terminal_project_produces_no_alerts(project_status):
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        project_status=project_status,
        steps=[
            make_step(
                status="BLOCKED",
                scheduled_completion=date(2026, 8, 1),
            )
        ],
    )

    assert checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    ) == []


def test_overdue_step():
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion=date(2026, 9, 1),
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert [alert.alert_type for alert in alerts] == ["OVERDUE"]
    assert alerts[0].severity == "CRITICAL"
    assert alerts[0].business_due_date == date(2026, 9, 1)


def test_due_today_step():
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion=date(2026, 9, 2),
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert [alert.alert_type for alert in alerts] == ["DUE_TODAY"]


def test_due_soon_step():
    checker = MerchantProjectChecker(due_soon_days=3)

    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion=date(2026, 9, 5),
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert [alert.alert_type for alert in alerts] == ["DUE_SOON"]


def test_step_outside_due_soon_window():
    checker = MerchantProjectChecker(due_soon_days=3)

    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion=date(2026, 9, 6),
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert alerts == []


@pytest.mark.parametrize(
    "step_status",
    ["COMPLETED", "SKIPPED", "SUPERSEDED"],
)
def test_terminal_step_suppresses_deadline_alert(step_status):
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        steps=[
            make_step(
                status=step_status,
                scheduled_completion=date(2026, 8, 1),
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert alerts == []


def test_blocked_step():
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        steps=[
            make_step(
                status="BLOCKED",
                scheduled_completion=None,
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert [alert.alert_type for alert in alerts] == ["BLOCKED"]
    assert alerts[0].project_step_id == STEP_ID


def test_unmet_dependency_blocks_ready_step():
    checker = MerchantProjectChecker()

    source_step = make_step(
        id=STEP_ID,
        step_name="Prerequisite",
        status="IN_PROGRESS",
        sequence_number=1,
    )
    destination_step = make_step(
        id=SECOND_STEP_ID,
        step_name="Dependent step",
        status="READY",
        sequence_number=2,
    )

    snapshot = make_snapshot(
        steps=[source_step, destination_step],
        dependencies=[
            {
                "id": (
                    "00000000-0000-0000-0000-000000000030"
                ),
                "from_step_id": STEP_ID,
                "to_step_id": SECOND_STEP_ID,
                "dependency_type": "MUST_COMPLETE_BEFORE",
            }
        ],
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    dependency_alerts = [
        alert
        for alert in alerts
        if alert.condition_fingerprint
        == f"dependency:{STEP_ID}:{SECOND_STEP_ID}"
    ]

    assert len(dependency_alerts) == 1
    assert dependency_alerts[0].alert_type == "BLOCKED"


def test_completed_dependency_does_not_block():
    checker = MerchantProjectChecker()

    source_step = make_step(
        id=STEP_ID,
        step_name="Prerequisite",
        status="COMPLETED",
        sequence_number=1,
    )
    destination_step = make_step(
        id=SECOND_STEP_ID,
        step_name="Dependent step",
        status="READY",
        sequence_number=2,
    )

    snapshot = make_snapshot(
        steps=[source_step, destination_step],
        dependencies=[
            {
                "from_step_id": STEP_ID,
                "to_step_id": SECOND_STEP_ID,
                "dependency_type": "MUST_COMPLETE_BEFORE",
            }
        ],
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert not any(
        alert.condition_fingerprint
        == f"dependency:{STEP_ID}:{SECOND_STEP_ID}"
        for alert in alerts
    )


def test_missing_legal_approval_gate():
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        steps=[
            make_step(
                step_name="Legal approval gate",
                step_type="APPROVAL_GATE",
                status="READY",
                scheduled_completion=date(2026, 9, 2),
            )
        ],
        revisions=[
            {
                "id": REVISION_ID,
                "revision_number": 1,
                "signed": False,
                "signed_at": None,
            }
        ],
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    missing_gate_alerts = [
        alert
        for alert in alerts
        if alert.alert_type == "MISSING_GATE"
    ]

    assert len(missing_gate_alerts) == 1
    assert "LEGAL approval" in missing_gate_alerts[0].message


def test_approved_legal_gate_is_not_missing():
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        steps=[
            make_step(
                step_name="Legal approval gate",
                step_type="APPROVAL_GATE",
                status="READY",
                scheduled_completion=date(2026, 9, 2),
            )
        ],
        revisions=[
            {
                "id": REVISION_ID,
                "revision_number": 1,
                "signed": False,
                "signed_at": None,
            }
        ],
        approvals=[
            {
                "document_revision_id": REVISION_ID,
                "approver_role": "LEGAL",
                "approval_status": "APPROVED",
            }
        ],
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert not any(
        alert.alert_type == "MISSING_GATE"
        for alert in alerts
    )


def test_unsigned_document_triggers_signing_gate():
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        steps=[
            make_step(
                step_name="Document signing gate",
                step_type="APPROVAL_GATE",
                status="READY",
                scheduled_completion=date(2026, 9, 2),
            )
        ],
        revisions=[
            {
                "id": REVISION_ID,
                "revision_number": 1,
                "signed": False,
                "signed_at": None,
            }
        ],
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert any(
        alert.alert_type == "MISSING_GATE"
        and "not signed" in alert.message
        for alert in alerts
    )


def test_required_procurement_without_identifier():
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        requires_procurement=True,
        steps=[
            make_step(
                step_name="Create Purchase Request",
                status="READY",
            )
        ],
        procurement=[],
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert any(
        alert.alert_type == "MISSING_GATE"
        and "no recorded PR/PO identifier" in alert.message
        for alert in alerts
    )


def test_deduplication_key_includes_project_step():
    first_alert = ProjectAlert(
        project_id=PROJECT_ID,
        project_step_id=STEP_ID,
        alert_type="DUE_TODAY",
        severity="HIGH",
        message="First step",
        business_due_date=date(2026, 9, 2),
    )
    second_alert = ProjectAlert(
        project_id=PROJECT_ID,
        project_step_id=SECOND_STEP_ID,
        alert_type="DUE_TODAY",
        severity="HIGH",
        message="Second step",
        business_due_date=date(2026, 9, 2),
    )

    assert (
        first_alert.deduplication_key("INTERNAL")
        != second_alert.deduplication_key("INTERNAL")
    )


def test_deduplication_key_is_stable():
    alert = ProjectAlert(
        project_id=PROJECT_ID,
        project_step_id=STEP_ID,
        alert_type="OVERDUE",
        severity="CRITICAL",
        message="Stable alert",
        business_due_date=date(2026, 9, 1),
    )

    first_key = alert.deduplication_key("INTERNAL")
    second_key = alert.deduplication_key("INTERNAL")

    assert first_key == second_key
    assert len(first_key) == 64


def test_checker_loads_snapshot_from_repository():
    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion=date(2026, 9, 2),
            )
        ]
    )

    class FakeRepository:
        requested_project_id = None

        def get_project_snapshot(self, project_id):
            self.requested_project_id = project_id
            return snapshot

    repository = FakeRepository()
    checker = MerchantProjectChecker()

    alerts = checker.check_repository(
        repository,
        PROJECT_ID,
        business_date=date(2026, 9, 2),
    )

    assert repository.requested_project_id == PROJECT_ID
    assert [alert.alert_type for alert in alerts] == ["DUE_TODAY"]


def test_naive_datetime_is_handled_deterministically():
    checker = MerchantProjectChecker()

    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion=datetime(
                    2026,
                    9,
                    2,
                    12,
                    0,
                    0,
                ),
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 2),
    )

    assert [alert.alert_type for alert in alerts] == ["DUE_TODAY"]