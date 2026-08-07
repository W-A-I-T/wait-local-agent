from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from wait_local_agent.agents import AgentService
from wait_local_agent.event_dispatch import EventDispatcher, EventDispatchError, _json_list
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store


def _seed(store: Store, *, client_id: str | None = "acme") -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    if client_id is not None:
        with store._connect() as connection:  # noqa: SLF001
            connection.execute("update tickets set client_id = ?", (client_id,))


def _event_agent(settings, store: Store, *, client_id: str | None = "acme"):
    service = AgentService(store, settings, SmartActionService(store, settings))
    definition = service.create(
        name="P1 event triage",
        description="Triage a newly created P1 ticket.",
        enabled=True,
        trigger="event",
        entity_type="ticket",
        filters={"event_type": "ticket.created", "priority": "P1"},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id=client_id,
    )
    return service, definition


def test_event_dispatch_matches_filters_redacts_and_is_idempotent(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)
    dispatcher = EventDispatcher(store, service)

    first = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1", "api_token": "do-not-store"},
        idempotency_key="provider-event-1",
        client_id="acme",
    )

    assert first.duplicate is False
    assert first.delivery.status == "completed"
    assert first.matched_agent_ids == [definition.id]
    assert len(first.run_ids) == 1
    assert len(store.list_agent_runs(client_id="acme")) == 1
    assert "do-not-store" not in first.delivery.payload_json
    saved_run = store.get_agent_run(first.run_ids[0])
    assert saved_run is not None
    assert "do-not-store" not in saved_run.state_json

    duplicate = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1", "api_token": "changed"},
        idempotency_key="provider-event-1",
        client_id="acme",
    )
    assert duplicate.duplicate is True
    assert duplicate.run_ids == first.run_ids
    assert len(store.list_agent_runs(client_id="acme")) == 1

    with pytest.raises(EventDispatchError, match="different event"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1002",
            payload={"priority": "P1"},
            idempotency_key="provider-event-1",
            client_id="acme",
        )

    second_key = dispatcher.dispatch(
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="provider-event-2",
        client_id="acme",
    )
    assert second_key.matched_agent_ids == [definition.id]
    assert second_key.run_ids == []
    assert len(store.list_agent_runs(client_id="acme")) == 1


def test_event_dispatch_rejects_unsupported_events_and_cross_tenant_entities(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, _ = _event_agent(settings, store)
    dispatcher = EventDispatcher(store, service)

    with pytest.raises(EventDispatchError, match="unsupported"):
        dispatcher.dispatch(
            event_type="ticket.deleted",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload={},
            idempotency_key="bad-event",
            client_id="acme",
        )
    with pytest.raises(EventDispatchError, match="only ticket"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="user",
            entity_id="TCK-1001",
            payload={},
            idempotency_key="bad-entity-type",
            client_id="acme",
        )
    with pytest.raises(EventDispatchError, match="entity_id"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id=" ",
            payload={},
            idempotency_key="bad-entity-id",
            client_id="acme",
        )
    with pytest.raises(EventDispatchError, match="event payload"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload=[],  # type: ignore[arg-type]
            idempotency_key="bad-payload",
            client_id="acme",
        )
    with pytest.raises(EventDispatchError, match="idempotency_key"):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload={},
            idempotency_key=" ",
            client_id="acme",
        )
    assert _json_list("not-json") == []
    assert _json_list("{}") == []
    with pytest.raises(LookupError):
        dispatcher.dispatch(
            event_type="ticket.created",
            entity_type="ticket",
            entity_id="TCK-1001",
            payload={"priority": "P1"},
            idempotency_key="wrong-tenant",
            client_id="beta",
        )


def test_event_dispatch_skips_disabled_nonmatching_and_wrong_scope_agents(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)
    store.create_agent_definition(replace(definition, id="disabled-agent", enabled=False))
    store.create_agent_definition(
        replace(definition, id="manual-agent", trigger="manual", filters={})
    )
    store.create_agent_definition(
        replace(definition, id="other-entity-agent", entity_type="user")
    )
    store.create_agent_definition(replace(definition, id="beta-agent", client_id="beta"))
    store.create_agent_definition(
        replace(
            definition,
            id="priority-mismatch-agent",
            filters={"event_type": "ticket.updated", "priority": "P2"},
        )
    )
    global_agent = store.create_agent_definition(
        replace(
            definition,
            id="global-agent",
            client_id=None,
            filters={"event_type": "ticket.updated"},
        )
    )

    result = EventDispatcher(store, service).dispatch(
        event_type="ticket.updated",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="branch-coverage-event",
        client_id="acme",
    )

    assert result.matched_agent_ids == [global_agent.id]
    assert len(result.run_ids) == 1

    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = null where id = ?", ("TCK-1002",))
    unscoped = EventDispatcher(store, service).dispatch(
        event_type="ticket.updated",
        entity_type="ticket",
        entity_id="TCK-1002",
        payload={"priority": "P1"},
        idempotency_key="branch-coverage-unscoped-event",
    )
    assert unscoped.matched_agent_ids == [global_agent.id]
    assert len(unscoped.run_ids) == 1


def test_event_dispatch_failure_is_recorded_without_blocking_other_agents(settings) -> None:
    store = Store(settings.data_path)
    _seed(store)
    service, definition = _event_agent(settings, store)

    class FailingAgentService:
        def run(self, *args, **kwargs):
            raise RuntimeError("provider secret=should-redact")

    result = EventDispatcher(store, FailingAgentService()).dispatch(  # type: ignore[arg-type]
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1"},
        idempotency_key="disabled-event",
        client_id="acme",
    )
    assert result.delivery.status == "failed"
    assert result.matched_agent_ids == [definition.id]
    assert result.run_ids == []
    assert "should-redact" not in result.delivery.error_detail
