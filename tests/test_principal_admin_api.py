from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import wait_local_agent.rbac as rbac_module
from wait_local_agent.api.app import create_app
from wait_local_agent.api.auth_routes import (
    PrincipalPatchRequest,
    _credential_created_at,
    _principal_view_by_id,
    _store,
)
from wait_local_agent.rbac import AuthContext, Role, resolve_auth_context
from wait_local_agent.store import PrincipalInvariantError, Store, hash_credential


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _secure(settings):
    return replace(settings, demo_mode=False, admin_token="bootstrap-admin", client_id="alpha")


def _seed_operator(store: Store, principal_id: str = "operator", token: str = "operator-secret") -> None:
    store.create_principal(principal_id, kind="staff", display_name="Operator")
    store.add_principal_credential(principal_id, token)
    store.add_principal_global_role(principal_id)


def _route_endpoint(application, path: str, method: str):
    from fastapi import routing as fastapi_routing
    from fastapi.routing import APIRoute
    from starlette.routing import Mount, Route

    included_router_type = getattr(fastapi_routing, "_IncludedRouter", None)

    def join_path(prefix: str, route_path: str) -> str:
        if not prefix:
            return route_path
        return f"{prefix.rstrip('/')}/{route_path.lstrip('/')}"

    def visit(routes, path_prefix: str = ""):
        for route in routes:
            if included_router_type is not None and isinstance(route, included_router_type):
                for route_context in route.effective_route_contexts():
                    original_route = route_context.original_route
                    if not isinstance(original_route, (APIRoute, Route)):
                        continue
                    full_path = join_path(path_prefix, route_context.path)
                    if full_path == path and method in (route_context.methods or set()):
                        return original_route.endpoint
                continue
            if isinstance(route, Mount):
                endpoint = visit(route.routes, join_path(path_prefix, route.path))
                if endpoint is not None:
                    return endpoint
                continue
            if not isinstance(route, (APIRoute, Route)):
                continue
            if join_path(path_prefix, route.path) == path and method in (route.methods or set()):
                return route.endpoint
        return None

    endpoint = visit(application.routes)
    if endpoint is not None:
        return endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _request_for(application) -> Request:
    return Request(
        {
            "type": "http",
            "app": application,
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
    )


def _operator_context() -> AuthContext:
    return AuthContext(
        role=Role.ADMIN,
        presented_token="operator-secret",
        principal_id="operator",
        is_msp_admin=True,
    )


def test_principal_management_crud_credentials_roles_and_audit(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    _seed_operator(store)
    client = TestClient(create_app(secure))

    created = client.post(
        "/auth/principals",
        headers=_auth("operator-secret"),
        json={"principal_id": "tech", "kind": "staff", "display_name": "Technician"},
    )
    assert created.status_code == 200
    assert created.json()["principal_id"] == "tech"
    assert created.json()["credentials"] == []

    added = client.post(
        "/auth/principals/tech/client-roles",
        headers=_auth("operator-secret"),
        json={"client_id": "alpha", "role": "technician"},
    )
    assert added.status_code == 200
    assert added.json()["client_roles"] == [["alpha", "technician"]]
    assert resolve_auth_context(secure, "Bearer operator-secret", store).is_msp_admin is True

    global_role = client.post(
        "/auth/principals/tech/global-roles",
        headers=_auth("operator-secret"),
        json={"role": "msp_admin"},
    )
    assert global_role.status_code == 200
    assert global_role.json()["global_roles"] == ["msp_admin"]
    store.add_principal_client_role("tech", "beta", "viewer")

    issued = client.post("/auth/principals/tech/credentials", headers=_auth("operator-secret"))
    assert issued.status_code == 200
    token = issued.json()["token"]
    credential_hash = issued.json()["credential_hash"]
    assert len(token) >= 32
    assert token not in client.get("/auth/principals", headers=_auth("operator-secret")).text
    assert store.find_principal_by_credential_hash(hash_credential(token)) is not None

    patched = client.patch(
        "/auth/principals/tech",
        headers=_auth("operator-secret"),
        json={"display_name": "Senior Technician"},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Senior Technician"

    revoked = client.post(
        "/auth/principals/tech/credentials/revoke",
        headers=_auth("operator-secret"),
        json={"credential_hash": credential_hash},
    )
    assert revoked.status_code == 200
    assert store.find_principal_by_credential_hash(hash_credential(token)) is None

    removed_role = client.request(
        "DELETE",
        "/auth/principals/tech/client-roles",
        headers=_auth("operator-secret"),
        json={"client_id": "alpha", "role": "technician"},
    )
    removed_global = client.request(
        "DELETE",
        "/auth/principals/tech/global-roles",
        headers=_auth("operator-secret"),
        json={"role": "msp_admin"},
    )
    assert removed_role.status_code == 200
    assert removed_global.status_code == 200
    assert removed_global.json()["global_roles"] == []

    event_types = [event.event_type for event in store.list_audit_events()]
    assert event_types == list(reversed([
        "principal.created",
        "principal.client_role.added",
        "principal.global_role.added",
        "principal.credential.issued",
        "principal.updated",
        "principal.credential.revoked",
        "principal.client_role.removed",
        "principal.global_role.removed",
    ]))


def test_principal_management_is_double_gated_and_has_self_lockout_guards(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    _seed_operator(store)
    store.create_principal("client-admin", kind="staff", display_name="Client admin")
    store.add_principal_credential("client-admin", "client-admin-secret")
    store.add_principal_client_role("client-admin", "alpha", "admin")
    client = TestClient(create_app(secure))

    assert client.get("/auth/principals", headers=_auth("client-admin-secret")).status_code == 403
    assert client.post(
        "/auth/principals",
        headers=_auth("operator-secret"),
        json={"principal_id": "new", "kind": "staff", "display_name": "New"},
    ).status_code == 200

    self_deactivate = client.patch(
        "/auth/principals/operator",
        headers=_auth("operator-secret"),
        json={"active": False},
    )
    self_demote = client.request(
        "DELETE",
        "/auth/principals/operator/global-roles",
        headers=_auth("operator-secret"),
        json={"role": "msp_admin"},
    )
    assert self_deactivate.status_code == 409
    assert self_demote.status_code == 409
    assert store.find_principal_by_credential_hash(hash_credential("operator-secret")) is not None


def test_principal_management_rejects_msp_admin_for_customer_principal(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    _seed_operator(store)
    store.create_principal("customer", kind="customer", display_name="Customer")
    client = TestClient(create_app(secure))

    response = client.post(
        "/auth/principals/customer/global-roles",
        headers=_auth("operator-secret"),
        json={"role": "msp_admin"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "only staff principals can receive the msp_admin role"
    customer = next(item for item in store.list_principals_with_details() if item.principal_id == "customer")
    assert customer.global_roles == ()


def test_principal_management_rejects_customer_membership_on_second_client(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    _seed_operator(store)
    store.create_principal("customer", kind="customer", display_name="Customer")
    store.add_principal_client_role("customer", "alpha", "viewer")
    client = TestClient(create_app(secure))

    response = client.post(
        "/auth/principals/customer/client-roles",
        headers=_auth("operator-secret"),
        json={"client_id": "beta", "role": "viewer"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "customer principals can belong to exactly one client"
    customer = next(item for item in store.list_principals_with_details() if item.principal_id == "customer")
    assert customer.client_roles == (("alpha", "viewer"),)


def test_principal_management_rejects_active_final_client_role_removal(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    _seed_operator(store)
    store.create_principal("target", kind="staff", display_name="Target")
    store.add_principal_client_role("target", "alpha", "viewer")
    client = TestClient(create_app(secure))

    response = client.request(
        "DELETE",
        "/auth/principals/target/client-roles",
        headers=_auth("operator-secret"),
        json={"client_id": "alpha", "role": "viewer"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "an active principal must retain a client role or the msp_admin role"
    target = next(item for item in store.list_principals_with_details() if item.principal_id == "target")
    assert target.client_roles == (("alpha", "viewer"),)


def test_principal_management_rejects_authenticated_final_client_scope_removal(settings, monkeypatch) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_principal("self", kind="staff", display_name="Self")
    store.add_principal_credential("self", "self-scope-token")
    store.add_principal_client_role("self", "alpha", "admin")
    client = TestClient(create_app(secure))
    monkeypatch.setattr(
        rbac_module,
        "resolve_auth_context",
        lambda *_args, **_kwargs: AuthContext(
            role=Role.ADMIN,
            presented_token="self-scope-token",
            principal_id="self",
            is_msp_admin=True,
        ),
    )

    response = client.request(
        "DELETE",
        "/auth/principals/self/client-roles",
        headers=_auth("self-scope-token"),
        json={"client_id": "alpha", "role": "admin"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "the authenticated principal cannot remove its final access scope"
    assert store.list_principals_with_details()[0].client_roles == (("alpha", "admin"),)


def test_principal_management_rejects_credential_for_inactive_principal(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    _seed_operator(store)
    store.create_principal("inactive", kind="staff", display_name="Inactive")
    store.set_principal_active("inactive", False)
    client = TestClient(create_app(secure))

    response = client.post(
        "/auth/principals/inactive/credentials",
        headers=_auth("operator-secret"),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "inactive principals cannot receive credentials"
    assert store.list_principal_credentials("inactive") == []


def test_principal_management_preserves_last_active_msp_admin_credential(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_principal("sole-admin", kind="staff", display_name="Sole admin")
    credential_hash = store.add_principal_credential("sole-admin", "sole-admin-token")
    store.add_principal_global_role("sole-admin")
    client = TestClient(create_app(secure))
    headers = _auth("bootstrap-admin")

    deactivated = client.patch(
        "/auth/principals/sole-admin",
        headers=headers,
        json={"active": False},
    )
    revoked = client.post(
        "/auth/principals/sole-admin/credentials/revoke",
        headers=headers,
        json={"credential_hash": credential_hash},
    )
    removed = client.request(
        "DELETE",
        "/auth/principals/sole-admin/global-roles",
        headers=headers,
        json={"role": "msp_admin"},
    )

    expected = "the final active msp_admin credential cannot be removed"
    assert deactivated.status_code == 409
    assert deactivated.json()["detail"] == expected
    assert revoked.status_code == 409
    assert revoked.json()["detail"] == expected
    assert removed.status_code == 409
    assert removed.json()["detail"] == expected
    assert store.has_msp_admin_credential() is True


def test_principal_management_allows_non_final_msp_admin_credential_and_role_changes(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    _seed_operator(store)
    store.create_principal("target", kind="staff", display_name="Target")
    first_hash = store.add_principal_credential("target", "target-first-token")
    store.add_principal_credential("target", "target-second-token")
    store.add_principal_client_role("target", "alpha", "admin")
    store.add_principal_global_role("target")

    store.revoke_principal_credential(first_hash)
    store.remove_principal_global_role("target")

    target = next(item for item in store.list_principals_with_details() if item.principal_id == "target")
    assert target.global_roles == ()
    assert target.client_roles == (("alpha", "admin"),)


def test_principal_management_rejects_global_role_removal_without_another_scope(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    _seed_operator(store)
    store.create_principal("target", kind="staff", display_name="Target")
    store.add_principal_global_role("target")
    client = TestClient(create_app(secure))

    response = client.request(
        "DELETE",
        "/auth/principals/target/global-roles",
        headers=_auth("operator-secret"),
        json={"role": "msp_admin"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "an active principal must retain a client role or the msp_admin role"


def test_principal_store_rejects_deactivation_of_final_active_msp_admin(settings) -> None:
    store = Store(settings.data_path)
    store.create_principal("sole-admin", kind="staff", display_name="Sole admin")
    store.add_principal_credential("sole-admin", "sole-admin-token")
    store.add_principal_global_role("sole-admin")

    with pytest.raises(PrincipalInvariantError, match="final active msp_admin credential"):
        store.set_principal_active("sole-admin", False)

    sole_admin = next(item for item in store.list_principals_with_details() if item.principal_id == "sole-admin")
    assert sole_admin.active is True


def test_principal_store_revokes_credential_by_unique_hash_prefix(settings) -> None:
    store = Store(settings.data_path)
    _seed_operator(store)
    store.create_principal("target", kind="staff", display_name="Target")
    credential_hash = store.add_principal_credential("target", "target-prefix-token")
    store.add_principal_global_role("target")

    store.revoke_principal_credential(credential_hash[:12])

    credentials = store.list_principal_credentials("target")
    assert len(credentials) == 1
    assert credentials[0].active is False


def test_principal_store_rejects_unmatched_credential_hash_prefix(settings) -> None:
    store = Store(settings.data_path)
    _seed_operator(store)

    with pytest.raises(KeyError) as missing:
        store.revoke_principal_credential("missing-prefix")

    assert missing.value.args == ("missing-prefix",)


def test_principal_store_rejects_client_role_removal_for_missing_principal(settings) -> None:
    store = Store(settings.data_path)

    with pytest.raises(KeyError) as missing:
        store.remove_principal_client_role("missing", "alpha", "viewer")

    assert missing.value.args == ("missing",)


def test_principal_store_rejects_global_role_removal_for_missing_principal(settings) -> None:
    store = Store(settings.data_path)

    with pytest.raises(KeyError) as missing:
        store.remove_principal_global_role("missing")

    assert missing.value.args == ("missing",)


def test_principal_management_refuses_all_writes_in_demo_mode(settings) -> None:
    client = TestClient(create_app(replace(settings, demo_mode=True, client_id="demo")))
    paths = [
        ("post", "/auth/principals", {"principal_id": "x", "kind": "staff", "display_name": "X"}),
        ("patch", "/auth/principals/demo", {"active": False}),
        ("post", "/auth/principals/demo/credentials", None),
        ("post", "/auth/principals/demo/credentials/revoke", {"credential_hash": "abc"}),
        ("post", "/auth/principals/demo/client-roles", {"client_id": "demo", "role": "viewer"}),
        ("delete", "/auth/principals/demo/client-roles", {"client_id": "demo", "role": "viewer"}),
        ("post", "/auth/principals/demo/global-roles", {"role": "msp_admin"}),
        ("delete", "/auth/principals/demo/global-roles", {"role": "msp_admin"}),
    ]
    for method, path, payload in paths:
        if method == "delete":
            response = client.request("DELETE", path, json=payload)
        else:
            response = (
                getattr(client, method)(path, json=payload)
                if payload is not None
                else getattr(client, method)(path)
            )
        assert response.status_code == 403, (method, path, response.text)


def test_principal_management_maps_store_errors_and_unusual_ids(settings, monkeypatch) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    _seed_operator(store)
    store.create_principal("target", kind="staff", display_name="Target")
    store.create_principal("inactive", kind="staff", display_name="Inactive")
    store.set_principal_active("inactive", False)
    client = TestClient(create_app(secure))

    def fail_create_value(self, *args, **kwargs):
        raise ValueError("invalid principal")

    monkeypatch.setattr(Store, "create_principal", fail_create_value)
    value_create = client.post(
        "/auth/principals",
        headers=_auth("operator-secret"),
        json={"principal_id": "value", "kind": "staff", "display_name": "Value"},
    )
    assert value_create.status_code == 422

    def fail_create_integrity(self, *args, **kwargs):
        raise sqlite3.IntegrityError("duplicate")

    monkeypatch.setattr(Store, "create_principal", fail_create_integrity)
    duplicate_create = client.post(
        "/auth/principals",
        headers=_auth("operator-secret"),
        json={"principal_id": "duplicate", "kind": "staff", "display_name": "Duplicate"},
    )
    assert duplicate_create.status_code == 409

    no_patch_fields = client.patch(
        "/auth/principals/target",
        headers=_auth("operator-secret"),
        json={},
    )
    assert no_patch_fields.status_code == 422

    update_application = create_app(secure)
    update_endpoint = _route_endpoint(update_application, "/auth/principals/{principal_id}", "PATCH")
    with pytest.raises(HTTPException) as blank_id:
        update_endpoint(
            "",
            PrincipalPatchRequest(active=True),
            _request_for(update_application),
            _operator_context(),
        )
    assert blank_id.value.status_code == 404

    def fail_active_key(self, *args, **kwargs):
        raise KeyError("target")

    monkeypatch.setattr(Store, "set_principal_active", fail_active_key)
    key_update = client.patch(
        "/auth/principals/target",
        headers=_auth("operator-secret"),
        json={"active": True},
    )
    assert key_update.status_code == 404

    def fail_display_value(self, *args, **kwargs):
        raise ValueError("invalid display name")

    monkeypatch.setattr(Store, "set_principal_display_name", fail_display_value)
    value_update = client.patch(
        "/auth/principals/target",
        headers=_auth("operator-secret"),
        json={"display_name": "Renamed"},
    )
    assert value_update.status_code == 422

    assert client.post(
        "/auth/principals/missing/credentials",
        headers=_auth("operator-secret"),
    ).status_code == 404
    assert client.post(
        "/auth/principals/inactive/credentials",
        headers=_auth("operator-secret"),
    ).status_code == 409

    target_hash = store.add_principal_credential("target", "target-secret")
    foreign_hash = hash_credential("operator-secret")
    assert client.post(
        "/auth/principals/missing/credentials/revoke",
        headers=_auth("operator-secret"),
        json={"credential_hash": target_hash},
    ).status_code == 404
    assert client.post(
        "/auth/principals/target/credentials/revoke",
        headers=_auth("operator-secret"),
        json={"credential_hash": foreign_hash},
    ).status_code == 404

    def fail_revoke_key(self, *args, **kwargs):
        raise KeyError("credential")

    monkeypatch.setattr(Store, "revoke_principal_credential", fail_revoke_key)
    key_revoke = client.post(
        "/auth/principals/target/credentials/revoke",
        headers=_auth("operator-secret"),
        json={"credential_hash": target_hash},
    )
    assert key_revoke.status_code == 404


def test_principal_management_maps_role_errors_and_missing_resources(settings, monkeypatch) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    _seed_operator(store)
    store.create_principal("target", kind="staff", display_name="Target")
    client = TestClient(create_app(secure))
    headers = _auth("operator-secret")

    assert client.post(
        "/auth/principals/missing/client-roles",
        headers=headers,
        json={"client_id": "alpha", "role": "viewer"},
    ).status_code == 404
    for client_id in (" ", "__quarantine__"):
        assert client.post(
            "/auth/principals/target/client-roles",
            headers=headers,
            json={"client_id": client_id, "role": "viewer"},
        ).status_code == 404
    assert client.post(
        "/auth/principals/target/client-roles",
        headers=headers,
        json={"client_id": "missing", "role": "viewer"},
    ).status_code == 404

    store.add_principal_client_role("target", "alpha", "viewer")
    assert client.post(
        "/auth/principals/target/client-roles",
        headers=headers,
        json={"client_id": "alpha", "role": "viewer"},
    ).status_code == 409

    def fail_client_role_value(self, *args, **kwargs):
        raise ValueError("unsupported client role")

    monkeypatch.setattr(Store, "add_principal_client_role", fail_client_role_value)
    value_client_role = client.post(
        "/auth/principals/target/client-roles",
        headers=headers,
        json={"client_id": "alpha", "role": "technician"},
    )
    assert value_client_role.status_code == 422

    assert client.request(
        "DELETE",
        "/auth/principals/missing/client-roles",
        headers=headers,
        json={"client_id": "alpha", "role": "viewer"},
    ).status_code == 404
    assert client.request(
        "DELETE",
        "/auth/principals/target/client-roles",
        headers=headers,
        json={"client_id": "missing", "role": "viewer"},
    ).status_code == 404
    assert client.request(
        "DELETE",
        "/auth/principals/target/client-roles",
        headers=headers,
        json={"client_id": " ", "role": "viewer"},
    ).status_code == 422

    assert client.post(
        "/auth/principals/missing/global-roles",
        headers=headers,
        json={"role": "msp_admin"},
    ).status_code == 404
    store.add_principal_global_role("target")
    assert client.post(
        "/auth/principals/target/global-roles",
        headers=headers,
        json={"role": "msp_admin"},
    ).status_code == 409

    def fail_global_role_value(self, *args, **kwargs):
        raise ValueError("unsupported global role")

    with monkeypatch.context() as patch:
        patch.setattr(Store, "add_principal_global_role", fail_global_role_value)
        value_global_role = client.post(
            "/auth/principals/target/global-roles",
            headers=headers,
            json={"role": "msp_admin"},
        )
    assert value_global_role.status_code == 422

    assert client.request(
        "DELETE",
        "/auth/principals/missing/global-roles",
        headers=headers,
        json={"role": "msp_admin"},
    ).status_code == 404

    assert client.request(
        "DELETE",
        "/auth/principals/target/global-roles",
        headers=headers,
        json={"role": "msp_admin"},
    ).status_code == 200
    assert client.request(
        "DELETE",
        "/auth/principals/target/global-roles",
        headers=headers,
        json={"role": "msp_admin"},
    ).status_code == 404

    def fail_remove_global_value(self, *args, **kwargs):
        raise ValueError("unsupported global role")

    monkeypatch.setattr(Store, "remove_principal_global_role", fail_remove_global_value)
    value_remove_global = client.request(
        "DELETE",
        "/auth/principals/target/global-roles",
        headers=headers,
        json={"role": "msp_admin"},
    )
    assert value_remove_global.status_code == 422


def test_principal_auth_defensive_helpers_report_unavailable_state(settings) -> None:
    secure = _secure(settings)
    application = create_app(secure)
    application.state.store = object()
    with pytest.raises(HTTPException) as unavailable:
        _store(_request_for(application))
    assert unavailable.value.status_code == 503

    store = Store(secure.data_path)
    with pytest.raises(HTTPException) as missing_view:
        _principal_view_by_id(store, "missing")
    assert missing_view.value.status_code == 404

    with pytest.raises(RuntimeError, match="credential was not persisted"):
        _credential_created_at(store, "missing", "credential-hash")
