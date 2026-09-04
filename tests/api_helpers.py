"""Shared test helpers for API route coverage."""

from __future__ import annotations

from wait_local_agent.halopsa import HaloReadResponse
from wait_local_agent.hudu import HuduReadResponse
from wait_local_agent.models import HaloReadResult
from wait_local_agent.store import Store


def _read_response(items):
    return HaloReadResponse(HaloReadResult("ready", "ok", len(items)), items)


def _hudu_response(items):
    return HuduReadResponse(HaloReadResult("ready", "ok", len(items)), items)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _provision_bound_principal(store: Store, principal_id: str, token: str, client_id: str, role: str) -> None:
    store.create_principal(principal_id, kind="staff")
    store.add_principal_credential(principal_id, token)
    store.add_principal_client_role(principal_id, client_id, role)
