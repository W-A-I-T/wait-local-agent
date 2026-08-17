from __future__ import annotations

import logging

from wait_local_agent.config import Settings
from wait_local_agent.models import TicketSummary
from wait_local_agent.providers import ModelProvider
from wait_local_agent.retrieval import retrieve_sources
from wait_local_agent.store import _QUARANTINE_CLIENT_ID, Store

LOGGER = logging.getLogger(__name__)


def classify_ticket(subject: str, body: str) -> str:
    text = f"{subject} {body}".lower()
    if "mfa" in text or "password" in text or "sign-in" in text:
        return "identity-access"
    if "mailbox" in text or "distribution" in text:
        return "collaboration-change"
    if "disk" in text or "printer" in text:
        return "endpoint-triage"
    return "general-service-desk"


class TicketIntelligenceService:
    def __init__(self, store: Store, settings: Settings, provider: ModelProvider) -> None:
        self.store = store
        self.settings = settings
        self.provider = provider

    def summarize(self, ticket_id: str) -> TicketSummary:
        ticket = self.store.get_ticket(ticket_id, include_quarantine=True)
        if ticket is None:
            raise KeyError(ticket_id)
        if ticket.client_id == _QUARANTINE_CLIENT_ID:
            LOGGER.warning("Skipping ticket intelligence for quarantined ticket %s", ticket_id)
            return TicketSummary(
                ticket_id=ticket.id,
                classification="",
                summary="",
                suggested_response="",
                sources=[],
            )
        sources = retrieve_sources(
            ticket,
            self.settings.allowed_doc_root,
            self.store,
            self.settings,
            client_id=ticket.client_id,
        )
        summary = TicketSummary(
            ticket_id=ticket.id,
            classification=classify_ticket(ticket.subject, ticket.body),
            summary=self.provider.summarize_ticket(ticket, sources),
            suggested_response=self.provider.draft_response(ticket, sources),
            sources=sources,
            approval_status=self.store.get_approval(ticket.id),  # type: ignore[arg-type]
            approval_comment=self.store.get_approval_comment(ticket.id),
        )
        self.store.add_audit_event("ticket.summarized", ticket.id, summary.classification)
        return summary
