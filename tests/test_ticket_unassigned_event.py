from __future__ import annotations

from pathlib import Path

from tests.support import ingest_local
from wait_local_agent.agents import AgentService, SUPPORTED_EVENT_TYPES
from wait_local_agent.event_dispatch import EventDispatcher
from wait_local_agent.msp_playbooks import create_msp_playbook_subscription
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store


def _seed_client_ticket(store: Store) -> None:
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ?", ("acme",))


def test_ticket_unassigned_event_is_supported_and_dispatchable(settings) -> None:
    assert "ticket.unassigned" in SUPPORTED_EVENT_TYPES

    store = Store(settings.data_path)
    _seed_client_ticket(store)
    service = AgentService(store, settings, SmartActionService(store, settings))

    result = EventDispatcher(store, service).dispatch(
        event_type="ticket.unassigned",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={},
        idempotency_key="ticket-unassigned-regression",
        client_id="acme",
    )

    assert result.delivery.status == "completed"
    assert result.matched_agent_ids == []
    assert result.matched_playbook_ids == []


def test_dispatch_review_can_subscribe_to_ticket_unassigned(settings) -> None:
    store = Store(settings.data_path)
    _seed_client_ticket(store)

    subscription = create_msp_playbook_subscription(
        store,
        "dispatch-review",
        event_type="ticket.unassigned",
        client_id="acme",
    )

    assert subscription.event_type == "ticket.unassigned"
    assert subscription.playbook_id == "dispatch-review"
    assert subscription.client_id == "acme"
