"""Redacted status and health reports for the Merchant alert worker."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Mapping, Protocol, Sequence

try:
    from claude.clients.merchant.repository import RUNTIME_DATABASE
    from claude.workers.merchant_alert_adapters import DeliveryAdapter
    from claude.workers.merchant_alert_contract import (
        DELIVERY_CHANNELS,
        WorkerLimits,
    )
except ModuleNotFoundError:
    from clients.merchant.repository import RUNTIME_DATABASE  # type: ignore
    from workers.merchant_alert_adapters import (  # type: ignore
        DeliveryAdapter,
    )
    from workers.merchant_alert_contract import (  # type: ignore
        DELIVERY_CHANNELS,
        WorkerLimits,
    )


EXPECTED_ALERT_ROLE = "merchant_alert"
EXPECTED_LEASE_COLUMNS = frozenset(
    {
        "claim_token",
        "claim_expires_at",
        "next_attempt_at",
        "last_attempt_at",
        "provider_message_id",
    }
)
EXPECTED_LEASE_CONSTRAINTS = frozenset(
    {
        "alert_deliveries_status_check",
        "alert_deliveries_claim_state_check",
        "alert_deliveries_next_attempt_state_check",
        "alert_deliveries_dead_letter_state_check",
        "alert_deliveries_provider_message_state_check",
    }
)
class OperationsRepository(Protocol):
    def get_alert_queue_status(
        self,
        *,
        delivery_channel: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return aggregate queue rows."""

    def get_alert_worker_health_snapshot(self) -> dict[str, Any]:
        """Return database identity and migration-4 schema facts."""


def build_status_report(
    repository: OperationsRepository,
    *,
    adapter: DeliveryAdapter,
    limits: WorkerLimits,
) -> dict[str, Any]:
    """Build a read-only, aggregate-only queue status report."""
    queues = repository.get_alert_queue_status(
        delivery_channel=adapter.channel
    )
    return {
        "success": True,
        "mode": "status",
        "configuration": dict(adapter.safe_configuration()),
        "limits": limits.to_safe_dict(),
        "queues": _safe_queue_rows(queues),
    }


def build_health_report(
    repository: OperationsRepository,
    *,
    adapter: DeliveryAdapter,
    limits: WorkerLimits,
) -> dict[str, Any]:
    """Build a read-only health proof without Merchant business rows."""
    snapshot = repository.get_alert_worker_health_snapshot()
    columns = frozenset(
        str(item) for item in snapshot.get("lease_columns", ())
    )
    constraints = frozenset(
        str(item) for item in snapshot.get("lease_constraints", ())
    )
    index_definition = str(
        snapshot.get("claim_index_definition") or ""
    ).lower()
    privileges = snapshot.get("alert_table_privileges")
    if not isinstance(privileges, Mapping):
        privileges = {}

    checks = {
        "runtime_database_exact": (
            snapshot.get("database") == RUNTIME_DATABASE
        ),
        "alert_role_exact": snapshot.get("user") == EXPECTED_ALERT_ROLE,
        "transaction_read_only": snapshot.get("read_only") == "on",
        "encoding_utf8": snapshot.get("encoding") == "UTF8",
        "migration_4_columns_exact": columns == EXPECTED_LEASE_COLUMNS,
        "migration_4_constraints_exact": (
            constraints == EXPECTED_LEASE_CONSTRAINTS
        ),
        "migration_4_claim_index_exact": _claim_index_exact(
            index_definition
        ),
        "alert_table_privileges_exact": (
            privileges.get("select") is True
            and privileges.get("insert") is True
            and privileges.get("update") is True
        ),
        "worker_configuration_valid": True,
        "adapter_configuration_valid": (
            adapter.safe_configuration().get("configured") is True
        ),
    }
    schema_ready = all(
        checks[name]
        for name in (
            "migration_4_columns_exact",
            "migration_4_constraints_exact",
            "migration_4_claim_index_exact",
        )
    )
    queues = (
        _safe_queue_rows(
            repository.get_alert_queue_status(
                delivery_channel=adapter.channel
            )
        )
        if schema_ready
        else []
    )
    failed_checks = [
        name for name, passed in checks.items() if not passed
    ]

    return {
        "success": not failed_checks,
        "mode": "health_check",
        "checks": checks,
        "failed_checks": failed_checks,
        "database": {
            "database": (
                RUNTIME_DATABASE
                if checks["runtime_database_exact"]
                else "UNEXPECTED"
            ),
            "user": (
                EXPECTED_ALERT_ROLE
                if checks["alert_role_exact"]
                else "UNEXPECTED"
            ),
            "read_only": (
                "on"
                if checks["transaction_read_only"]
                else "UNEXPECTED"
            ),
            "encoding": (
                "UTF8" if checks["encoding_utf8"] else "UNEXPECTED"
            ),
        },
        "configuration": dict(adapter.safe_configuration()),
        "limits": limits.to_safe_dict(),
        "queues": queues,
    }


def _safe_queue_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []

    for row in rows:
        channel = str(row.get("delivery_channel") or "").upper()
        if channel not in DELIVERY_CHANNELS:
            channel = "UNKNOWN"

        result.append(
            {
                "delivery_channel": channel,
                "total_count": _safe_count(row.get("total_count")),
                "ready_count": _safe_count(row.get("ready_count")),
                "active_claim_count": _safe_count(
                    row.get("active_claim_count")
                ),
                "expired_claim_count": _safe_count(
                    row.get("expired_claim_count")
                ),
                "retryable_failure_count": _safe_count(
                    row.get("retryable_failure_count")
                ),
                "dead_letter_count": _safe_count(
                    row.get("dead_letter_count")
                ),
                "oldest_pending_at": _safe_timestamp(
                    row.get("oldest_pending_at")
                ),
                "most_recent_delivery_at": _safe_timestamp(
                    row.get("most_recent_delivery_at")
                ),
            }
        )

    return result


def _safe_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _safe_timestamp(value: Any) -> date | datetime | None:
    return value if isinstance(value, (date, datetime)) else None


def _claim_index_exact(index_definition: str) -> bool:
    compact = " ".join(index_definition.split())
    return bool(
        "alert_deliveries_claim_idx" in compact
        and "merchant_ops.alert_deliveries" in compact
        and re.search(
            r"\(\s*delivery_channel\s*,\s*delivery_status\s*,\s*"
            r"next_attempt_at\s*,\s*claim_expires_at\s*,\s*"
            r"created_at\s*,\s*id\s*\)\s*$",
            compact,
        )
    )
