"""Unit tests for the standalone Merchant alert worker."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from claude.workers import merchant_alert as merchant_alert_module
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
    _resolve_worker_limits,
    _validate_mode_arguments,
    build_argument_parser,
)
from claude.clients.merchant.repository import AlertClaimLostError
from claude.workers.merchant_alert_contract import (
    AlertContractError,
    DeliveryFailureCode,
    SafeDeliveryError,
    WorkerLimits,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
STEP_ID = "00000000-0000-0000-0000-000000000002"
ALERT_ID = "00000000-0000-0000-0000-000000000003"
CLAIM_TOKEN = "00000000-0000-0000-0000-000000000004"


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


def make_claimed_delivery(attempt_number=1, channel="INTERNAL"):
    return {
        "id": ALERT_ID,
        "project_id": PROJECT_ID,
        "project_step_id": STEP_ID,
        "alert_type": "DUE_TODAY",
        "business_due_date": date(2026, 9, 2),
        "condition_fingerprint": None,
        "deduplication_key": "a" * 64,
        "delivery_channel": channel,
        "delivery_status": "CLAIMED",
        "delivery_attempt_count": attempt_number,
        "claim_token": CLAIM_TOKEN,
        "private_note": "must-not-be-emitted",
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
        self.list_open_project_limits = []
        self.requested_project_ids = []
        self.enqueued_alerts = []
        self.enqueue_channels = []
        self.claim_arguments = []
        self.sent_alert_ids = []
        self.failed_alerts = []

    def list_open_project_ids(self, *, limit=100):
        self.list_open_project_ids_called += 1
        self.list_open_project_limits.append(limit)
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

    def mark_alert_sent(
        self,
        alert_id,
        claim_token,
        *,
        provider_message_id=None,
    ):
        self.sent_alert_ids.append(
            (alert_id, claim_token, provider_message_id)
        )

    def mark_alert_failed(
        self,
        alert_id,
        claim_token,
        error_summary,
        *,
        retry_after_seconds,
    ):
        self.failed_alerts.append(
            (
                alert_id,
                claim_token,
                error_summary,
                retry_after_seconds,
            )
        )


class FailingDeliveryAdapter:
    channel = "INTERNAL"

    def deliver(self, delivery: dict[str, Any]) -> None:
        raise RuntimeError(
            "Simulated delivery adapter failure"
        )


class TerminalDeliveryAdapter:
    channel = "INTERNAL"

    def deliver(self, delivery: dict[str, Any]) -> None:
        raise SafeDeliveryError(
            DeliveryFailureCode.PROVIDER_REJECTED,
            retryable=False,
        )


class ClaimLostRepository(FakeRepository):
    def mark_alert_sent(
        self,
        alert_id,
        claim_token,
        *,
        provider_message_id=None,
    ):
        raise AlertClaimLostError(
            "Alert delivery claim is no longer current"
        )


class SuccessfulEmailAdapter:
    channel = "EMAIL"

    def deliver(self, delivery: dict[str, Any]) -> str:
        return f"email:{delivery['id']}"


def make_worker(
    repository,
    *,
    adapter=None,
    limits=None,
):
    return MerchantAlertWorker(
        repository,
        checker=MerchantProjectChecker(due_soon_days=3),
        delivery_adapter=adapter,
        delivery_channel="INTERNAL",
        limits=limits or WorkerLimits(),
    )


def test_external_delivery_channels_fail_closed_without_configuration(
    monkeypatch,
):
    repository = FakeRepository()

    for variable in (
        "MERCHANT_ALERT_EMAIL_SMTP_HOST",
        "MERCHANT_ALERT_EMAIL_SMTP_PORT",
        "MERCHANT_ALERT_EMAIL_SECURITY",
        "MERCHANT_ALERT_EMAIL_USERNAME",
        "MERCHANT_ALERT_EMAIL_PASSWORD",
        "MERCHANT_ALERT_EMAIL_SENDER",
        "MERCHANT_ALERT_EMAIL_RECIPIENTS",
        "MERCHANT_ALERT_SLACK_BOT_TOKEN",
        "MERCHANT_ALERT_SLACK_CHANNEL_ID",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(
        AlertContractError,
        match="CONFIG_EMAIL_INCOMPLETE",
    ):
        MerchantAlertWorker(
            repository,
            delivery_channel="EMAIL",
        )

    with pytest.raises(
        AlertContractError,
        match="CONFIG_SLACK_INCOMPLETE",
    ):
        MerchantAlertWorker(
            repository,
            delivery_channel="SLACK",
        )


def test_configured_external_adapter_is_used_without_network():
    repository = FakeRepository(
        claimed_deliveries=[
            make_claimed_delivery(channel="EMAIL"),
        ]
    )
    worker = MerchantAlertWorker(
        repository,
        checker=MerchantProjectChecker(due_soon_days=3),
        delivery_adapter=SuccessfulEmailAdapter(),
        delivery_channel="EMAIL",
    )

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        mode="DELIVER",
    )

    assert summary.deliveries_sent == 1
    assert summary.deliveries_failed == 0
    assert repository.enqueue_channels == ["EMAIL"]
    assert repository.claim_arguments[0]["delivery_channel"] == "EMAIL"
    assert repository.sent_alert_ids == [
        (
            ALERT_ID,
            CLAIM_TOKEN,
            f"email:{ALERT_ID}",
        )
    ]


def test_injected_adapter_channel_must_match_selection():
    with pytest.raises(ValueError, match="channel does not match"):
        MerchantAlertWorker(
            FakeRepository(),
            delivery_adapter=SuccessfulEmailAdapter(),
            delivery_channel="INTERNAL",
        )


def test_dry_run_calculates_without_writing(
    capsys,
):
    repository = FakeRepository()
    worker = make_worker(repository)

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        mode="DRY_RUN",
    )

    assert summary.projects_checked == 1
    assert summary.alerts_calculated == 1
    assert summary.alerts_enqueued == 0
    assert summary.deliveries_claimed == 0
    assert repository.enqueued_alerts == []
    assert repository.claim_arguments == []
    assert repository.sent_alert_ids == []
    assert repository.failed_alerts == []
    assert repository.list_open_project_limits == [100]

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
        mode="ENQUEUE_ONLY",
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
    worker = make_worker(
        repository,
        limits=WorkerLimits(
            claim_limit=10,
            max_attempts=4,
            lease_seconds=180,
            retry_base_seconds=120,
            retry_max_seconds=600,
        ),
    )

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        mode="DELIVER",
    )

    assert summary.projects_checked == 1
    assert summary.alerts_calculated == 1
    assert summary.alerts_enqueued == 1
    assert summary.deliveries_claimed == 1
    assert summary.deliveries_sent == 1
    assert summary.deliveries_failed == 0

    assert repository.sent_alert_ids == [
        (
            ALERT_ID,
            CLAIM_TOKEN,
            f"internal:{ALERT_ID}",
        )
    ]
    assert repository.failed_alerts == []

    assert repository.claim_arguments == [
        {
            "delivery_channel": "INTERNAL",
            "limit": 10,
            "max_attempts": 4,
            "lease_seconds": 180,
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
    assert payload["attempt_number"] == 1
    assert "private_note" not in payload
    assert "claim_token" not in payload


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
        mode="DELIVER",
    )

    assert summary.deliveries_claimed == 1
    assert summary.deliveries_sent == 0
    assert summary.deliveries_failed == 1

    assert repository.sent_alert_ids == []
    assert repository.failed_alerts == [
        (
            ALERT_ID,
            CLAIM_TOKEN,
            "UNEXPECTED_FAILURE",
            300,
        )
    ]


def test_terminal_delivery_failure_enters_dead_letter():
    repository = FakeRepository(
        claimed_deliveries=[make_claimed_delivery()]
    )
    worker = make_worker(
        repository,
        adapter=TerminalDeliveryAdapter(),
    )

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        mode="DELIVER",
    )

    assert summary.deliveries_failed == 1
    assert repository.failed_alerts == [
        (
            ALERT_ID,
            CLAIM_TOKEN,
            "PROVIDER_REJECTED",
            None,
        )
    ]


def test_final_retryable_attempt_enters_dead_letter():
    repository = FakeRepository(
        claimed_deliveries=[make_claimed_delivery(attempt_number=5)]
    )
    worker = make_worker(
        repository,
        adapter=FailingDeliveryAdapter(),
    )

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        mode="DELIVER",
    )

    assert summary.deliveries_failed == 1
    assert repository.failed_alerts[0][-1] is None


def test_stale_claim_cannot_be_completed_or_failed():
    repository = ClaimLostRepository(
        claimed_deliveries=[make_claimed_delivery()]
    )
    worker = make_worker(repository)

    summary = worker.run_once(
        business_date=date(2026, 9, 2),
        mode="DELIVER",
    )

    assert summary.deliveries_sent == 0
    assert summary.deliveries_failed == 1
    assert repository.failed_alerts == []


def test_explicit_project_ids_skip_project_listing(
    capsys,
):
    repository = FakeRepository()
    worker = make_worker(repository)

    summary = worker.run_once(
        project_ids=[PROJECT_ID],
        business_date=date(2026, 9, 2),
        mode="DRY_RUN",
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
        mode="DRY_RUN",
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
            "--dry-run",
            "--project-id",
            PROJECT_ID,
            "--business-date",
            "2026-09-02",
            "--due-soon-days",
            "5",
            "--claim-limit",
            "10",
            "--lease-seconds",
            "180",
            "--retry-max-seconds",
            "900",
        ]
    )

    assert arguments.mode == "DRY_RUN"
    assert arguments.project_ids == [PROJECT_ID]
    assert arguments.business_date == date(2026, 9, 2)
    assert arguments.due_soon_days == 5
    assert arguments.claim_limit == 10
    assert arguments.lease_seconds == 180
    assert arguments.retry_max_seconds == 900


def test_argument_parser_defers_to_documented_due_soon_default():
    arguments = build_argument_parser().parse_args(["--dry-run"])

    assert arguments.due_soon_days is None
    assert DEFAULT_DUE_SOON_DAYS == 7


def test_argument_parser_requires_exactly_one_mode():
    parser = build_argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])

    with pytest.raises(SystemExit):
        parser.parse_args(["--dry-run", "--deliver"])


def test_status_rejects_project_arguments_before_repository_access():
    arguments = build_argument_parser().parse_args(
        ["--status", "--project-id", PROJECT_ID]
    )

    with pytest.raises(
        AlertContractError,
        match="CONFIG_MODE_ARGUMENT_CONFLICT",
    ):
        _validate_mode_arguments(arguments)


def test_worker_limits_resolve_cli_over_environment():
    arguments = build_argument_parser().parse_args(
        [
            "--deliver",
            "--project-limit",
            "40",
            "--claim-limit",
            "10",
            "--network-timeout-seconds",
            "20",
        ]
    )
    limits = _resolve_worker_limits(
        arguments,
        {
            "MERCHANT_ALERT_PROJECT_LIMIT": "30",
            "MERCHANT_ALERT_CLAIM_LIMIT": "8",
        },
    )

    assert limits.project_limit == 40
    assert limits.claim_limit == 10
    assert limits.network_timeout_seconds == 20
    assert limits.max_attempts == 5


def test_project_selection_is_bounded_before_repository_reads():
    repository = FakeRepository()
    worker = make_worker(
        repository,
        limits=WorkerLimits(project_limit=1),
    )

    with pytest.raises(
        AlertContractError,
        match="CONFIG_PROJECT_SELECTION_LIMIT_EXCEEDED",
    ):
        worker.run_once(
            project_ids=[PROJECT_ID, STEP_ID],
            mode="DRY_RUN",
        )

    assert repository.requested_project_ids == []
    assert repository.list_open_project_ids_called == 0


class FakeOperationalRepository:
    def __init__(self, *, migration_4_ready=True):
        self.migration_4_ready = migration_4_ready
        self.status_calls = []

    def get_alert_queue_status(self, *, delivery_channel=None):
        self.status_calls.append(delivery_channel)
        return []

    def get_alert_worker_health_snapshot(self):
        return {
            "database": "coding_agent_merchant",
            "user": "merchant_alert",
            "read_only": "on",
            "encoding": "UTF8",
            "lease_columns": (
                (
                    "claim_token",
                    "claim_expires_at",
                    "next_attempt_at",
                    "last_attempt_at",
                    "provider_message_id",
                )
                if self.migration_4_ready
                else ()
            ),
            "lease_constraints": (
                (
                    "alert_deliveries_status_check",
                    "alert_deliveries_claim_state_check",
                    "alert_deliveries_next_attempt_state_check",
                    "alert_deliveries_dead_letter_state_check",
                    "alert_deliveries_provider_message_state_check",
                )
                if self.migration_4_ready
                else ()
            ),
            "claim_index_definition": (
                "CREATE INDEX alert_deliveries_claim_idx ON "
                "merchant_ops.alert_deliveries "
                "(delivery_channel, delivery_status, next_attempt_at, "
                "claim_expires_at, created_at, id)"
                if self.migration_4_ready
                else None
            ),
            "alert_table_privileges": {
                "select": True,
                "insert": True,
                "update": True,
            },
        }


def test_main_status_is_read_only_aggregate_mode(monkeypatch, capsys):
    repository = FakeOperationalRepository()
    monkeypatch.setattr(
        merchant_alert_module,
        "MerchantRepository",
        lambda role: repository,
    )

    assert merchant_alert_module.main(["--status"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["success"] is True
    assert report["mode"] == "status"
    assert report["queues"] == []
    assert repository.status_calls == ["INTERNAL"]


def test_main_health_failure_uses_distinct_exit_code(monkeypatch, capsys):
    repository = FakeOperationalRepository(migration_4_ready=False)
    monkeypatch.setattr(
        merchant_alert_module,
        "MerchantRepository",
        lambda role: repository,
    )

    assert merchant_alert_module.main(["--health-check"]) == 3

    report = json.loads(capsys.readouterr().out)
    assert report["success"] is False
    assert report["failed_checks"] == [
        "migration_4_columns_exact",
        "migration_4_constraints_exact",
        "migration_4_claim_index_exact",
    ]
    assert repository.status_calls == []


def test_invalid_limit_fails_before_repository_construction(
    monkeypatch,
    capsys,
):
    repository_constructions = []
    monkeypatch.setattr(
        merchant_alert_module,
        "MerchantRepository",
        lambda role: repository_constructions.append(role),
    )

    assert merchant_alert_module.main(
        ["--deliver", "--project-limit", "0"]
    ) == 1

    assert repository_constructions == []
    error = json.loads(capsys.readouterr().err)
    assert error == {
        "success": False,
        "error": "CONFIGURATION_INVALID",
    }
