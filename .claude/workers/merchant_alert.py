#!/usr/bin/env python3
"""Standalone Merchant alert worker.

The worker:

1. Calculates deterministic project alerts.
2. Enqueues new alerts using stable deduplication keys.
3. Claims deliveries with FOR UPDATE SKIP LOCKED.
4. Delivers INTERNAL alerts as JSON.
5. Updates alert-delivery state only.

It never changes projects, steps, approvals, documents, or procurement state.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Sequence


try:
    from claude.agents.tools.merchant.checker import (
        MerchantProjectChecker,
        ProjectAlert,
    )
    from claude.agents.tools.merchant.deadline_policy import (
        DEFAULT_DUE_SOON_DAYS,
    )
    from claude.clients.merchant.repository import MerchantRepository
except ModuleNotFoundError:
    # Direct execution fallback:
    # python .claude/workers/merchant_alert.py --once
    CLAUDE_ROOT = Path(__file__).resolve().parents[1]

    if str(CLAUDE_ROOT) not in sys.path:
        sys.path.insert(0, str(CLAUDE_ROOT))

    from agents.tools.merchant.checker import (  # type: ignore
        MerchantProjectChecker,
        ProjectAlert,
    )
    from agents.tools.merchant.deadline_policy import (  # type: ignore
        DEFAULT_DUE_SOON_DAYS,
    )
    from clients.merchant.repository import (  # type: ignore
        MerchantRepository,
    )


SUPPORTED_DELIVERY_CHANNELS = frozenset({"INTERNAL"})


@dataclass
class WorkerSummary:
    projects_checked: int = 0
    alerts_calculated: int = 0
    alerts_enqueued: int = 0
    deliveries_claimed: int = 0
    deliveries_sent: int = 0
    deliveries_failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "projects_checked": self.projects_checked,
            "alerts_calculated": self.alerts_calculated,
            "alerts_enqueued": self.alerts_enqueued,
            "deliveries_claimed": self.deliveries_claimed,
            "deliveries_sent": self.deliveries_sent,
            "deliveries_failed": self.deliveries_failed,
        }


class InternalDeliveryAdapter:
    """Deliver an alert to stdout as one JSON line."""

    channel = "INTERNAL"

    def deliver(self, delivery: dict[str, Any]) -> None:
        payload = {
            "event": "merchant_project_alert",
            "delivery_channel": self.channel,
            "delivery_id": str(delivery["id"]),
            "project_id": str(delivery["project_id"]),
            "project_step_id": (
                str(delivery["project_step_id"])
                if delivery.get("project_step_id")
                else None
            ),
            "alert_type": delivery["alert_type"],
            "business_due_date": _json_value(
                delivery.get("business_due_date")
            ),
            "condition_fingerprint": delivery.get(
                "condition_fingerprint"
            ),
            "deduplication_key": delivery["deduplication_key"],
            "delivery_attempt_count": delivery[
                "delivery_attempt_count"
            ],
        }

        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )


class MerchantAlertWorker:
    def __init__(
        self,
        repository: MerchantRepository,
        *,
        checker: MerchantProjectChecker | None = None,
        delivery_adapter: InternalDeliveryAdapter | None = None,
        delivery_channel: str = "INTERNAL",
    ) -> None:
        normalized_channel = delivery_channel.strip().upper()

        if normalized_channel not in SUPPORTED_DELIVERY_CHANNELS:
            raise ValueError(
                f"Delivery channel {normalized_channel!r} is not "
                "configured. Only INTERNAL is supported. "
                "Email and Slack fail closed until adapters and "
                "credentials are explicitly configured."
            )

        self.repository = repository
        self.checker = checker or MerchantProjectChecker()
        self.delivery_adapter = (
            delivery_adapter or InternalDeliveryAdapter()
        )
        self.delivery_channel = normalized_channel

    def run_once(
        self,
        *,
        project_ids: Sequence[str] | None = None,
        business_date: date | None = None,
        dry_run: bool = False,
        enqueue_only: bool = False,
        claim_limit: int = 25,
        max_attempts: int = 5,
        retry_after_seconds: int = 300,
    ) -> WorkerSummary:
        summary = WorkerSummary()

        selected_project_ids = (
            list(project_ids)
            if project_ids
            else self.repository.list_open_project_ids()
        )

        calculated_alerts: list[ProjectAlert] = []

        for project_id in selected_project_ids:
            alerts = self.checker.check_repository(
                self.repository,
                project_id,
                business_date=business_date,
            )

            summary.projects_checked += 1
            summary.alerts_calculated += len(alerts)
            calculated_alerts.extend(alerts)

        if dry_run:
            for alert in calculated_alerts:
                print(
                    json.dumps(
                        {
                            "event": "merchant_alert_dry_run",
                            **_serializable_alert(
                                alert,
                                self.delivery_channel,
                            ),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )

            return summary

        alert_records = [
            alert.to_dict(self.delivery_channel)
            for alert in calculated_alerts
        ]

        summary.alerts_enqueued = self.repository.enqueue_alerts(
            alert_records,
            delivery_channel=self.delivery_channel,
        )

        if enqueue_only:
            return summary

        deliveries = self.repository.claim_pending_alerts(
            delivery_channel=self.delivery_channel,
            limit=claim_limit,
            max_attempts=max_attempts,
            retry_after_seconds=retry_after_seconds,
        )

        summary.deliveries_claimed = len(deliveries)

        for delivery in deliveries:
            delivery_id = str(delivery["id"])

            try:
                self.delivery_adapter.deliver(delivery)
                self.repository.mark_alert_sent(delivery_id)
                summary.deliveries_sent += 1

            except Exception as exc:
                self.repository.mark_alert_failed(
                    delivery_id,
                    _safe_error_summary(exc),
                )
                summary.deliveries_failed += 1

        return summary


def _serializable_alert(
    alert: ProjectAlert,
    delivery_channel: str,
) -> dict[str, Any]:
    result = alert.to_dict(delivery_channel)
    result["business_due_date"] = _json_value(
        result.get("business_due_date")
    )
    return result


def _json_value(value: Any) -> Any:
    if isinstance(value, (date,)):
        return value.isoformat()

    return value


def _safe_error_summary(error: Exception) -> str:
    summary = " ".join(str(error).split())

    if not summary:
        summary = error.__class__.__name__

    return summary[:500]


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merchant-alert",
        description="Calculate and deliver Merchant project alerts",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one worker cycle and exit",
    )
    parser.add_argument(
        "--project-id",
        action="append",
        dest="project_ids",
        help=(
            "Check only this project UUID. Repeat for multiple projects. "
            "When omitted, all non-terminal projects are checked."
        ),
    )
    parser.add_argument(
        "--business-date",
        type=date.fromisoformat,
        help=(
            "Deterministic business date in YYYY-MM-DD format. "
            "Defaults to the current Asia/Ho_Chi_Minh date."
        ),
    )
    parser.add_argument(
        "--due-soon-days",
        type=int,
        default=DEFAULT_DUE_SOON_DAYS,
        help="Number of days used for DUE_SOON alerts",
    )
    parser.add_argument(
        "--channel",
        default="INTERNAL",
        help="Delivery channel. Only INTERNAL is currently configured.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate and print alerts without writing to PostgreSQL",
    )
    parser.add_argument(
        "--enqueue-only",
        action="store_true",
        help="Enqueue alerts but do not claim or deliver them",
    )
    parser.add_argument(
        "--claim-limit",
        type=int,
        default=25,
        help="Maximum deliveries claimed per run",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=5,
        help="Maximum delivery attempts per alert",
    )
    parser.add_argument(
        "--retry-after-seconds",
        type=int,
        default=300,
        help="Retry delay for failed or abandoned deliveries",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    if args.due_soon_days < 0:
        parser.error("--due-soon-days cannot be negative")

    if args.claim_limit <= 0:
        parser.error("--claim-limit must be greater than zero")

    if args.max_attempts <= 0:
        parser.error("--max-attempts must be greater than zero")

    if args.retry_after_seconds < 0:
        parser.error("--retry-after-seconds cannot be negative")

    try:
        repository = MerchantRepository(role="alert")
        checker = MerchantProjectChecker(
            due_soon_days=args.due_soon_days
        )
        worker = MerchantAlertWorker(
            repository,
            checker=checker,
            delivery_channel=args.channel,
        )

        summary = worker.run_once(
            project_ids=args.project_ids,
            business_date=args.business_date,
            dry_run=args.dry_run,
            enqueue_only=args.enqueue_only,
            claim_limit=args.claim_limit,
            max_attempts=args.max_attempts,
            retry_after_seconds=args.retry_after_seconds,
        )

        print(
            json.dumps(
                {
                    "success": summary.deliveries_failed == 0,
                    "mode": (
                        "dry_run"
                        if args.dry_run
                        else "enqueue_only"
                        if args.enqueue_only
                        else "deliver"
                    ),
                    **summary.to_dict(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

        return 0 if summary.deliveries_failed == 0 else 1

    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": _safe_error_summary(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
