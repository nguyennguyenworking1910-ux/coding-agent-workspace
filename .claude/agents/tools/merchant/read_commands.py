"""Read-only command orchestration for the Merchant CLI."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from .checker import (
    MerchantProjectChecker,
    ProjectAlert,
)
from .cli_contract import (
    redact_payload,
)

try:
    from claude.clients.merchant.read_repository import (
        DEFAULT_HISTORY_LIMIT,
        MerchantReadRepository,
    )
except ModuleNotFoundError:
    from clients.merchant.read_repository import (  # type: ignore
        DEFAULT_HISTORY_LIMIT,
        MerchantReadRepository,
    )


BLOCKER_ALERT_TYPES = frozenset(
    {
        "BLOCKED",
        "MISSING_GATE",
    }
)


class MerchantReadCommands:
    """Execute Merchant reads and redact every public result."""

    def __init__(
        self,
        repository: MerchantReadRepository,
        *,
        checker: MerchantProjectChecker | None = None,
    ) -> None:
        self.repository = repository
        self.checker = checker or MerchantProjectChecker()

    def merchant_list(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        merchants = self.repository.list_merchants(
            status=status,
        )
        return _redacted_list(merchants)

    def project_list(
        self,
        *,
        merchant_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        projects = self.repository.list_projects(
            merchant_id=merchant_id,
            status=status,
        )
        return _redacted_list(projects)

    def project_show(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        detail = self.repository.get_project_detail(project_id)
        redacted = redact_payload(detail)
        return cast(dict[str, Any], redacted)

    def project_history(
        self,
        project_id: str,
        *,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> list[dict[str, Any]]:
        events = self.repository.get_project_history(
            project_id,
            limit=limit,
        )
        return _redacted_list(events)

    def project_alerts(
        self,
        project_id: str,
        *,
        business_date: date | None = None,
    ) -> list[dict[str, Any]]:
        alerts = self._calculate_alerts(
            project_id,
            business_date=business_date,
        )
        return _redacted_list(
            [alert.to_dict() for alert in alerts]
        )

    def project_blockers(
        self,
        project_id: str,
        *,
        business_date: date | None = None,
    ) -> list[dict[str, Any]]:
        alerts = self._calculate_alerts(
            project_id,
            business_date=business_date,
        )
        blockers = [
            alert.to_dict()
            for alert in alerts
            if alert.alert_type in BLOCKER_ALERT_TYPES
        ]
        return _redacted_list(blockers)

    def _calculate_alerts(
        self,
        project_id: str,
        *,
        business_date: date | None,
    ) -> list[ProjectAlert]:
        snapshot = self.repository.get_project_detail(project_id)
        return self.checker.check_snapshot(
            snapshot,
            business_date=business_date,
        )


def _redacted_list(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    redacted = redact_payload(records)
    return cast(list[dict[str, Any]], redacted)
