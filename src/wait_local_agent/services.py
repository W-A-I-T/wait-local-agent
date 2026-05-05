from __future__ import annotations

from wait_local_agent.config import Settings
from wait_local_agent.models import TicketSummary
from wait_local_agent.providers import ModelProvider
from wait_local_agent.retrieval import retrieve_sources
from wait_local_agent.store import Store


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
        ticket = self.store.get_ticket(ticket_id)
        if ticket is None:
            raise KeyError(ticket_id)
        sources = retrieve_sources(ticket, self.settings.allowed_doc_root)
        summary = TicketSummary(
            ticket_id=ticket.id,
            classification=classify_ticket(ticket.subject, ticket.body),
            summary=self.provider.summarize_ticket(ticket, sources),
            suggested_response=self.provider.draft_response(ticket, sources),
            sources=sources,
            approval_status=self.store.get_approval(ticket.id),  # type: ignore[arg-type]
        )
        self.store.add_audit_event("ticket.summarized", ticket.id, summary.classification)
        return summary

