from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.support import ensure_test_clients
from wait_local_agent.api.app import QuarantineReclassificationRequest, create_app
from wait_local_agent.client_scope import AllClients
from wait_local_agent.models import Ticket, utc_now
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.store import Store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _provider_ticket(instance_id: str, company_id: str, external_id: str = "remote-1") -> Ticket:
    return Ticket(
        id="caller-id-is-ignored",
        client="Provider customer",
        subject="Provider subject",
        body="Provider body",
        priority="Low",
        status="Open",
        source_system="halopsa",
        connector_instance_id=instance_id,
        external_id=external_id,
        external_client_id=company_id,
    )


def _active_instance(store: Store, *, client_id: str | None = None, display_name: str = "Primary Halo"):
    instance = store.create_connector_instance("halopsa", display_name, client_id=client_id)
    active = store.update_connector_instance(instance.connector_instance_id, status="active")
    assert active is not None
    return active


def test_unmapped_provider_ticket_persists_and_retenants_atomically(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    ensure_test_clients(store, "client-a", "client-b")
    instance = _active_instance(store)
    ticket = _provider_ticket(instance.connector_instance_id, "company-a")

    first = store.ingest_provider_tickets([ticket], connector_instance_id=instance.connector_instance_id)
    second = store.ingest_provider_tickets([ticket], connector_instance_id=instance.connector_instance_id)

    assert first.written == 0 and first.quarantined == 1
    assert second.written == 0 and second.quarantined == 1
    quarantined = store.list_quarantined_tickets(instance.connector_instance_id)
    assert len(quarantined) == 1
    assert quarantined[0].client_id == "__quarantine__"
    assert store.list_ticket_status_history(quarantined[0].id) == []
    triage = store.list_unmapped_records(AllClients(), connector_instance_id=instance.connector_instance_id)
    assert len(triage) == 1 and triage[0].occurrence_count == 2
    assert [event for event in store.list_audit_events() if event.event_type == "ticket.quarantined"]

    mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-a", "client-a"
    )
    verified, retenanted_count = store.verify_client_connector_mapping(
        AllClients(), mapping.mapping_id, return_retenanted_count=True
    )
    assert verified.client_id == "client-a"
    assert retenanted_count == 1
    history = store.list_ticket_status_history(quarantined[0].id)
    assert len(history) == 1
    assert history[0]["from_status"] == ""
    assert history[0]["source"] == "mapping_verification"
    assert store.list_unmapped_records(AllClients(), connector_instance_id=instance.connector_instance_id)[
        0
    ].resolved_at
    assert [event for event in store.list_audit_events("client-a") if event.event_type == "ticket.tenanted"]


def test_provider_ownership_invariant_and_retenant_guards(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    ensure_test_clients(store, "client-a", "client-b")
    instance = _active_instance(store)
    first_mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-a", "client-a"
    )
    store.verify_client_connector_mapping(AllClients(), first_mapping.mapping_id)
    store.ingest_provider_tickets(
        [_provider_ticket(instance.connector_instance_id, "company-a")],
        connector_instance_id=instance.connector_instance_id,
    )
    conflict = store.ingest_provider_tickets(
        [_provider_ticket(instance.connector_instance_id, "company-b")],
        connector_instance_id=instance.connector_instance_id,
    )
    assert conflict.quarantined == 1
    assert store.list_quarantined_tickets() == []
    assert store.list_unmapped_records(AllClients())[0].reason == "no_verified_mapping"

    quarantine = store.ingest_provider_tickets(
        [_provider_ticket(instance.connector_instance_id, "company-b", external_id="remote-b")],
        connector_instance_id=instance.connector_instance_id,
    )
    assert quarantine.quarantined == 1

    archived = store.set_client_status(AllClients(), "client-b", "archived")
    assert archived is not None
    inactive_mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-b", "client-b"
    )
    with pytest.raises(ValueError, match="target client must exist and be active"):
        store.verify_client_connector_mapping(AllClients(), inactive_mapping.mapping_id)
    assert store.list_client_connector_mappings(AllClients())[1].verified == 0

    with store._connect() as connection:  # noqa: SLF001
        with pytest.raises(ValueError, match="connector instance and external company are required"):
            store.retenant_quarantined_tickets(
                connection,
                " ",
                "company-b",
                "client-a",
            )
        with pytest.raises(ValueError, match="target client must exist and be active"):
            store.retenant_quarantined_tickets(
                connection,
                instance.connector_instance_id,
                "company-b",
                " ",
            )
        with pytest.raises(ValueError, match="reserved"):
            store.retenant_quarantined_tickets(
                connection,
                instance.connector_instance_id,
                "company-b",
                "__quarantine__",
            )

    restored = store.set_client_status(AllClients(), "client-b", "active")
    assert restored is not None
    pinned = _active_instance(store, client_id="client-a", display_name="Pinned Halo")
    mismatch = store.create_client_connector_mapping(
        AllClients(), pinned.connector_instance_id, "company-c", "client-b"
    )
    store.ingest_provider_tickets(
        [_provider_ticket(pinned.connector_instance_id, "company-c", external_id="remote-c")],
        connector_instance_id=pinned.connector_instance_id,
    )
    with pytest.raises(ValueError, match="connector instance client conflicts"):
        store.verify_client_connector_mapping(AllClients(), mismatch.mapping_id)

    no_rows_mapping = store.create_client_connector_mapping(
        AllClients(), pinned.connector_instance_id, "company-d", "client-b"
    )
    assert store.verify_client_connector_mapping(AllClients(), no_rows_mapping.mapping_id).verified == 1
    with pytest.raises(ValueError, match="connector instance client conflicts"):
        store.ingest_provider_tickets(
            [_provider_ticket(pinned.connector_instance_id, "company-d", external_id="remote-d")],
            connector_instance_id=pinned.connector_instance_id,
        )


def test_quarantine_reconciliation_routes_list_and_reclassify(settings) -> None:
    store = Store(settings.data_path)
    ensure_test_clients(store, "client-a", "client-b")
    instance = _active_instance(store, client_id="client-a")
    ticket = _provider_ticket(instance.connector_instance_id, "company-a", external_id="remote-a")
    result = store.ingest_provider_tickets([ticket], connector_instance_id=instance.connector_instance_id)
    assert result.quarantined == 1
    ticket_id = store.list_quarantined_tickets(instance.connector_instance_id)[0].id

    app = create_app(settings)
    endpoints = {
        (route.path, method): route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }
    list_quarantined = endpoints[("/ingestion/quarantined", "GET")]
    reclassify = endpoints[("/ingestion/quarantined/{ticket_id}/reclassify", "POST")]
    operator_context = AuthContext(
        role=Role.ADMIN,
        presented_token="bootstrap-admin",
        is_msp_admin=True,
    )
    bound_context = AuthContext(
        role=Role.VIEWER,
        presented_token="bound-secret",
        client_id="client-a",
        client_ids=frozenset({"client-a"}),
    )

    listed = list_quarantined(operator_context)
    assert [item["id"] for item in listed] == [ticket_id]
    filtered = list_quarantined(operator_context, connector_instance_id=instance.connector_instance_id)
    assert [item["id"] for item in filtered] == [ticket_id]
    with pytest.raises(HTTPException) as empty_filter:
        list_quarantined(operator_context, connector_instance_id=" ")
    assert empty_filter.value.status_code == 400
    assert list_quarantined(bound_context) == []
    bound_list = list_quarantined(bound_context, connector_instance_id=instance.connector_instance_id)
    assert [item["id"] for item in bound_list] == [ticket_id]
    with pytest.raises(HTTPException) as forbidden:
        reclassify(
            ticket_id,
            QuarantineReclassificationRequest(client_id="client-a"),
            bound_context,
        )
    assert forbidden.value.status_code == 403

    archived = store.set_client_status(AllClients(), "client-b", "archived")
    assert archived is not None
    with pytest.raises(HTTPException) as inactive:
        reclassify(
            ticket_id,
            QuarantineReclassificationRequest(client_id="client-b"),
            operator_context,
        )
    assert inactive.value.status_code == 400
    with pytest.raises(HTTPException) as reserved:
        reclassify(
            ticket_id,
            QuarantineReclassificationRequest(client_id="__quarantine__"),
            operator_context,
        )
    assert reserved.value.status_code == 400
    with pytest.raises(HTTPException) as missing:
        reclassify(
            "missing",
            QuarantineReclassificationRequest(client_id="client-a"),
            operator_context,
        )
    assert missing.value.status_code == 400
    assert reclassify(
        ticket_id,
        QuarantineReclassificationRequest(client_id="client-a"),
        operator_context,
    ) == {"ticket_id": ticket_id, "client_id": "client-a"}
    assert list_quarantined(operator_context) == []


def test_quarantined_route_uses_viewer_access_and_instance_scope(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="client-a",
        admin_token="bootstrap-admin",
        api_token="",
    )
    store = Store(secure_settings.data_path)
    ensure_test_clients(store, "client-a", "client-b")
    instance_a = _active_instance(store, client_id="client-a", display_name="Acme Halo")
    instance_b = _active_instance(store, client_id="client-b", display_name="Beta Halo")
    ticket_a = _provider_ticket(instance_a.connector_instance_id, "company-a", external_id="remote-a")
    ticket_b = _provider_ticket(instance_b.connector_instance_id, "company-b", external_id="remote-b")
    assert (
        store.ingest_provider_tickets([ticket_a], connector_instance_id=instance_a.connector_instance_id).quarantined
        == 1
    )
    assert (
        store.ingest_provider_tickets([ticket_b], connector_instance_id=instance_b.connector_instance_id).quarantined
        == 1
    )
    ticket_a_id = store.list_quarantined_tickets(instance_a.connector_instance_id)[0].id
    ticket_b_id = store.list_quarantined_tickets(instance_b.connector_instance_id)[0].id

    store.create_principal("client-a-viewer", kind="staff")
    store.add_principal_credential("client-a-viewer", "viewer-secret")
    store.add_principal_client_role("client-a-viewer", "client-a", "viewer")

    client = TestClient(create_app(secure_settings))
    scoped = client.get(
        "/ingestion/quarantined",
        params={"connector_instance_id": instance_a.connector_instance_id},
        headers=_auth("viewer-secret"),
    )
    assert scoped.status_code == 200
    assert [item["id"] for item in scoped.json()] == [ticket_a_id]
    assert ticket_b_id not in {item["id"] for item in scoped.json()}

    foreign = client.get(
        "/ingestion/quarantined",
        params={"connector_instance_id": instance_b.connector_instance_id},
        headers=_auth("viewer-secret"),
    )
    assert foreign.status_code == 200
    assert foreign.json() == []

    empty = client.get(
        "/ingestion/quarantined",
        params={"connector_instance_id": ""},
        headers=_auth("viewer-secret"),
    )
    assert empty.status_code == 400
    assert (
        client.get(
            "/ingestion/quarantined",
            params={"connector_instance_id": " "},
            headers=_auth("viewer-secret"),
        ).status_code
        == 400
    )


def test_quarantined_reclassify_route_guards_and_audits(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="client-a",
        admin_token="bootstrap-admin",
        api_token="",
    )
    store = Store(secure_settings.data_path)
    ensure_test_clients(store, "client-a", "client-b")
    instance = _active_instance(store, display_name="Reclassify Halo")
    quarantine = _provider_ticket(instance.connector_instance_id, "company-a", external_id="remote-quarantine")
    assert (
        store.ingest_provider_tickets([quarantine], connector_instance_id=instance.connector_instance_id).quarantined
        == 1
    )
    quarantine_id = store.list_quarantined_tickets(instance.connector_instance_id)[0].id

    mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-normal", "client-a"
    )
    assert store.verify_client_connector_mapping(AllClients(), mapping.mapping_id) is not None
    normal = _provider_ticket(instance.connector_instance_id, "company-normal", external_id="remote-normal")
    assert store.ingest_provider_tickets([normal], connector_instance_id=instance.connector_instance_id).written == 1
    normal_ticket = next(ticket for ticket in store.list_tickets("client-a") if ticket.external_id == "remote-normal")

    store.create_principal("client-a-admin", kind="staff")
    store.add_principal_credential("client-a-admin", "operator-looking-secret")
    store.add_principal_client_role("client-a-admin", "client-a", "admin")

    client = TestClient(create_app(secure_settings))
    assert (
        client.post(
            f"/ingestion/quarantined/{quarantine_id}/reclassify",
            headers=_auth("operator-looking-secret"),
            json={"client_id": "client-a"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/ingestion/quarantined/missing/reclassify",
            headers=_auth("bootstrap-admin"),
            json={"client_id": "client-a"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/ingestion/quarantined/{normal_ticket.id}/reclassify",
            headers=_auth("bootstrap-admin"),
            json={"client_id": "client-a"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/ingestion/quarantined/{quarantine_id}/reclassify",
            headers=_auth("bootstrap-admin"),
            json={"client_id": "client-b"},
        ).status_code
        == 200
    )

    # The inactive-target guard is exercised on a second quarantine ticket.
    second = _provider_ticket(instance.connector_instance_id, "company-second", external_id="remote-second")
    assert (
        store.ingest_provider_tickets([second], connector_instance_id=instance.connector_instance_id).quarantined == 1
    )
    second_id = store.list_quarantined_tickets(instance.connector_instance_id)[0].id
    archived = store.set_client_status(AllClients(), "client-b", "archived")
    assert archived is not None
    inactive = client.post(
        f"/ingestion/quarantined/{second_id}/reclassify",
        headers=_auth("bootstrap-admin"),
        json={"client_id": "client-b"},
    )
    assert inactive.status_code == 400
    reserved = client.post(
        f"/ingestion/quarantined/{second_id}/reclassify",
        headers=_auth("bootstrap-admin"),
        json={"client_id": "__quarantine__"},
    )
    assert reserved.status_code == 400

    reclassified = store.get_ticket(quarantine_id, "client-b")
    assert reclassified is not None
    history = store.list_ticket_status_history(quarantine_id, client_id="client-b")
    assert len(history) == 1
    assert history[0]["source"] == "mapping_verification"
    assert any(
        event.event_type == "ticket.tenanted" and event.subject_id == quarantine_id and event.client_id == "client-b"
        for event in store.list_audit_events("client-b")
    )


def test_mapping_verify_route_maps_quarantine_retenant_errors_and_success(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="client-a",
        admin_token="bootstrap-admin",
        api_token="",
    )
    store = Store(secure_settings.data_path)
    ensure_test_clients(store, "client-a", "client-b")
    unpinned = _active_instance(store, display_name="Unpinned Halo")
    pinned = _active_instance(store, client_id="client-a", display_name="Pinned Halo")

    inactive_mapping = store.create_client_connector_mapping(
        AllClients(), unpinned.connector_instance_id, "company-inactive", "client-b"
    )
    inactive_ticket = _provider_ticket(
        unpinned.connector_instance_id, "company-inactive", external_id="remote-inactive"
    )
    assert (
        store.ingest_provider_tickets(
            [inactive_ticket], connector_instance_id=unpinned.connector_instance_id
        ).quarantined
        == 1
    )
    assert store.set_client_status(AllClients(), "client-b", "archived") is not None

    client = TestClient(create_app(secure_settings))
    inactive = client.post(
        f"/client-connector-mappings/{inactive_mapping.mapping_id}/verify",
        headers=_auth("bootstrap-admin"),
    )
    assert inactive.status_code == 409

    assert store.set_client_status(AllClients(), "client-b", "active") is not None

    mismatch_mapping = store.create_client_connector_mapping(
        AllClients(), pinned.connector_instance_id, "company-mismatch", "client-b"
    )
    mismatch_ticket = _provider_ticket(pinned.connector_instance_id, "company-mismatch", external_id="remote-mismatch")
    assert (
        store.ingest_provider_tickets([mismatch_ticket], connector_instance_id=pinned.connector_instance_id).quarantined
        == 1
    )
    mismatch = client.post(
        f"/client-connector-mappings/{mismatch_mapping.mapping_id}/verify",
        headers=_auth("bootstrap-admin"),
    )
    assert mismatch.status_code == 409

    success_mapping = store.create_client_connector_mapping(
        AllClients(), unpinned.connector_instance_id, "company-success", "client-a"
    )
    success_ticket = _provider_ticket(unpinned.connector_instance_id, "company-success", external_id="remote-success")
    assert (
        store.ingest_provider_tickets(
            [success_ticket], connector_instance_id=unpinned.connector_instance_id
        ).quarantined
        == 1
    )
    success_ticket_id = next(
        ticket.id
        for ticket in store.list_quarantined_tickets(unpinned.connector_instance_id)
        if ticket.external_id == "remote-success"
    )

    success = client.post(
        f"/client-connector-mappings/{success_mapping.mapping_id}/verify",
        headers=_auth("bootstrap-admin"),
    )
    assert success.status_code == 200
    assert success.json()["verified"] == 1
    assert success.json()["retenanted_count"] == 1

    retenanted = store.get_ticket(success_ticket_id, "client-a")
    assert retenanted is not None


def test_legacy_quarantine_reclassification_seeds_history_and_audit(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    now = utc_now()
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into tickets
              (id, client, subject, body, priority, status, client_id,
               requester_id, created_at, updated_at, source_system,
               connector_instance_id, external_id, external_client_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-quarantine",
                "Legacy",
                "Legacy subject",
                "Legacy body",
                "Low",
                "Open",
                "__quarantine__",
                None,
                now,
                now,
                "local",
                None,
                None,
                None,
            ),
        )

    store.reclassify_quarantined_ticket("legacy-quarantine", "client-a")
    assert store.get_ticket("legacy-quarantine", "client-a") is not None
    history = store.list_ticket_status_history("legacy-quarantine", client_id="client-a")
    assert len(history) == 1 and history[0]["source"] == "mapping_verification"
    assert [event for event in store.list_audit_events("client-a") if event.event_type == "ticket.tenanted"]
    with pytest.raises(ValueError, match="not quarantined"):
        store.reclassify_quarantined_ticket("legacy-quarantine", "client-a")
    with pytest.raises(ValueError, match="reserved"):
        store.reclassify_quarantined_ticket("legacy-quarantine", "__quarantine__")
