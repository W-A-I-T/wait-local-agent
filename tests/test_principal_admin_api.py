from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.rbac import resolve_auth_context
from wait_local_agent.store import Store, hash_credential


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _secure(settings):
    return replace(settings, demo_mode=False, admin_token="bootstrap-admin", client_id="alpha")


def _seed_operator(store: Store, principal_id: str = "operator", token: str = "operator-secret") -> None:
    store.create_principal(principal_id, kind="staff", display_name="Operator")
    store.add_principal_credential(principal_id, token)
    store.add_principal_global_role(principal_id)


def test_principal_management_crud_credentials_roles_and_audit(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
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
