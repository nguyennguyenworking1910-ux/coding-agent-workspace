"""Deterministic Merchant project health and alert calculator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


MERCHANT_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

TERMINAL_PROJECT_STATUSES = frozenset({"COMPLETED", "CANCELLED"})
TERMINAL_STEP_STATUSES = frozenset(
    {"COMPLETED", "SKIPPED", "SUPERSEDED"}
)
ACTIVE_STEP_STATUSES = frozenset(
    {"PENDING", "READY", "IN_PROGRESS", "BLOCKED"}
)

ALERT_ORDER = {
    "OVERDUE": 0,
    "DUE_TODAY": 1,
    "BLOCKED": 2,
    "MISSING_GATE": 3,
    "DUE_SOON": 4,
}


@dataclass(frozen=True)
class ProjectAlert:
    project_id: str
    alert_type: str
    severity: str
    message: str
    project_step_id: str | None = None
    step_name: str | None = None
    business_due_date: date | None = None
    condition_fingerprint: str | None = None

    def deduplication_key(
        self,
        delivery_channel: str = "INTERNAL",
    ) -> str:
        """Return a stable key that includes the individual project step."""
        stable_payload = {
            "project_id": self.project_id,
            "project_step_id": self.project_step_id,
            "alert_type": self.alert_type,
            "business_due_date": (
                self.business_due_date.isoformat()
                if self.business_due_date
                else None
            ),
            "condition_fingerprint": self.condition_fingerprint,
            "delivery_channel": delivery_channel.strip().upper(),
        }

        encoded = json.dumps(
            stable_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(encoded).hexdigest()

    def to_dict(
        self,
        delivery_channel: str = "INTERNAL",
    ) -> dict[str, Any]:
        result = asdict(self)
        result["business_due_date"] = self.business_due_date
        result["deduplication_key"] = self.deduplication_key(
            delivery_channel
        )
        return result


class MerchantProjectChecker:
    """Calculate project alerts without changing workflow state."""

    def __init__(self, *, due_soon_days: int = 3) -> None:
        if due_soon_days < 0:
            raise ValueError("due_soon_days cannot be negative")

        self.due_soon_days = due_soon_days

    def check_repository(
        self,
        repository: Any,
        project_id: str,
        *,
        business_date: date | None = None,
    ) -> list[ProjectAlert]:
        snapshot = repository.get_project_snapshot(project_id)

        return self.check_snapshot(
            snapshot,
            business_date=business_date,
        )

    def check_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        business_date: date | None = None,
    ) -> list[ProjectAlert]:
        project = dict(snapshot.get("project") or {})

        if not project:
            raise ValueError("Project snapshot has no project record")

        project_id = str(project["id"])
        project_status = str(project.get("status", "")).upper()

        # Terminal projects never produce alerts.
        if project_status in TERMINAL_PROJECT_STATUSES:
            return []

        effective_date = business_date or datetime.now(
            MERCHANT_TIMEZONE
        ).date()

        steps = [dict(step) for step in snapshot.get("steps", [])]
        dependencies = [
            dict(edge)
            for edge in snapshot.get("dependencies", [])
        ]
        revisions = [
            dict(revision)
            for revision in snapshot.get("document_revisions", [])
        ]
        approvals = [
            dict(approval)
            for approval in snapshot.get("document_approvals", [])
        ]
        procurement = [
            dict(record)
            for record in snapshot.get("procurement_records", [])
        ]

        alerts: list[ProjectAlert] = []

        for step in steps:
            alerts.extend(
                self._deadline_alerts(
                    project_id,
                    step,
                    effective_date,
                )
            )

            blocked_alert = self._blocked_alert(project_id, step)

            if blocked_alert is not None:
                alerts.append(blocked_alert)

            missing_gate_alert = self._missing_gate_alert(
                project_id,
                step,
                revisions,
                approvals,
                procurement,
                effective_date,
            )

            if missing_gate_alert is not None:
                alerts.append(missing_gate_alert)

        alerts.extend(
            self._dependency_alerts(
                project_id,
                steps,
                dependencies,
            )
        )

        if project.get("requires_procurement"):
            procurement_alert = self._project_procurement_alert(
                project_id,
                steps,
                procurement,
            )

            if procurement_alert is not None:
                alerts.append(procurement_alert)

        return _deduplicate_and_sort(alerts)

    def _deadline_alerts(
        self,
        project_id: str,
        step: Mapping[str, Any],
        business_date: date,
    ) -> list[ProjectAlert]:
        status = str(step.get("status", "")).upper()

        if status not in ACTIVE_STEP_STATUSES:
            return []

        due_date = _as_date(step.get("scheduled_completion"))

        if due_date is None:
            return []

        step_id = str(step["id"])
        step_name = str(step.get("step_name") or "Unnamed step")

        if due_date < business_date:
            return [
                ProjectAlert(
                    project_id=project_id,
                    project_step_id=step_id,
                    step_name=step_name,
                    alert_type="OVERDUE",
                    severity="CRITICAL",
                    business_due_date=due_date,
                    message=(
                        f"Step '{step_name}' was due on "
                        f"{due_date.isoformat()} and is still {status}."
                    ),
                )
            ]

        if due_date == business_date:
            return [
                ProjectAlert(
                    project_id=project_id,
                    project_step_id=step_id,
                    step_name=step_name,
                    alert_type="DUE_TODAY",
                    severity="HIGH",
                    business_due_date=due_date,
                    message=f"Step '{step_name}' is due today.",
                )
            ]

        due_soon_limit = business_date + timedelta(
            days=self.due_soon_days
        )

        if due_date <= due_soon_limit:
            remaining_days = (due_date - business_date).days

            return [
                ProjectAlert(
                    project_id=project_id,
                    project_step_id=step_id,
                    step_name=step_name,
                    alert_type="DUE_SOON",
                    severity="MEDIUM",
                    business_due_date=due_date,
                    message=(
                        f"Step '{step_name}' is due in "
                        f"{remaining_days} day(s)."
                    ),
                )
            ]

        return []

    @staticmethod
    def _blocked_alert(
        project_id: str,
        step: Mapping[str, Any],
    ) -> ProjectAlert | None:
        if str(step.get("status", "")).upper() != "BLOCKED":
            return None

        step_id = str(step["id"])
        step_name = str(step.get("step_name") or "Unnamed step")

        return ProjectAlert(
            project_id=project_id,
            project_step_id=step_id,
            step_name=step_name,
            alert_type="BLOCKED",
            severity="HIGH",
            condition_fingerprint=f"step-status:{step_id}:BLOCKED",
            message=f"Step '{step_name}' is blocked.",
        )

    def _missing_gate_alert(
        self,
        project_id: str,
        step: Mapping[str, Any],
        revisions: list[Mapping[str, Any]],
        approvals: list[Mapping[str, Any]],
        procurement: list[Mapping[str, Any]],
        business_date: date,
    ) -> ProjectAlert | None:
        if str(step.get("step_type", "")).upper() != "APPROVAL_GATE":
            return None

        status = str(step.get("status", "")).upper()

        if status in TERMINAL_STEP_STATUSES:
            return None

        due_date = _as_date(step.get("scheduled_completion"))

        # Do not warn about a future gate that is not ready yet.
        if (
            status == "PENDING"
            and (due_date is None or due_date > business_date)
        ):
            return None

        step_id = str(step["id"])
        step_name = str(step.get("step_name") or "Approval gate")
        normalized_name = step_name.upper()

        latest_revision = _latest_revision(revisions)
        missing_reason: str | None = None

        if "LEGAL" in normalized_name:
            if not _has_approval(
                latest_revision,
                approvals,
                "LEGAL",
            ):
                missing_reason = "latest document lacks LEGAL approval"

        elif "ACCOUNT" in normalized_name:
            if not _has_approval(
                latest_revision,
                approvals,
                "ACCOUNTING",
            ):
                missing_reason = (
                    "latest document lacks ACCOUNTING approval"
                )

        elif "PARTNER" in normalized_name:
            if not _has_approval(
                latest_revision,
                approvals,
                "PARTNER",
            ):
                missing_reason = "latest document lacks PARTNER approval"

        elif "SIGN" in normalized_name:
            if not latest_revision:
                missing_reason = "no document revision exists"
            elif not latest_revision.get("signed"):
                missing_reason = "latest document is not signed"
            elif latest_revision.get("signed_at") is None:
                missing_reason = "signed document has no signed_at timestamp"

        elif any(
            keyword in normalized_name
            for keyword in ("PROCUREMENT", "PURCHASE", "PR GATE")
        ):
            if not _has_procurement_identifier(procurement):
                missing_reason = "procurement record has no external ID"

        else:
            missing_reason = f"approval gate remains {status}"

        if missing_reason is None:
            return None

        return ProjectAlert(
            project_id=project_id,
            project_step_id=step_id,
            step_name=step_name,
            alert_type="MISSING_GATE",
            severity="HIGH",
            business_due_date=due_date,
            condition_fingerprint=(
                f"approval-gate:{step_id}:{missing_reason}"
            ),
            message=f"Gate '{step_name}' is missing: {missing_reason}.",
        )

    @staticmethod
    def _dependency_alerts(
        project_id: str,
        steps: list[Mapping[str, Any]],
        dependencies: list[Mapping[str, Any]],
    ) -> list[ProjectAlert]:
        step_by_id = {
            str(step["id"]): step
            for step in steps
        }

        alerts: list[ProjectAlert] = []

        for dependency in dependencies:
            source_id = str(dependency["from_step_id"])
            destination_id = str(dependency["to_step_id"])

            source = step_by_id.get(source_id)
            destination = step_by_id.get(destination_id)

            if source is None or destination is None:
                continue

            source_status = str(source.get("status", "")).upper()
            destination_status = str(
                destination.get("status", "")
            ).upper()

            if source_status in TERMINAL_STEP_STATUSES:
                continue

            # PENDING is normal while waiting. READY or IN_PROGRESS with an
            # unmet dependency represents inconsistent workflow state.
            if destination_status not in {
                "READY",
                "IN_PROGRESS",
                "BLOCKED",
            }:
                continue

            destination_name = str(
                destination.get("step_name") or "Unnamed step"
            )
            source_name = str(
                source.get("step_name") or "Unnamed prerequisite"
            )

            alerts.append(
                ProjectAlert(
                    project_id=project_id,
                    project_step_id=destination_id,
                    step_name=destination_name,
                    alert_type="BLOCKED",
                    severity="HIGH",
                    condition_fingerprint=(
                        f"dependency:{source_id}:{destination_id}"
                    ),
                    message=(
                        f"Step '{destination_name}' depends on "
                        f"unfinished step '{source_name}'."
                    ),
                )
            )

        return alerts

    @staticmethod
    def _project_procurement_alert(
        project_id: str,
        steps: list[Mapping[str, Any]],
        procurement: list[Mapping[str, Any]],
    ) -> ProjectAlert | None:
        if _has_procurement_identifier(procurement):
            return None

        procurement_step = next(
            (
                step
                for step in steps
                if any(
                    keyword in str(
                        step.get("step_name", "")
                    ).upper()
                    for keyword in (
                        "PROCUREMENT",
                        "PURCHASE REQUEST",
                        "CREATE PR",
                    )
                )
                and str(step.get("status", "")).upper()
                not in TERMINAL_STEP_STATUSES
            ),
            None,
        )

        if procurement_step is None:
            return None

        step_id = str(procurement_step["id"])
        step_name = str(
            procurement_step.get("step_name") or "Procurement"
        )

        return ProjectAlert(
            project_id=project_id,
            project_step_id=step_id,
            step_name=step_name,
            alert_type="MISSING_GATE",
            severity="HIGH",
            condition_fingerprint=f"procurement:{step_id}:external-id",
            message=(
                f"Project requires procurement, but step "
                f"'{step_name}' has no recorded PR/PO identifier."
            ),
        )


def _as_date(value: Any) -> date | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()

        return value.astimezone(MERCHANT_TIMEZONE).date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        return date.fromisoformat(value[:10])

    raise ValueError(f"Unsupported date value: {value!r}")


def _latest_revision(
    revisions: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    available = list(revisions)

    if not available:
        return None

    return max(
        available,
        key=lambda revision: (
            int(revision.get("revision_number") or 0),
            str(revision.get("id") or ""),
        ),
    )


def _has_approval(
    latest_revision: Mapping[str, Any] | None,
    approvals: Iterable[Mapping[str, Any]],
    approver_role: str,
) -> bool:
    if latest_revision is None:
        return False

    revision_id = str(latest_revision["id"])

    return any(
        str(approval.get("document_revision_id")) == revision_id
        and str(approval.get("approver_role", "")).upper()
        == approver_role
        and str(approval.get("approval_status", "")).upper()
        == "APPROVED"
        for approval in approvals
    )


def _has_procurement_identifier(
    procurement: Iterable[Mapping[str, Any]],
) -> bool:
    return any(
        str(record.get("external_id") or "").strip()
        for record in procurement
    )


def _deduplicate_and_sort(
    alerts: Iterable[ProjectAlert],
) -> list[ProjectAlert]:
    unique: dict[str, ProjectAlert] = {}

    for alert in alerts:
        key = alert.deduplication_key("INTERNAL")
        unique.setdefault(key, alert)

    return sorted(
        unique.values(),
        key=lambda alert: (
            ALERT_ORDER.get(alert.alert_type, 99),
            alert.business_due_date or date.max,
            alert.project_step_id or "",
            alert.condition_fingerprint or "",
        ),
    )