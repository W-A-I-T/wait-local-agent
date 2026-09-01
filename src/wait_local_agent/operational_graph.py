"""Deterministic, bounded client operational graph reads and seeders."""

from __future__ import annotations

import json
import logging
from typing import TypedDict

from wait_local_agent.client_scope import AllClients, BoundClients, ClientScope
from wait_local_agent.m365_graph import M365GraphReadProvider
from wait_local_agent.models import EntityLink, EntityRef, SubGraph
from wait_local_agent.rmm import RmmInventoryProvider
from wait_local_agent.store import Store

LOGGER = logging.getLogger(__name__)


class RmmInventorySeedSummary(TypedDict):
    devices: int
    alerts: int
    links: int
    errors: list[str]


class M365InventorySeedSummary(TypedDict):
    users: int
    devices: int
    links: int
    errors: list[str]


class ClientGraphSyncSummary(TypedDict):
    rmm: RmmInventorySeedSummary
    m365: M365InventorySeedSummary


class OperationalGraphService:
    """Build bounded graph views from tenant-scoped persisted relationships."""

    HARD_MAX_DEPTH = 5
    HARD_MAX_NODES = 200

    def __init__(
        self,
        store: Store,
        rmm_provider: RmmInventoryProvider | None = None,
        m365_client: M365GraphReadProvider | None = None,
    ) -> None:
        self.store = store
        self.rmm_provider = rmm_provider
        self.m365_client = m365_client

    def client_graph(
        self,
        scope: ClientScope | str | None,
        *,
        entity_type: str | None = None,
        link_type: str | None = None,
        source_system: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> SubGraph:
        """Return one bounded, filterable page of a client's graph."""

        _require_single_scope(scope)
        effective_limit = min(limit, self.HARD_MAX_NODES)
        refs = self.store.list_entity_refs(
            scope,
            entity_type=entity_type,
            source_system=source_system,
            link_type=link_type,
            offset=offset,
            limit=effective_limit,
        )
        links = self.store.list_entity_links_page(
            scope,
            entity_type=entity_type,
            source_system=source_system,
            link_type=link_type,
            offset=offset,
            limit=effective_limit,
        )
        total_refs = self.store.count_entity_refs(
            scope, entity_type=entity_type, source_system=source_system, link_type=link_type
        )
        total_links = self.store.count_entity_links(
            scope,
            entity_type=entity_type,
            source_system=source_system,
            link_type=link_type,
        )
        return SubGraph(
            refs=tuple(refs),
            links=tuple(links),
            total_refs=total_refs,
            total_links=total_links,
            has_more=(offset + effective_limit < total_refs or offset + effective_limit < total_links),
            entity_type_counts=self.store.count_entity_refs_by_type(scope),
        )

    def subgraph(
        self,
        scope: ClientScope | str | None,
        root_ref_id: int,
        *,
        max_depth: int = 2,
        max_nodes: int = 200,
    ) -> SubGraph:
        """Return a stable BFS subgraph subject to hard depth and node caps."""

        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth must be a non-negative integer")
        if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes < 1:
            raise ValueError("max_nodes must be a positive integer")
        effective_depth = min(max_depth, self.HARD_MAX_DEPTH)
        effective_nodes = min(max_nodes, self.HARD_MAX_NODES)
        root = self.store.get_entity_ref(scope, root_ref_id)
        if root is None:
            return SubGraph(refs=(), links=())

        refs_by_id: dict[int, EntityRef] = {root.id: root}
        links_by_id: dict[int, EntityLink] = {}
        frontier = [root.id]
        for _ in range(effective_depth):
            if not frontier or len(refs_by_id) >= effective_nodes:
                break
            next_frontier: list[int] = []
            for ref_id in frontier:
                for link, neighbor in self.store.neighbors(scope, ref_id):
                    if neighbor.id not in refs_by_id:
                        if len(refs_by_id) >= effective_nodes:
                            continue
                        refs_by_id[neighbor.id] = neighbor
                        next_frontier.append(neighbor.id)
                    links_by_id[link.id] = link
            frontier = next_frontier

        return SubGraph(
            refs=tuple(refs_by_id.values()),
            links=tuple(links_by_id[link_id] for link_id in sorted(links_by_id)),
        )

    def ticket_context(
        self, scope: ClientScope | str | None, ticket_id: str
    ) -> SubGraph | None:
        """Resolve a scoped ticket reference and return its bounded graph context."""

        normalized_ticket_id = ticket_id.strip()
        if not normalized_ticket_id:
            return None
        ticket_ref = next(
            (
                ref
                for ref in self.store.list_entity_refs(scope, entity_type="ticket")
                if ref.external_id == normalized_ticket_id
            ),
            None,
        )
        if ticket_ref is None:
            return None
        return self.subgraph(scope, ticket_ref.id)

    def seed_ticket_requester(
        self, scope: ClientScope | str | None, ticket_id: str
    ) -> EntityLink | None:
        """Persist the deterministic ticket-requester relationship, if present."""

        _require_single_scope(scope)
        ticket = self.store.get_ticket(ticket_id.strip(), client_id=scope, include_quarantine=False)
        if ticket is None or not ticket.requester_id or not ticket.requester_id.strip():
            return None
        source_system = (ticket.source_system or "").strip() or "local"
        ticket_ref = self.store.upsert_entity_ref(
            scope,
            entity_type="ticket",
            source_system=source_system,
            external_id=ticket.id,
            display_name=ticket.subject,
            provenance="ticket_field",
        )
        requester_ref = self.store.upsert_entity_ref(
            scope,
            entity_type="user",
            source_system=source_system,
            external_id=ticket.requester_id.strip(),
            display_name=ticket.requester_id.strip(),
            provenance="ticket_field",
        )
        return self.store.upsert_entity_link(
            scope,
            from_ref_id=ticket_ref.id,
            to_ref_id=requester_ref.id,
            link_type="requested_by",
            provenance="ticket_field",
        )

    def seed_canonical_assets(
        self, scope: ClientScope | str | None
    ) -> list[EntityRef]:
        """Persist deterministic device and optional owner relationships for a tenant."""

        _require_single_scope(scope)
        seeded: list[EntityRef] = []
        for asset in self.store.list_canonical_assets(client_id=scope):
            if asset.id is None:
                continue
            source_system = asset.source_module.strip() or "local"
            attributes = _object_attributes(asset.attributes_json)
            device_ref = self.store.upsert_entity_ref(
                scope,
                entity_type="device",
                source_system=source_system,
                external_id=asset.canonical_id,
                display_name=asset.display_name,
                canonical_asset_id=asset.id,
                provenance="canonical_asset",
                attributes=attributes,
            )
            seeded.append(device_ref)
            owner = asset.owner.strip()
            if not owner:
                continue
            owner_ref = self.store.upsert_entity_ref(
                scope,
                entity_type="user",
                source_system="local",
                external_id=owner,
                display_name=owner,
                provenance="canonical_asset",
            )
            self.store.upsert_entity_link(
                scope,
                from_ref_id=owner_ref.id,
                to_ref_id=device_ref.id,
                link_type="owns_device",
                provenance="canonical_asset",
            )
        return seeded

    def seed_rmm_inventory(
        self, scope: ClientScope | str | None
    ) -> RmmInventorySeedSummary:
        """Persist tenant-scoped RMM devices, alerts, and explicit alert links."""

        _require_single_scope(scope)
        provider = self.rmm_provider
        if provider is None:
            return {"devices": 0, "alerts": 0, "links": 0, "errors": ["rmm provider unavailable"]}
        client_id = scope.client_id if isinstance(scope, BoundClients) else str(scope)
        source_system = provider.adapter_id.strip() or "rmm"
        summary: RmmInventorySeedSummary = {"devices": 0, "alerts": 0, "links": 0, "errors": []}

        try:
            devices = sorted(provider.list_devices(client_id), key=lambda device: device.device_id)
        except Exception:  # provider failures must degrade the sync, not break the API
            LOGGER.exception("RMM device inventory failed for client %s", client_id)
            devices = []
            summary["errors"].append("device inventory unavailable")

        device_refs: dict[str, EntityRef] = {}
        for device in devices:
            device_ref = self.store.upsert_entity_ref(
                scope,
                entity_type="device",
                source_system=source_system,
                external_id=device.device_id,
                display_name=device.name,
                provenance="rmm_inventory",
                attributes={"category": device.category, **device.attributes},
            )
            device_refs[device.device_id] = device_ref
            summary["devices"] += 1

        try:
            alerts = sorted(provider.list_alerts(client_id), key=lambda alert: alert.alert_id)
        except Exception:  # provider failures must degrade the sync, not break the API
            LOGGER.exception("RMM alert inventory failed for client %s", client_id)
            alerts = []
            summary["errors"].append("alert inventory unavailable")

        for alert in alerts:
            alert_ref = self.store.upsert_entity_ref(
                scope,
                entity_type="alert",
                source_system=source_system,
                external_id=alert.alert_id,
                display_name=alert.title,
                provenance="rmm_inventory",
                attributes={"severity": alert.severity, "status": alert.status, "device_id": alert.device_id},
            )
            summary["alerts"] += 1
            alert_device_ref = device_refs.get(alert.device_id)
            if alert_device_ref is not None:
                self.store.upsert_entity_link(
                    scope,
                    from_ref_id=alert_ref.id,
                    to_ref_id=alert_device_ref.id,
                    link_type="alerted_on",
                    provenance="rmm_inventory",
                )
                summary["links"] += 1
        return summary

    def seed_m365_inventory(
        self, scope: ClientScope | str | None
    ) -> M365InventorySeedSummary:
        """Persist Microsoft 365 identity and Intune metadata for one client."""

        _require_single_scope(scope)
        provider = self.m365_client
        summary: M365InventorySeedSummary = {"users": 0, "devices": 0, "links": 0, "errors": []}
        if provider is None:
            summary["errors"].append("microsoft 365 provider unavailable")
            return summary

        users_response = provider.list_users(page_size=self.HARD_MAX_NODES)
        if users_response.result.status != "ready":
            summary["errors"].append(f"user inventory unavailable: {users_response.result.message}")
            users = []
        else:
            users = sorted(users_response.items, key=lambda user: user.id)

        connection = getattr(provider, "connection", None)
        profile_id = getattr(connection, "profile_id", None)
        tenant_external_id = profile_id.strip() if isinstance(profile_id, str) and profile_id.strip() else "environment"
        self.store.upsert_entity_ref(
            scope,
            entity_type="m365_account",
            source_system="m365",
            external_id=tenant_external_id,
            display_name="Microsoft 365 tenant",
            provenance="m365_inventory",
        )

        user_refs: dict[str, EntityRef] = {}
        user_refs_by_upn: dict[str, EntityRef] = {}
        for user in users:
            user_id = user.id.strip()
            if not user_id:
                continue
            upn = user.user_principal_name.strip()
            user_ref = self.store.upsert_entity_ref(
                scope,
                entity_type="user",
                source_system="m365",
                external_id=user_id,
                display_name=user.display_name.strip() or upn or user_id,
                provenance="m365_inventory",
                attributes={
                    "user_principal_name": upn,
                    "mail": user.mail.strip(),
                    "account_enabled": user.account_enabled,
                },
            )
            user_refs[user_id] = user_ref
            if upn:
                user_refs_by_upn[upn.casefold()] = user_ref
            summary["users"] += 1

        devices_response = provider.list_managed_devices(page_size=self.HARD_MAX_NODES)
        if devices_response.result.status != "ready":
            summary["errors"].append(f"device inventory unavailable: {devices_response.result.message}")
            devices = []
        else:
            devices = sorted(devices_response.items, key=lambda device: device.id)
        for device in devices:
            device_id = device.id.strip()
            if not device_id:
                continue
            device_ref = self.store.upsert_entity_ref(
                scope,
                entity_type="device",
                source_system="m365",
                external_id=device_id,
                display_name=device.device_name.strip() or device_id,
                provenance="m365_inventory",
                attributes={
                    "user_id": device.user_id.strip(),
                    "user_principal_name": device.user_principal_name.strip(),
                    "operating_system": device.operating_system.strip(),
                    "os_version": device.os_version.strip(),
                    "compliance_state": device.compliance_state.strip(),
                    "management_agent": device.management_agent.strip(),
                    "owner_type": device.owner_type.strip(),
                    "last_sync_date_time": device.last_sync_date_time.strip(),
                },
            )
            summary["devices"] += 1
            owner_ref = user_refs.get(device.user_id.strip()) or user_refs_by_upn.get(
                device.user_principal_name.strip().casefold()
            )
            if owner_ref is not None:
                self.store.upsert_entity_link(
                    scope,
                    from_ref_id=owner_ref.id,
                    to_ref_id=device_ref.id,
                    link_type="owns_device",
                    provenance="m365_inventory",
                )
                summary["links"] += 1
        return summary

    def seed_client_inventory(self, scope: ClientScope | str | None) -> ClientGraphSyncSummary:
        """Run the scheduled RMM and Microsoft 365 inventory contributors."""

        return {"rmm": self.seed_rmm_inventory(scope), "m365": self.seed_m365_inventory(scope)}


def _object_attributes(attributes_json: str) -> dict[str, object]:
    try:
        payload = json.loads(attributes_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _require_single_scope(scope: ClientScope | str | None) -> None:
    if isinstance(scope, AllClients) or scope is None:
        raise ValueError("operational graph writes require a single client scope")
    if isinstance(scope, BoundClients) and len(scope.client_ids) != 1:
        raise ValueError("operational graph writes require a single client scope")
    if isinstance(scope, str) and not scope.strip():
        raise ValueError("operational graph writes require a single client scope")
