from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.rbac import (
    Role,
    _principal_auth_context,
    admin_credential_configured,
    resolve_auth_context,
    resolve_client_scope,
)
from wait_local_agent.store import PrincipalAuthRecord, Store, hash_credential


def test_principals_migration_is_additive_and_credentials_are_hashed(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_principal("customer-a")
    stored_hash = store.add_principal_credential("customer-a", "customer-secret")
    store.add_principal_client_role("customer-a", "client-a", "viewer")

    with sqlite3.connect(store.path) as connection:
        versions = connection.execute("select version, name from schema_migrations order by version").fetchall()
        assert versions == [
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
        ]
        assert connection.execute(
            "select credential_hash from principal_credentials where principal_id = 'customer-a'"
        ).fetchone() == (hash_credential("customer-secret"),)
        assert connection.execute(
            "select 1 from principal_credentials where credential_hash = 'customer-secret'"
        ).fetchone() is None
    assert stored_hash == hash_credential("customer-secret")


def test_store_principal_credential_accessors_report_msp_admin_and_hits(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    assert store.has_msp_admin_credential() is False
    assert store.find_principal_by_credential_hash(hash_credential("missing")) is None

    store.create_principal("msp-admin", kind="staff")
    credential_hash = store.add_principal_credential("msp-admin", "msp-secret")
    store.add_principal_client_role("msp-admin", "acme", "admin")

    principal = store.find_principal_by_credential_hash(credential_hash)
    assert principal is not None
    assert principal.principal_id == "msp-admin"
    assert principal.principal_kind == "staff"
    assert principal.client_roles == (("acme", "admin"),)
    assert principal.global_roles == frozenset()
    assert store.has_msp_admin_credential() is False

    store.add_principal_global_role("msp-admin")

    assert store.has_msp_admin_credential() is True
    principal = store.find_principal_by_credential_hash(credential_hash)
    assert principal is not None
    assert principal.global_roles == frozenset({"msp_admin"})


def test_store_principal_accessors_reject_invalid_values(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    with pytest.raises(ValueError):
        store.create_principal("", kind="staff")
    with pytest.raises(ValueError):
        store.create_principal("p1", kind="bogus")

    with pytest.raises(ValueError):
        store.add_principal_credential("", "tok")
    with pytest.raises(KeyError):
        store.add_principal_credential("missing-principal", "tok")

    store.create_principal("p1", kind="staff")

    with pytest.raises(ValueError):
        store.add_principal_client_role("", "acme", "admin")
    with pytest.raises(ValueError):
        store.add_principal_client_role("p1", "", "admin")
    with pytest.raises(ValueError):
        store.add_principal_client_role("p1", "acme", "bogus-role")
    with pytest.raises(KeyError):
        store.add_principal_client_role("missing", "acme", "admin")

    with pytest.raises(ValueError):
        store.add_principal_global_role("", "msp_admin")
    with pytest.raises(ValueError):
        store.add_principal_global_role("p1", "not-msp-admin")
    with pytest.raises(KeyError):
        store.add_principal_global_role("missing", "msp_admin")

    store.add_principal_credential("p1", "tok")
    store.add_principal_client_role("p1", "acme", "admin")
    store.add_principal_global_role("p1")

    assert store.has_msp_admin_credential() is True
    principal = store.find_principal_by_credential_hash(hash_credential("tok"))
    assert principal == PrincipalAuthRecord(
        principal_id="p1",
        principal_kind="staff",
        client_roles=(("acme", "admin"),),
        global_roles=frozenset({"msp_admin"}),
    )


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


def test_bootstrap_tokens_are_cross_client_but_principals_remain_bound(settings) -> None:
    secured = replace(
        settings,
        demo_mode=False,
        client_id="client-a",
        api_token="api-bootstrap",
        admin_token="admin-bootstrap",
        tech_token="tech-bootstrap",
        viewer_token="viewer-bootstrap",
    )

    for token, role in (
        ("api-bootstrap", Role.ADMIN),
        ("admin-bootstrap", Role.ADMIN),
        ("tech-bootstrap", Role.TECHNICIAN),
        ("viewer-bootstrap", Role.VIEWER),
    ):
        context = resolve_auth_context(secured, f"Bearer {token}")
        assert context.role == role
        assert context.is_msp_admin is True
        assert resolve_client_scope(context, "client-b").client_id == "client-b"

    technician = resolve_auth_context(secured, "Bearer tech-bootstrap")
    assert technician.client_ids == frozenset({"client-a"})


def test_bound_non_admin_principal_cannot_select_foreign_client(settings) -> None:
    store = Store(settings.data_path)
    store.create_principal("technician-a", kind="staff")
    store.add_principal_credential("technician-a", "technician-a-secret")
    store.add_principal_client_role("technician-a", "client-a", "technician")
    secured = replace(settings, demo_mode=False, client_id="client-a", admin_token="bootstrap-admin")

    context = resolve_auth_context(secured, "Bearer technician-a-secret", store)

    assert context.client_ids == frozenset({"client-a"})
    assert context.is_msp_admin is False
    with pytest.raises(HTTPException, match="outside authenticated scope"):
        resolve_client_scope(context, "client-b")


def test_msp_admin_principal_can_select_any_client(settings) -> None:
    store = Store(settings.data_path)
    store.create_principal("msp", kind="staff")
    store.add_principal_credential("msp", "msp-secret")
    store.add_principal_client_role("msp", "client-a", "viewer")
    store.add_principal_client_role("msp", "client-b", "technician")
    store.add_principal_global_role("msp")
    secured = replace(settings, demo_mode=False, client_id="client-b", admin_token="bootstrap-admin")

    context = resolve_auth_context(secured, "Bearer msp-secret", store)

    assert context.role == Role.ADMIN
    assert context.client_id == "client-b"
    assert context.client_ids == frozenset({"client-a", "client-b"})
    assert context.is_msp_admin is True


def test_principal_resolution_rejects_invalid_memberships_and_roles(settings) -> None:
    secured = replace(settings, demo_mode=False, client_id="client-a", admin_token="bootstrap-admin")

    customer_without_membership = Store(settings.data_path)
    customer_without_membership.create_principal("customer-empty")
    customer_without_membership.add_principal_credential("customer-empty", "empty-secret")
    with pytest.raises(HTTPException, match="invalid client membership"):
        resolve_auth_context(secured, "Bearer empty-secret", customer_without_membership)

    customer_with_multiple_memberships = Store(settings.data_path)
    customer_with_multiple_memberships.create_principal("customer-many")
    customer_with_multiple_memberships.add_principal_credential("customer-many", "many-secret")
    customer_with_multiple_memberships.add_principal_client_role("customer-many", "client-a", "viewer")
    with sqlite3.connect(customer_with_multiple_memberships.path) as connection:
        connection.execute(
            """
            insert into principal_client_roles (principal_id, client_id, role)
            values (?, ?, ?)
            """,
            ("customer-many", "client-b", "viewer"),
        )
    with pytest.raises(HTTPException, match="invalid client membership"):
        resolve_auth_context(secured, "Bearer many-secret", customer_with_multiple_memberships)

    staff_without_membership = Store(settings.data_path)
    staff_without_membership.create_principal("staff-empty", kind="staff")
    staff_without_membership.add_principal_credential("staff-empty", "staff-empty-secret")
    with pytest.raises(HTTPException, match="no client membership"):
        resolve_auth_context(secured, "Bearer staff-empty-secret", staff_without_membership)

    invalid_role = PrincipalAuthRecord(
        principal_id="invalid-role",
        principal_kind="staff",
        client_roles=(("client-a", "not-a-role"),),
        global_roles=frozenset(),
    )
    with pytest.raises(HTTPException, match="invalid role"):
        _principal_auth_context(secured, "invalid-role-secret", invalid_role)


@pytest.mark.parametrize(
    ("api_token", "admin_token", "persisted_msp_admin", "expected"),
    [
        ("", "", False, False),
        ("api-token", "", False, True),
        ("", "admin-token", False, True),
        ("", "", True, True),
    ],
)
def test_admin_credential_configured_checks_bootstrap_and_persisted_credentials(
    settings,
    api_token: str,
    admin_token: str,
    persisted_msp_admin: bool,
    expected: bool,
) -> None:
    store = Store(settings.data_path)
    if persisted_msp_admin:
        store.create_principal("msp", kind="staff")
        store.add_principal_credential("msp", "msp-secret")
        store.add_principal_global_role("msp")

    secured = replace(settings, api_token=api_token, admin_token=admin_token)

    assert admin_credential_configured(secured, store) is expected


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
    assert app.state.settings.allow_power_platform_deployment is False
    assert secrets.status_code == 403
