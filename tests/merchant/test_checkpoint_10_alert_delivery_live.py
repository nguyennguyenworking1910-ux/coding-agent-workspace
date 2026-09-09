"""Cleanup-safe Gate 10.6 alert-delivery lifecycle on the test DB."""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import date
from typing import Any, Callable

import pytest
from psycopg import sql
from psycopg.rows import dict_row

from claude.clients.merchant.repository import (
    AlertClaimLostError,
    MerchantRepository,
    RepositoryConfig,
    TEST_DATABASE,
)
from claude.workers.merchant_alert_adapters import (
    InternalDeliveryAdapter,
)


LIVE_TESTS_ENABLED = (
    os.environ.get("MERCHANT_RUN_LIVE_TESTS", "").strip() == "1"
)
EXPECTED_MIGRATIONS = (1, 2, 3, 4)
BUSINESS_TABLES = (
    "merchants",
    "merchant_contacts",
    "projects",
    "project_steps",
    "project_step_dependencies",
    "document_revisions",
    "document_approvals",
    "procurement_records",
    "integration_identifiers",
    "project_events",
    "alert_deliveries",
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_LIVE_TESTS=1 for the Gate 10.6 "
        "test-database alert-delivery lifecycle"
    ),
)
def test_checkpoint_10_alert_delivery_live_lifecycle():
    config = RepositoryConfig.from_env("test")
    assert config.database == TEST_DATABASE
    assert config.database.endswith("_test")
    assert config.user == "merchant_test"
    assert config.host == "127.0.0.1"
    assert config.port == 5434

    repository = MerchantRepository(config)
    identifiers = _temporary_identifiers()
    checks: dict[str, bool] = {}
    observations: dict[str, Any] = {}
    cleanup_counts: dict[str, int] = {}

    initial_counts = _business_counts(repository)
    initial_templates = _template_counts(repository)
    initial_migrations = _migration_versions(repository)

    assert initial_migrations == EXPECTED_MIGRATIONS
    assert initial_templates == {
        "templates": 4,
        "template_steps": 64,
        "template_dependencies": 68,
    }
    assert all(value == 0 for value in initial_counts.values()), (
        "Merchant test database must have empty business tables before "
        "the Gate 10.6 lifecycle"
    )

    try:
        identity = _database_identity(repository)
        template_id, template_step_id = _template_reference(repository)
        _insert_fictitious_project(
            repository,
            identifiers,
            template_id=template_id,
            template_step_id=template_step_id,
        )

        acknowledgement = _acknowledgement_lifecycle(
            repository,
            identifiers,
        )
        retry = _retry_lifecycle(repository, identifiers)
        lease = _concurrent_lease_lifecycle(config, identifiers)
        dead_letter = _dead_letter_lifecycle(
            repository,
            identifiers,
        )
        exhausted = _exhausted_attempt_lifecycle(
            repository,
            identifiers,
        )
        queue_rows = repository.get_alert_queue_status(
            delivery_channel="INTERNAL"
        )
        queue = queue_rows[0] if len(queue_rows) == 1 else {}

        checks = {
            "correct_test_database": identity["database"]
            == TEST_DATABASE,
            "correct_test_user": identity["user"]
            == "merchant_test",
            "read_only_identity_proof": identity["read_only"] == "on",
            "encoding_utf8": identity["encoding"] == "UTF8",
            "duplicate_enqueue_suppressed": (
                acknowledgement["first_inserted"] == 1
                and acknowledgement["duplicate_inserted"] == 0
            ),
            "internal_payload_allowlisted": (
                acknowledgement["payload_allowlisted"] is True
            ),
            "acknowledgement_compatible": (
                acknowledgement["status"] == "ACKNOWLEDGED"
            ),
            "retry_wait_enforced": retry["immediate_claim_count"] == 0,
            "retry_claim_token_rotated": (
                retry["claim_token_rotated"] is True
            ),
            "retry_stale_token_rejected": (
                retry["stale_token_rejected"] is True
            ),
            "retry_succeeded": (
                retry["status"] == "SENT"
                and retry["attempt_count"] == 2
            ),
            "concurrent_claim_exclusion": (
                lease["parallel_claim_counts"] == [0, 1]
            ),
            "active_lease_excluded": (
                lease["active_lease_claim_count"] == 0
            ),
            "expired_lease_reclaimed": (
                lease["reclaimed"] is True
                and lease["claim_token_rotated"] is True
            ),
            "expired_lease_stale_token_rejected": (
                lease["stale_token_rejected"] is True
            ),
            "dead_letter_terminal": (
                dead_letter["status"] == "DEAD_LETTER"
                and dead_letter["claim_count_after"] == 0
            ),
            "exhausted_attempts_dead_lettered": (
                exhausted["status"] == "DEAD_LETTER"
                and exhausted["error"] == "ATTEMPTS_EXHAUSTED"
            ),
            "queue_status_exact": (
                int(queue.get("total_count", -1)) == 5
                and int(queue.get("ready_count", -1)) == 0
                and int(queue.get("active_claim_count", -1)) == 0
                and int(queue.get("expired_claim_count", -1)) == 0
                and int(queue.get("retryable_failure_count", -1)) == 0
                and int(queue.get("dead_letter_count", -1)) == 2
                and queue.get("most_recent_delivery_at") is not None
            ),
            "templates_unchanged_during_lifecycle": (
                _template_counts(repository) == initial_templates
            ),
            "migrations_unchanged_during_lifecycle": (
                _migration_versions(repository) == initial_migrations
            ),
            "no_unrelated_business_rows_created": (
                _scoped_business_counts(repository, identifiers)
                == {
                    "merchants": 1,
                    "projects": 1,
                    "project_steps": 1,
                    "project_events": 0,
                    "alert_deliveries": 5,
                }
            ),
        }
        observations = {
            "database": identity,
            "initial_business_counts": initial_counts,
            "template_counts": initial_templates,
            "migration_versions": list(initial_migrations),
            "delivery_results": {
                "acknowledgement_status": acknowledgement["status"],
                "retry_status": retry["status"],
                "retry_attempt_count": retry["attempt_count"],
                "parallel_claim_counts": lease[
                    "parallel_claim_counts"
                ],
                "lease_status": lease["status"],
                "dead_letter_status": dead_letter["status"],
                "exhausted_status": exhausted["status"],
            },
            "queue": _safe_queue_summary(queue),
        }
    finally:
        cleanup_counts = _cleanup_temporary_records(
            repository,
            identifiers,
        )

    final_counts = _business_counts(repository)
    final_templates = _template_counts(repository)
    final_migrations = _migration_versions(repository)
    checks["only_expected_records_cleaned"] = cleanup_counts == {
        "alert_deliveries": 5,
        "project_steps": 1,
        "projects": 1,
        "merchants": 1,
    }
    checks["business_state_restored"] = final_counts == initial_counts
    checks["template_state_restored"] = final_templates == initial_templates
    checks["migration_state_preserved"] = (
        final_migrations == initial_migrations
    )
    observations["cleanup_counts"] = cleanup_counts
    observations["final_business_counts"] = final_counts

    report = {
        "success": bool(checks) and all(checks.values()),
        "checks": checks,
        "observations": observations,
    }
    print(json.dumps(report, indent=2, default=str))
    failed_checks = [
        name for name, passed in checks.items() if not passed
    ]
    assert report["success"], (
        "Gate 10.6 alert-delivery lifecycle failed: "
        + ", ".join(failed_checks)
    )


def _temporary_identifiers() -> dict[str, uuid.UUID]:
    return {
        "merchant_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "project_step_id": uuid.uuid4(),
        "acknowledged_by": uuid.uuid4(),
    }


def _database_identity(
    repository: MerchantRepository,
) -> dict[str, Any]:
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        current_database() AS database,
                        current_user AS user,
                        current_setting('transaction_read_only')
                            AS read_only,
                        current_setting('server_encoding') AS encoding
                    """,
                    (),
                )
                return dict(cursor.fetchone())


def _business_counts(
    repository: MerchantRepository,
) -> dict[str, int]:
    counts = {}
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                for table in BUSINESS_TABLES:
                    cursor.execute(
                        sql.SQL(
                            "SELECT COUNT(*) AS count "
                            "FROM merchant_ops.{}"
                        ).format(sql.Identifier(table)),
                        (),
                    )
                    counts[table] = int(cursor.fetchone()["count"])
    return counts


def _template_counts(
    repository: MerchantRepository,
) -> dict[str, int]:
    tables = {
        "templates": "workflow_templates",
        "template_steps": "workflow_template_steps",
        "template_dependencies": "workflow_template_dependencies",
    }
    counts = {}
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                for label, table in tables.items():
                    cursor.execute(
                        sql.SQL(
                            "SELECT COUNT(*) AS count "
                            "FROM merchant_ops.{}"
                        ).format(sql.Identifier(table)),
                        (),
                    )
                    counts[label] = int(cursor.fetchone()["count"])
    return counts


def _migration_versions(
    repository: MerchantRepository,
) -> tuple[int, ...]:
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT version
                    FROM merchant_ops.schema_migrations
                    ORDER BY version
                    """,
                    (),
                )
                return tuple(
                    int(row["version"]) for row in cursor.fetchall()
                )


def _template_reference(
    repository: MerchantRepository,
) -> tuple[uuid.UUID, uuid.UUID]:
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        template.id AS template_id,
                        step.id AS template_step_id
                    FROM merchant_ops.workflow_templates AS template
                    JOIN merchant_ops.workflow_template_steps AS step
                      ON step.template_id = template.id
                    WHERE template.is_active = TRUE
                    ORDER BY
                        template.name,
                        template.version,
                        step.sequence_number,
                        step.id
                    LIMIT 1
                    """,
                    (),
                )
                row = cursor.fetchone()
    assert row is not None, "A standard workflow template is required"
    return row["template_id"], row["template_step_id"]


def _insert_fictitious_project(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
    *,
    template_id: uuid.UUID,
    template_step_id: uuid.UUID,
) -> None:
    token = identifiers["merchant_id"].hex[:12].upper()
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.merchants (
                        id, code, name, account_status, version
                    )
                    VALUES (%s, %s, %s, 'ACTIVE', 1)
                    """,
                    (
                        identifiers["merchant_id"],
                        f"GATE10_{token}",
                        "Fictitious Gate 10 alert merchant",
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.projects (
                        id,
                        merchant_id,
                        project_type,
                        workflow_variant,
                        workflow_template_version_id,
                        title,
                        status,
                        requires_procurement,
                        payment_period_number,
                        version
                    )
                    VALUES (
                        %s, %s, 'MEDIA_TOP_UP', %s, %s, %s,
                        'IN_PROGRESS', FALSE, 1, 1
                    )
                    """,
                    (
                        identifiers["project_id"],
                        identifiers["merchant_id"],
                        f"GATE10_{token}",
                        template_id,
                        "Fictitious Gate 10 alert project",
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.project_steps (
                        id,
                        project_id,
                        template_step_id,
                        branch_key,
                        step_name,
                        status,
                        sequence_number,
                        scheduled_start,
                        scheduled_completion,
                        version
                    )
                    VALUES (
                        %s, %s, %s, 'gate10', %s, 'READY', 1,
                        CURRENT_DATE, CURRENT_DATE, 1
                    )
                    """,
                    (
                        identifiers["project_step_id"],
                        identifiers["project_id"],
                        template_step_id,
                        "Fictitious Gate 10 alert step",
                    ),
                )


def _alert_record(
    identifiers: dict[str, uuid.UUID],
    label: str,
) -> dict[str, Any]:
    return {
        "project_id": str(identifiers["project_id"]),
        "project_step_id": str(identifiers["project_step_id"]),
        "alert_type": "DUE_TODAY",
        "business_due_date": date.today(),
        "condition_fingerprint": None,
        "deduplication_key": hashlib.sha256(
            f"gate10:{identifiers['project_id']}:{label}".encode("utf-8")
        ).hexdigest(),
    }


def _enqueue(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
    label: str,
) -> tuple[dict[str, Any], int]:
    record = _alert_record(identifiers, label)
    inserted = repository.enqueue_alerts(
        [record],
        delivery_channel="INTERNAL",
    )
    return record, inserted


def _claim_one(
    repository: MerchantRepository,
    *,
    max_attempts: int = 3,
    lease_seconds: int = 30,
) -> dict[str, Any]:
    claimed = repository.claim_pending_alerts(
        delivery_channel="INTERNAL",
        limit=1,
        max_attempts=max_attempts,
        lease_seconds=lease_seconds,
    )
    assert len(claimed) == 1
    return claimed[0]


def _acknowledgement_lifecycle(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, Any]:
    record, first_inserted = _enqueue(
        repository,
        identifiers,
        "acknowledgement",
    )
    duplicate_inserted = repository.enqueue_alerts(
        [record],
        delivery_channel="INTERNAL",
    )
    claim = _claim_one(repository)
    output = io.StringIO()
    with redirect_stdout(output):
        provider_message_id = InternalDeliveryAdapter().deliver(claim)
    payload = json.loads(output.getvalue())
    repository.mark_alert_sent(
        str(claim["id"]),
        str(claim["claim_token"]),
        provider_message_id=provider_message_id,
    )

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE merchant_ops.alert_deliveries
                    SET
                        delivery_status = 'ACKNOWLEDGED',
                        acknowledged_at = CURRENT_TIMESTAMP,
                        acknowledged_by = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND delivery_status = 'SENT'
                    """,
                    (identifiers["acknowledged_by"], claim["id"]),
                )
                assert cursor.rowcount == 1

    state = _delivery_state(repository, record["deduplication_key"])
    return {
        "first_inserted": first_inserted,
        "duplicate_inserted": duplicate_inserted,
        "payload_allowlisted": (
            set(payload)
            == {
                "event",
                "delivery_id",
                "project_id",
                "project_step_id",
                "alert_type",
                "business_due_date",
                "condition_fingerprint",
                "deduplication_key",
                "delivery_channel",
                "attempt_number",
            }
            and "claim_token" not in output.getvalue()
        ),
        "status": state["delivery_status"],
    }


def _retry_lifecycle(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, Any]:
    record, inserted = _enqueue(repository, identifiers, "retry")
    assert inserted == 1
    first = _claim_one(repository)
    repository.mark_alert_failed(
        str(first["id"]),
        str(first["claim_token"]),
        "TRANSPORT_UNAVAILABLE",
        retry_after_seconds=60,
    )
    immediate = repository.claim_pending_alerts(
        delivery_channel="INTERNAL",
        limit=1,
        max_attempts=3,
        lease_seconds=30,
    )
    _make_retry_ready(repository, first["id"])
    second = _claim_one(repository)
    stale_token_rejected = _claim_update_rejected(
        lambda: repository.mark_alert_sent(
            str(first["id"]),
            str(first["claim_token"]),
        )
    )
    repository.mark_alert_sent(
        str(second["id"]),
        str(second["claim_token"]),
        provider_message_id=f"internal:{second['id']}",
    )
    state = _delivery_state(repository, record["deduplication_key"])
    return {
        "immediate_claim_count": len(immediate),
        "claim_token_rotated": (
            str(first["claim_token"]) != str(second["claim_token"])
        ),
        "stale_token_rejected": stale_token_rejected,
        "status": state["delivery_status"],
        "attempt_count": int(state["delivery_attempt_count"]),
    }


def _concurrent_lease_lifecycle(
    config: RepositoryConfig,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, Any]:
    repository = MerchantRepository(config)
    record, inserted = _enqueue(repository, identifiers, "lease")
    assert inserted == 1
    barrier = threading.Barrier(2)

    def competing_claim() -> list[dict[str, Any]]:
        competitor = MerchantRepository(config)
        barrier.wait(timeout=10)
        return competitor.claim_pending_alerts(
            delivery_channel="INTERNAL",
            limit=1,
            max_attempts=3,
            lease_seconds=30,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: competing_claim(), range(2)))

    claim_counts = sorted(len(result) for result in results)
    first = next(result[0] for result in results if result)
    active_lease_claim_count = len(
        repository.claim_pending_alerts(
            delivery_channel="INTERNAL",
            limit=1,
            max_attempts=3,
            lease_seconds=30,
        )
    )
    _expire_claim(repository, first["id"])
    second = _claim_one(repository)
    stale_token_rejected = _claim_update_rejected(
        lambda: repository.mark_alert_failed(
            str(first["id"]),
            str(first["claim_token"]),
            "CLAIM_LOST",
            retry_after_seconds=60,
        )
    )
    repository.mark_alert_sent(
        str(second["id"]),
        str(second["claim_token"]),
        provider_message_id=f"internal:{second['id']}",
    )
    state = _delivery_state(repository, record["deduplication_key"])
    return {
        "parallel_claim_counts": claim_counts,
        "active_lease_claim_count": active_lease_claim_count,
        "reclaimed": int(second["delivery_attempt_count"]) == 2,
        "claim_token_rotated": (
            str(first["claim_token"]) != str(second["claim_token"])
        ),
        "stale_token_rejected": stale_token_rejected,
        "status": state["delivery_status"],
    }


def _dead_letter_lifecycle(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, Any]:
    record, inserted = _enqueue(repository, identifiers, "dead-letter")
    assert inserted == 1
    first = _claim_one(repository, max_attempts=2)
    repository.mark_alert_failed(
        str(first["id"]),
        str(first["claim_token"]),
        "TRANSPORT_TIMEOUT",
        retry_after_seconds=60,
    )
    _make_retry_ready(repository, first["id"])
    second = _claim_one(repository, max_attempts=2)
    repository.mark_alert_failed(
        str(second["id"]),
        str(second["claim_token"]),
        "PROVIDER_REJECTED",
        retry_after_seconds=None,
    )
    claim_count_after = len(
        repository.claim_pending_alerts(
            delivery_channel="INTERNAL",
            limit=1,
            max_attempts=2,
            lease_seconds=30,
        )
    )
    state = _delivery_state(repository, record["deduplication_key"])
    return {
        "status": state["delivery_status"],
        "claim_count_after": claim_count_after,
    }


def _exhausted_attempt_lifecycle(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, Any]:
    record, inserted = _enqueue(repository, identifiers, "exhausted")
    assert inserted == 1
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE merchant_ops.alert_deliveries
                    SET
                        delivery_attempt_count = 2,
                        last_attempt_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE deduplication_key = %s
                      AND delivery_status = 'PENDING'
                    """,
                    (record["deduplication_key"],),
                )
                assert cursor.rowcount == 1
    claimed = repository.claim_pending_alerts(
        delivery_channel="INTERNAL",
        limit=1,
        max_attempts=2,
        lease_seconds=30,
    )
    assert claimed == []
    state = _delivery_state(repository, record["deduplication_key"])
    return {
        "status": state["delivery_status"],
        "error": state["last_error_summary"],
    }


def _claim_update_rejected(operation: Callable[[], None]) -> bool:
    try:
        operation()
    except AlertClaimLostError:
        return True
    return False


def _make_retry_ready(
    repository: MerchantRepository,
    delivery_id: uuid.UUID,
) -> None:
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE merchant_ops.alert_deliveries
                    SET next_attempt_at = CURRENT_TIMESTAMP
                        - INTERVAL '1 second'
                    WHERE id = %s
                      AND delivery_status = 'FAILED'
                    """,
                    (delivery_id,),
                )
                assert cursor.rowcount == 1


def _expire_claim(
    repository: MerchantRepository,
    delivery_id: uuid.UUID,
) -> None:
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE merchant_ops.alert_deliveries
                    SET
                        last_attempt_at = CURRENT_TIMESTAMP
                            - INTERVAL '2 seconds',
                        claim_expires_at = CURRENT_TIMESTAMP
                            - INTERVAL '1 second'
                    WHERE id = %s
                      AND delivery_status = 'CLAIMED'
                    """,
                    (delivery_id,),
                )
                assert cursor.rowcount == 1


def _delivery_state(
    repository: MerchantRepository,
    deduplication_key: str,
) -> dict[str, Any]:
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        delivery_status,
                        delivery_attempt_count,
                        last_error_summary
                    FROM merchant_ops.alert_deliveries
                    WHERE deduplication_key = %s
                      AND delivery_channel = 'INTERNAL'
                    """,
                    (deduplication_key,),
                )
                row = cursor.fetchone()
    assert row is not None
    return dict(row)


def _scoped_business_counts(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, int]:
    queries = {
        "merchants": (
            "SELECT COUNT(*) AS count FROM merchant_ops.merchants "
            "WHERE id = %s",
            identifiers["merchant_id"],
        ),
        "projects": (
            "SELECT COUNT(*) AS count FROM merchant_ops.projects "
            "WHERE id = %s",
            identifiers["project_id"],
        ),
        "project_steps": (
            "SELECT COUNT(*) AS count FROM merchant_ops.project_steps "
            "WHERE project_id = %s",
            identifiers["project_id"],
        ),
        "project_events": (
            "SELECT COUNT(*) AS count FROM merchant_ops.project_events "
            "WHERE project_id = %s",
            identifiers["project_id"],
        ),
        "alert_deliveries": (
            "SELECT COUNT(*) AS count "
            "FROM merchant_ops.alert_deliveries WHERE project_id = %s",
            identifiers["project_id"],
        ),
    }
    counts = {}
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                for label, (query, value) in queries.items():
                    cursor.execute(query, (value,))
                    counts[label] = int(cursor.fetchone()["count"])
    return counts


def _cleanup_temporary_records(
    repository: MerchantRepository,
    identifiers: dict[str, uuid.UUID],
) -> dict[str, int]:
    statements = (
        (
            "alert_deliveries",
            "DELETE FROM merchant_ops.alert_deliveries "
            "WHERE project_id = %s",
            identifiers["project_id"],
        ),
        (
            "project_steps",
            "DELETE FROM merchant_ops.project_steps WHERE project_id = %s",
            identifiers["project_id"],
        ),
        (
            "projects",
            "DELETE FROM merchant_ops.projects WHERE id = %s",
            identifiers["project_id"],
        ),
        (
            "merchants",
            "DELETE FROM merchant_ops.merchants WHERE id = %s",
            identifiers["merchant_id"],
        ),
    )
    counts = {}
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                for label, statement, value in statements:
                    cursor.execute(statement, (value,))
                    counts[label] = cursor.rowcount
    return counts


def _safe_queue_summary(queue: dict[str, Any]) -> dict[str, Any]:
    return {
        "delivery_channel": queue.get("delivery_channel"),
        "total_count": int(queue.get("total_count", 0)),
        "ready_count": int(queue.get("ready_count", 0)),
        "active_claim_count": int(queue.get("active_claim_count", 0)),
        "expired_claim_count": int(queue.get("expired_claim_count", 0)),
        "retryable_failure_count": int(
            queue.get("retryable_failure_count", 0)
        ),
        "dead_letter_count": int(queue.get("dead_letter_count", 0)),
    }
