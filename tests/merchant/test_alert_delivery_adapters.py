"""Unit contracts for INTERNAL, EMAIL, and SLACK alert adapters."""

from __future__ import annotations

import json
import smtplib
from datetime import date
from urllib.error import HTTPError

import pytest

from claude.workers import merchant_alert_adapters as adapters_module
from claude.workers.merchant_alert_adapters import (
    EmailConfiguration,
    EmailDeliveryAdapter,
    InternalDeliveryAdapter,
    SLACK_API_URL,
    SlackApiTransport,
    SlackConfiguration,
    SlackDeliveryAdapter,
    SmtpTransport,
    _RejectRedirectHandler,
    build_delivery_adapter,
)
from claude.workers.merchant_alert_contract import (
    AlertContractError,
    DeliveryFailureCode,
    SafeDeliveryError,
    WorkerLimits,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
STEP_ID = "00000000-0000-0000-0000-000000000002"
DELIVERY_ID = "00000000-0000-0000-0000-000000000003"
PRIVATE_MARKER = "must-not-appear-in-provider-payload"

EMAIL_HOST = "smtp.example.invalid"
EMAIL_USERNAME = "alert-worker@example.invalid"
EMAIL_PASSWORD = "fictitious-email-secret-123"
EMAIL_SENDER = "alert-worker@example.invalid"
EMAIL_RECIPIENT = "operator@example.invalid"
SLACK_TOKEN = (
    "xoxb-000000000000-000000000000-"
    "fictitiousslacksecret"
)
SLACK_CHANNEL = "C000000001"


def delivery_record(channel="INTERNAL"):
    return {
        "id": DELIVERY_ID,
        "project_id": PROJECT_ID,
        "project_step_id": STEP_ID,
        "alert_type": "DUE_TODAY",
        "business_due_date": date(2026, 9, 9),
        "condition_fingerprint": None,
        "deduplication_key": "a" * 64,
        "delivery_channel": channel,
        "delivery_attempt_count": 2,
        "claim_token": "00000000-0000-0000-0000-000000000004",
        "merchant_name": PRIVATE_MARKER,
        "contact_email": "private-recipient@example.invalid",
    }


def email_environment():
    return {
        "MERCHANT_ALERT_EMAIL_SMTP_HOST": EMAIL_HOST,
        "MERCHANT_ALERT_EMAIL_SMTP_PORT": "587",
        "MERCHANT_ALERT_EMAIL_SECURITY": "STARTTLS",
        "MERCHANT_ALERT_EMAIL_USERNAME": EMAIL_USERNAME,
        "MERCHANT_ALERT_EMAIL_PASSWORD": EMAIL_PASSWORD,
        "MERCHANT_ALERT_EMAIL_SENDER": EMAIL_SENDER,
        "MERCHANT_ALERT_EMAIL_RECIPIENTS": EMAIL_RECIPIENT,
    }


def slack_environment():
    return {
        "MERCHANT_ALERT_SLACK_BOT_TOKEN": SLACK_TOKEN,
        "MERCHANT_ALERT_SLACK_CHANNEL_ID": SLACK_CHANNEL,
    }


class FakeEmailTransport:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def send(
        self,
        configuration,
        message,
        *,
        timeout_seconds,
    ):
        self.calls.append(
            (configuration, message, timeout_seconds)
        )
        if self.error is not None:
            raise self.error


class FakeSlackTransport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(
        self,
        configuration,
        request_payload,
        *,
        timeout_seconds,
    ):
        self.calls.append(
            (configuration, request_payload, timeout_seconds)
        )
        if self.error is not None:
            raise self.error
        return self.response


class FakeSmtpClient:
    def __init__(self, *arguments, **keywords):
        self.arguments = arguments
        self.keywords = keywords
        self.operations = []

    def __enter__(self):
        self.operations.append("enter")
        return self

    def __exit__(self, exception_type, exception, traceback):
        self.operations.append("exit")

    def ehlo(self):
        self.operations.append("ehlo")

    def starttls(self, *, context):
        assert context is not None
        self.operations.append("starttls")

    def login(self, username, password):
        self.operations.append(("login", username, password))

    def send_message(self, message):
        self.operations.append(("send_message", message))
        return {}


class FakeUrlResponse:
    def __init__(self, body):
        self.body = body
        self.read_size = None

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        return None

    def read(self, size):
        self.read_size = size
        return self.body


class FakeUrlOpener:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        return self.response


def test_internal_adapter_emits_only_allowlisted_payload(capsys):
    provider_id = InternalDeliveryAdapter().deliver(
        delivery_record()
    )
    payload = json.loads(capsys.readouterr().out)

    assert provider_id == f"internal:{DELIVERY_ID}"
    assert payload == {
        "event": "merchant_project_alert",
        "delivery_id": DELIVERY_ID,
        "project_id": PROJECT_ID,
        "project_step_id": STEP_ID,
        "alert_type": "DUE_TODAY",
        "business_due_date": "2026-09-09",
        "condition_fingerprint": None,
        "deduplication_key": "a" * 64,
        "delivery_channel": "INTERNAL",
        "attempt_number": 2,
    }


def test_email_configuration_is_strict_and_redacted():
    configuration = EmailConfiguration.from_env(
        email_environment()
    )

    assert configuration.smtp_port == 587
    assert configuration.security == "STARTTLS"
    assert configuration.recipients == (EMAIL_RECIPIENT,)
    assert configuration.to_safe_dict() == {
        "channel": "EMAIL",
        "configured": True,
        "security": "STARTTLS",
        "recipient_count": 1,
    }

    representation = repr(configuration)
    for private_value in (
        EMAIL_HOST,
        EMAIL_USERNAME,
        EMAIL_PASSWORD,
        EMAIL_SENDER,
        EMAIL_RECIPIENT,
    ):
        assert private_value not in representation


@pytest.mark.parametrize(
    "missing_variable",
    [
        "MERCHANT_ALERT_EMAIL_SMTP_HOST",
        "MERCHANT_ALERT_EMAIL_SMTP_PORT",
        "MERCHANT_ALERT_EMAIL_SECURITY",
        "MERCHANT_ALERT_EMAIL_USERNAME",
        "MERCHANT_ALERT_EMAIL_PASSWORD",
        "MERCHANT_ALERT_EMAIL_SENDER",
        "MERCHANT_ALERT_EMAIL_RECIPIENTS",
    ],
)
def test_email_configuration_requires_every_setting(missing_variable):
    environment = email_environment()
    environment.pop(missing_variable)

    with pytest.raises(
        AlertContractError,
        match="CONFIG_EMAIL_INCOMPLETE",
    ):
        EmailConfiguration.from_env(environment)


@pytest.mark.parametrize(
    ("variable", "value", "reason_code"),
    [
        (
            "MERCHANT_ALERT_EMAIL_SMTP_HOST",
            "https://smtp.example.invalid/path",
            "CONFIG_EMAIL_HOST_INVALID",
        ),
        (
            "MERCHANT_ALERT_EMAIL_SMTP_PORT",
            "0",
            "CONFIG_EMAIL_PORT_INVALID",
        ),
        (
            "MERCHANT_ALERT_EMAIL_SMTP_PORT",
            "+587",
            "CONFIG_EMAIL_PORT_INVALID",
        ),
        (
            "MERCHANT_ALERT_EMAIL_SECURITY",
            "NONE",
            "CONFIG_EMAIL_SECURITY_INVALID",
        ),
        (
            "MERCHANT_ALERT_EMAIL_PASSWORD",
            "short",
            "CONFIG_EMAIL_PASSWORD_INVALID",
        ),
        (
            "MERCHANT_ALERT_EMAIL_SENDER",
            "sender@example.invalid\r\nBcc: hidden@example.invalid",
            "CONFIG_EMAIL_SENDER_INVALID",
        ),
        (
            "MERCHANT_ALERT_EMAIL_RECIPIENTS",
            "not-an-email",
            "CONFIG_EMAIL_RECIPIENTS_INVALID",
        ),
        (
            "MERCHANT_ALERT_EMAIL_RECIPIENTS",
            f"{EMAIL_RECIPIENT},{EMAIL_RECIPIENT}",
            "CONFIG_EMAIL_RECIPIENTS_INVALID",
        ),
    ],
)
def test_email_configuration_rejects_unsafe_values(
    variable,
    value,
    reason_code,
):
    environment = email_environment()
    environment[variable] = value

    with pytest.raises(AlertContractError, match=reason_code):
        EmailConfiguration.from_env(environment)


def test_email_delivery_uses_stable_id_and_safe_body():
    transport = FakeEmailTransport()
    adapter = build_delivery_adapter(
        "EMAIL",
        environ=email_environment(),
        limits=WorkerLimits(network_timeout_seconds=17),
        email_transport=transport,
    )

    first = adapter.deliver(delivery_record("EMAIL"))
    second = adapter.deliver(delivery_record("EMAIL"))

    assert first == second == f"email:{DELIVERY_ID}"
    assert len(transport.calls) == 2
    configuration, message, timeout = transport.calls[0]
    second_message = transport.calls[1][1]

    assert configuration.recipients == (EMAIL_RECIPIENT,)
    assert timeout == 17
    assert message["Message-ID"] == second_message["Message-ID"]
    assert DELIVERY_ID in message["Message-ID"]
    assert message["X-Merchant-Delivery-ID"] == DELIVERY_ID
    assert message["X-Merchant-Deduplication-Key"] == "a" * 64

    body = message.get_content()
    assert PRIVATE_MARKER not in body
    assert "private-recipient@example.invalid" not in body
    assert "claim_token" not in body
    assert EMAIL_PASSWORD not in body


@pytest.mark.parametrize(
    ("security", "expected_client", "uses_starttls"),
    [
        ("STARTTLS", "smtp", True),
        ("TLS", "smtp_ssl", False),
    ],
)
def test_smtp_transport_requires_encrypted_authenticated_session(
    monkeypatch,
    security,
    expected_client,
    uses_starttls,
):
    environment = email_environment()
    environment["MERCHANT_ALERT_EMAIL_SECURITY"] = security
    configuration = EmailConfiguration.from_env(environment)
    created = {}

    def smtp_factory(*arguments, **keywords):
        client = FakeSmtpClient(*arguments, **keywords)
        created["smtp"] = client
        return client

    def smtp_ssl_factory(*arguments, **keywords):
        client = FakeSmtpClient(*arguments, **keywords)
        created["smtp_ssl"] = client
        return client

    monkeypatch.setattr(
        adapters_module.smtplib,
        "SMTP",
        smtp_factory,
    )
    monkeypatch.setattr(
        adapters_module.smtplib,
        "SMTP_SSL",
        smtp_ssl_factory,
    )

    adapter = EmailDeliveryAdapter(
        configuration=configuration,
        timeout_seconds=23,
        transport=SmtpTransport(),
    )
    assert adapter.deliver(delivery_record("EMAIL")) == (
        f"email:{DELIVERY_ID}"
    )

    client = created[expected_client]
    assert client.arguments == (EMAIL_HOST, 587)
    assert client.keywords["timeout"] == 23
    assert ("login", EMAIL_USERNAME, EMAIL_PASSWORD) in client.operations
    assert any(
        isinstance(operation, tuple)
        and operation[0] == "send_message"
        for operation in client.operations
    )
    assert ("starttls" in client.operations) is uses_starttls
    if uses_starttls:
        assert client.operations.index("starttls") < next(
            index
            for index, operation in enumerate(client.operations)
            if isinstance(operation, tuple)
            and operation[0] == "login"
        )


@pytest.mark.parametrize(
    ("transport_error", "expected_code", "retryable"),
    [
        (
            TimeoutError("private timeout details"),
            DeliveryFailureCode.TRANSPORT_TIMEOUT,
            True,
        ),
        (
            smtplib.SMTPAuthenticationError(
                535,
                b"private authentication details",
            ),
            DeliveryFailureCode.CONFIGURATION_INVALID,
            False,
        ),
        (
            smtplib.SMTPRecipientsRefused(
                {
                    EMAIL_RECIPIENT: (
                        550,
                        b"private provider body",
                    )
                }
            ),
            DeliveryFailureCode.PROVIDER_REJECTED,
            False,
        ),
        (
            smtplib.SMTPDataError(451, b"private provider body"),
            DeliveryFailureCode.TRANSPORT_UNAVAILABLE,
            True,
        ),
        (
            smtplib.SMTPDataError(550, b"private provider body"),
            DeliveryFailureCode.PROVIDER_REJECTED,
            False,
        ),
        (
            OSError("private network details"),
            DeliveryFailureCode.TRANSPORT_UNAVAILABLE,
            True,
        ),
        (
            RuntimeError("private unexpected details"),
            DeliveryFailureCode.UNEXPECTED_FAILURE,
            True,
        ),
    ],
)
def test_email_transport_failures_are_redacted(
    transport_error,
    expected_code,
    retryable,
):
    adapter = build_delivery_adapter(
        "EMAIL",
        environ=email_environment(),
        email_transport=FakeEmailTransport(transport_error),
    )

    with pytest.raises(SafeDeliveryError) as captured:
        adapter.deliver(delivery_record("EMAIL"))

    assert captured.value.code is expected_code
    assert captured.value.retryable is retryable
    assert "private" not in str(captured.value).lower()
    assert "private" not in repr(captured.value).lower()
    assert EMAIL_RECIPIENT not in str(captured.value)


def test_slack_configuration_is_strict_and_redacted():
    configuration = SlackConfiguration.from_env(
        slack_environment()
    )

    assert configuration.channel_id == SLACK_CHANNEL
    assert configuration.to_safe_dict() == {
        "channel": "SLACK",
        "configured": True,
    }
    assert SLACK_TOKEN not in repr(configuration)
    assert SLACK_CHANNEL not in repr(configuration)


@pytest.mark.parametrize(
    ("environment", "reason_code"),
    [
        ({}, "CONFIG_SLACK_INCOMPLETE"),
        (
            {
                "MERCHANT_ALERT_SLACK_BOT_TOKEN": "unsafe-token",
                "MERCHANT_ALERT_SLACK_CHANNEL_ID": SLACK_CHANNEL,
            },
            "CONFIG_SLACK_TOKEN_INVALID",
        ),
        (
            {
                "MERCHANT_ALERT_SLACK_BOT_TOKEN": SLACK_TOKEN,
                "MERCHANT_ALERT_SLACK_CHANNEL_ID": "general",
            },
            "CONFIG_SLACK_CHANNEL_INVALID",
        ),
    ],
)
def test_slack_configuration_rejects_missing_or_invalid_values(
    environment,
    reason_code,
):
    with pytest.raises(AlertContractError, match=reason_code):
        SlackConfiguration.from_env(environment)


def test_slack_delivery_uses_stable_id_and_safe_text():
    transport = FakeSlackTransport(
        response={
            "ok": True,
            "ts": "1760000000.000001",
            "provider_private_body": PRIVATE_MARKER,
        }
    )
    adapter = build_delivery_adapter(
        "SLACK",
        environ=slack_environment(),
        limits=WorkerLimits(network_timeout_seconds=19),
        slack_transport=transport,
    )

    provider_id = adapter.deliver(delivery_record("SLACK"))

    assert provider_id == "slack:1760000000.000001"
    configuration, request, timeout = transport.calls[0]
    assert configuration.channel_id == SLACK_CHANNEL
    assert timeout == 19
    assert request["channel"] == SLACK_CHANNEL
    assert request["client_msg_id"] == DELIVERY_ID
    assert request["metadata"]["event_payload"] == {
        "delivery_id": DELIVERY_ID,
        "deduplication_key": "a" * 64,
    }
    assert PRIVATE_MARKER not in request["text"]
    assert "private-recipient@example.invalid" not in request["text"]
    assert "claim_token" not in request["text"]
    assert SLACK_TOKEN not in json.dumps(request)


def test_slack_transport_uses_fixed_endpoint_and_bounded_response(
    monkeypatch,
):
    response = FakeUrlResponse(
        b'{"ok": true, "ts": "1760000000.000001"}'
    )
    opener = FakeUrlOpener(response)
    handlers = []

    def opener_factory(*supplied_handlers):
        handlers.extend(supplied_handlers)
        return opener

    monkeypatch.setattr(
        adapters_module,
        "build_opener",
        opener_factory,
    )
    configuration = SlackConfiguration.from_env(
        slack_environment()
    )
    transport = SlackApiTransport()
    result = transport.post(
        configuration,
        {
            "channel": SLACK_CHANNEL,
            "client_msg_id": DELIVERY_ID,
            "text": "safe payload",
        },
        timeout_seconds=29,
    )

    assert result == {
        "ok": True,
        "ts": "1760000000.000001",
    }
    assert len(handlers) == 1
    assert isinstance(handlers[0], _RejectRedirectHandler)

    request, timeout = opener.calls[0]
    assert request.full_url == SLACK_API_URL
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == (
        f"Bearer {SLACK_TOKEN}"
    )
    assert timeout == 29
    assert response.read_size == 65_537


@pytest.mark.parametrize(
    ("response", "expected_code", "retryable"),
    [
        (
            {"ok": False, "error": "ratelimited"},
            DeliveryFailureCode.TRANSPORT_UNAVAILABLE,
            True,
        ),
        (
            {"ok": False, "error": "invalid_auth"},
            DeliveryFailureCode.CONFIGURATION_INVALID,
            False,
        ),
        (
            {"ok": False, "error": "channel_not_found"},
            DeliveryFailureCode.PROVIDER_REJECTED,
            False,
        ),
        (
            {"ok": False, "error": PRIVATE_MARKER},
            DeliveryFailureCode.PROVIDER_RESPONSE_INVALID,
            False,
        ),
        (
            {"ok": True, "ts": PRIVATE_MARKER},
            DeliveryFailureCode.PROVIDER_RESPONSE_INVALID,
            True,
        ),
        (
            ["not", "a", "mapping"],
            DeliveryFailureCode.PROVIDER_RESPONSE_INVALID,
            True,
        ),
    ],
)
def test_slack_provider_responses_are_mapped_without_body_leakage(
    response,
    expected_code,
    retryable,
):
    adapter = build_delivery_adapter(
        "SLACK",
        environ=slack_environment(),
        slack_transport=FakeSlackTransport(response=response),
    )

    with pytest.raises(SafeDeliveryError) as captured:
        adapter.deliver(delivery_record("SLACK"))

    assert captured.value.code is expected_code
    assert captured.value.retryable is retryable
    assert PRIVATE_MARKER not in str(captured.value)
    assert PRIVATE_MARKER not in repr(captured.value)


@pytest.mark.parametrize(
    ("transport_error", "expected_code", "retryable"),
    [
        (
            TimeoutError("private timeout details"),
            DeliveryFailureCode.TRANSPORT_TIMEOUT,
            True,
        ),
        (
            HTTPError(
                "https://slack.example.invalid/private",
                401,
                "private response",
                None,
                None,
            ),
            DeliveryFailureCode.CONFIGURATION_INVALID,
            False,
        ),
        (
            HTTPError(
                "https://slack.example.invalid/private",
                429,
                "private response",
                None,
                None,
            ),
            DeliveryFailureCode.TRANSPORT_UNAVAILABLE,
            True,
        ),
        (
            OSError("private network details"),
            DeliveryFailureCode.TRANSPORT_UNAVAILABLE,
            True,
        ),
        (
            RuntimeError("private unexpected details"),
            DeliveryFailureCode.UNEXPECTED_FAILURE,
            True,
        ),
    ],
)
def test_slack_transport_failures_are_redacted(
    transport_error,
    expected_code,
    retryable,
):
    adapter = build_delivery_adapter(
        "SLACK",
        environ=slack_environment(),
        slack_transport=FakeSlackTransport(error=transport_error),
    )

    with pytest.raises(SafeDeliveryError) as captured:
        adapter.deliver(delivery_record("SLACK"))

    assert captured.value.code is expected_code
    assert captured.value.retryable is retryable
    assert "private" not in str(captured.value).lower()
    assert "private" not in repr(captured.value).lower()


def test_adapter_factory_supports_all_channels_without_network_io():
    limits = WorkerLimits(network_timeout_seconds=13)
    email_transport = FakeEmailTransport()
    slack_transport = FakeSlackTransport(
        response={"ok": True, "ts": "1760000000.000001"}
    )

    internal = build_delivery_adapter(
        "internal",
        environ={},
        limits=limits,
    )
    email = build_delivery_adapter(
        "email",
        environ=email_environment(),
        limits=limits,
        email_transport=email_transport,
    )
    slack = build_delivery_adapter(
        "slack",
        environ=slack_environment(),
        limits=limits,
        slack_transport=slack_transport,
    )

    assert internal.channel == "INTERNAL"
    assert email.channel == "EMAIL"
    assert slack.channel == "SLACK"
    assert email_transport.calls == []
    assert slack_transport.calls == []


def test_external_adapter_factory_fails_before_transport_without_config():
    email_transport = FakeEmailTransport()
    slack_transport = FakeSlackTransport()

    with pytest.raises(AlertContractError, match="CONFIG_EMAIL_INCOMPLETE"):
        build_delivery_adapter(
            "EMAIL",
            environ={},
            email_transport=email_transport,
        )

    with pytest.raises(AlertContractError, match="CONFIG_SLACK_INCOMPLETE"):
        build_delivery_adapter(
            "SLACK",
            environ={},
            slack_transport=slack_transport,
        )

    assert email_transport.calls == []
    assert slack_transport.calls == []


def test_invalid_channel_fails_without_echoing_rejected_value():
    rejected = "PRIVATE_WEBHOOK_DESTINATION"

    with pytest.raises(AlertContractError) as captured:
        build_delivery_adapter(rejected, environ={})

    assert captured.value.reason_code == "CONFIG_DELIVERY_CHANNEL_INVALID"
    assert rejected not in str(captured.value)
    assert rejected not in repr(captured.value)


def test_slack_redirects_are_explicitly_rejected():
    handler = _RejectRedirectHandler()

    assert handler.redirect_request(
        None,
        None,
        302,
        "private redirect response",
        {},
        "https://redirect.example.invalid/private",
    ) is None


def test_adapter_representations_exclude_configuration():
    email = build_delivery_adapter(
        "EMAIL",
        environ=email_environment(),
        email_transport=FakeEmailTransport(),
    )
    slack = build_delivery_adapter(
        "SLACK",
        environ=slack_environment(),
        slack_transport=FakeSlackTransport(),
    )

    representations = repr(email) + repr(slack)
    for private_value in (
        EMAIL_HOST,
        EMAIL_USERNAME,
        EMAIL_PASSWORD,
        EMAIL_SENDER,
        EMAIL_RECIPIENT,
        SLACK_TOKEN,
        SLACK_CHANNEL,
    ):
        assert private_value not in representations
