"""Strict delivery adapters for Merchant project alerts.

The adapters accept only :class:`DeliveryPayload` fields, keep credentials
and destinations out of representations and errors, and convert transport
failures to stable reason codes. EMAIL and SLACK configuration is read only
from environment mappings; no secret or destination is accepted by the CLI.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from claude.workers.merchant_alert_contract import (
        AlertContractError,
        DELIVERY_CHANNELS,
        DeliveryFailureCode,
        DeliveryPayload,
        SafeDeliveryError,
        WorkerLimits,
    )
except ModuleNotFoundError:
    from workers.merchant_alert_contract import (  # type: ignore
        AlertContractError,
        DELIVERY_CHANNELS,
        DeliveryFailureCode,
        DeliveryPayload,
        SafeDeliveryError,
        WorkerLimits,
    )


SLACK_API_URL = "https://slack.com/api/chat.postMessage"
MAX_EMAIL_RECIPIENTS = 20
MAX_SLACK_RESPONSE_BYTES = 65_536
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9]"
    r"(?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
SLACK_TOKEN_PATTERN = re.compile(r"^xoxb-[A-Za-z0-9-]{15,250}$")
SLACK_CHANNEL_PATTERN = re.compile(r"^[CG][A-Z0-9]{8,20}$")
SLACK_MESSAGE_ID_PATTERN = re.compile(r"^[0-9]{10,}\.[0-9]{6}$")


class DeliveryAdapter(Protocol):
    """Channel adapter contract used by the one-shot worker."""

    channel: str

    def deliver(self, delivery: Mapping[str, Any]) -> str | None:
        """Deliver one claimed record and return a redacted provider id."""

    def safe_configuration(self) -> Mapping[str, Any]:
        """Return only non-sensitive operational configuration."""


class EmailTransport(Protocol):
    def send(
        self,
        configuration: "EmailConfiguration",
        message: EmailMessage,
        *,
        timeout_seconds: int,
    ) -> None:
        """Send one already-constructed message."""


class SlackTransport(Protocol):
    def post(
        self,
        configuration: "SlackConfiguration",
        request_payload: Mapping[str, Any],
        *,
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        """Post one already-constructed Slack request."""


@dataclass(frozen=True, repr=False)
class EmailConfiguration:
    smtp_host: str
    smtp_port: int
    security: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    sender: str = field(repr=False)
    recipients: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.smtp_host, str)
            or not HOST_PATTERN.fullmatch(self.smtp_host)
        ):
            raise AlertContractError("CONFIG_EMAIL_HOST_INVALID")
        if (
            isinstance(self.smtp_port, bool)
            or not isinstance(self.smtp_port, int)
            or self.smtp_port < 1
            or self.smtp_port > 65_535
        ):
            raise AlertContractError("CONFIG_EMAIL_PORT_INVALID")
        if (
            not isinstance(self.security, str)
            or self.security not in {"TLS", "STARTTLS"}
        ):
            raise AlertContractError("CONFIG_EMAIL_SECURITY_INVALID")
        _validated_secret_text(
            self.username,
            "CONFIG_EMAIL_USERNAME_INVALID",
            minimum=1,
            maximum=320,
        )
        _validated_secret_text(
            self.password,
            "CONFIG_EMAIL_PASSWORD_INVALID",
            minimum=8,
            maximum=1_024,
        )
        _validated_email(self.sender, "CONFIG_EMAIL_SENDER_INVALID")
        if (
            not isinstance(self.recipients, tuple)
            or not self.recipients
            or len(self.recipients) > MAX_EMAIL_RECIPIENTS
            or not all(
                isinstance(item, str) for item in self.recipients
            )
            or len({item.lower() for item in self.recipients})
            != len(self.recipients)
        ):
            raise AlertContractError("CONFIG_EMAIL_RECIPIENTS_INVALID")
        for recipient in self.recipients:
            _validated_email(
                recipient,
                "CONFIG_EMAIL_RECIPIENTS_INVALID",
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
    ) -> "EmailConfiguration":
        values = {
            name: _required_setting(environ, name, "CONFIG_EMAIL_INCOMPLETE")
            for name in (
                "MERCHANT_ALERT_EMAIL_SMTP_HOST",
                "MERCHANT_ALERT_EMAIL_SMTP_PORT",
                "MERCHANT_ALERT_EMAIL_SECURITY",
                "MERCHANT_ALERT_EMAIL_USERNAME",
                "MERCHANT_ALERT_EMAIL_PASSWORD",
                "MERCHANT_ALERT_EMAIL_SENDER",
                "MERCHANT_ALERT_EMAIL_RECIPIENTS",
            )
        }

        host = values["MERCHANT_ALERT_EMAIL_SMTP_HOST"]
        if not HOST_PATTERN.fullmatch(host):
            raise AlertContractError("CONFIG_EMAIL_HOST_INVALID")

        port_text = values["MERCHANT_ALERT_EMAIL_SMTP_PORT"]
        if not port_text.isascii() or not port_text.isdecimal():
            raise AlertContractError("CONFIG_EMAIL_PORT_INVALID")
        port = int(port_text, 10)
        if port < 1 or port > 65_535:
            raise AlertContractError("CONFIG_EMAIL_PORT_INVALID")

        security = values["MERCHANT_ALERT_EMAIL_SECURITY"].upper()
        if security not in {"TLS", "STARTTLS"}:
            raise AlertContractError("CONFIG_EMAIL_SECURITY_INVALID")

        username = _validated_secret_text(
            values["MERCHANT_ALERT_EMAIL_USERNAME"],
            "CONFIG_EMAIL_USERNAME_INVALID",
            minimum=1,
            maximum=320,
        )
        password = _validated_secret_text(
            values["MERCHANT_ALERT_EMAIL_PASSWORD"],
            "CONFIG_EMAIL_PASSWORD_INVALID",
            minimum=8,
            maximum=1_024,
        )
        sender = _validated_email(
            values["MERCHANT_ALERT_EMAIL_SENDER"],
            "CONFIG_EMAIL_SENDER_INVALID",
        )
        recipients = tuple(
            _validated_email(
                item,
                "CONFIG_EMAIL_RECIPIENTS_INVALID",
            )
            for item in values[
                "MERCHANT_ALERT_EMAIL_RECIPIENTS"
            ].split(",")
        )

        if (
            not recipients
            or len(recipients) > MAX_EMAIL_RECIPIENTS
            or len({item.lower() for item in recipients})
            != len(recipients)
        ):
            raise AlertContractError("CONFIG_EMAIL_RECIPIENTS_INVALID")

        return cls(
            smtp_host=host,
            smtp_port=port,
            security=security,
            username=username,
            password=password,
            sender=sender,
            recipients=recipients,
        )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "channel": "EMAIL",
            "configured": True,
            "security": self.security,
            "recipient_count": len(self.recipients),
        }

    def __repr__(self) -> str:
        return (
            "EmailConfiguration(channel='EMAIL', configured=True, "
            f"security={self.security!r}, "
            f"recipient_count={len(self.recipients)})"
        )


@dataclass(frozen=True, repr=False)
class SlackConfiguration:
    bot_token: str = field(repr=False)
    channel_id: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.bot_token, str)
            or not SLACK_TOKEN_PATTERN.fullmatch(self.bot_token)
        ):
            raise AlertContractError("CONFIG_SLACK_TOKEN_INVALID")
        if (
            not isinstance(self.channel_id, str)
            or not SLACK_CHANNEL_PATTERN.fullmatch(self.channel_id)
        ):
            raise AlertContractError("CONFIG_SLACK_CHANNEL_INVALID")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
    ) -> "SlackConfiguration":
        token = _required_setting(
            environ,
            "MERCHANT_ALERT_SLACK_BOT_TOKEN",
            "CONFIG_SLACK_INCOMPLETE",
        )
        channel_id = _required_setting(
            environ,
            "MERCHANT_ALERT_SLACK_CHANNEL_ID",
            "CONFIG_SLACK_INCOMPLETE",
        ).upper()

        if not SLACK_TOKEN_PATTERN.fullmatch(token):
            raise AlertContractError("CONFIG_SLACK_TOKEN_INVALID")
        if not SLACK_CHANNEL_PATTERN.fullmatch(channel_id):
            raise AlertContractError("CONFIG_SLACK_CHANNEL_INVALID")

        return cls(bot_token=token, channel_id=channel_id)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "channel": "SLACK",
            "configured": True,
        }

    def __repr__(self) -> str:
        return "SlackConfiguration(channel='SLACK', configured=True)"


class InternalDeliveryAdapter:
    """Emit one allowlisted payload as a UTF-8 JSON line."""

    channel = "INTERNAL"

    def safe_configuration(self) -> Mapping[str, Any]:
        return {"channel": self.channel, "configured": True}

    def deliver(self, delivery: Mapping[str, Any]) -> str:
        payload = DeliveryPayload.from_delivery_record(delivery)
        output = {
            "event": "merchant_project_alert",
            **payload.to_safe_dict(),
        }
        print(
            json.dumps(output, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        return f"internal:{payload.delivery_id}"


class SmtpTransport:
    """Authenticated SMTP transport with mandatory TLS."""

    def send(
        self,
        configuration: EmailConfiguration,
        message: EmailMessage,
        *,
        timeout_seconds: int,
    ) -> None:
        context = ssl.create_default_context()

        if configuration.security == "TLS":
            client_type = smtplib.SMTP_SSL
            client_arguments = {"context": context}
        else:
            client_type = smtplib.SMTP
            client_arguments = {}

        with client_type(
            configuration.smtp_host,
            configuration.smtp_port,
            timeout=timeout_seconds,
            **client_arguments,
        ) as client:
            if configuration.security == "STARTTLS":
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()

            client.login(
                configuration.username,
                configuration.password,
            )
            refused = client.send_message(message)

            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)


@dataclass(repr=False)
class EmailDeliveryAdapter:
    configuration: EmailConfiguration = field(repr=False)
    timeout_seconds: int
    transport: EmailTransport = field(repr=False)
    channel: str = field(default="EMAIL", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.configuration, EmailConfiguration):
            raise AlertContractError("CONFIG_EMAIL_INVALID")
        _validated_timeout(self.timeout_seconds)
        if not callable(getattr(self.transport, "send", None)):
            raise AlertContractError("CONFIG_EMAIL_TRANSPORT_INVALID")

    def __repr__(self) -> str:
        return (
            "EmailDeliveryAdapter(channel='EMAIL', configured=True, "
            f"timeout_seconds={self.timeout_seconds})"
        )

    def safe_configuration(self) -> Mapping[str, Any]:
        return {
            **self.configuration.to_safe_dict(),
            "timeout_seconds": self.timeout_seconds,
        }

    def deliver(self, delivery: Mapping[str, Any]) -> str:
        payload = DeliveryPayload.from_delivery_record(delivery)
        message = self._message(payload)

        try:
            self.transport.send(
                self.configuration,
                message,
                timeout_seconds=self.timeout_seconds,
            )
        except (TimeoutError, socket.timeout) as exc:
            raise _safe_error(
                DeliveryFailureCode.TRANSPORT_TIMEOUT,
                retryable=True,
            ) from exc
        except (
            smtplib.SMTPAuthenticationError,
            smtplib.SMTPNotSupportedError,
        ) as exc:
            raise _safe_error(
                DeliveryFailureCode.CONFIGURATION_INVALID,
                retryable=False,
            ) from exc
        except (
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
        ) as exc:
            raise _safe_error(
                DeliveryFailureCode.PROVIDER_REJECTED,
                retryable=False,
            ) from exc
        except smtplib.SMTPDataError as exc:
            retryable = 400 <= exc.smtp_code < 500
            raise _safe_error(
                (
                    DeliveryFailureCode.TRANSPORT_UNAVAILABLE
                    if retryable
                    else DeliveryFailureCode.PROVIDER_REJECTED
                ),
                retryable=retryable,
            ) from exc
        except (
            smtplib.SMTPConnectError,
            smtplib.SMTPHeloError,
            smtplib.SMTPServerDisconnected,
            OSError,
        ) as exc:
            raise _safe_error(
                DeliveryFailureCode.TRANSPORT_UNAVAILABLE,
                retryable=True,
            ) from exc
        except Exception as exc:
            raise _safe_error(
                DeliveryFailureCode.UNEXPECTED_FAILURE,
                retryable=True,
            ) from exc

        return f"email:{payload.delivery_id}"

    def _message(self, payload: DeliveryPayload) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.configuration.sender
        message["To"] = ", ".join(self.configuration.recipients)
        message["Subject"] = (
            f"Merchant alert {payload.alert_type} "
            f"[{payload.delivery_id}]"
        )
        sender_domain = self.configuration.sender.rsplit("@", 1)[1]
        message["Message-ID"] = (
            f"<merchant-alert-{payload.delivery_id}@{sender_domain}>"
        )
        message["X-Merchant-Delivery-ID"] = payload.delivery_id
        message["X-Merchant-Deduplication-Key"] = (
            payload.deduplication_key
        )
        message.set_content(
            json.dumps(
                {
                    "event": "merchant_project_alert",
                    **payload.to_safe_dict(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            subtype="plain",
            charset="utf-8",
        )
        return message


class SlackApiTransport:
    """Bounded Slack Web API transport for ``chat.postMessage``."""

    def post(
        self,
        configuration: SlackConfiguration,
        request_payload: Mapping[str, Any],
        *,
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        encoded = json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        request = Request(
            SLACK_API_URL,
            data=encoded,
            headers={
                "Authorization": f"Bearer {configuration.bot_token}",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "merchant-alert-worker/1",
            },
            method="POST",
        )

        opener = build_opener(_RejectRedirectHandler())

        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_SLACK_RESPONSE_BYTES + 1)

        if len(body) > MAX_SLACK_RESPONSE_BYTES:
            raise ValueError("SLACK_RESPONSE_TOO_LARGE")

        decoded = json.loads(body.decode("utf-8"))

        if not isinstance(decoded, dict):
            raise ValueError("SLACK_RESPONSE_INVALID")

        return decoded


@dataclass(repr=False)
class SlackDeliveryAdapter:
    configuration: SlackConfiguration = field(repr=False)
    timeout_seconds: int
    transport: SlackTransport = field(repr=False)
    channel: str = field(default="SLACK", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.configuration, SlackConfiguration):
            raise AlertContractError("CONFIG_SLACK_INVALID")
        _validated_timeout(self.timeout_seconds)
        if not callable(getattr(self.transport, "post", None)):
            raise AlertContractError("CONFIG_SLACK_TRANSPORT_INVALID")

    def __repr__(self) -> str:
        return (
            "SlackDeliveryAdapter(channel='SLACK', configured=True, "
            f"timeout_seconds={self.timeout_seconds})"
        )

    def safe_configuration(self) -> Mapping[str, Any]:
        return {
            **self.configuration.to_safe_dict(),
            "timeout_seconds": self.timeout_seconds,
        }

    def deliver(self, delivery: Mapping[str, Any]) -> str:
        payload = DeliveryPayload.from_delivery_record(delivery)
        safe_payload = {
            "event": "merchant_project_alert",
            **payload.to_safe_dict(),
        }
        request_payload = {
            "channel": self.configuration.channel_id,
            "client_msg_id": payload.delivery_id,
            "text": json.dumps(
                safe_payload,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "metadata": {
                "event_type": "merchant_project_alert",
                "event_payload": {
                    "delivery_id": payload.delivery_id,
                    "deduplication_key": payload.deduplication_key,
                },
            },
        }

        try:
            response = self.transport.post(
                self.configuration,
                request_payload,
                timeout_seconds=self.timeout_seconds,
            )
        except (TimeoutError, socket.timeout) as exc:
            raise _safe_error(
                DeliveryFailureCode.TRANSPORT_TIMEOUT,
                retryable=True,
            ) from exc
        except HTTPError as exc:
            if exc.code in {401, 403}:
                code = DeliveryFailureCode.CONFIGURATION_INVALID
                retryable = False
            elif exc.code == 429 or exc.code >= 500:
                code = DeliveryFailureCode.TRANSPORT_UNAVAILABLE
                retryable = True
            else:
                code = DeliveryFailureCode.PROVIDER_REJECTED
                retryable = False
            raise _safe_error(code, retryable=retryable) from exc
        except (URLError, ConnectionError, OSError) as exc:
            raise _safe_error(
                DeliveryFailureCode.TRANSPORT_UNAVAILABLE,
                retryable=True,
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise _safe_error(
                DeliveryFailureCode.PROVIDER_RESPONSE_INVALID,
                retryable=True,
            ) from exc
        except Exception as exc:
            raise _safe_error(
                DeliveryFailureCode.UNEXPECTED_FAILURE,
                retryable=True,
            ) from exc

        if not isinstance(response, Mapping):
            raise _safe_error(
                DeliveryFailureCode.PROVIDER_RESPONSE_INVALID,
                retryable=True,
            )

        if response.get("ok") is not True:
            code, retryable = _slack_rejection_policy(
                response.get("error")
            )
            raise _safe_error(code, retryable=retryable)

        message_id = response.get("ts")
        if (
            not isinstance(message_id, str)
            or not SLACK_MESSAGE_ID_PATTERN.fullmatch(message_id)
        ):
            raise _safe_error(
                DeliveryFailureCode.PROVIDER_RESPONSE_INVALID,
                retryable=True,
            )

        return f"slack:{message_id}"


def build_delivery_adapter(
    delivery_channel: str,
    *,
    environ: Mapping[str, str] | None = None,
    limits: WorkerLimits | None = None,
    email_transport: EmailTransport | None = None,
    slack_transport: SlackTransport | None = None,
) -> DeliveryAdapter:
    """Build one adapter, validating all settings before network I/O."""
    source = os.environ if environ is None else environ
    worker_limits = limits or WorkerLimits.from_env(source)
    normalized_channel = str(delivery_channel).strip().upper()

    if normalized_channel not in DELIVERY_CHANNELS:
        raise AlertContractError("CONFIG_DELIVERY_CHANNEL_INVALID")

    if normalized_channel == "INTERNAL":
        return InternalDeliveryAdapter()
    if normalized_channel == "EMAIL":
        return EmailDeliveryAdapter(
            configuration=EmailConfiguration.from_env(source),
            timeout_seconds=worker_limits.network_timeout_seconds,
            transport=email_transport or SmtpTransport(),
        )

    return SlackDeliveryAdapter(
        configuration=SlackConfiguration.from_env(source),
        timeout_seconds=worker_limits.network_timeout_seconds,
        transport=slack_transport or SlackApiTransport(),
    )


class _RejectRedirectHandler(HTTPRedirectHandler):
    """Prevent bearer credentials from following provider redirects."""

    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


def _required_setting(
    environ: Mapping[str, str],
    variable: str,
    reason_code: str,
) -> str:
    value = environ.get(variable)
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
    ):
        raise AlertContractError(reason_code)
    return value


def _validated_secret_text(
    value: str,
    reason_code: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    if (
        not isinstance(value, str)
        or len(value) < minimum
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise AlertContractError(reason_code)
    return value


def _validated_email(value: str, reason_code: str) -> str:
    if not isinstance(value, str):
        raise AlertContractError(reason_code)
    normalized = value.strip()
    if len(normalized) > 320 or not EMAIL_PATTERN.fullmatch(normalized):
        raise AlertContractError(reason_code)
    return normalized


def _validated_timeout(value: Any) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > 60
    ):
        raise AlertContractError("CONFIG_NETWORK_TIMEOUT_INVALID")


def _safe_error(
    code: DeliveryFailureCode,
    *,
    retryable: bool,
) -> SafeDeliveryError:
    return SafeDeliveryError(code, retryable=retryable)


def _slack_rejection_policy(
    provider_code: Any,
) -> tuple[DeliveryFailureCode, bool]:
    normalized = provider_code if isinstance(provider_code, str) else ""

    if normalized in {
        "ratelimited",
        "internal_error",
        "service_unavailable",
        "request_timeout",
    }:
        return DeliveryFailureCode.TRANSPORT_UNAVAILABLE, True
    if normalized in {
        "invalid_auth",
        "not_authed",
        "account_inactive",
        "token_revoked",
        "missing_scope",
    }:
        return DeliveryFailureCode.CONFIGURATION_INVALID, False
    if normalized in {
        "channel_not_found",
        "not_in_channel",
        "is_archived",
        "msg_too_long",
    }:
        return DeliveryFailureCode.PROVIDER_REJECTED, False
    return DeliveryFailureCode.PROVIDER_RESPONSE_INVALID, False
