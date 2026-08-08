"""Bounded technician command parsing over the existing smart-action catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TICKET_ID_PATTERN = re.compile(r"\bTCK-[A-Za-z0-9][A-Za-z0-9_.:-]{0,62}\b", re.IGNORECASE)
_SAFE_TICKET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
_HELP_TEXT = (
    "Supported technician requests: summarize, triage, find similar tickets, "
    "show documentation, suggest a fix, check ticket quality, assess sentiment, "
    "assess escalation, or suggest dispatch. Include a TCK-* ticket ID."
)


@dataclass(frozen=True)
class TechnicianChatCommand:
    action_id: str | None
    payload: dict[str, object]
    reply: str


class TechnicianChatParseError(ValueError):
    """Raised when a technician request is outside the bounded command catalog."""


def parse_technician_message(message: str, *, ticket_id: str | None = None) -> TechnicianChatCommand:
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        raise TechnicianChatParseError("message must be a non-empty string of at most 2000 characters")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in message):
        raise TechnicianChatParseError("message contains unsupported control characters")
    normalized = " ".join(message.split()).strip()
    if normalized.casefold() in {"help", "?", "what can you do"}:
        return TechnicianChatCommand(None, {}, _HELP_TEXT)

    resolved_ticket_id = _resolve_ticket_id(normalized, ticket_id)
    if resolved_ticket_id is None:
        raise TechnicianChatParseError("include a ticket ID such as TCK-1001")
    payload: dict[str, object] = {"ticket_id": resolved_ticket_id}
    lowered = normalized.casefold()
    action_id, reply = _match_action(lowered)
    return TechnicianChatCommand(action_id, payload, reply)


def _resolve_ticket_id(message: str, ticket_id: str | None) -> str | None:
    candidate = ticket_id.strip() if isinstance(ticket_id, str) else ""
    if not candidate:
        match = _TICKET_ID_PATTERN.search(message)
        candidate = match.group(0) if match else ""
    if not candidate:
        return None
    if not _SAFE_TICKET_ID_PATTERN.fullmatch(candidate):
        raise TechnicianChatParseError("ticket_id contains unsupported characters")
    return candidate


def _match_action(message: str) -> tuple[str, str]:
    choices = (
        (
            ("similar", "related incident", "related ticket"),
            "find-similar-tickets",
            "Here are the closest related tickets.",
        ),
        (
            ("documentation", "runbook", "knowledge"),
            "knowledge-search",
            "I searched the permitted local documentation.",
        ),
        (
            ("resolution", "suggest a fix", "fix this", "solve"),
            "suggest-resolution",
            "I prepared a bounded resolution suggestion.",
        ),
        (("quality", "ticket qa", "ticket check"), "ticket-quality", "I checked the ticket quality fields."),
        (("sentiment", "customer tone"), "ticket-sentiment", "I assessed the customer-facing sentiment."),
        (("escalat", "sla"), "ticket-escalation", "I assessed the escalation urgency."),
        (("dispatch", "assign"), "dispatch-suggestion", "I prepared a technician dispatch suggestion."),
        (("triage", "classif"), "ticket-triage", "I classified the ticket with deterministic triage."),
        (("summar", "overview", "brief"), "ticket-summary", "I prepared a ticket summary."),
    )
    for terms, action_id, reply in choices:
        if any(term in message for term in terms):
            payload_reply = reply
            return action_id, payload_reply
    raise TechnicianChatParseError(_HELP_TEXT)


__all__ = ["TechnicianChatCommand", "TechnicianChatParseError", "parse_technician_message"]
