from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support import ingest_local
from wait_local_agent.client_scope import AllClients
from wait_local_agent.models import Ticket
from wait_local_agent.store import Store


def _ticket(
    ticket_id: str,
    *,
    client_id: str | None = None,
    connector_instance_id: str | None = None,
    external_id: str | None = None,
    external_client_id: str | None = None,
) -> Ticket:
    return Ticket(
        id=ticket_id,
        client="Acme",
        subject="Imported ticket",
        body="Ticket body",
        priority="Low",
        status="Open",
        client_id=client_id,
        source_system="halopsa" if connector_instance_id else None,
        connector_instance_id=connector_instance_id,
        external_id=external_id,
        external_client_id=external_client_id,
    )


def _verified_mapping(store: Store) -> tuple[str, str]:
    store.create_client("client-a", "Acme")
    instance = store.create_connector_instance("halopsa", "Primary Halo")
    store.update_connector_instance(instance.connector_instance_id, status="active")
    mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-a", "client-a"
    )
    store.verify_client_connector_mapping(AllClients(), mapping.mapping_id)
    return instance.connector_instance_id, mapping.external_company_id


def test_ingest_tickets_resolves_verified_mapping_and_method_instance(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    connector_instance_id, external_company_id = _verified_mapping(store)
    ticket = _ticket(
        "TCK-RESOLVED",
        connector_instance_id=connector_instance_id,
        external_id="remote-resolved",
        external_client_id=external_company_id,
    )

    summary = store.ingest_provider_tickets([ticket], connector_instance_id=connector_instance_id)

    assert summary.written == 1
    assert summary.quarantined == 0
    written = next(iter(store.list_tickets("client-a")), None)
    assert written is not None
    assert written.client_id == "client-a"
    assert written.connector_instance_id == connector_instance_id
    assert written.external_client_id == external_company_id
    assert store.list_unmapped_records(AllClients()) == []


def test_ingest_tickets_quarantines_unmapped_ticket_once(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    instance = store.create_connector_instance("halopsa", "Primary Halo")
    ticket = _ticket(
        "TCK-UNMAPPED",
        connector_instance_id=instance.connector_instance_id,
        external_id="remote-unmapped",
        external_client_id="company-unmapped",
    )

    store.update_connector_instance(instance.connector_instance_id, status="active")
    first = store.ingest_provider_tickets([ticket], connector_instance_id=instance.connector_instance_id)
    second = store.ingest_provider_tickets([ticket], connector_instance_id=instance.connector_instance_id)

    assert first.written == 0
    assert first.quarantined == 1
    assert second.written == 0
    assert second.quarantined == 1
    assert store.get_ticket(ticket.id) is None
    records = store.list_unmapped_records(AllClients())
    assert len(records) == 1
    assert records[0].connector_instance_id == instance.connector_instance_id
    assert records[0].external_id == "remote-unmapped"
    assert records[0].reason == "no_verified_mapping"
    assert records[0].occurrence_count == 2
    assert records[0].last_seen_at is not None


def test_provider_identity_is_instance_scoped_and_input_id_is_ignored(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    first = store.create_connector_instance("halopsa", "Acme")
    second = store.create_connector_instance("halopsa", "Beta")
    store.update_connector_instance(first.connector_instance_id, status="active")
    store.update_connector_instance(second.connector_instance_id, status="active")
    for instance, client_id in ((first, "client-a"), (second, "client-b")):
        mapping = store.create_client_connector_mapping(
            AllClients(), instance.connector_instance_id, "company-shared", client_id
        )
        store.verify_client_connector_mapping(AllClients(), mapping.mapping_id)

    records = [
        _ticket(
            "caller-id-one",
            connector_instance_id=first.connector_instance_id,
            external_id=" remote-shared ",
            external_client_id="company-shared",
        ),
        _ticket(
            "caller-id-two",
            connector_instance_id=second.connector_instance_id,
            external_id="remote-shared",
            external_client_id="company-shared",
        ),
    ]
    summary = store.ingest_provider_tickets([records[0]], connector_instance_id=first.connector_instance_id)
    assert summary == type(summary)(written=1, quarantined=0)
    summary = store.ingest_provider_tickets([records[1]], connector_instance_id=second.connector_instance_id)
    assert summary == type(summary)(written=1, quarantined=0)
    tickets = store.list_tickets(AllClients())
    assert len(tickets) == 2
    assert {ticket.client_id for ticket in tickets} == {"client-a", "client-b"}
    assert tickets[0].id != tickets[1].id


def test_provider_reingest_updates_legacy_id_and_history_uses_persisted_id(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    connector_instance_id, external_company_id = _verified_mapping(store)
    first = _ticket(
        "caller-id",
        connector_instance_id=connector_instance_id,
        external_id="remote-legacy",
        external_client_id=external_company_id,
    )
    assert store.ingest_provider_tickets([first], connector_instance_id=connector_instance_id).written == 1
    persisted = store.list_tickets("client-a")[0]
    updated = _ticket(
        "another-caller-id",
        connector_instance_id=connector_instance_id,
        external_id="remote-legacy",
        external_client_id=external_company_id,
    )
    updated = Ticket(**{**updated.__dict__, "status": "Resolved"})
    assert store.ingest_provider_tickets([updated], connector_instance_id=connector_instance_id).written == 1
    refreshed = store.get_ticket(persisted.id, "client-a")
    assert refreshed is not None
    assert refreshed.status == "Resolved"
    history = store.list_ticket_status_history(persisted.id, client_id="client-a")
    assert history[-1]["ticket_id"] == persisted.id


def test_ingest_tickets_preserves_explicit_client_without_resolution(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    instance = store.create_connector_instance("halopsa", "Primary Halo")
    ticket = _ticket(
        "TCK-EXPLICIT",
        client_id="client-a",
        connector_instance_id=instance.connector_instance_id,
        external_id="remote-explicit",
        external_client_id="company-without-mapping",
    )

    store.update_connector_instance(instance.connector_instance_id, status="active")
    with pytest.raises(ValueError, match="must not carry client_id"):
        store.ingest_provider_tickets([ticket], connector_instance_id=instance.connector_instance_id)


def test_ingest_tickets_preserves_no_provenance_ingestion(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    ticket = _ticket("TCK-LOCAL")

    summary = store.ingest_tickets([ticket], client_id="client-a")

    assert summary.written == 1
    assert summary.quarantined == 0
    written = store.get_ticket(ticket.id)
    assert written is not None
    assert written.client_id == "client-a"
    assert written.connector_instance_id is None


def test_local_ingest_requires_active_client_and_rejects_takeover(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    ticket = _ticket("TCK-LOCAL")
    with pytest.raises(ValueError, match="active client"):
        store.ingest_tickets([ticket], client_id="missing")
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    store.ingest_tickets([ticket], client_id="client-a")
    with pytest.raises(ValueError, match="another client"):
        store.ingest_tickets([ticket], client_id="client-b")


def test_provider_rejects_partial_local_provenance_and_conflicts(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    connector_instance_id, external_company_id = _verified_mapping(store)
    base = _ticket(
        "caller-id",
        connector_instance_id=connector_instance_id,
        external_id="remote-provider",
        external_client_id=external_company_id,
    )
    with pytest.raises(ValueError, match="connector provenance"):
        store.ingest_tickets([base], client_id="client-a")
    with pytest.raises(ValueError, match="conflicts"):
        store.ingest_provider_tickets(
            [Ticket(**{**base.__dict__, "connector_instance_id": "other-instance"})],
            connector_instance_id=connector_instance_id,
        )
    with pytest.raises(ValueError, match="require external_id"):
        store.ingest_provider_tickets(
            [Ticket(**{**base.__dict__, "external_id": None})],
            connector_instance_id=connector_instance_id,
        )


def test_end_user_ticket_validates_active_client_and_rejects_provenance(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    with pytest.raises(ValueError, match="active client"):
        store.create_end_user_ticket(
            client_id="missing",
            requester_id="requester",
            subject="Subject",
            body="Body",
        )
    store.create_client("client-a", "Acme")
    with pytest.raises(ValueError, match="connector provenance"):
        store.create_end_user_ticket(
            client_id="client-a",
            requester_id="requester",
            subject="Subject",
            body="Body",
            external_id="remote-id",
        )


def test_ingest_ticket_file_routes_resolution_and_keeps_count(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    connector_instance_id, external_company_id = _verified_mapping(store)
    ticket = _ticket(
        "TCK-FILE",
        connector_instance_id=connector_instance_id,
        external_id="remote-file",
        external_client_id=external_company_id,
    )
    ticket_path = tmp_path / "tickets.json"
    ticket_path.write_text(json.dumps([ticket.__dict__]), encoding="utf-8")

    with pytest.raises(ValueError, match="connector provenance"):
        ingest_local(store, ticket_path, client_id="client-a")
