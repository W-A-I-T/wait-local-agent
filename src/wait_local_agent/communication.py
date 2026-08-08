"""Preview-only communication contracts for ticket and end-user messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

CommunicationChannel = Literal["ticket_note", "email", "teams", "slack", "sms"]
COMMUNICATION_CHANNELS = frozenset({"ticket_note", "email", "teams", "slack", "sms"})


@dataclass(frozen=True)
class MessageDraft:
    channel: CommunicationChannel
    recipient: str
    subject: str
    body: str
    approval_required: bool = True
    send_enabled: bool = False


class CommunicationClient(Protocol):
    def preview(self, draft: MessageDraft) -> MessageDraft:
        """Validate or enrich a draft without sending it."""


class DraftOnlyCommunicationClient:
    """Safe default adapter; it deliberately has no outbound transport."""

    def preview(self, draft: MessageDraft) -> MessageDraft:
        return draft


def build_message_draft(
    channel: str,
    *,
    recipient: str,
    subject: str = "",
    body: str,
) -> MessageDraft:
    normalized_channel = channel.strip().lower()
    if normalized_channel not in COMMUNICATION_CHANNELS:
        raise ValueError(f"unsupported communication channel: {channel}")
    normalized_recipient = recipient.strip()
    if not normalized_recipient:
        raise ValueError("communication recipient is required")
    normalized_subject = subject.strip()
    if len(normalized_subject) > 200:
        raise ValueError("communication subject must be at most 200 characters")
    normalized_body = body.strip()
    if not normalized_body:
        raise ValueError("communication body is required")
    if len(normalized_body) > 4000:
        raise ValueError("communication body must be at most 4000 characters")
    return MessageDraft(
        channel=normalized_channel,  # type: ignore[arg-type]
        recipient=normalized_recipient,
        subject=normalized_subject,
        body=normalized_body,
    )
