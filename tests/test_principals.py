from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.rbac import Role, resolve_auth_context
from wait_local_agent.store import Store, hash_credential


def test_principals_migration_is_additive_and_credentials_are_hashed(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_principal("customer-a")
    stored_hash = store.add_principal_credential("customer-a", "customer-secret")
    store.add_principal_client_role("customer-a", "client-a", "viewer")

    with sqlite3.connect(store.path) as connection:
        versions = connection.execute("select version, name from schema_migrations order by version").fetchall()
        assert versions == [(0, "baseline"), (1, "principals")]
        assert connection.execute(
            "select credential_hash from principal_credentials where principal_id = 'customer-a'"
        ).fetchone() == (hash_credential("customer-secret"),)
        assert connection.execute(
            "select 1 from principal_credentials where credential_hash = 'customer-secret'"
        ).fetchone() is None
    assert stored_hash == hash_credential("customer-secret")


def test_principal_resolution_uses_memberships_and_denies_unknown_credentials(settings) -> None:
    store = Store(settings.data_path)
    store.create_principal("customer-a")
    store.add_principal_credential("customer-a", "customer-secret")
    store.add_principal_client_role("customer-a", "client-a", "admin")
    secured = replace(settings, demo_mode=False, client_id="client-a", admin_token="bootstrap-admin")

    context = resolve_auth_context(secured, "Bearer customer-secret", store)

    assert context.principal_id == "customer-a"
    assert context.role == Role.ADMIN
    assert context.client_id == "client-a"
    assert context.client_ids == frozenset({"client-a"})
    assert context.is_msp_admin is False
    with pytest.raises(HTTPException, match="invalid bearer token"):
        resolve_auth_context(secured, "Bearer unknown", store)


def test_generic_admin_membership_is_not_msp_admin(settings) -> None:
    store = Store(settings.data_path)
    store.create_principal("staff-a", kind="staff")
    store.add_principal_credential("staff-a", "staff-secret")
    store.add_principal_client_role("staff-a", "client-a", "admin")
    store.add_principal_client_role("staff-a", "client-b", "viewer")
    secured = replace(settings, demo_mode=False, client_id="client-a", admin_token="bootstrap-admin")

    context = resolve_auth_context(secured, "Bearer staff-secret", store)

    assert context.role == Role.ADMIN
    assert context.client_ids == frozenset({"client-a", "client-b"})
    assert context.is_msp_admin is False


def test_non_demo_startup_requires_admin_credential(settings) -> None:
    with pytest.raises(RuntimeError, match="without an admin credential"):
        create_app(replace(settings, demo_mode=False))


def test_persisted_msp_admin_credential_allows_non_demo_startup(settings) -> None:
    store = Store(settings.data_path)
    store.create_principal("msp", kind="staff")
    store.add_principal_credential("msp", "msp-secret")
    store.add_principal_global_role("msp")
    app = create_app(replace(settings, demo_mode=False))

    response = TestClient(app).get("/auth/role", headers={"Authorization": "Bearer msp-secret"})

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_demo_mode_is_bounded_and_disables_writes(settings) -> None:
    app = create_app(replace(settings, demo_mode=True, allow_write_actions=True, client_id="demo-client"))
    client = TestClient(app)

    context = resolve_auth_context(app.state.settings, None, app.state.store)
    secrets = client.get("/secrets")

    assert context.client_id == "demo-client"
    assert context.client_ids == frozenset({"demo-client"})
    assert context.is_msp_admin is False
    assert app.state.settings.allow_write_actions is False
    assert secrets.status_code == 403
