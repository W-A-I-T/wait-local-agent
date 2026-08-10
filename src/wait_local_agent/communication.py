"""Preview-first and approval-gated outbound communication boundary."""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from wait_local_agent.config import Settings

CommunicationChannel = Literal["ticket_note", "email", "teams", "slack", "sms"]


@dataclass(frozen=True)
class CommunicationMessage:
    channel: CommunicationChannel
    recipient: str
    body: str
    subject: str = ""
    client_id: str | None = None
    ticket_id: str | None = None


@dataclass(frozen=True)
class CommunicationDraft:
    channel: CommunicationChannel
    recipient: str
    subject: str
    body: str
    adapter_id: str
    delivery_mode: Literal["preview"] = "preview"
    sendable: bool = False


@dataclass(frozen=True)
class CommunicationDelivery:
    channel: CommunicationChannel
    recipient: str
    subject: str
    adapter_id: str
    delivery_mode: Literal["local", "sent"]
    sendable: bool
    message: str
    receipt_id: str = ""
    accepted_at: str = ""
    provider_status: str = "accepted"
    provider_status_code: int | None = None


class CommunicationProvider(Protocol):
    def draft(self, message: CommunicationMessage) -> CommunicationDraft:
        """Return a local preview without making a network request."""


class CommunicationSender(Protocol):
    def send(self, message: CommunicationMessage) -> CommunicationDelivery:
        """Deliver an already-approved message through a configured adapter."""


class PreviewCommunicationAdapter:
    """Deterministic channel adapter used by the local, read-first core."""

    def __init__(self, channel: CommunicationChannel) -> None:
        self.channel = channel
        self.adapter_id = f"preview-{channel}"

    def draft(self, message: CommunicationMessage) -> CommunicationDraft:
        if message.channel != self.channel:
            raise ValueError("message channel does not match adapter")
        return CommunicationDraft(
            channel=message.channel,
            recipient=message.recipient,
            subject=message.subject,
            body=message.body,
            adapter_id=self.adapter_id,
        )


class EmailPreviewAdapter(PreviewCommunicationAdapter):
    def __init__(self) -> None:
        super().__init__("email")


class TeamsPreviewAdapter(PreviewCommunicationAdapter):
    def __init__(self) -> None:
        super().__init__("teams")


class SlackPreviewAdapter(PreviewCommunicationAdapter):
    def __init__(self) -> None:
        super().__init__("slack")


class SmsPreviewAdapter(PreviewCommunicationAdapter):
    def __init__(self) -> None:
        super().__init__("sms")


class TicketNotePreviewAdapter(PreviewCommunicationAdapter):
    def __init__(self) -> None:
        super().__init__("ticket_note")


class PreviewCommunicationProvider:
    """Route channel drafts to the corresponding side-effect-free adapter."""

    def __init__(self) -> None:
        self._adapters: dict[CommunicationChannel, PreviewCommunicationAdapter] = {
            "ticket_note": TicketNotePreviewAdapter(),
            "email": EmailPreviewAdapter(),
            "teams": TeamsPreviewAdapter(),
            "slack": SlackPreviewAdapter(),
            "sms": SmsPreviewAdapter(),
        }

    def draft(self, message: CommunicationMessage) -> CommunicationDraft:
        try:
            adapter = self._adapters[message.channel]
        except KeyError as exc:
            raise ValueError("unsupported communication channel") from exc
        return adapter.draft(message)

    def send(self, message: CommunicationMessage) -> CommunicationDelivery:
        raise ValueError("communication delivery is not configured")


class CommunicationDeliveryError(Exception):
    """Safe, user-facing delivery failure without provider response bodies."""


class _WebhookAdapter:
    def __init__(
        self,
        channel: CommunicationChannel,
        endpoint: str,
        *,
        auth_token: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.channel = channel
        self.endpoint = endpoint
        self.auth_token = auth_token
        self.transport = transport

    def send(self, message: CommunicationMessage, settings: Settings) -> CommunicationDelivery:
        endpoint = _safe_http_url(self.endpoint)
        if self.channel in {"teams", "slack"}:
            payload = {"text": message.body}
            if message.subject:
                payload["text"] = f"{message.subject}\n\n{message.body}"
        else:
            payload = {
                "to": message.recipient,
                "body": message.body,
            }
        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        try:
            with httpx.Client(
                timeout=settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(endpoint, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise CommunicationDeliveryError(
                f"{self.channel} delivery failed before receiving a response"
            ) from exc
        except httpx.HTTPError as exc:
            raise CommunicationDeliveryError(f"{self.channel} delivery failed") from exc
        if response.status_code >= 400:
            raise CommunicationDeliveryError(
                f"{self.channel} delivery failed with HTTP {response.status_code}"
            )
        return CommunicationDelivery(
            channel=message.channel,
            recipient=message.recipient,
            subject=message.subject,
            adapter_id=f"webhook-{message.channel}",
            delivery_mode="sent",
            sendable=True,
            message=f"{message.channel} delivery accepted by configured endpoint",
            receipt_id=_local_receipt_id(f"webhook-{message.channel}"),
            accepted_at=_utc_timestamp(),
            provider_status="accepted",
            provider_status_code=response.status_code,
        )


class _EmailAdapter:
    def __init__(self, settings: Settings, *, smtp_factory: Callable[..., Any] | None = None) -> None:
        self.settings = settings
        self.smtp_factory = smtp_factory or smtplib.SMTP

    def send(self, message: CommunicationMessage) -> CommunicationDelivery:
        sender = self.settings.communication_email_from.strip()
        recipient = _safe_email_address(message.recipient)
        if not sender:
            raise CommunicationDeliveryError("email delivery requires WAIT_COMMUNICATION_EMAIL_FROM")
        if not self.settings.communication_email_host.strip():
            raise CommunicationDeliveryError("email delivery requires WAIT_COMMUNICATION_EMAIL_HOST")
        email = EmailMessage()
        email["From"] = sender
        email["To"] = recipient
        email["Subject"] = message.subject or "WAIT Local Agent notification"
        email.set_content(message.body)
        try:
            with self.smtp_factory(
                self.settings.communication_email_host,
                self.settings.communication_email_port,
                timeout=self.settings.connector_timeout_seconds,
            ) as smtp:
                if self.settings.communication_email_tls:
                    smtp.starttls()
                if self.settings.communication_email_username:
                    smtp.login(
                        self.settings.communication_email_username,
                        self.settings.communication_email_password,
                    )
                smtp.send_message(email)
        except CommunicationDeliveryError:
            raise
        except (OSError, smtplib.SMTPException) as exc:
            raise CommunicationDeliveryError("email delivery failed") from exc
        return CommunicationDelivery(
            channel=message.channel,
            recipient=recipient,
            subject=message.subject,
            adapter_id="smtp-email",
            delivery_mode="sent",
            sendable=True,
            message="email delivery accepted by configured SMTP server",
            receipt_id=_local_receipt_id("smtp-email"),
            accepted_at=_utc_timestamp(),
            provider_status="accepted_by_smtp",
        )


class ConfiguredCommunicationProvider(PreviewCommunicationProvider):
    """Keep previews local while enabling explicit, approval-completed delivery."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        smtp_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.transport = transport
        self.smtp_factory = smtp_factory

    def send(self, message: CommunicationMessage) -> CommunicationDelivery:
        if not self.settings.allow_write_actions:
            raise CommunicationDeliveryError(
                "communication delivery is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
            )
        if not self.settings.allow_http_probing:
            raise CommunicationDeliveryError(
                "communication delivery is blocked until WAIT_ALLOW_HTTP_PROBING=true"
            )
        if message.channel == "email":
            return _EmailAdapter(self.settings, smtp_factory=self.smtp_factory).send(message)
        endpoint, token, missing = self._webhook_config(message.channel)
        if missing:
            raise CommunicationDeliveryError(
                f"{message.channel} delivery is not configured; set {missing}"
            )
        return _WebhookAdapter(
            message.channel,
            endpoint,
            auth_token=token,
            transport=self.transport,
        ).send(message, self.settings)

    def _webhook_config(self, channel: CommunicationChannel) -> tuple[str, str, str]:
        if channel == "teams":
            endpoint = self.settings.communication_teams_webhook_url
            return (
                endpoint,
                "",
                "" if endpoint else "WAIT_COMMUNICATION_TEAMS_WEBHOOK_URL",
            )
        if channel == "slack":
            endpoint = self.settings.communication_slack_webhook_url
            return (
                endpoint,
                "",
                "" if endpoint else "WAIT_COMMUNICATION_SLACK_WEBHOOK_URL",
            )
        if channel == "sms":
            endpoint = self.settings.communication_sms_webhook_url
            return (
                endpoint,
                self.settings.communication_sms_auth_token,
                "" if endpoint else "WAIT_COMMUNICATION_SMS_WEBHOOK_URL",
            )
        raise CommunicationDeliveryError("ticket notes use the local ticket-note path")


def _safe_http_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CommunicationDeliveryError("communication endpoint must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CommunicationDeliveryError(
            "communication endpoint must not contain credentials or query data"
        )
    return value.strip()


def _safe_email_address(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise CommunicationDeliveryError("email recipient contains control characters")
    name, address = parseaddr(value.strip())
    if name or not address or "@" not in address or address.count("@") != 1:
        raise CommunicationDeliveryError("email recipient is invalid")
    return address


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _local_receipt_id(adapter_id: str) -> str:
    """Return an opaque local receipt; providers do not expose a shared ID contract."""
    return f"{adapter_id}:{uuid4().hex}"


__all__ = [
    "CommunicationChannel",
    "CommunicationDelivery",
    "CommunicationDeliveryError",
    "CommunicationDraft",
    "CommunicationMessage",
    "CommunicationProvider",
    "CommunicationSender",
    "ConfiguredCommunicationProvider",
    "EmailPreviewAdapter",
    "PreviewCommunicationAdapter",
    "PreviewCommunicationProvider",
    "SlackPreviewAdapter",
    "SmsPreviewAdapter",
    "TicketNotePreviewAdapter",
    "TeamsPreviewAdapter",
]
