from __future__ import annotations

from pathlib import Path

from wait_local_agent.models import SourceReference, Ticket
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store


def _seed_tickets(store: Store) -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))


class FakeProvider:
    def summarize_ticket(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return f"Summary for {ticket.id}"

    def draft_response(self, ticket: Ticket, sources: list[SourceReference]) -> str:
        return f"Resolution for {ticket.id}"


def test_registry_lists_all_seed_actions(settings) -> None:
    service = SmartActionService(Store(settings.data_path), settings)

    assert [manifest.action_id for manifest in service.list()] == [
        "dispatch-suggestion",
        "find-similar-tickets",
        "suggest-resolution",
        "ticket-summary",
        "ticket-triage",
    ]
    assert service.describe("ticket-triage").kind == "deterministic"


def test_deterministic_action_persists_run_and_audit(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    result = service.invoke("ticket-triage", {"ticket_id": "TCK-1001"}, "technician")

    assert result.status == "success"
    assert result.output["classification"] == "identity-access"
    assert result.run_id is not None
    run = store.get_smart_action_run(result.run_id)
    assert run is not None
    assert run.status == "success"
    event_types = [event.event_type for event in store.list_audit_events()]
    assert "smart_action.invoked" in event_types
    assert "smart_action.completed" in event_types


def test_ai_actions_report_missing_provider(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    result = service.invoke("ticket-summary", {"ticket_id": "TCK-1001"}, "technician")

    assert result.status == "provider_not_configured"
    assert result.error_detail
    assert result.run_id is not None
    assert store.get_smart_action_run(result.run_id).status == "provider_not_configured"  # type: ignore[union-attr]


def test_resolution_has_retrieval_citations_and_provider_label(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings, provider=FakeProvider(), provider_configured=True)

    result = service.invoke("suggest-resolution", {"ticket_id": "TCK-1002"}, "technician")

    assert result.status == "success"
    assert result.output["ai_assisted"] is True
    assert result.output["provider_id"] == "deterministic"
    citations = result.output["citations"]
    assert isinstance(citations, list)
    assert citations[0]["title"] == "Shared Mailbox Runbook"
    assert result.evidence == citations


def test_dispatch_requires_approval_and_completes_after_approval(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    service = SmartActionService(store, settings)

    pending = service.invoke(
        "dispatch-suggestion",
        {
            "ticket_id": "TCK-1001",
            "technicians": [{"id": "tech-b", "workload": 4}, {"id": "tech-a", "workload": 2}],
        },
        "technician",
        confirm=True,
    )

    assert pending.status == "pending_approval"
    assert pending.approval_id is not None
    assert pending.run_id is not None
    approval = store.update_approval_request(pending.approval_id, "approved", "reviewed")
    completed = service.complete_approval(approval.id or 0, approver="approver")

    assert completed is not None
    assert completed.status == "success"
    assert completed.output["approved"] is True
    assert isinstance(completed.output["recommendation"], dict)
    assert completed.output["recommendation"]["technician_id"] == "tech-a"
    assert store.get_smart_action_run(pending.run_id).status == "success"  # type: ignore[union-attr]
