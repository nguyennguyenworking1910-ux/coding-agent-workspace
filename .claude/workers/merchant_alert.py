#!/usr/bin/env python3
"""Standalone Merchant alert worker.

The worker:

1. Calculates deterministic project alerts.
2. Enqueues new alerts using stable deduplication keys.
3. Claims deliveries with token-bound, expiring leases.
4. Delivers an allowlisted payload through the selected adapter.
5. Completes or retries only the currently owned claim.

It never changes projects, steps, approvals, documents, or procurement state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import types
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


try:
    from claude.agents.tools.merchant.checker import (
        MerchantProjectChecker,
        ProjectAlert,
    )
    from claude.agents.tools.merchant.deadline_policy import (
        DEFAULT_DUE_SOON_DAYS,
    )
    from claude.clients.merchant.repository import (
        AlertClaimLostError,
        MerchantRepository,
    )
    from claude.workers.merchant_alert_adapters import (
        DeliveryAdapter,
        InternalDeliveryAdapter,
        build_delivery_adapter,
    )
    from claude.workers.merchant_alert_contract import (
        AlertContractError,
        DELIVERY_CHANNELS,
        SafeDeliveryError,
        WorkerLimits,
        safe_failure_summary,
    )
    from claude.workers.merchant_alert_operations import (
        build_health_report,
        build_status_report,
    )
except ModuleNotFoundError as exc:
    if exc.name != "claude":
        raise

    # Direct execution fallback:
    # python .claude/workers/merchant_alert.py --dry-run
    CLAUDE_ROOT = Path(__file__).resolve().parents[1]
    claude_package = types.ModuleType("claude")
    claude_package.__path__ = [str(CLAUDE_ROOT)]
    sys.modules["claude"] = claude_package

    from claude.agents.tools.merchant.checker import (  # type: ignore
        MerchantProjectChecker,
        ProjectAlert,
    )
    from claude.agents.tools.merchant.deadline_policy import (  # type: ignore
        DEFAULT_DUE_SOON_DAYS,
    )
    from claude.clients.merchant.repository import (  # type: ignore
        AlertClaimLostError,
        MerchantRepository,
    )
    from claude.workers.merchant_alert_adapters import (  # type: ignore
        DeliveryAdapter,
        InternalDeliveryAdapter,
        build_delivery_adapter,
    )
    from claude.workers.merchant_alert_contract import (  # type: ignore
        AlertContractError,
        DELIVERY_CHANNELS,
        SafeDeliveryError,
        WorkerLimits,
        safe_failure_summary,
    )
    from claude.workers.merchant_alert_operations import (  # type: ignore
        build_health_report,
        build_status_report,
    )


SUPPORTED_DELIVERY_CHANNELS = DELIVERY_CHANNELS
EXECUTION_MODES = frozenset({"DRY_RUN", "ENQUEUE_ONLY", "DELIVER"})
MAX_DUE_SOON_DAYS = 365
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXIT_SUCCESS = 0
EXIT_OPERATION_FAILED = 1
EXIT_HEALTH_FAILED = 3


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


class MerchantAlertWorker:
    def __init__(
        self,
        repository: MerchantRepository,
        *,
        checker: MerchantProjectChecker | None = None,
        delivery_adapter: DeliveryAdapter | None = None,
        delivery_channel: str = "INTERNAL",
        limits: WorkerLimits | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        normalized_channel = delivery_channel.strip().upper()

        if normalized_channel not in SUPPORTED_DELIVERY_CHANNELS:
            raise ValueError(
                "delivery_channel is not supported"
            )

        source = os.environ if environ is None else environ
        selected_limits = limits or WorkerLimits.from_env(source)
        selected_adapter = (
            delivery_adapter
            if delivery_adapter is not None
            else build_delivery_adapter(
                normalized_channel,
                environ=source,
                limits=selected_limits,
            )
        )

        if selected_adapter.channel != normalized_channel:
            raise ValueError("Delivery adapter channel does not match")

        self.repository = repository
        self.checker = checker or MerchantProjectChecker()
        self.delivery_adapter = selected_adapter
        self.delivery_channel = normalized_channel
        self.limits = selected_limits

    def run_once(
        self,
        *,
        project_ids: Sequence[str] | None = None,
        business_date: date | None = None,
        mode: str,
    ) -> WorkerSummary:
        normalized_mode = str(mode).strip().upper()
        if normalized_mode not in EXECUTION_MODES:
            raise AlertContractError("CONFIG_EXECUTION_MODE_INVALID")

        summary = WorkerSummary()

        if project_ids:
            if len(project_ids) > self.limits.project_limit:
                raise AlertContractError(
                    "CONFIG_PROJECT_SELECTION_LIMIT_EXCEEDED"
                )
            selected_project_ids = list(project_ids)
        else:
            selected_project_ids = self.repository.list_open_project_ids(
                limit=self.limits.project_limit
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

        if normalized_mode == "DRY_RUN":
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

        if normalized_mode == "ENQUEUE_ONLY":
            return summary

        deliveries = self.repository.claim_pending_alerts(
            delivery_channel=self.delivery_channel,
            limit=self.limits.claim_limit,
            max_attempts=self.limits.max_attempts,
            lease_seconds=self.limits.lease_seconds,
        )

        summary.deliveries_claimed = len(deliveries)

        for delivery in deliveries:
            delivery_id = str(delivery["id"])
            claim_token = str(delivery.get("claim_token") or "")
            attempt_number = delivery.get("delivery_attempt_count")

            try:
                provider_message_id = self.delivery_adapter.deliver(
                    delivery
                )

            except Exception as exc:
                retryable = (
                    exc.retryable
                    if isinstance(exc, SafeDeliveryError)
                    else True
                )
                retry_delay = (
                    self.limits.retry_delay_seconds(attempt_number)
                    if retryable
                    else None
                )

                try:
                    self.repository.mark_alert_failed(
                        delivery_id,
                        claim_token,
                        safe_failure_summary(exc),
                        retry_after_seconds=retry_delay,
                    )
                except AlertClaimLostError:
                    pass

                summary.deliveries_failed += 1
                continue

            try:
                self.repository.mark_alert_sent(
                    delivery_id,
                    claim_token,
                    provider_message_id=provider_message_id,
                )
                summary.deliveries_sent += 1
            except AlertClaimLostError:
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
    return safe_failure_summary(error)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merchant-alert",
        description="Calculate and deliver Merchant project alerts",
    )

    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--dry-run",
        dest="mode",
        action="store_const",
        const="DRY_RUN",
        help="Calculate and print without database writes",
    )
    modes.add_argument(
        "--enqueue-only",
        dest="mode",
        action="store_const",
        const="ENQUEUE_ONLY",
        help="Calculate and enqueue without claiming or delivery",
    )
    modes.add_argument(
        "--deliver",
        dest="mode",
        action="store_const",
        const="DELIVER",
        help="Calculate, enqueue, claim, and deliver one bounded cycle",
    )
    modes.add_argument(
        "--status",
        dest="mode",
        action="store_const",
        const="STATUS",
        help="Read aggregate queue status and exit",
    )
    modes.add_argument(
        "--health-check",
        dest="mode",
        action="store_const",
        const="HEALTH_CHECK",
        help="Verify worker configuration and database readiness",
    )
    parser.add_argument(
        "--project-id",
        action="append",
        type=_uuid_argument,
        dest="project_ids",
        help=(
            "Check only this project UUID. Repeat for multiple projects. "
            "When omitted, all non-terminal projects are checked."
        ),
    )
    parser.add_argument(
        "--business-date",
        type=_date_argument,
        help=(
            "Deterministic business date in YYYY-MM-DD format. "
            "Defaults to the current Asia/Ho_Chi_Minh date."
        ),
    )
    parser.add_argument(
        "--due-soon-days",
        type=int,
        default=None,
        help="Number of days used for DUE_SOON alerts",
    )
    parser.add_argument(
        "--channel",
        default="INTERNAL",
        type=_channel_argument,
        help="INTERNAL, EMAIL, or SLACK",
    )
    parser.add_argument(
        "--project-limit",
        type=int,
        default=None,
        help="Maximum candidate projects for this run",
    )
    parser.add_argument(
        "--claim-limit",
        type=int,
        default=None,
        help="Maximum deliveries claimed per run",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Maximum delivery attempts per alert",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=None,
        help="Claim lease duration in seconds",
    )
    parser.add_argument(
        "--retry-base-seconds",
        "--retry-after-seconds",
        dest="retry_base_seconds",
        type=int,
        default=None,
        help="Base retry delay for failed deliveries",
    )
    parser.add_argument(
        "--retry-max-seconds",
        type=int,
        default=None,
        help="Maximum exponential retry delay",
    )
    parser.add_argument(
        "--network-timeout-seconds",
        type=int,
        default=None,
        help="EMAIL or SLACK request timeout",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        _validate_mode_arguments(args)
        limits = _resolve_worker_limits(args, os.environ)
        adapter = build_delivery_adapter(
            args.channel,
            environ=os.environ,
            limits=limits,
        )
        repository = MerchantRepository(role="alert")

        if args.mode == "STATUS":
            _print_json(
                build_status_report(
                    repository,
                    adapter=adapter,
                    limits=limits,
                )
            )
            return EXIT_SUCCESS

        if args.mode == "HEALTH_CHECK":
            report = build_health_report(
                repository,
                adapter=adapter,
                limits=limits,
            )
            _print_json(report)
            return (
                EXIT_SUCCESS
                if report["success"]
                else EXIT_HEALTH_FAILED
            )

        checker = MerchantProjectChecker(
            due_soon_days=(
                args.due_soon_days
                if args.due_soon_days is not None
                else DEFAULT_DUE_SOON_DAYS
            )
        )
        worker = MerchantAlertWorker(
            repository,
            checker=checker,
            delivery_adapter=adapter,
            delivery_channel=args.channel,
            limits=limits,
        )

        summary = worker.run_once(
            project_ids=args.project_ids,
            business_date=args.business_date,
            mode=args.mode,
        )

        _print_json(
            {
                "success": summary.deliveries_failed == 0,
                "mode": args.mode.lower(),
                **summary.to_dict(),
            }
        )

        return (
            EXIT_SUCCESS
            if summary.deliveries_failed == 0
            else EXIT_OPERATION_FAILED
        )

    except Exception as exc:
        _print_json(
            {
                "success": False,
                "error": _safe_error_summary(exc),
            },
            stream=sys.stderr,
        )
        return EXIT_OPERATION_FAILED


def _resolve_worker_limits(
    arguments: argparse.Namespace,
    environ: Mapping[str, str],
) -> WorkerLimits:
    configured = WorkerLimits.from_env(environ)

    def selected(name: str) -> int:
        value = getattr(arguments, name)
        return value if value is not None else getattr(configured, name)

    return WorkerLimits(
        project_limit=selected("project_limit"),
        claim_limit=selected("claim_limit"),
        max_attempts=selected("max_attempts"),
        lease_seconds=selected("lease_seconds"),
        retry_base_seconds=selected("retry_base_seconds"),
        retry_max_seconds=selected("retry_max_seconds"),
        network_timeout_seconds=selected("network_timeout_seconds"),
    )


def _validate_mode_arguments(arguments: argparse.Namespace) -> None:
    if arguments.mode in {"STATUS", "HEALTH_CHECK"}:
        if arguments.project_ids or arguments.business_date is not None:
            raise AlertContractError("CONFIG_MODE_ARGUMENT_CONFLICT")
        if arguments.due_soon_days is not None:
            raise AlertContractError("CONFIG_MODE_ARGUMENT_CONFLICT")

    if arguments.due_soon_days is not None and (
        isinstance(arguments.due_soon_days, bool)
        or arguments.due_soon_days < 0
        or arguments.due_soon_days > MAX_DUE_SOON_DAYS
    ):
        raise AlertContractError("CONFIG_DUE_SOON_DAYS_OUT_OF_RANGE")


def _uuid_argument(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "project id must be a UUID"
        ) from exc


def _date_argument(value: str) -> date:
    if not ISO_DATE_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "business date must use YYYY-MM-DD"
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "business date must be valid"
        ) from exc


def _channel_argument(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in SUPPORTED_DELIVERY_CHANNELS:
        raise argparse.ArgumentTypeError(
            "channel must be INTERNAL, EMAIL, or SLACK"
        )
    return normalized


def _print_json(
    payload: Mapping[str, Any],
    *,
    stream: Any = None,
) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=_json_value,
        ),
        file=stream,
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
