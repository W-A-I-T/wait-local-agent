from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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
        external_id="remote-resolved",
        external_client_id=external_company_id,
    )

    summary = store.ingest_tickets([ticket], connector_instance_id=connector_instance_id)

    assert summary.written == 1
    assert summary.quarantined == 0
    written = store.get_ticket(ticket.id)
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

    first = store.ingest_tickets([ticket])
    second = store.ingest_tickets([ticket])

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

    with patch.object(store, "resolve_client_for", side_effect=AssertionError("must not resolve")):
        summary = store.ingest_tickets([ticket])

    assert summary.written == 1
    assert summary.quarantined == 0
    written = store.get_ticket(ticket.id)
    assert written is not None
    assert written.client_id == "client-a"
    assert store.list_unmapped_records(AllClients()) == []


def test_ingest_tickets_preserves_no_provenance_ingestion(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    ticket = _ticket("TCK-LOCAL")

    summary = store.ingest_tickets([ticket])

    assert summary.written == 1
    assert summary.quarantined == 0
    written = store.get_ticket(ticket.id)
    assert written is not None
    assert written.client_id is None
    assert written.connector_instance_id is None


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

    assert store.ingest_ticket_file(ticket_path) == 1
    written = store.get_ticket(ticket.id)
    assert written is not None
    assert written.client_id == "client-a"
