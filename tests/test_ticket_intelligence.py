from __future__ import annotations

from pathlib import Path

from wait_local_agent.providers import provider_from_settings
from wait_local_agent.services import TicketIntelligenceService, classify_ticket
from wait_local_agent.store import Store


def test_ticket_summary_includes_classification_sources_and_pending_approval(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    service = TicketIntelligenceService(store, settings, provider_from_settings(settings))

    summary = service.summarize("TCK-1001")

    assert summary.classification == "identity-access"
    assert summary.approval_status == "pending"
    assert summary.sources
    assert "approval-first" in summary.summary


def test_ticket_summary_prefers_matching_runbook(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    service = TicketIntelligenceService(store, settings, provider_from_settings(settings))

    summary = service.summarize("TCK-1002")

    assert summary.classification == "collaboration-change"
    assert summary.sources[0].title == "Shared Mailbox Runbook"
    assert "Shared Mailbox Runbook" in summary.summary


def test_approval_state_changes_are_audited(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))

    store.set_approval("TCK-1001", "approved")

    assert store.get_approval("TCK-1001") == "approved"
    event_types = [event.event_type for event in store.list_audit_events()]
    assert "approval.updated" in event_types


def test_general_service_desk_classification() -> None:
    assert classify_ticket("Question", "Need a quick status update") == "general-service-desk"


def test_endpoint_triage_classification() -> None:
    assert classify_ticket("Printer offline", "Queue is stuck") == "endpoint-triage"
