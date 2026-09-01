from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from wait_local_agent.api.app import create_app
from wait_local_agent.client_scope import AllClients, BoundClients
from wait_local_agent.m365_graph import (
    M365GraphManagedDevice,
    M365GraphManagedDeviceReadResponse,
    M365GraphReadProvider,
    M365GraphReadResponse,
    M365GraphUser,
)
from wait_local_agent.models import CanonicalAsset, ConnectorReadResult, Ticket
from wait_local_agent.operational_graph import OperationalGraphService
from wait_local_agent.rbac import AuthContext, Role, resolve_auth_context
from wait_local_agent.rmm import (
    RmmAlert,
    RmmDevice,
    RmmInventoryProvider,
    RmmProviderResolutionError,
)
from wait_local_agent.store import Store


class _FakeRmmProvider:
    adapter_id = "fake-rmm"

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        return [RmmDevice("device-1", "Device 1", "workstation", {"os": "test"})]

    def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
        return [
            RmmAlert("alert-1", "device-1", "high", "Disk full"),
            RmmAlert("alert-missing", "missing-device", "low", "Unknown device"),
        ]


class _FakeM365Provider:
    connection = SimpleNamespace(profile_id="m365-profile-1")

    def list_users(self, *, page_size: int = 200) -> M365GraphReadResponse:
        return M365GraphReadResponse(
            ConnectorReadResult("ready", "ok", 1),
            [M365GraphUser("oid-1", "Alex User", "alex@example.test", "", True, "", "")],
        )

    def list_managed_devices(self, *, page_size: int = 200) -> M365GraphManagedDeviceReadResponse:
        return M365GraphManagedDeviceReadResponse(
            ConnectorReadResult("ready", "ok", 1),
            [
                M365GraphManagedDevice(
                    "device-1", "oid-1", "Alex Laptop", "company", "", "2026-08-31T00:00:00Z",
                    "Windows", "compliant", "mdm", "11", True, "", False, "oid-1@example.test",
                    "Alex User", "Laptop", "Acme",
                )
            ],
        )


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
        assert connection.execute("select count(*) from external_entity_refs").fetchone()[0] == 2
        assert connection.execute("select count(*) from entity_links").fetchone()[0] == 1
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
        assert connection.execute("select count(*) from schema_migrations").fetchone()[0] == 11


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


def test_rmm_inventory_seeder_is_scoped_idempotent_and_skips_missing_devices(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    _seed_clients(store)
    graph = OperationalGraphService(store, rmm_provider=cast(RmmInventoryProvider, _FakeRmmProvider()))

    first = graph.seed_rmm_inventory("client-a")
    second = graph.seed_rmm_inventory("client-a")

    assert first == {"devices": 1, "alerts": 2, "links": 1, "errors": []}
    assert second == first
    assert len(store.list_entity_refs("client-a")) == 3
    assert len(store.list_entity_refs("client-b")) == 0
    device = store.find_entity_ref("client-a", "device", "fake-rmm", "device-1")
    alert = store.find_entity_ref("client-a", "alert", "fake-rmm", "alert-1")
    assert device is not None and alert is not None
    links = store.list_entity_links("client-a", alert.id)
    assert len(links) == 1
    assert links[0].link_type == "alerted_on"
    assert links[0].to_ref_id == device.id


def test_rmm_inventory_provider_failure_is_non_raising(tmp_path: Path) -> None:
    class FailingProvider(_FakeRmmProvider):
        def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
            raise RuntimeError("provider credentials must not escape")

    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    summary = OperationalGraphService(
        store, rmm_provider=cast(RmmInventoryProvider, FailingProvider())
    ).seed_rmm_inventory("client-a")
    assert summary == {"devices": 0, "alerts": 2, "links": 0, "errors": ["device inventory unavailable"]}


def test_rmm_alert_inventory_failure_is_non_raising(tmp_path: Path) -> None:
    class FailingAlertsProvider(_FakeRmmProvider):
        def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
            raise RuntimeError("alert provider unavailable")

    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    summary = OperationalGraphService(
        store, rmm_provider=cast(RmmInventoryProvider, FailingAlertsProvider())
    ).seed_rmm_inventory("client-a")
    assert summary == {"devices": 1, "alerts": 0, "links": 0, "errors": ["alert inventory unavailable"]}


def test_rmm_inventory_without_provider_is_non_raising(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    assert OperationalGraphService(store).seed_rmm_inventory("client-a") == {
        "devices": 0,
        "alerts": 0,
        "links": 0,
        "errors": ["rmm provider unavailable"],
    }


def test_m365_inventory_handles_unavailable_and_empty_payload_edges(tmp_path: Path) -> None:
    class PartialM365Provider:
        connection = SimpleNamespace(profile_id=" ")

        def list_users(self, *, page_size: int = 200) -> M365GraphReadResponse:
            return M365GraphReadResponse(ConnectorReadResult("failed", "users unavailable", 0), [])

        def list_managed_devices(self, *, page_size: int = 200) -> M365GraphManagedDeviceReadResponse:
            return M365GraphManagedDeviceReadResponse(
                ConnectorReadResult("ready", "ok", 2),
                [
                    M365GraphManagedDevice(
                        " ", "", "ignored", "", "", "", "", "", "", "", False, "", False, "", "", "", ""
                    ),
                    M365GraphManagedDevice(
                        "device-2", "missing-user", "", "", "", "", "", "", "", "", False, "", False, "", "", "", ""
                    ),
                ],
            )

    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    assert OperationalGraphService(store).seed_m365_inventory("client-a") == {
        "users": 0,
        "devices": 0,
        "links": 0,
        "errors": ["microsoft 365 provider unavailable"],
    }
    graph = OperationalGraphService(
        store, m365_client=cast(M365GraphReadProvider, PartialM365Provider())
    )
    summary = graph.seed_m365_inventory("client-a")
    assert summary == {
        "users": 0,
        "devices": 1,
        "links": 0,
        "errors": ["user inventory unavailable: users unavailable"],
    }
    device = store.find_entity_ref("client-a", "device", "m365", "device-2")
    assert device is not None
    assert device.display_name == "device-2"

    class UserPayloadProvider(PartialM365Provider):
        def list_users(self, *, page_size: int = 200) -> M365GraphReadResponse:
            return M365GraphReadResponse(
                ConnectorReadResult("ready", "ok", 2),
                [
                    M365GraphUser(" ", "ignored", "", "", None, "", ""),
                    M365GraphUser("user-1", "", "", "", True, "", ""),
                ],
            )

    user_graph = OperationalGraphService(
        store, m365_client=cast(M365GraphReadProvider, UserPayloadProvider())
    )
    assert user_graph.seed_m365_inventory("client-a")["users"] == 1
    user_ref = store.find_entity_ref("client-a", "user", "m365", "user-1")
    assert user_ref is not None
    assert user_ref.display_name == "user-1"


def test_m365_inventory_reports_device_status_and_combined_sync(tmp_path: Path) -> None:
    class DeviceFailureProvider(_FakeM365Provider):
        def list_managed_devices(self, *, page_size: int = 200) -> M365GraphManagedDeviceReadResponse:
            return M365GraphManagedDeviceReadResponse(
                ConnectorReadResult("failed", "devices unavailable", 0), []
            )

    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    graph = OperationalGraphService(
        store,
        rmm_provider=cast(RmmInventoryProvider, _FakeRmmProvider()),
        m365_client=cast(M365GraphReadProvider, DeviceFailureProvider()),
    )
    summary = graph.seed_client_inventory("client-a")
    assert summary["rmm"]["devices"] == 1
    assert summary["m365"] == {
        "users": 1,
        "devices": 0,
        "links": 0,
        "errors": ["device inventory unavailable: devices unavailable"],
    }


def test_m365_inventory_is_metadata_only_scoped_and_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    _seed_clients(store)
    graph = OperationalGraphService(store, m365_client=cast(M365GraphReadProvider, _FakeM365Provider()))

    first = graph.seed_m365_inventory("client-a")
    second = graph.seed_m365_inventory("client-a")

    assert first == {"users": 1, "devices": 1, "links": 1, "errors": []}
    assert second == first
    refs = store.list_entity_refs("client-a")
    assert {(ref.entity_type, ref.source_system, ref.external_id) for ref in refs} == {
        ("m365_account", "m365", "m365-profile-1"),
        ("user", "m365", "oid-1"),
        ("device", "m365", "device-1"),
    }
    device_ref = store.find_entity_ref("client-a", "device", "m365", "device-1")
    assert device_ref is not None
    assert "message" not in device_ref.attributes_json.lower()
    assert len(store.list_entity_links("client-a", refs[1].id)) == 1
    assert len(store.list_entity_refs("client-b")) == 0


def test_client_graph_pagination_filters_and_has_more_are_accurate(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    _seed_clients(store)
    refs = [
        store.upsert_entity_ref(
            "client-a",
            entity_type="device" if index else "user",
            source_system="m365" if index < 2 else "local",
            external_id=f"ref-{index}",
            provenance="test",
        )
        for index in range(3)
    ]
    store.upsert_entity_link(
        "client-a", from_ref_id=refs[0].id, to_ref_id=refs[1].id,
        link_type="owns_device", provenance="test",
    )
    graph = OperationalGraphService(store)

    page = graph.client_graph("client-a", source_system="m365", offset=0, limit=1)
    assert [ref.external_id for ref in page.refs] == ["ref-0"]
    assert page.total_refs == 2
    assert page.total_links == 1
    assert page.has_more is True
    assert page.entity_type_counts == {"device": 2, "user": 1}
    filtered = graph.client_graph("client-a", entity_type="device", link_type="owns_device", limit=1)
    assert [ref.external_id for ref in filtered.refs] == ["ref-1"]
    assert filtered.total_refs == 1
    assert filtered.total_links == 1
    assert filtered.has_more is False


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


def test_client_graph_endpoints_are_fail_closed_and_operator_gated(settings, monkeypatch) -> None:
    import wait_local_agent.api.app as app_module

    store = Store(settings.data_path)
    _seed_clients(store)
    monkeypatch.setattr(app_module, "rmm_provider_from_settings", lambda *_args: _FakeRmmProvider())
    secure_settings = replace(
        settings, demo_mode=False, api_token="bootstrap-admin", viewer_token="", allow_http_probing=True
    )
    app = create_app(secure_settings)
    viewer = AuthContext(
        role=Role.VIEWER, presented_token="viewer", client_ids=frozenset({"client-a"}), demo_mode=False
    )
    non_operator = AuthContext(
        role=Role.ADMIN, presented_token="admin", client_ids=frozenset({"client-a"}), demo_mode=False
    )
    operator = AuthContext(
        role=Role.ADMIN,
        presented_token="operator",
        client_ids=frozenset(),
        is_msp_admin=True,
        demo_mode=False,
    )
    graph_route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/clients/{client_id}/graph"
    )
    sync_route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/clients/{client_id}/graph/sync-rmm"
    )

    with pytest.raises(HTTPException) as foreign:
        graph_route.endpoint("client-b", viewer)
    assert foreign.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        sync_route.endpoint("client-a", non_operator)
    assert denied.value.status_code == 403
    result = sync_route.endpoint("client-a", operator)
    assert result["devices"] == 1
    assert "credentials" not in str(result).lower()
    graph = graph_route.endpoint("client-a", viewer)
    assert len(graph["refs"]) == 3


def test_m365_graph_endpoint_is_operator_and_probing_gated(settings, monkeypatch) -> None:
    import wait_local_agent.api.app as app_module

    class FakeM365GraphClient(_FakeM365Provider):
        def __init__(self, _settings, **kwargs) -> None:
            self.connection = kwargs.get("connection", self.connection)

    store = Store(settings.data_path)
    _seed_clients(store)
    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    monkeypatch.setattr(
        app_module.M365ConnectionResolver,
        "resolve",
        lambda _resolver, _client_id=None: SimpleNamespace(profile_id="m365-profile-1"),
    )
    active_settings = replace(settings, allow_http_probing=True)
    app = create_app(active_settings)
    route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/clients/{client_id}/graph/sync-m365"
    )
    operator = AuthContext(
        role=Role.ADMIN,
        presented_token="operator",
        client_ids=frozenset(),
        is_msp_admin=True,
        demo_mode=False,
    )

    result = route.endpoint("client-a", operator)
    assert result["users"] == 1
    assert result["devices"] == 1
    assert "credentials" not in str(result).lower()

    blocked_app = create_app(replace(active_settings, allow_http_probing=False))
    blocked_route = next(
        route
        for route in blocked_app.routes
        if isinstance(route, APIRoute) and route.path == "/clients/{client_id}/graph/sync-m365"
    )
    with pytest.raises(HTTPException, match="probing is disabled") as error:
        blocked_route.endpoint("client-a", operator)
    assert error.value.status_code == 409


def test_scheduled_graph_sync_runner_guards(settings, monkeypatch) -> None:
    import wait_local_agent.api.app as app_module

    app = create_app(settings)
    store = app.state.store
    store.create_client("client-a", "Acme")
    runner = app.state.scheduler._graph_sync_runner  # noqa: SLF001
    assert runner is not None

    store.set_client_status(AllClients(), "client-a", "archived")
    with pytest.raises(ValueError, match="client must be active"):
        runner("client-a")

    store.set_client_status(AllClients(), "client-a", "active")

    def raise_resolution_error(*_args) -> object:
        raise RmmProviderResolutionError("ambiguous RMM provider")

    monkeypatch.setattr(app_module, "rmm_provider_from_settings", raise_resolution_error)
    with pytest.raises(ValueError, match="ambiguous RMM provider"):
        runner("client-a")

    monkeypatch.setattr(app_module, "rmm_provider_from_settings", lambda *_args: _FakeRmmProvider())
    with pytest.raises(ValueError, match="RMM read probing is disabled"):
        runner("client-a")
