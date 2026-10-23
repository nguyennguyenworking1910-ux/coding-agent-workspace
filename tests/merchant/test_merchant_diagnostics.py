import json

import pytest

from claude.hooks.merchant_diagnostics import (
    DiagnosticContractError,
    build_diagnostic_event,
    serialize_diagnostic_event,
)


def valid_event(**overrides):
    values = {
        "event_type": "merchant.recovery",
        "stage": "evidence_verification",
        "outcome": "verified",
        "run_id": "run-1",
        "task_id": "task-1",
        "write_id": "write-1",
        "claim_generation": 1,
    }
    values.update(overrides)
    return build_diagnostic_event(**values)


def test_valid_event_round_trip():
    event = valid_event()
    encoded = serialize_diagnostic_event(event)

    assert json.loads(encoded) == event
    assert event["schema_version"] == 1


@pytest.mark.parametrize("field", [
    "payload",
    "confirmation_token",
    "runtime_authorization",
    "password",
    "merchant_name",
    "execution_attempt_id",
])
def test_unapproved_fields_rejected(field):
    with pytest.raises(DiagnosticContractError):
        valid_event(**{field: "SENSITIVE_SECRET_VALUE"})


@pytest.mark.parametrize("value", [
    "",
    "contains space",
    "customer@example.com",
    "abc/../../secret",
    "a" * 129,
    123,
    None,
])
def test_unsafe_identity_rejected(value):
    with pytest.raises(DiagnosticContractError):
        valid_event(run_id=value)


@pytest.mark.parametrize("generation", [
    True, False, 0, -1, 1.0, "1",
])
def test_invalid_generation_rejected(generation):
    with pytest.raises(DiagnosticContractError):
        valid_event(claim_generation=generation)


def test_unknown_event_type_rejected():
    with pytest.raises(DiagnosticContractError):
        valid_event(event_type="merchant.arbitrary")


def test_failure_requires_classified_error():
    with pytest.raises(DiagnosticContractError):
        valid_event(outcome="failed")

    event = valid_event(
        outcome="failed",
        error_code="PERSISTENCE_FAILED",
    )
    assert event["error_code"] == "PERSISTENCE_FAILED"


def test_success_rejects_error_code():
    with pytest.raises(DiagnosticContractError):
        valid_event(error_code="UNKNOWN_FAILURE")


def test_invalid_error_never_leaks_secret():
    secret = "VERY_PRIVATE_CREDENTIAL_VALUE"

    with pytest.raises(DiagnosticContractError) as error:
        valid_event(password=secret)

    assert secret not in str(error.value)


def test_serializer_rejects_injected_field():
    event = valid_event()
    event["password"] = "SECRET_VALUE"

    with pytest.raises(DiagnosticContractError):
        serialize_diagnostic_event(event)


def test_serializer_rejects_noncanonical_schema():
    event = valid_event()
    event["schema_version"] = True

    with pytest.raises(DiagnosticContractError):
        serialize_diagnostic_event(event)


def test_event_construction_has_no_persistence_side_effect(
    tmp_path, monkeypatch
):
    import os

    monkeypatch.chdir(tmp_path)
    before = set(os.listdir(tmp_path))

    event = valid_event()
    serialize_diagnostic_event(event)

    assert set(os.listdir(tmp_path)) == before



def test_diagnostic_serializer_rejects_secret_injection():
    """Never serialize extra sensitive fields."""
    secret = "DO_NOT_LEAK_PRIVATE_TOKEN"
    event = valid_event()
    event["runtime_authorization"] = secret

    with pytest.raises(DiagnosticContractError) as error:
        serialize_diagnostic_event(event)

    assert secret not in str(error.value)


@pytest.mark.parametrize("field,value", [
    ("event_type", "merchant.untrusted"),
    ("stage", "private_payload"),
    ("outcome", "unauthorized"),
    ("run_id", "secret@example.com"),
    ("task_id", "../private"),
    ("write_id", "write with spaces"),
    ("claim_generation", True),
    ("claim_generation", -1),
    ("error_code", "PRIVATE_EXCEPTION_MESSAGE"),
])
def test_diagnostic_serializer_rejects_malformed_values(
    field, value
):
    event = valid_event()
    event[field] = value

    with pytest.raises(DiagnosticContractError):
        serialize_diagnostic_event(event)


def test_diagnostic_sink_failure_does_not_expose_secret():
    from claude.hooks.merchant_diagnostics import (
        emit_diagnostic_event,
    )

    event = valid_event()
    secret = "SENSITIVE_SINK_EXCEPTION"

    def broken_sink(_payload):
        raise RuntimeError(secret)

    assert emit_diagnostic_event(event, broken_sink) is False


def test_diagnostic_sink_rejects_unapproved_payload():
    from claude.hooks.merchant_diagnostics import (
        emit_diagnostic_event,
    )

    captured = []
    event = valid_event()
    event["password"] = "PRIVATE_VALUE"

    assert emit_diagnostic_event(
        event, captured.append
    ) is False

    assert captured == []
