"""Checkpoint 8.1 Merchant deadline policy tests."""

from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from claude.agents.tools.merchant.checker import (
    MerchantProjectChecker,
)
from claude.agents.tools.merchant.deadline_policy import (
    DEFAULT_DUE_SOON_DAYS,
    DUE_SOON,
    DUE_TODAY,
    MERCHANT_TIMEZONE_NAME,
    OVERDUE,
    DeadlinePolicy,
)

from .test_checker import make_snapshot, make_step


def test_default_policy_uses_merchant_timezone_and_seven_days():
    policy = DeadlinePolicy()

    assert MERCHANT_TIMEZONE_NAME == "Asia/Ho_Chi_Minh"
    assert policy.timezone.key == MERCHANT_TIMEZONE_NAME
    assert DEFAULT_DUE_SOON_DAYS == 7
    assert policy.due_soon_days == 7


@pytest.mark.parametrize(
    "value",
    (-1, True, False, 1.5, "7", None),
)
def test_invalid_due_soon_configuration_fails_closed(value):
    with pytest.raises(
        ValueError,
        match="non-negative integer",
    ):
        DeadlinePolicy(due_soon_days=value)


@pytest.mark.parametrize("value", (0, 1, 7, 30))
def test_non_negative_integer_windows_are_accepted(value):
    assert DeadlinePolicy(due_soon_days=value).due_soon_days == value


def test_explicit_date_and_naive_datetime_use_business_calendar():
    policy = DeadlinePolicy()

    assert policy.normalize_date(date(2026, 9, 7)) == date(2026, 9, 7)
    assert policy.normalize_date(
        datetime(2026, 9, 7, 23, 59)
    ) == date(2026, 9, 7)


def test_aware_datetime_is_converted_to_merchant_timezone():
    policy = DeadlinePolicy()

    assert policy.normalize_date(
        datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    ) == date(2026, 9, 8)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("2026-09-07", date(2026, 9, 7)),
        (" 2026-09-07 ", date(2026, 9, 7)),
        ("2026-09-07T18:00:00Z", date(2026, 9, 8)),
        ("2026-09-07T18:00:00+00:00", date(2026, 9, 8)),
        ("2026-09-07T23:00:00", date(2026, 9, 7)),
    ),
)
def test_iso_strings_are_normalized_strictly(value, expected):
    assert DeadlinePolicy().normalize_date(value) == expected


@pytest.mark.parametrize(
    "value",
    ("", "not-a-date", "2026-02-30", object()),
)
def test_invalid_deadline_values_fail_closed(value):
    with pytest.raises(ValueError):
        DeadlinePolicy().normalize_date(value)


@pytest.mark.parametrize(
    ("due_date", "alert_type", "days_until_due"),
    (
        (date(2026, 9, 6), OVERDUE, -1),
        (date(2026, 9, 7), DUE_TODAY, 0),
        (date(2026, 9, 8), DUE_SOON, 1),
        (date(2026, 9, 14), DUE_SOON, 7),
        (date(2026, 9, 15), None, 8),
    ),
)
def test_deadline_categories_have_exact_boundaries(
    due_date,
    alert_type,
    days_until_due,
):
    evaluation = DeadlinePolicy().evaluate(
        due_date,
        business_date=date(2026, 9, 7),
    )

    assert evaluation.alert_type == alert_type
    assert evaluation.days_until_due == days_until_due
    assert evaluation.due_date == due_date


def test_missing_deadline_has_no_alert_or_day_delta():
    evaluation = DeadlinePolicy().evaluate(
        None,
        business_date=date(2026, 9, 7),
    )

    assert evaluation.alert_type is None
    assert evaluation.days_until_due is None
    assert evaluation.due_date is None


def test_zero_day_window_does_not_classify_future_dates():
    policy = DeadlinePolicy(due_soon_days=0)

    today = policy.evaluate(
        date(2026, 9, 7),
        business_date=date(2026, 9, 7),
    )
    tomorrow = policy.evaluate(
        date(2026, 9, 8),
        business_date=date(2026, 9, 7),
    )

    assert today.alert_type == DUE_TODAY
    assert tomorrow.alert_type is None


def test_default_business_date_uses_merchant_timezone():
    policy = DeadlinePolicy()

    assert policy.resolve_business_date(
        now=datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    ) == date(2026, 9, 8)


def test_checker_uses_seven_day_default_boundary():
    checker = MerchantProjectChecker()
    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion=date(2026, 9, 14)
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 7),
    )

    assert checker.due_soon_days == 7
    assert [alert.alert_type for alert in alerts] == [DUE_SOON]


def test_checker_excludes_day_after_due_soon_boundary():
    checker = MerchantProjectChecker()
    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion=date(2026, 9, 15)
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 7),
    )

    assert alerts == []


def test_checker_normalizes_aware_business_and_due_datetimes():
    checker = MerchantProjectChecker()
    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion=(
                    "2026-09-07T18:00:00+00:00"
                )
            )
        ]
    )

    alerts = checker.check_snapshot(
        snapshot,
        business_date=datetime(
            2026,
            9,
            7,
            17,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert [alert.alert_type for alert in alerts] == [DUE_TODAY]
    assert alerts[0].business_due_date == date(2026, 9, 8)


def test_checker_does_not_mutate_deadline_snapshot():
    checker = MerchantProjectChecker()
    snapshot = make_snapshot(
        steps=[
            make_step(
                scheduled_completion="2026-09-14"
            )
        ]
    )
    original = deepcopy(snapshot)

    checker.check_snapshot(
        snapshot,
        business_date=date(2026, 9, 7),
    )

    assert snapshot == original
