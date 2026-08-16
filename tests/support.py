from __future__ import annotations

from pathlib import Path

from wait_local_agent.client_scope import AllClients
from wait_local_agent.store import Store

DEFAULT_TEST_CLIENT_ID = "acme"


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
