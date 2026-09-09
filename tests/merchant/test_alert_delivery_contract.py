"""Contracts for production Merchant alert payloads and worker limits."""

from datetime import date, datetime
from pathlib import Path

import pytest

from claude.workers.merchant_alert_contract import (
    DEFAULT_CLAIM_LIMIT,
    DEFAULT_LEASE_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_NETWORK_TIMEOUT_SECONDS,
    DEFAULT_PROJECT_LIMIT,
    DEFAULT_RETRY_BASE_SECONDS,
    DEFAULT_RETRY_MAX_SECONDS,
    AlertContractError,
    DeliveryFailureCode,
    DeliveryPayload,
    SafeDeliveryError,
    WorkerLimits,
    safe_failure_summary,
)


DELIVERY_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
STEP_ID = "00000000-0000-0000-0000-000000000003"
DEDUPLICATION_KEY = "a" * 64
PRIVATE_VALUE = "private-recipient@example.invalid"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_record(**overrides):
    record = {
        "id": DELIVERY_ID,
        "project_id": PROJECT_ID,
        "project_step_id": STEP_ID,
        "alert_type": "DUE_TODAY",
        "business_due_date": date(2026, 9, 9),
        "condition_fingerprint": None,
        "deduplication_key": DEDUPLICATION_KEY,
        "delivery_channel": "INTERNAL",
        "delivery_attempt_count": 1,
    }
    record.update(overrides)
    return record


def test_contract_module_has_no_database_or_network_dependency():
    source = (
        PROJECT_ROOT
        / ".claude"
        / "workers"
        / "merchant_alert_contract.py"
    ).read_text(encoding="utf-8")

    for forbidden_import in (
        "psycopg",
        "requests",
        "smtplib",
        "socket",
        "urllib",
    ):
        assert forbidden_import not in source


def test_worker_limits_use_reviewed_defaults():
    limits = WorkerLimits.from_env({})

    assert limits == WorkerLimits()
    assert limits.to_safe_dict() == {
        "project_limit": DEFAULT_PROJECT_LIMIT,
        "claim_limit": DEFAULT_CLAIM_LIMIT,
        "max_attempts": DEFAULT_MAX_ATTEMPTS,
        "lease_seconds": DEFAULT_LEASE_SECONDS,
        "retry_base_seconds": DEFAULT_RETRY_BASE_SECONDS,
        "retry_max_seconds": DEFAULT_RETRY_MAX_SECONDS,
        "network_timeout_seconds": (
            DEFAULT_NETWORK_TIMEOUT_SECONDS
        ),
    }


def test_worker_limits_accept_exact_valid_environment():
    limits = WorkerLimits.from_env(
        {
            "MERCHANT_ALERT_PROJECT_LIMIT": "200",
            "MERCHANT_ALERT_CLAIM_LIMIT": "40",
            "MERCHANT_ALERT_MAX_ATTEMPTS": "6",
            "MERCHANT_ALERT_LEASE_SECONDS": "180",
            "MERCHANT_ALERT_RETRY_BASE_SECONDS": "60",
            "MERCHANT_ALERT_RETRY_MAX_SECONDS": "900",
            "MERCHANT_ALERT_NETWORK_TIMEOUT_SECONDS": "20",
        }
    )

    assert limits == WorkerLimits(
        project_limit=200,
        claim_limit=40,
        max_attempts=6,
        lease_seconds=180,
        retry_base_seconds=60,
        retry_max_seconds=900,
        network_timeout_seconds=20,
    )


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("MERCHANT_ALERT_PROJECT_LIMIT", "0"),
        ("MERCHANT_ALERT_PROJECT_LIMIT", "501"),
        ("MERCHANT_ALERT_CLAIM_LIMIT", "101"),
        ("MERCHANT_ALERT_MAX_ATTEMPTS", "11"),
        ("MERCHANT_ALERT_LEASE_SECONDS", "29"),
        ("MERCHANT_ALERT_RETRY_BASE_SECONDS", "0"),
        ("MERCHANT_ALERT_RETRY_MAX_SECONDS", "86401"),
        ("MERCHANT_ALERT_NETWORK_TIMEOUT_SECONDS", "61"),
        ("MERCHANT_ALERT_CLAIM_LIMIT", "not-an-integer"),
        ("MERCHANT_ALERT_CLAIM_LIMIT", "+25"),
        ("MERCHANT_ALERT_CLAIM_LIMIT", ""),
    ],
)
def test_worker_limits_reject_invalid_values_without_echo(
    variable,
    value,
):
    with pytest.raises(AlertContractError) as raised:
        WorkerLimits.from_env({variable: value})

    if value:
        assert value not in str(raised.value)
        assert value not in repr(raised.value)


def test_worker_limits_reject_retry_max_below_base():
    with pytest.raises(
        AlertContractError,
        match="CONFIG_RETRY_MAX_BELOW_BASE",
    ):
        WorkerLimits(
            retry_base_seconds=301,
            retry_max_seconds=300,
        )


def test_worker_limits_reject_lease_without_timeout_margin():
    with pytest.raises(
        AlertContractError,
        match="CONFIG_LEASE_TOO_SHORT_FOR_NETWORK_TIMEOUT",
    ):
        WorkerLimits(
            lease_seconds=30,
            network_timeout_seconds=30,
        )


def test_retry_delay_is_bounded_and_exhaustion_is_terminal():
    limits = WorkerLimits(
        max_attempts=5,
        retry_base_seconds=300,
        retry_max_seconds=1_000,
    )

    assert limits.retry_delay_seconds(1) == 300
    assert limits.retry_delay_seconds(2) == 600
    assert limits.retry_delay_seconds(3) == 1_000
    assert limits.retry_delay_seconds(4) == 1_000
    assert limits.retry_delay_seconds(5) is None


@pytest.mark.parametrize("attempt", [0, 6, True, 1.5])
def test_retry_delay_rejects_invalid_attempt(attempt):
    with pytest.raises(AlertContractError):
        WorkerLimits().retry_delay_seconds(attempt)


def test_deadline_payload_normalizes_safe_fields():
    payload = DeliveryPayload.from_delivery_record(
        make_record(
            id=DELIVERY_ID.upper(),
            delivery_channel=" internal ",
        )
    )

    assert payload.to_safe_dict() == {
        "delivery_id": DELIVERY_ID,
        "project_id": PROJECT_ID,
        "project_step_id": STEP_ID,
        "alert_type": "DUE_TODAY",
        "business_due_date": "2026-09-09",
        "condition_fingerprint": None,
        "deduplication_key": DEDUPLICATION_KEY,
        "delivery_channel": "INTERNAL",
        "attempt_number": 1,
    }


def test_condition_payload_requires_safe_fingerprint():
    payload = DeliveryPayload.from_delivery_record(
        make_record(
            alert_type="blocked",
            business_due_date=None,
            condition_fingerprint=(
                "dependency:00000000-0000-0000-0000-000000000004:"
                "00000000-0000-0000-0000-000000000003"
            ),
            delivery_channel="SLACK",
        )
    )

    assert payload.alert_type == "BLOCKED"
    assert payload.delivery_channel == "SLACK"
    assert payload.business_due_date is None


def test_payload_projection_discards_private_and_arbitrary_fields():
    payload = DeliveryPayload.from_delivery_record(
        make_record(
            merchant_name=PRIVATE_VALUE,
            contact_email=PRIVATE_VALUE,
            message=PRIVATE_VALUE,
            last_error_summary=PRIVATE_VALUE,
            provider_response=PRIVATE_VALUE,
        )
    )
    encoded = repr(payload.to_safe_dict())

    assert PRIVATE_VALUE not in encoded
    assert set(payload.to_safe_dict()) == {
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


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"id": "invalid"}, "PAYLOAD_DELIVERY_ID_INVALID"),
        ({"project_id": "invalid"}, "PAYLOAD_PROJECT_ID_INVALID"),
        (
            {"project_step_id": "invalid"},
            "PAYLOAD_PROJECT_STEP_ID_INVALID",
        ),
        ({"alert_type": "UNKNOWN"}, "PAYLOAD_ALERT_TYPE_INVALID"),
        (
            {"delivery_channel": "UNKNOWN"},
            "PAYLOAD_DELIVERY_CHANNEL_INVALID",
        ),
        (
            {"business_due_date": "09/09/2026"},
            "PAYLOAD_BUSINESS_DUE_DATE_INVALID",
        ),
        (
            {"business_due_date": datetime(2026, 9, 9)},
            "PAYLOAD_BUSINESS_DUE_DATE_INVALID",
        ),
        (
            {"deduplication_key": "not-a-hash"},
            "PAYLOAD_DEDUPLICATION_KEY_INVALID",
        ),
        (
            {"delivery_attempt_count": 0},
            "CONFIG_ATTEMPT_NUMBER_OUT_OF_RANGE",
        ),
    ],
)
def test_payload_rejects_invalid_fields(overrides, reason_code):
    with pytest.raises(AlertContractError, match=reason_code):
        DeliveryPayload.from_delivery_record(
            make_record(**overrides)
        )


def test_payload_error_never_echoes_rejected_private_value():
    with pytest.raises(AlertContractError) as raised:
        DeliveryPayload.from_delivery_record(
            make_record(delivery_channel=PRIVATE_VALUE)
        )

    assert PRIVATE_VALUE not in str(raised.value)
    assert PRIVATE_VALUE not in repr(raised.value)


def test_payload_rejects_missing_condition_evidence():
    with pytest.raises(
        AlertContractError,
        match="PAYLOAD_CONDITION_EVIDENCE_REQUIRED",
    ):
        DeliveryPayload.from_delivery_record(
            make_record(
                alert_type="BLOCKED",
                business_due_date=None,
                condition_fingerprint=None,
            )
        )


def test_deadline_alert_requires_due_date():
    with pytest.raises(
        AlertContractError,
        match="PAYLOAD_DEADLINE_DATE_REQUIRED",
    ):
        DeliveryPayload.from_delivery_record(
            make_record(
                business_due_date=None,
                condition_fingerprint="deadline:fallback",
            )
        )


def test_condition_alert_requires_fingerprint():
    with pytest.raises(
        AlertContractError,
        match="PAYLOAD_FINGERPRINT_REQUIRED",
    ):
        DeliveryPayload.from_delivery_record(
            make_record(
                alert_type="MISSING_GATE",
                condition_fingerprint=None,
            )
        )


@pytest.mark.parametrize(
    "fingerprint",
    [
        "contains whitespace",
        "contains/newline\n",
        "x" * 256,
    ],
)
def test_payload_rejects_unsafe_fingerprint(fingerprint):
    with pytest.raises(
        AlertContractError,
        match="PAYLOAD_CONDITION_FINGERPRINT_INVALID",
    ):
        DeliveryPayload.from_delivery_record(
            make_record(
                alert_type="BLOCKED",
                business_due_date=None,
                condition_fingerprint=fingerprint,
            )
        )


def test_missing_required_record_field_uses_stable_reason():
    record = make_record()
    del record["project_id"]

    with pytest.raises(
        AlertContractError,
        match="PAYLOAD_REQUIRED_FIELD_MISSING",
    ):
        DeliveryPayload.from_delivery_record(record)


def test_safe_delivery_error_never_carries_transport_detail():
    error = SafeDeliveryError(
        DeliveryFailureCode.TRANSPORT_TIMEOUT,
        retryable=True,
    )

    assert str(error) == "TRANSPORT_TIMEOUT"
    assert "TRANSPORT_TIMEOUT" in repr(error)
    assert error.retryable is True
    assert PRIVATE_VALUE not in str(error)
    assert PRIVATE_VALUE not in repr(error)


def test_failure_summary_never_copies_unknown_exception_text():
    error = RuntimeError(
        f"Connection failed using secret {PRIVATE_VALUE}"
    )

    assert safe_failure_summary(error) == "UNEXPECTED_FAILURE"
    assert PRIVATE_VALUE not in safe_failure_summary(error)


def test_failure_summary_preserves_only_allowlisted_safe_code():
    error = SafeDeliveryError(
        DeliveryFailureCode.PROVIDER_REJECTED,
        retryable=False,
    )

    assert safe_failure_summary(error) == "PROVIDER_REJECTED"


def test_contract_error_maps_to_configuration_code():
    error = AlertContractError("PRIVATE_DETAIL_MUST_NOT_ESCAPE")

    assert safe_failure_summary(error) == "CONFIGURATION_INVALID"
    assert "PRIVATE_DETAIL" not in safe_failure_summary(error)
