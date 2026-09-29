"""Read-only command orchestration for the Merchant CLI."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

from .checker import (
    ALERT_TYPES,
    MerchantProjectChecker,
    ProjectAlert,
)
from .cli_contract import (
    redact_payload,
)
from .entity_resolver import (
    resolve_merchant_entity,
)
from .project_entity_resolver import resolve_project_entity
from .step_entity_resolver import (
    resolve_step_entity,
)
from .document_revision_entity_resolver import (
    resolve_document_revision_entity,
)

try:
    from claude.clients.merchant.read_repository import (
        DEFAULT_ALERT_PROJECT_LIMIT,
        DEFAULT_HISTORY_LIMIT,
        MerchantReadRepository,
    )
except ModuleNotFoundError:
    from clients.merchant.read_repository import (  # type: ignore
        DEFAULT_ALERT_PROJECT_LIMIT,
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

    def merchant_resolve(
        self,
        query: str,
    ) -> dict[str, Any]:
        """Resolve one Merchant reference from the authoritative catalog."""

        merchants = self.repository.list_merchants()

        catalog = [
            {
                "id": merchant.get(
                    "id"
                ),
                "code": merchant.get(
                    "code"
                ),
                "name": merchant.get(
                    "name"
                ),

                # Runtime Merchant storage currently exposes
                # no authoritative alias source.
                "aliases": (),
            }
            for merchant in merchants
        ]

        resolution = resolve_merchant_entity(
            query,
            catalog,
        )

        return {
            "success": True,
            "mode": "RESOLUTION",
            **resolution.to_dict(),
        }

    def project_resolve(
        self,
        *,
        merchant_id: str,
        query: str,
    ) -> dict[str, Any]:
        projects = self.repository.list_projects(
            merchant_id=merchant_id,
            status=None,
        )

        resolution = resolve_project_entity(
            query,
            merchant_id,
            projects,
        )

        return {
            "success": True,
            "mode": "PROJECT_RESOLUTION",
            **resolution.to_dict(),
        }

    def step_resolve(
        self,
        *,
        project_id: str,
        query: str,
    ) -> dict[str, Any]:
        """Resolve one Step inside one authoritative Project."""

        detail = (
            self.repository
            .get_project_detail(
                project_id
            )
        )

        steps = detail.get(
            "steps",
            []
        )

        resolution = (
            resolve_step_entity(
                query,
                project_id,
                steps,
            )
        )

        return {
            "success": True,
            "mode": "STEP_RESOLUTION",
            **resolution.to_dict(),
        }

    def document_resolve(
        self,
        *,
        query: str,
        merchant_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            merchant_id is None
            and project_id is None
        ):
            raise ValueError(
                "document resolve requires exactly one of "
                "merchant_id or project_id"
            )

        if (
            merchant_id is not None
            and project_id is not None
        ):
            raise ValueError(
                "document resolve requires exactly one of "
                "merchant_id or project_id"
            )

        if project_id is not None:
            detail = self.repository.get_project_detail(
                project_id
            )

            project = detail.get(
                "project"
            )

            if not isinstance(
                project,
                dict,
            ):
                raise ValueError(
                    "Project detail is missing project metadata"
                )

            trusted_merchant_id = str(
                project.get(
                    "merchant_id"
                )
                or ""
            ).strip()

            revisions = (
                self.repository.list_document_revisions(
                    merchant_id=trusted_merchant_id,
                    project_id=project_id,
                )
            )

            resolution = (
                resolve_document_revision_entity(
                    query,
                    trusted_merchant_id,
                    revisions,
                    project_id=project_id,
                )
            )

        else:
            trusted_merchant_id = str(
                merchant_id
            )

            revisions = (
                self.repository.list_document_revisions(
                    merchant_id=trusted_merchant_id,
                )
            )

            resolution = (
                resolve_document_revision_entity(
                    query,
                    trusted_merchant_id,
                    revisions,
                )
            )

        return {
            "success": True,
            "mode": "DOCUMENT_REVISION_RESOLUTION",
            **resolution.to_dict(),
        }

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
        project_id: str | None = None,
        *,
        merchant_id: str | None = None,
        alert_type: str | None = None,
        due_date_before: date | None = None,
        business_date: date | None = None,
        project_limit: int = DEFAULT_ALERT_PROJECT_LIMIT,
    ) -> list[dict[str, Any]]:
        normalized_alert_type = _optional_alert_type(alert_type)
        normalized_due_date = _optional_due_date(due_date_before)
        project_ids = (
            self.repository.list_alert_candidate_project_ids(
                merchant_id=merchant_id,
                project_id=project_id,
                limit=project_limit,
            )
        )

        alerts: list[ProjectAlert] = []

        for candidate_project_id in project_ids:
            alerts.extend(
                self._calculate_alerts(
                    candidate_project_id,
                    business_date=business_date,
                )
            )

        filtered = [
            alert
            for alert in alerts
            if (
                normalized_alert_type is None
                or alert.alert_type == normalized_alert_type
            )
            and (
                normalized_due_date is None
                or (
                    alert.business_due_date is not None
                    and alert.business_due_date
                    <= normalized_due_date
                )
            )
        ]

        return _redacted_list(
            [alert.to_dict() for alert in filtered]
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


def _optional_alert_type(value: Any) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(
            "alert_type must be one of: "
            + ", ".join(sorted(ALERT_TYPES))
        )

    normalized = value.strip().upper()

    if normalized not in ALERT_TYPES:
        raise ValueError(
            "alert_type must be one of: "
            + ", ".join(sorted(ALERT_TYPES))
        )

    return normalized


def _optional_due_date(value: Any) -> date | None:
    if value is None:
        return None

    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError("due_date_before must be a date")

    return value
