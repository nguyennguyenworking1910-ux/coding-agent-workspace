"""Timezone-aware deadline policy for Merchant project alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo


MERCHANT_TIMEZONE_NAME = "Asia/Ho_Chi_Minh"
MERCHANT_TIMEZONE = ZoneInfo(MERCHANT_TIMEZONE_NAME)
DEFAULT_DUE_SOON_DAYS = 7

OVERDUE = "OVERDUE"
DUE_TODAY = "DUE_TODAY"
DUE_SOON = "DUE_SOON"


@dataclass(frozen=True)
class DeadlineEvaluation:
    """One normalized deadline compared with one business date."""

    business_date: date
    due_date: date | None
    alert_type: str | None
    days_until_due: int | None


@dataclass(frozen=True)
class DeadlinePolicy:
    """Classify deadlines using the Merchant business timezone."""

    due_soon_days: int = DEFAULT_DUE_SOON_DAYS
    timezone: ZoneInfo = MERCHANT_TIMEZONE

    def __post_init__(self) -> None:
        if (
            isinstance(self.due_soon_days, bool)
            or not isinstance(self.due_soon_days, int)
            or self.due_soon_days < 0
        ):
            raise ValueError(
                "due_soon_days must be a non-negative integer"
            )

        if not isinstance(self.timezone, ZoneInfo):
            raise ValueError("timezone must be a ZoneInfo instance")

    def normalize_date(self, value: Any) -> date | None:
        """Normalize a database or CLI date into the business timezone."""

        if value is None:
            return None

        if isinstance(value, datetime):
            return self._datetime_date(value)

        if isinstance(value, date):
            return value

        if isinstance(value, str):
            return self._string_date(value)

        raise ValueError(
            f"Unsupported Merchant deadline value: {type(value).__name__}"
        )

    def resolve_business_date(
        self,
        value: Any = None,
        *,
        now: datetime | None = None,
    ) -> date:
        """Return an explicit date or today's Merchant business date."""

        if value is not None:
            normalized = self.normalize_date(value)

            if normalized is None:  # Defensive; value is known non-null.
                raise ValueError("business_date cannot be null")

            return normalized

        current = now or datetime.now(self.timezone)

        if not isinstance(current, datetime):
            raise ValueError("now must be a datetime")

        return self._datetime_date(current)

    def evaluate(
        self,
        due_value: Any,
        *,
        business_date: Any = None,
        now: datetime | None = None,
    ) -> DeadlineEvaluation:
        """Classify one deadline without mutating any workflow state."""

        effective_date = self.resolve_business_date(
            business_date,
            now=now,
        )
        due_date = self.normalize_date(due_value)

        if due_date is None:
            return DeadlineEvaluation(
                business_date=effective_date,
                due_date=None,
                alert_type=None,
                days_until_due=None,
            )

        days_until_due = (due_date - effective_date).days

        if days_until_due < 0:
            alert_type = OVERDUE
        elif days_until_due == 0:
            alert_type = DUE_TODAY
        elif days_until_due <= self.due_soon_days:
            alert_type = DUE_SOON
        else:
            alert_type = None

        return DeadlineEvaluation(
            business_date=effective_date,
            due_date=due_date,
            alert_type=alert_type,
            days_until_due=days_until_due,
        )

    def _datetime_date(self, value: datetime) -> date:
        if value.tzinfo is None:
            localized = value.replace(tzinfo=self.timezone)
        else:
            localized = value.astimezone(self.timezone)

        return localized.date()

    def _string_date(self, value: str) -> date:
        text = value.strip()

        if not text:
            raise ValueError("Merchant deadline value cannot be empty")

        try:
            if len(text) == 10:
                return date.fromisoformat(text)

            normalized = (
                f"{text[:-1]}+00:00"
                if text.endswith(("Z", "z"))
                else text
            )
            return self._datetime_date(
                datetime.fromisoformat(normalized)
            )
        except ValueError as exc:
            raise ValueError(
                "Merchant deadline value must be an ISO date or datetime"
            ) from exc
