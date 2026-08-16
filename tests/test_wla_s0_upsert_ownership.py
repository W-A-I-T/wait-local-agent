from __future__ import annotations

from pathlib import Path

from tests.support import ensure_test_clients
from wait_local_agent.client_scope import AllClients
from wait_local_agent.models import Ticket
from wait_local_agent.store import Store


def _active_instance(store: Store) -> str:
    instance = store.create_connector_instance("halopsa", "Shared Halo")
    active = store.update_connector_instance(instance.connector_instance_id, status="active")
    assert active is not None
    return active.connector_instance_id


def _verified_mapping(store: Store, instance_id: str, external_company_id: str, client_id: str) -> None:
    mapping = store.create_client_connector_mapping(
        AllClients(), instance_id, external_company_id, client_id
    )
    store.verify_client_connector_mapping(AllClients(), mapping.mapping_id)


def _provider_ticket(
    instance_id: str,
    external_company_id: str,
    *,
    subject: str,
    body: str,
    status: str,
    external_id: str = "remote-ticket",
) -> Ticket:
    return Ticket(
        id="provider-input-id-is-ignored",
        client="Provider customer",
        subject=subject,
        body=body,
        priority="Low",
        status=status,
        source_system="halopsa",
        connector_instance_id=instance_id,
        external_id=external_id,
        external_client_id=external_company_id,
    )


def test_provider_upsert_blocks_cross_owner_contamination(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    ensure_test_clients(store, "client-a", "client-b")
    instance_id = _active_instance(store)
    _verified_mapping(store, instance_id, "company-a", "client-a")
    _verified_mapping(store, instance_id, "company-b", "client-b")

    first = _provider_ticket(
        instance_id,
        "company-a",
        subject="A subject",
        body="A body",
        status="Open",
    )
    first_summary = store.ingest_provider_tickets([first], connector_instance_id=instance_id)

    persisted_before = store.list_tickets("client-a")[0]
    history_before = store.list_ticket_status_history(persisted_before.id)
    audit_before = store.list_audit_events()

    conflict = _provider_ticket(
        instance_id,
        "company-b",
        subject="B subject",
        body="B body",
        status="Closed",
    )
    summary = store.ingest_provider_tickets([conflict], connector_instance_id=instance_id)

    assert summary.written == 0
    assert summary.quarantined == 1
    assert first_summary.written == 1
    assert first_summary.quarantined == 0
    persisted_after = store.list_tickets("client-a")[0]
    assert persisted_after == persisted_before
    assert persisted_after.id == persisted_before.id
    assert persisted_after.client_id == "client-a"
    assert persisted_after.subject == "A subject"
    assert persisted_after.body == "A body"
    assert persisted_after.status == "Open"
    assert persisted_after.external_client_id == "company-a"
    assert store.list_tickets("client-b") == []
    assert store.list_ticket_status_history(persisted_before.id, client_id="client-b") == []
    assert store.list_ticket_status_history(persisted_before.id) == history_before
    assert [event for event in store.list_audit_events("client-b") if event.event_type == "ticket.ingested"] == []
    assert [event for event in store.list_audit_events() if event.event_type == "ticket.ingested"] == audit_before

    unmapped = store.list_unmapped_records(AllClients(), connector_instance_id=instance_id)
    assert len(unmapped) == 1
    assert unmapped[0].reason == "ownership_conflict"
    assert unmapped[0].external_company_id == "company-b"
    assert unmapped[0].external_id == "remote-ticket"


def test_provider_upsert_same_owner_updates_content_idempotently(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    ensure_test_clients(store, "client-a")
    instance_id = _active_instance(store)
    _verified_mapping(store, instance_id, "company-a", "client-a")

    first = _provider_ticket(
        instance_id,
        "company-a",
        subject="Before",
        body="Before body",
        status="Open",
    )
    first_summary = store.ingest_provider_tickets([first], connector_instance_id=instance_id)
    persisted_before = store.list_tickets("client-a")[0]

    second = _provider_ticket(
        instance_id,
        "company-a",
        subject="After",
        body="After body",
        status="Closed",
    )
    second_summary = store.ingest_provider_tickets([second], connector_instance_id=instance_id)

    assert first_summary.written == 1
    assert second_summary.written == 1
    persisted_after = store.list_tickets("client-a")[0]
    assert len(store.list_tickets(AllClients())) == 1
    assert persisted_after.id == persisted_before.id
    assert persisted_after.client_id == "client-a"
    assert persisted_after.subject == "After"
    assert persisted_after.body == "After body"
    assert persisted_after.status == "Closed"
    assert persisted_after.external_client_id == "company-a"


def test_provider_upsert_new_row_uses_resolved_client(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    ensure_test_clients(store, "client-a")
    instance_id = _active_instance(store)
    _verified_mapping(store, instance_id, "company-a", "client-a")

    summary = store.ingest_provider_tickets(
        [
            _provider_ticket(
                instance_id,
                "company-a",
                subject="New ticket",
                body="New body",
                status="Open",
                external_id="new-remote-ticket",
            )
        ],
        connector_instance_id=instance_id,
    )

    assert summary.written == 1
    assert summary.quarantined == 0
    tickets = store.list_tickets("client-a")
    assert len(tickets) == 1
    assert tickets[0].client_id == "client-a"
    assert tickets[0].external_id == "new-remote-ticket"
    assert tickets[0].external_client_id == "company-a"
