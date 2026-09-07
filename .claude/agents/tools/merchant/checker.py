"""Deterministic Merchant project health and alert calculator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable, Mapping

from .deadline_policy import (
    DEFAULT_DUE_SOON_DAYS,
    DUE_SOON,
    DUE_TODAY,
    OVERDUE,
    DeadlinePolicy,
)


TERMINAL_PROJECT_STATUSES = frozenset({"COMPLETED", "CANCELLED"})
TERMINAL_STEP_STATUSES = frozenset(
    {"COMPLETED", "SKIPPED", "SUPERSEDED"}
)
ACTIVE_STEP_STATUSES = frozenset(
    {"PENDING", "READY", "IN_PROGRESS", "BLOCKED"}
)

REQUIRES_PROCUREMENT_CONDITION = "requires_procurement"
PARTNER_APPROVAL_GATE = "RECORD PARTNER APPROVAL"
SIGNING_GATE = "VALIDATE SIGNING GATE"
EXISTING_DOCUMENT_GATE = "VALIDATE EXISTING SIGNED DOCUMENT"
SIGNING_REQUIRED_ROLES = (
    "LEGAL",
    "ACCOUNTING",
    "PARTNER",
)

ALERT_ORDER = {
    "OVERDUE": 0,
    "DUE_TODAY": 1,
    "BLOCKED": 2,
    "MISSING_GATE": 3,
    "DUE_SOON": 4,
}
ALERT_TYPES = frozenset(ALERT_ORDER)


@dataclass(frozen=True)
class ProjectAlert:
    project_id: str
    alert_type: str
    severity: str
    message: str
    project_step_id: str | None = None
    step_name: str | None = None
    branch_key: str | None = None
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

    def __init__(
        self,
        *,
        due_soon_days: int = DEFAULT_DUE_SOON_DAYS,
    ) -> None:
        self.deadline_policy = DeadlinePolicy(
            due_soon_days=due_soon_days
        )
        self.due_soon_days = self.deadline_policy.due_soon_days

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

        effective_date = self.deadline_policy.resolve_business_date(
            business_date
        )

        steps = [dict(step) for step in snapshot.get("steps", [])]
        active_steps = [
            step
            for step in steps
            if _step_is_active(project, step)
        ]
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

        for step in active_steps:
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
                project,
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
                active_steps,
                dependencies,
            )
        )

        if project.get("requires_procurement"):
            procurement_alert = self._project_procurement_alert(
                project_id,
                active_steps,
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

        deadline = self.deadline_policy.evaluate(
            step.get("scheduled_completion"),
            business_date=business_date,
        )
        due_date = deadline.due_date

        if due_date is None or deadline.alert_type is None:
            return []

        step_id = str(step["id"])
        step_name = str(step.get("step_name") or "Unnamed step")

        if deadline.alert_type == OVERDUE:
            return [
                ProjectAlert(
                    project_id=project_id,
                    project_step_id=step_id,
                    step_name=step_name,
                    branch_key=_branch_key(step),
                    alert_type="OVERDUE",
                    severity="CRITICAL",
                    business_due_date=due_date,
                    message=(
                        f"Step '{step_name}' was due on "
                        f"{due_date.isoformat()} and is still {status}."
                    ),
                )
            ]

        if deadline.alert_type == DUE_TODAY:
            return [
                ProjectAlert(
                    project_id=project_id,
                    project_step_id=step_id,
                    step_name=step_name,
                    branch_key=_branch_key(step),
                    alert_type="DUE_TODAY",
                    severity="HIGH",
                    business_due_date=due_date,
                    message=f"Step '{step_name}' is due today.",
                )
            ]

        if deadline.alert_type == DUE_SOON:
            remaining_days = deadline.days_until_due

            return [
                ProjectAlert(
                    project_id=project_id,
                    project_step_id=step_id,
                    step_name=step_name,
                    branch_key=_branch_key(step),
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
            branch_key=_branch_key(step),
            alert_type="BLOCKED",
            severity="HIGH",
            condition_fingerprint=f"step-status:{step_id}:BLOCKED",
            message=f"Step '{step_name}' is blocked.",
        )

    def _missing_gate_alert(
        self,
        project_id: str,
        project: Mapping[str, Any],
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

        due_date = self.deadline_policy.normalize_date(
            step.get("scheduled_completion")
        )

        # Do not warn about a future gate that is not ready yet.
        if (
            status == "PENDING"
            and (due_date is None or due_date > business_date)
        ):
            return None

        step_id = str(step["id"])
        step_name = str(step.get("step_name") or "Approval gate")
        reasons = _missing_gate_reasons(
            project_id=project_id,
            project=project,
            step=step,
            revisions=revisions,
            approvals=approvals,
            procurement=procurement,
            business_date=business_date,
            deadline_policy=self.deadline_policy,
        )

        if not reasons:
            return None

        reason_codes = tuple(code for code, _ in reasons)
        missing_reason = "; ".join(
            description for _, description in reasons
        )

        return ProjectAlert(
            project_id=project_id,
            project_step_id=step_id,
            step_name=step_name,
            branch_key=_branch_key(step),
            alert_type="MISSING_GATE",
            severity="HIGH",
            business_due_date=due_date,
            condition_fingerprint=(
                f"approval-gate:{step_id}:"
                + "|".join(reason_codes)
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
                    branch_key=_branch_key(destination),
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
        if _has_purchase_request_identifier(
            project_id,
            procurement,
        ):
            return None

        procurement_steps = [
            step
            for step in steps
            if _is_procurement_step(step)
            and str(step.get("status", "")).upper()
            not in TERMINAL_STEP_STATUSES
        ]
        procurement_step = min(
            procurement_steps,
            key=lambda step: (
                0
                if _normalize_step_name(step.get("step_name"))
                == "RECORD PURCHASE REQUEST NUMBER"
                else 1,
                int(step.get("sequence_number") or 0),
                str(step.get("id") or ""),
            ),
            default=None,
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
            branch_key=_branch_key(procurement_step),
            alert_type="MISSING_GATE",
            severity="HIGH",
            condition_fingerprint=f"procurement:{step_id}:external-id",
            message=(
                f"Project requires procurement, but step "
                f"'{step_name}' has no recorded PR/PO identifier; "
                "a Purchase Request number is required."
            ),
        )


def _latest_revision(
    revisions: Iterable[Mapping[str, Any]],
    *,
    project_id: str | None = None,
) -> Mapping[str, Any] | None:
    available = [
        revision
        for revision in revisions
        if revision.get("superseded_by") is None
        and (
            project_id is None
            or revision.get("project_id") is None
            or str(revision.get("project_id")) == project_id
        )
    ]

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


def _step_is_active(
    project: Mapping[str, Any],
    step: Mapping[str, Any],
) -> bool:
    condition_key = step.get("condition_key")

    if condition_key is None:
        return True

    if not isinstance(condition_key, str) or not condition_key.strip():
        raise ValueError(
            "Workflow condition_key must be a non-empty string"
        )

    normalized_key = condition_key.strip().lower()

    if normalized_key == REQUIRES_PROCUREMENT_CONDITION:
        return bool(project.get("requires_procurement"))

    raise ValueError(
        f"Unsupported workflow condition key: {normalized_key}"
    )


def _branch_key(step: Mapping[str, Any]) -> str | None:
    value = step.get("branch_key")

    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def _normalize_step_name(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _is_procurement_step(step: Mapping[str, Any]) -> bool:
    if (
        str(step.get("condition_key") or "").strip().lower()
        == REQUIRES_PROCUREMENT_CONDITION
    ):
        return True

    normalized_name = _normalize_step_name(step.get("step_name"))
    return any(
        keyword in normalized_name
        for keyword in (
            "PROCUREMENT",
            "PURCHASE REQUEST",
            "CREATE PR",
        )
    )


def _has_purchase_request_identifier(
    project_id: str,
    procurement: Iterable[Mapping[str, Any]],
) -> bool:
    return any(
        str(record.get("external_id") or "").strip()
        and str(record.get("procurement_type") or "").strip().upper()
        == "PURCHASE_REQUEST"
        and (
            record.get("project_id") is None
            or str(record.get("project_id")) == project_id
        )
        for record in procurement
    )


def _missing_gate_reasons(
    *,
    project_id: str,
    project: Mapping[str, Any],
    step: Mapping[str, Any],
    revisions: list[Mapping[str, Any]],
    approvals: list[Mapping[str, Any]],
    procurement: list[Mapping[str, Any]],
    business_date: date,
    deadline_policy: DeadlinePolicy,
) -> tuple[tuple[str, str], ...]:
    normalized_name = _normalize_step_name(step.get("step_name"))
    latest_revision = _latest_revision(
        revisions,
        project_id=project_id,
    )

    if normalized_name == EXISTING_DOCUMENT_GATE:
        return _existing_document_reasons(
            project=project,
            revisions=revisions,
            business_date=business_date,
            deadline_policy=deadline_policy,
        )

    if normalized_name == PARTNER_APPROVAL_GATE:
        return _approval_reasons(
            latest_revision,
            approvals,
            ("PARTNER",),
            require_approved_at=True,
        )

    if normalized_name == SIGNING_GATE:
        reasons = list(
            _approval_reasons(
                latest_revision,
                approvals,
                SIGNING_REQUIRED_ROLES,
                require_approved_at=True,
            )
        )

        if (
            project.get("requires_procurement")
            and not _has_purchase_request_identifier(
                project_id,
                procurement,
            )
        ):
            reasons.append(
                (
                    "MISSING_PURCHASE_REQUEST",
                    "required Purchase Request number is missing",
                )
            )

        if (
            latest_revision is not None
            and latest_revision.get("signed")
            and latest_revision.get("signed_at") is None
        ):
            reasons.append(
                (
                    "INVALID_SIGNED_DOCUMENT",
                    "signed document has no signed_at timestamp",
                )
            )

        return tuple(reasons)

    # Compatibility fallback for legacy/custom templates that predate
    # canonical gate names. Exact stored gate names above always win.
    if "LEGAL" in normalized_name:
        return _legacy_approval_reason(
            latest_revision,
            approvals,
            "LEGAL",
        )

    if "ACCOUNT" in normalized_name:
        return _legacy_approval_reason(
            latest_revision,
            approvals,
            "ACCOUNTING",
        )

    if "PARTNER" in normalized_name:
        return _legacy_approval_reason(
            latest_revision,
            approvals,
            "PARTNER",
        )

    if "SIGN" in normalized_name:
        if latest_revision is None:
            return (("MISSING_DOCUMENT_REVISION", "no document revision exists"),)

        if not latest_revision.get("signed"):
            return (("UNSIGNED_DOCUMENT", "latest document is not signed"),)

        if latest_revision.get("signed_at") is None:
            return (
                (
                    "INVALID_SIGNED_DOCUMENT",
                    "signed document has no signed_at timestamp",
                ),
            )

        return ()

    if any(
        keyword in normalized_name
        for keyword in ("PROCUREMENT", "PURCHASE", "PR GATE")
    ):
        if not _has_purchase_request_identifier(
            project_id,
            procurement,
        ):
            return (
                (
                    "MISSING_PURCHASE_REQUEST",
                    "procurement record has no Purchase Request external ID",
                ),
            )

        return ()

    status = str(step.get("status", "")).upper()
    return (
        (
            "INCOMPLETE_MANUAL_GATE",
            f"approval gate remains {status}",
        ),
    )


def _approval_reasons(
    latest_revision: Mapping[str, Any] | None,
    approvals: Iterable[Mapping[str, Any]],
    required_roles: Iterable[str],
    *,
    require_approved_at: bool,
) -> tuple[tuple[str, str], ...]:
    roles = tuple(required_roles)

    if latest_revision is None:
        return (
            (
                "MISSING_DOCUMENT_REVISION",
                "no active document revision exists",
            ),
        )

    revision_id = str(latest_revision["id"])
    approval_rows = [
        approval
        for approval in approvals
        if str(approval.get("document_revision_id")) == revision_id
    ]
    reasons: list[tuple[str, str]] = []

    for role in roles:
        role_rows = [
            approval
            for approval in approval_rows
            if str(approval.get("approver_role", "")).upper() == role
        ]
        approved = any(
            str(approval.get("approval_status", "")).upper()
            == "APPROVED"
            and (
                not require_approved_at
                or approval.get("approved_at") is not None
            )
            for approval in role_rows
        )

        if approved:
            continue

        rejected = any(
            str(approval.get("approval_status", "")).upper()
            == "REJECTED"
            for approval in role_rows
        )
        code_prefix = "REJECTED" if rejected else "MISSING"
        description_prefix = "rejected" if rejected else "lacks"
        reasons.append(
            (
                f"{code_prefix}_{role}_APPROVAL",
                f"latest document {description_prefix} {role} approval",
            )
        )

    return tuple(reasons)


def _legacy_approval_reason(
    latest_revision: Mapping[str, Any] | None,
    approvals: Iterable[Mapping[str, Any]],
    role: str,
) -> tuple[tuple[str, str], ...]:
    if _has_approval(latest_revision, approvals, role):
        return ()

    return (
        (
            f"MISSING_{role}_APPROVAL",
            f"latest document lacks {role} approval",
        ),
    )


def _existing_document_reasons(
    *,
    project: Mapping[str, Any],
    revisions: Iterable[Mapping[str, Any]],
    business_date: date,
    deadline_policy: DeadlinePolicy,
) -> tuple[tuple[str, str], ...]:
    reused_revision_id = project.get("reused_document_revision_id")
    reasons: list[tuple[str, str]] = []

    if reused_revision_id is None:
        reasons.append(
            (
                "MISSING_REUSED_DOCUMENT",
                "project has no reused document revision",
            )
        )
        reused_revision = None
    else:
        reused_revision = next(
            (
                revision
                for revision in revisions
                if str(revision.get("id"))
                == str(reused_revision_id)
            ),
            None,
        )

        if reused_revision is None:
            reasons.append(
                (
                    "MISSING_REUSED_DOCUMENT_EVIDENCE",
                    "reused document evidence is unavailable",
                )
            )

    payment_period = project.get("payment_period_number")

    if (
        not isinstance(payment_period, int)
        or isinstance(payment_period, bool)
        or payment_period < 2
    ):
        reasons.append(
            (
                "INVALID_PAYMENT_PERIOD",
                "existing-document workflow requires payment period 2 or later",
            )
        )

    if reused_revision is None:
        return tuple(reasons)

    if reused_revision.get("superseded_by") is not None:
        reasons.append(
            (
                "SUPERSEDED_REUSED_DOCUMENT",
                "reused document revision has been superseded",
            )
        )

    if not reused_revision.get("signed"):
        reasons.append(
            (
                "UNSIGNED_REUSED_DOCUMENT",
                "reused document revision is not signed",
            )
        )
    elif reused_revision.get("signed_at") is None:
        reasons.append(
            (
                "INVALID_SIGNED_DOCUMENT",
                "signed reused document has no signed_at timestamp",
            )
        )

    effective_date = deadline_policy.normalize_date(
        reused_revision.get("effective_date")
    )
    expiry_date = deadline_policy.normalize_date(
        reused_revision.get("expiry_date")
    )

    if effective_date is not None and effective_date > business_date:
        reasons.append(
            (
                "DOCUMENT_NOT_EFFECTIVE",
                "reused document is not effective yet",
            )
        )

    if expiry_date is not None and expiry_date < business_date:
        reasons.append(
            (
                "EXPIRED_REUSED_DOCUMENT",
                "reused document has expired",
            )
        )

    return tuple(reasons)


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
            alert.branch_key or "",
            alert.project_step_id or "",
            alert.condition_fingerprint or "",
        ),
    )
