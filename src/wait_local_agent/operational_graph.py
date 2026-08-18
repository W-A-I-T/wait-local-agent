"""Deterministic, bounded client operational graph reads and seeders."""

from __future__ import annotations

import json

from wait_local_agent.client_scope import AllClients, BoundClients, ClientScope
from wait_local_agent.models import EntityLink, EntityRef, SubGraph
from wait_local_agent.store import Store


class OperationalGraphService:
    """Build bounded graph views from tenant-scoped persisted relationships."""

    HARD_MAX_DEPTH = 5
    HARD_MAX_NODES = 200

    def __init__(self, store: Store) -> None:
        self.store = store

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
