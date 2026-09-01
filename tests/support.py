from __future__ import annotations

from pathlib import Path

from wait_local_agent.client_scope import AllClients
from wait_local_agent.store import Store

DEFAULT_TEST_CLIENT_ID = "acme"

PINNED_SCHEMA_MIGRATIONS: list[tuple[int, str]] = [
    (0, "baseline"),
    (1, "principals"),
    (2, "clients_and_connectors"),
    (3, "provenance_and_ingestion"),
    (4, "canonical_assets_tenant_unique"),
    (5, "ticket_identity_and_tenancy"),
    (6, "poll_lease"),
    (7, "operational_graph"),
    (8, "auth_sessions_and_config"),
    (9, "principal_identities"),
    (10, "client_candidates"),
    (11, "client_baselines"),
    (12, "commercial_activations"),
    (13, "document_authority"),
]


def ensure_test_client(store: Store, client_id: str = DEFAULT_TEST_CLIENT_ID) -> str:
    """Create the active tenant used by local-ingest fixtures when needed."""

    existing = store.get_client(AllClients(), client_id)
    if existing is None:
        store.create_client(client_id, "Test Client")
    elif existing.status != "active":
        store.set_client_status(AllClients(), client_id, "active")
    return client_id


def ensure_test_clients(store: Store, *client_ids: str) -> tuple[str, ...]:
    """Create every active tenant required by a direct-write fixture."""

    return tuple(ensure_test_client(store, client_id) for client_id in client_ids)


def ingest_local(store: Store, path: Path, *, client_id: str = DEFAULT_TEST_CLIENT_ID) -> int:
    return store.ingest_ticket_file(path, client_id=ensure_test_client(store, client_id))
