"""Preview-first outbound communication boundary.

The open core can prepare a message for a configured channel, but this module
does not send anything.  A future connector may implement the same provider
interface behind an explicit, approval-gated execution path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

CommunicationChannel = Literal["email", "teams", "slack", "sms"]


@dataclass(frozen=True)
class CommunicationMessage:
    channel: CommunicationChannel
    recipient: str
    body: str
    subject: str = ""
    client_id: str | None = None


@dataclass(frozen=True)
class CommunicationDraft:
    channel: CommunicationChannel
    recipient: str
    subject: str
    body: str
    adapter_id: str
    delivery_mode: Literal["preview"] = "preview"
    sendable: bool = False


class CommunicationProvider(Protocol):
    def draft(self, message: CommunicationMessage) -> CommunicationDraft:
        """Return a local preview without making a network request."""


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


class PreviewCommunicationProvider:
    """Route channel drafts to the corresponding side-effect-free adapter."""

    def __init__(self) -> None:
        self._adapters: dict[CommunicationChannel, PreviewCommunicationAdapter] = {
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


__all__ = [
    "CommunicationChannel",
    "CommunicationDraft",
    "CommunicationMessage",
    "CommunicationProvider",
    "EmailPreviewAdapter",
    "PreviewCommunicationAdapter",
    "PreviewCommunicationProvider",
    "SlackPreviewAdapter",
    "SmsPreviewAdapter",
    "TeamsPreviewAdapter",
]
