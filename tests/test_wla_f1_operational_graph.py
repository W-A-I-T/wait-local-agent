from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from wait_local_agent.api.app import create_app
from wait_local_agent.client_scope import AllClients, BoundClients
from wait_local_agent.models import CanonicalAsset, Ticket
from wait_local_agent.operational_graph import OperationalGraphService
from wait_local_agent.rbac import resolve_auth_context
from wait_local_agent.store import Store


def _seed_clients(store: Store) -> None:
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")


def test_v7_operational_graph_is_additive_idempotent_and_fk_clean(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    _seed_clients(store)
    store.ingest_tickets(
        [
            Ticket(
                id="ticket-a",
                client="Acme",
                subject="A",
                body="Body",
                priority="Low",
                status="Open",
                requester_id="user-a",
            )
        ],
        client_id="client-a",
    )
    store.upsert_canonical_asset(
        canonical_id="device-a",
        asset_type="endpoint-agent",
        display_name="Device A",
        attributes={},
        client_id="client-a",
    )

    with store._connect() as connection:  # noqa: SLF001
        before_counts = {
            table: int(connection.execute(f"select count(*) from {table}").fetchone()[0])  # nosec B608: fixed test table names
            for table in ("clients", "tickets", "canonical_assets")
        }
        store._apply_operational_graph_migration(connection)  # noqa: SLF001
        after_counts = {
            table: int(connection.execute(f"select count(*) from {table}").fetchone()[0])  # nosec B608: fixed test table names
            for table in ("clients", "tickets", "canonical_assets")
        }
        assert after_counts == before_counts
        assert connection.execute("select count(*) from external_entity_refs").fetchone()[0] == 0
        assert connection.execute("select count(*) from entity_links").fetchone()[0] == 0
        assert connection.execute("pragma foreign_keys").fetchone()[0] == 1
        assert connection.execute("pragma foreign_key_check").fetchall() == []
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        after_schema = [
            tuple(row)
            for row in connection.execute(
                "select type, name, sql from sqlite_master "
                "where name in ('external_entity_refs', 'entity_links', 'ux_eer_identity', 'ux_el_identity') "
                "order by type, name"
            )
        ]
        store._apply_operational_graph_migration(connection)  # noqa: SLF001
        assert after_schema == [
            tuple(row)
            for row in connection.execute(
                "select type, name, sql from sqlite_master "
                "where name in ('external_entity_refs', 'entity_links', 'ux_eer_identity', 'ux_el_identity') "
                "order by type, name"
            )
        ]
        assert connection.execute("select count(*) from schema_migrations").fetchone()[0] == 8


def test_graph_store_is_fail_closed_and_cross_tenant_links_raise(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    _seed_clients(store)
    ref_a = store.upsert_entity_ref(
        "client-a",
        entity_type="user",
        source_system="local",
        external_id="user-a",
        provenance="test",
    )
    ref_b = store.upsert_entity_ref(
        BoundClients(frozenset({"client-b"})),
        entity_type="device",
        source_system="local",
        external_id="device-b",
        provenance="test",
    )

    assert store.list_entity_refs("client-a") == [ref_a]
    assert store.get_entity_ref("client-a", ref_b.id) is None
    assert store.list_entity_refs(AllClients()) == [ref_a, ref_b]
    with pytest.raises(ValueError):
        store.list_entity_refs(None)
    with pytest.raises(ValueError):
        store.upsert_entity_link(
            "client-a",
            from_ref_id=ref_a.id,
            to_ref_id=ref_b.id,
            link_type="requested_by",
            provenance="test",
        )
    with pytest.raises(ValueError):
        store.upsert_entity_ref(
            "client-a",
            entity_type="not-an-entity",
            source_system="local",
            external_id="bad",
            provenance="test",
        )
    with pytest.raises(ValueError):
        store.upsert_entity_link(
            "client-a",
            from_ref_id=ref_a.id,
            to_ref_id=ref_a.id,
            link_type="not-a-link",
            provenance="test",
        )


def test_entity_ref_and_link_validation_direction_filters_and_lookup(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    _seed_clients(store)
    connector_b = store.create_connector_instance(
        "halopsa",
        "Beta Halo",
        client_id="client-b",
        credential_ref="vault:beta",
    )
    asset_b = store.upsert_canonical_asset(
        canonical_id="device-b",
        asset_type="endpoint-agent",
        display_name="Device B",
        attributes={},
        client_id="client-b",
    )
    ref_a = store.upsert_entity_ref(
        "client-a",
        entity_type="user",
        source_system="local",
        external_id="user-a",
        provenance="test",
    )
    ref_b = store.upsert_entity_ref(
        "client-a",
        entity_type="device",
        source_system="local",
        external_id="device-a",
        provenance="test",
    )

    assert store.find_entity_ref("client-a", "user", "local", "user-a") == ref_a
    assert store.find_entity_ref(AllClients(), "device", "local", "missing") is None
    with pytest.raises(ValueError):
        store.upsert_entity_ref("client-a", entity_type="user", source_system="", external_id="x", provenance="test")
    with pytest.raises(ValueError):
        store.upsert_entity_ref(
            "client-a", entity_type="user", source_system="local", external_id="", provenance="test"
        )
    with pytest.raises(ValueError):
        store.upsert_entity_ref(
            "client-a",
            entity_type="user",
            source_system="local",
            external_id="x",
            provenance="test",
            attributes=[],  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        store.upsert_entity_ref("client-a", entity_type="user", source_system="local", external_id="x", provenance="")
    with pytest.raises(ValueError):
        store.upsert_entity_ref(
            "client-a",
            entity_type="device",
            source_system="local",
            external_id="device-b",
            provenance="test",
            connector_instance_id=connector_b.connector_instance_id,
        )
    with pytest.raises(ValueError):
        store.upsert_entity_ref(
            "client-a",
            entity_type="device",
            source_system="local",
            external_id="device-b",
            provenance="test",
            canonical_asset_id=asset_b.id,
        )

    link = store.upsert_entity_link(
        "client-a",
        from_ref_id=ref_a.id,
        to_ref_id=ref_b.id,
        link_type="assigned_to",
        provenance="test",
    )
    assert store.list_entity_links("client-a", ref_a.id, direction="from") == [link]
    assert store.list_entity_links("client-a", ref_b.id, direction="to") == [link]
    assert store.list_entity_links("client-a", ref_a.id, direction="outgoing") == [link]
    assert store.list_entity_links("client-a", ref_b.id, direction="incoming") == [link]
    assert store.list_entity_links("client-a", ref_a.id, direction="both") == [link]
    with pytest.raises(ValueError):
        store.list_entity_links("client-a", ref_a.id, direction="sideways")
    with pytest.raises(ValueError):
        store.upsert_entity_link(
            "client-a",
            from_ref_id=ref_a.id,
            to_ref_id=ref_b.id,
            link_type="assigned_to",
            provenance="test",
            confidence=1.1,
        )
    with pytest.raises(ValueError):
        store.upsert_entity_link(
            "client-a",
            from_ref_id=ref_a.id,
            to_ref_id=ref_b.id,
            link_type="assigned_to",
            provenance="test",
            attributes=[],  # type: ignore[arg-type]
        )


def test_operational_graph_validation_empty_cases_and_hard_caps(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    graph = OperationalGraphService(store)

    assert graph.subgraph("client-a", 999) == graph.subgraph("client-a", 999)
    assert graph.ticket_context("client-a", "   ") is None
    assert graph.ticket_context("client-a", "missing") is None
    for invalid_depth in (True, -1, "1"):
        with pytest.raises(ValueError):
            graph.subgraph("client-a", 999, max_depth=invalid_depth)  # type: ignore[arg-type]
    for invalid_nodes in (True, 0, "1"):
        with pytest.raises(ValueError):
            graph.subgraph("client-a", 999, max_nodes=invalid_nodes)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        graph.seed_ticket_requester(AllClients(), "missing")
    with pytest.raises(ValueError):
        graph.seed_canonical_assets(BoundClients(frozenset({"client-a", "client-b"})))
    with pytest.raises(ValueError):
        graph.seed_canonical_assets("")

    refs = [
        store.upsert_entity_ref(
            "client-a",
            entity_type="device",
            source_system="local",
            external_id=f"node-{index}",
            provenance="test",
        )
        for index in range(3)
    ]
    for ref in refs[1:]:
        store.upsert_entity_link(
            "client-a",
            from_ref_id=refs[0].id,
            to_ref_id=ref.id,
            link_type="assigned_to",
            provenance="test",
        )
    capped = graph.subgraph("client-a", refs[0].id, max_depth=99, max_nodes=2)
    assert [ref.id for ref in capped.refs] == [refs[0].id, refs[1].id]
    assert len(capped.links) == 1


def test_operational_graph_handles_invalid_asset_attributes_and_context(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    store.ingest_tickets(
        [
            Ticket(
                id="ticket-a",
                client="Acme",
                subject="A",
                body="B",
                priority="Low",
                status="Open",
                requester_id="user-a",
            )
        ],
        client_id="client-a",
    )
    asset = store.upsert_canonical_asset(
        canonical_id="device-a",
        asset_type="endpoint-agent",
        display_name="Device A",
        attributes={},
        client_id="client-a",
        source_module="",
    )
    with sqlite3.connect(store.path) as connection:
        connection.execute("update canonical_assets set attributes_json = ? where id = ?", ("not-json", asset.id))
    graph = OperationalGraphService(store)
    assert graph.seed_canonical_assets("client-a")[0].attributes_json == "{}"
    with sqlite3.connect(store.path) as connection:
        connection.execute("update canonical_assets set attributes_json = ? where id = ?", ("[]", asset.id))
    assert graph.seed_canonical_assets("client-a")[0].attributes_json == "{}"
    graph.seed_ticket_requester("client-a", "ticket-a")
    context = graph.ticket_context("client-a", " ticket-a ")
    assert context is not None
    assert {ref.external_id for ref in context.refs} == {"ticket-a", "user-a"}


def test_canonical_asset_seeder_skips_assets_without_ids() -> None:
    asset = CanonicalAsset(
        id=None,
        canonical_id="device-without-id",
        asset_type="endpoint-agent",
        display_name="Device",
        attributes_json="{}",
        first_seen="now",
        last_seen="now",
    )
    store = SimpleNamespace(list_canonical_assets=lambda *, client_id: [asset])
    assert OperationalGraphService(store).seed_canonical_assets("client-a") == []  # type: ignore[arg-type]


def test_seeders_are_deterministic_and_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    store.ingest_tickets(
        [
            Ticket(
                id="ticket-a",
                client="Acme",
                subject="Printer",
                body="Body",
                priority="Low",
                status="Open",
                requester_id="user-a",
            ),
            Ticket(
                id="ticket-without-requester",
                client="Acme",
                subject="No requester",
                body="Body",
                priority="Low",
                status="Open",
            ),
        ],
        client_id="client-a",
    )
    store.upsert_canonical_asset(
        canonical_id="device-a",
        asset_type="endpoint-agent",
        display_name="Device A",
        attributes={"os": "test"},
        client_id="client-a",
        owner="user-a",
        source_module="collector",
    )
    store.upsert_canonical_asset(
        canonical_id="device-without-owner",
        asset_type="endpoint-agent",
        display_name="Device B",
        attributes={},
        client_id="client-a",
        owner="",
        source_module="collector",
    )
    graph = OperationalGraphService(store)

    first_ticket_link = graph.seed_ticket_requester("client-a", "ticket-a")
    assert first_ticket_link is not None
    assert graph.seed_ticket_requester("client-a", "ticket-without-requester") is None
    first_devices = graph.seed_canonical_assets("client-a")
    first_refs = store.list_entity_refs("client-a")
    first_links = store.list_entity_links("client-a", first_ticket_link.from_ref_id)

    assert {ref.entity_type for ref in first_devices} == {"device"}
    assert len(first_refs) == 4
    assert len(first_links) == 1
    assert first_links[0].link_type == "requested_by"

    graph.seed_ticket_requester("client-a", "ticket-a")
    graph.seed_canonical_assets("client-a")
    second_refs = store.list_entity_refs("client-a")
    second_links = store.list_entity_links("client-a", first_ticket_link.from_ref_id)
    assert [ref.id for ref in second_refs] == [ref.id for ref in first_refs]
    assert [(link.id, link.from_ref_id, link.to_ref_id, link.link_type) for link in second_links] == [
        (link.id, link.from_ref_id, link.to_ref_id, link.link_type) for link in first_links
    ]
    assert len(store.list_entity_links("client-a", first_devices[0].id)) == 1


def test_traversal_is_bounded_and_stable(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    refs = [
        store.upsert_entity_ref(
            "client-a",
            entity_type="device" if index else "ticket",
            source_system="local",
            external_id=f"node-{index}",
            provenance="test",
        )
        for index in range(5)
    ]
    for left, right in zip(refs[:-1], refs[1:], strict=True):
        store.upsert_entity_link(
            "client-a",
            from_ref_id=left.id,
            to_ref_id=right.id,
            link_type="assigned_to",
            provenance="test",
        )
    graph = OperationalGraphService(store)

    one_hop = graph.subgraph("client-a", refs[0].id, max_depth=1, max_nodes=200)
    capped_nodes = graph.subgraph("client-a", refs[0].id, max_depth=99, max_nodes=2)
    repeated = graph.subgraph("client-a", refs[0].id, max_depth=99, max_nodes=2)
    assert [ref.id for ref in one_hop.refs] == [refs[0].id, refs[1].id]
    assert len(one_hop.links) == 1
    assert len(capped_nodes.refs) == 2
    assert len(capped_nodes.links) == 1
    assert capped_nodes == repeated
    assert graph.ticket_context("client-b", "node-0") is None


def test_context_endpoint_returns_404_for_ticket_outside_principal_scope(settings) -> None:
    store = Store(settings.data_path)
    _seed_clients(store)
    store.ingest_tickets(
        [
            Ticket(
                id="ticket-b",
                client="Beta",
                subject="Foreign",
                body="Body",
                priority="Low",
                status="Open",
                requester_id="user-b",
            )
        ],
        client_id="client-b",
    )
    store.create_principal("viewer", kind="customer")
    store.add_principal_credential("viewer", "viewer-secret")
    store.add_principal_client_role("viewer", "client-a", "viewer")
    secure_settings = replace(settings, demo_mode=False, api_token="bootstrap-admin", viewer_token="")
    app = create_app(secure_settings)
    route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/tickets/{ticket_id}/context"
    )
    viewer = resolve_auth_context(secure_settings, "Bearer viewer-secret", app.state.store)

    with pytest.raises(HTTPException) as error:
        route.endpoint("ticket-b", viewer)

    assert error.value.status_code == 404
    assert error.value.detail == "ticket not found"
