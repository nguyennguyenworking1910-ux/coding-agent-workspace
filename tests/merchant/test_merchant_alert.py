"""Unit tests for the standalone Merchant alert worker."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from claude.agents.tools.merchant.checker import (
    MerchantProjectChecker,
)
from claude.agents.tools.merchant.deadline_policy import (
    DEFAULT_DUE_SOON_DAYS,
)
from claude.workers.merchant_alert import (
    InternalDeliveryAdapter,
    MerchantAlertWorker,
    WorkerSummary,
    build_argument_parser,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
STEP_ID = "00000000-0000-0000-0000-000000000002"
ALERT_ID = "00000000-0000-0000-0000-000000000003"


def make_snapshot(project_status="IN_PROGRESS"):
    return {
        "project": {
            "id": PROJECT_ID,
            "merchant_id": (
                "00000000-0000-0000-0000-000000000010"
            ),
            "merchant_code": "TEST",
            "merchant_name": "Test Merchant",
            "project_type": "MEDIA_TOP_UP",
            "workflow_variant": "TEST_WORKFLOW",
            "title": "Test Project",
            "status": project_status,
            "requires_procurement": False,
            "version": 1,
        },
        "steps": [
            {
                "id": STEP_ID,
                "project_id": PROJECT_ID,
                "template_step_id": (
                    "00000000-0000-0000-0000-000000000020"
                ),
                "branch_key": None,
                "step_name": "Due step",
                "status": "READY",
                "sequence_number": 1,
                "scheduled_start": None,
                "scheduled_completion": date(2026, 9, 2),
                "actual_start": None,
                "actual_completion": None,
                "notes": None,
                "version": 1,
                "step_type": "SEQUENTIAL",
                "condition_key": None,
                "is_optional": False,
            }
        ],
        "dependencies": [],
        "document_revisions": [],
        "document_approvals": [],
        "procurement_records": [],
    }


def make_claimed_delivery():
    return {
        "id": ALERT_ID,
        "project_id": PROJECT_ID,
        "project_step_id": STEP_ID,
        "alert_type": "DUE_TODAY",
        "business_due_date": date(2026, 9, 2),
        "condition_fingerprint": None,
        "deduplication_key": "stable-delivery-key",
        "delivery_channel": "INTERNAL",
        "delivery_status": "FAILED",
        "delivery_attempt_count": 1,
    }


class FakeRepository:
    def __init__(
        self,
        *,
        snapshot=None,
        claimed_deliveries=None,
    ):
        self.snapshot = snapshot or make_snapshot()
        self.claimed_deliveries = list(
            claimed_deliveries or []
        )

        self.list_open_project_ids_called = 0
        self.requested_project_ids = []
        self.enqueued_alerts = []
        self.enqueue_channels = []
        self.claim_arguments = []
        self.sent_alert_ids = []
        self.failed_alerts = []

    def list_open_project_ids(self):
        self.list_open_project_ids_called += 1
        return [PROJECT_ID]

    def get_project_snapshot(self, project_id):
        self.requested_project_ids.append(project_id)
        return self.snapshot

    def enqueue_alerts(
        self,
        alerts,
        *,
        delivery_channel="INTERNAL",
    ):
        self.enqueued_alerts.extend(alerts)
        self.enqueue_channels.append(delivery_channel)
        return len(alerts)

    def claim_pending_alerts(self, **arguments):
        self.claim_arguments.append(arguments)
        return list(self.claimed_deliveries)

    def mark_alert_sent(self, alert_id):
        self.sent_alert_ids.append(alert_id)

    def mark_alert_failed(self, alert_id, error_summary):
        self.failed_alerts.append(
            (alert_id, error_summary)
        )


class FailingDeliveryAdapter:
    channel = "INTERNAL"

    def deliver(self, delivery: dict[str, Any]) -> None:
        raise RuntimeError(
            "Simulated delivery adapter failure"
        )


def make_worker(
    repository,
    *,
    adapter=None,
):
    return MerchantAlertWorker(
        repository,
        checker=MerchantProjectChecker(due_soon_days=3),
        delivery_adapter=adapter,
        delivery_channel="INTERNAL",
    )


def test_external_delivery_channels_fail_closed():
    repository = FakeRepository()

    with pytest.raises(
        ValueError,
        match="Only INTERNAL is supported",
    ):
        MerchantAlertWorker(
            repository,
            delivery_channel="EMAIL",
        )

    with pytest.raises(
        ValueError,
        match="Only INTERNAL is supported",
    ):
        MerchantAlertWorker(
            repository,
            delivery_channel="SLACK",
        )


def test_dry_run_calculates_without_writing(
    capsys,
):
    repository = FakeRepository()
    worker = make_worker(repository)

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        dry_run=True,
    )

    assert summary.projects_checked == 1
    assert summary.alerts_calculated == 1
    assert summary.alerts_enqueued == 0
    assert summary.deliveries_claimed == 0
    assert repository.enqueued_alerts == []
    assert repository.claim_arguments == []
    assert repository.sent_alert_ids == []
    assert repository.failed_alerts == []

    output_lines = capsys.readouterr().out.strip().splitlines()

    assert len(output_lines) == 1

    payload = json.loads(output_lines[0])

    assert payload["event"] == "merchant_alert_dry_run"
    assert payload["project_id"] == PROJECT_ID
    assert payload["project_step_id"] == STEP_ID
    assert payload["alert_type"] == "DUE_TODAY"
    assert payload["business_due_date"] == "2026-09-02"


def test_enqueue_only_does_not_claim_or_deliver():
    repository = FakeRepository()
    worker = make_worker(repository)

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        enqueue_only=True,
    )

    assert summary.projects_checked == 1
    assert summary.alerts_calculated == 1
    assert summary.alerts_enqueued == 1
    assert summary.deliveries_claimed == 0

    assert len(repository.enqueued_alerts) == 1
    assert repository.enqueue_channels == ["INTERNAL"]
    assert repository.claim_arguments == []
    assert repository.sent_alert_ids == []
    assert repository.failed_alerts == []

    enqueued = repository.enqueued_alerts[0]

    assert enqueued["project_id"] == PROJECT_ID
    assert enqueued["project_step_id"] == STEP_ID
    assert enqueued["alert_type"] == "DUE_TODAY"
    assert len(enqueued["deduplication_key"]) == 64


def test_successful_internal_delivery(
    capsys,
):
    repository = FakeRepository(
        claimed_deliveries=[
            make_claimed_delivery(),
        ]
    )
    worker = make_worker(repository)

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        claim_limit=10,
        max_attempts=4,
        retry_after_seconds=120,
    )

    assert summary.projects_checked == 1
    assert summary.alerts_calculated == 1
    assert summary.alerts_enqueued == 1
    assert summary.deliveries_claimed == 1
    assert summary.deliveries_sent == 1
    assert summary.deliveries_failed == 0

    assert repository.sent_alert_ids == [ALERT_ID]
    assert repository.failed_alerts == []

    assert repository.claim_arguments == [
        {
            "delivery_channel": "INTERNAL",
            "limit": 10,
            "max_attempts": 4,
            "retry_after_seconds": 120,
        }
    ]

    output_lines = capsys.readouterr().out.strip().splitlines()

    assert len(output_lines) == 1

    payload = json.loads(output_lines[0])

    assert payload["event"] == "merchant_project_alert"
    assert payload["delivery_id"] == ALERT_ID
    assert payload["project_id"] == PROJECT_ID
    assert payload["project_step_id"] == STEP_ID
    assert payload["delivery_channel"] == "INTERNAL"


def test_delivery_failure_is_recorded():
    repository = FakeRepository(
        claimed_deliveries=[
            make_claimed_delivery(),
        ]
    )
    worker = make_worker(
        repository,
        adapter=FailingDeliveryAdapter(),
    )

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
    )

    assert summary.deliveries_claimed == 1
    assert summary.deliveries_sent == 0
    assert summary.deliveries_failed == 1

    assert repository.sent_alert_ids == []
    assert repository.failed_alerts == [
        (
            ALERT_ID,
            "Simulated delivery adapter failure",
        )
    ]


def test_explicit_project_ids_skip_project_listing(
    capsys,
):
    repository = FakeRepository()
    worker = make_worker(repository)

    summary = worker.run_once(
        project_ids=[PROJECT_ID],
        business_date=date(2026, 9, 2),
        dry_run=True,
    )

    capsys.readouterr()

    assert summary.projects_checked == 1
    assert repository.list_open_project_ids_called == 0
    assert repository.requested_project_ids == [PROJECT_ID]


def test_terminal_project_produces_no_alerts(
    capsys,
):
    repository = FakeRepository(
        snapshot=make_snapshot(
            project_status="COMPLETED",
        )
    )
    worker = make_worker(repository)

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        dry_run=True,
    )

    assert summary.projects_checked == 1
    assert summary.alerts_calculated == 0
    assert capsys.readouterr().out == ""


def test_worker_summary_serialization():
    summary = WorkerSummary(
        projects_checked=2,
        alerts_calculated=3,
        alerts_enqueued=2,
        deliveries_claimed=1,
        deliveries_sent=1,
        deliveries_failed=0,
    )

    assert summary.to_dict() == {
        "projects_checked": 2,
        "alerts_calculated": 3,
        "alerts_enqueued": 2,
        "deliveries_claimed": 1,
        "deliveries_sent": 1,
        "deliveries_failed": 0,
    }


def test_argument_parser():
    parser = build_argument_parser()

    arguments = parser.parse_args(
        [
            "--once",
            "--project-id",
            PROJECT_ID,
            "--business-date",
            "2026-09-02",
            "--due-soon-days",
            "5",
            "--dry-run",
            "--claim-limit",
            "10",
        ]
    )

    assert arguments.once is True
    assert arguments.project_ids == [PROJECT_ID]
    assert arguments.business_date == date(2026, 9, 2)
    assert arguments.due_soon_days == 5
    assert arguments.dry_run is True
    assert arguments.claim_limit == 10


def test_argument_parser_uses_documented_due_soon_default():
    arguments = build_argument_parser().parse_args(["--once"])

    assert arguments.due_soon_days == DEFAULT_DUE_SOON_DAYS == 7
