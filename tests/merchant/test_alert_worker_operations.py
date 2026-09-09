"""Unit contracts for Merchant alert status and health reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from claude.workers.merchant_alert_contract import WorkerLimits
from claude.workers.merchant_alert_operations import (
    EXPECTED_LEASE_COLUMNS,
    EXPECTED_LEASE_CONSTRAINTS,
    build_health_report,
    build_status_report,
)


PRIVATE_MARKER = "must-not-appear-in-operational-output"


class FakeAdapter:
    channel = "INTERNAL"

    def safe_configuration(self):
        return {
            "channel": "INTERNAL",
            "configured": True,
        }


class FakeOperationsRepository:
    def __init__(self, *, health=None, queues=None):
        self.health = health or healthy_snapshot()
        self.queues = queues or []
        self.queue_channels = []
        self.health_calls = 0

    def get_alert_queue_status(self, *, delivery_channel=None):
        self.queue_channels.append(delivery_channel)
        return list(self.queues)

    def get_alert_worker_health_snapshot(self):
        self.health_calls += 1
        return dict(self.health)


def healthy_snapshot():
    return {
        "database": "coding_agent_merchant",
        "user": "merchant_alert",
        "read_only": "on",
        "encoding": "UTF8",
        "lease_columns": tuple(sorted(EXPECTED_LEASE_COLUMNS)),
        "lease_constraints": tuple(
            sorted(EXPECTED_LEASE_CONSTRAINTS)
        ),
        "claim_index_definition": (
            "CREATE INDEX alert_deliveries_claim_idx ON "
            "merchant_ops.alert_deliveries "
            "(delivery_channel, delivery_status, next_attempt_at, "
            "claim_expires_at, created_at, id)"
        ),
        "alert_table_privileges": {
            "select": True,
            "insert": True,
            "update": True,
        },
        "private_database_detail": PRIVATE_MARKER,
    }


def queue_row():
    return {
        "delivery_channel": "INTERNAL",
        "total_count": 6,
        "ready_count": 2,
        "active_claim_count": 1,
        "expired_claim_count": 1,
        "retryable_failure_count": 1,
        "dead_letter_count": 1,
        "oldest_pending_at": datetime(
            2026,
            9,
            9,
            tzinfo=timezone.utc,
        ),
        "most_recent_delivery_at": None,
        "merchant_name": PRIVATE_MARKER,
        "destination": "private-destination@example.invalid",
    }


def test_status_is_aggregate_only_and_redacted():
    repository = FakeOperationsRepository(queues=[queue_row()])
    report = build_status_report(
        repository,
        adapter=FakeAdapter(),
        limits=WorkerLimits(),
    )

    assert report["success"] is True
    assert report["mode"] == "status"
    assert report["configuration"] == {
        "channel": "INTERNAL",
        "configured": True,
    }
    assert report["queues"][0]["total_count"] == 6
    assert "merchant_name" not in report["queues"][0]
    assert "destination" not in report["queues"][0]
    assert repository.queue_channels == ["INTERNAL"]
    assert PRIVATE_MARKER not in json.dumps(report, default=str)


def test_healthy_runtime_returns_complete_safe_proof():
    repository = FakeOperationsRepository(queues=[queue_row()])
    report = build_health_report(
        repository,
        adapter=FakeAdapter(),
        limits=WorkerLimits(),
    )

    assert report["success"] is True
    assert report["failed_checks"] == []
    assert all(report["checks"].values())
    assert report["database"] == {
        "database": "coding_agent_merchant",
        "user": "merchant_alert",
        "read_only": "on",
        "encoding": "UTF8",
    }
    assert repository.health_calls == 1
    assert repository.queue_channels == ["INTERNAL"]
    assert PRIVATE_MARKER not in json.dumps(report, default=str)


def test_missing_migration_4_fails_without_querying_new_queue_columns():
    snapshot = healthy_snapshot()
    snapshot["lease_columns"] = ()
    snapshot["lease_constraints"] = ()
    snapshot["claim_index_definition"] = None
    repository = FakeOperationsRepository(health=snapshot)

    report = build_health_report(
        repository,
        adapter=FakeAdapter(),
        limits=WorkerLimits(),
    )

    assert report["success"] is False
    assert report["failed_checks"] == [
        "migration_4_columns_exact",
        "migration_4_constraints_exact",
        "migration_4_claim_index_exact",
    ]
    assert report["queues"] == []
    assert repository.queue_channels == []


def test_wrong_claim_index_order_fails_closed():
    snapshot = healthy_snapshot()
    snapshot["claim_index_definition"] = (
        "CREATE INDEX alert_deliveries_claim_idx ON "
        "merchant_ops.alert_deliveries "
        "(delivery_status, delivery_channel, next_attempt_at, "
        "claim_expires_at, created_at, id)"
    )
    repository = FakeOperationsRepository(health=snapshot)

    report = build_health_report(
        repository,
        adapter=FakeAdapter(),
        limits=WorkerLimits(),
    )

    assert report["success"] is False
    assert report["failed_checks"] == [
        "migration_4_claim_index_exact"
    ]
    assert repository.queue_channels == []


def test_identity_and_privilege_failures_use_named_checks_only():
    snapshot = healthy_snapshot()
    snapshot.update(
        {
            "database": "unsafe_database",
            "user": "unsafe_role",
            "read_only": "off",
            "encoding": "LATIN1",
            "alert_table_privileges": {
                "select": True,
                "insert": False,
                "update": False,
            },
        }
    )
    report = build_health_report(
        FakeOperationsRepository(health=snapshot),
        adapter=FakeAdapter(),
        limits=WorkerLimits(),
    )

    assert report["success"] is False
    assert report["failed_checks"] == [
        "runtime_database_exact",
        "alert_role_exact",
        "transaction_read_only",
        "encoding_utf8",
        "alert_table_privileges_exact",
    ]
    assert report["database"] == {
        "database": "UNEXPECTED",
        "user": "UNEXPECTED",
        "read_only": "UNEXPECTED",
        "encoding": "UNEXPECTED",
    }
    assert "unsafe_database" not in json.dumps(report, default=str)
    assert "unsafe_role" not in json.dumps(report, default=str)
    assert PRIVATE_MARKER not in json.dumps(report, default=str)


def test_queue_output_rejects_unreviewed_values():
    row = queue_row()
    row.update(
        {
            "delivery_channel": PRIVATE_MARKER,
            "total_count": PRIVATE_MARKER,
            "ready_count": -10,
            "oldest_pending_at": PRIVATE_MARKER,
        }
    )
    report = build_status_report(
        FakeOperationsRepository(queues=[row]),
        adapter=FakeAdapter(),
        limits=WorkerLimits(),
    )

    assert report["queues"][0]["delivery_channel"] == "UNKNOWN"
    assert report["queues"][0]["total_count"] == 0
    assert report["queues"][0]["ready_count"] == 0
    assert report["queues"][0]["oldest_pending_at"] is None
    assert PRIVATE_MARKER not in json.dumps(report, default=str)


def test_status_and_health_expose_only_reviewed_limit_values():
    limits = WorkerLimits(
        project_limit=40,
        claim_limit=10,
        max_attempts=4,
        lease_seconds=180,
        retry_base_seconds=60,
        retry_max_seconds=900,
        network_timeout_seconds=20,
    )
    repository = FakeOperationsRepository()

    status = build_status_report(
        repository,
        adapter=FakeAdapter(),
        limits=limits,
    )
    health = build_health_report(
        repository,
        adapter=FakeAdapter(),
        limits=limits,
    )

    assert status["limits"] == limits.to_safe_dict()
    assert health["limits"] == limits.to_safe_dict()
