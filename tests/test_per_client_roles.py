from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


@pytest.fixture()
def mixed_role_client(live_settings):
    settings = replace(live_settings, client_id="alpha")
    store = Store(settings.data_path)
    for client_id in ("alpha", "beta"):
        store.create_client(client_id, f"Client {client_id.title()}")
    store.create_principal_with_access(
        "mixed-role", kind="staff", display_name="Mixed role operator",
        client_roles=(("alpha", "admin"), ("beta", "viewer")),
        credential="mixed-role-local-fixture",
    )
    with TestClient(create_app(settings)) as client:
        yield client, store


def _sign_in(client: TestClient, method: str) -> dict[str, str]:
    if method == "bearer":
        return {"Authorization": "Bearer mixed-role-local-fixture"}
    response = client.post("/auth/login/local", json={"token": "mixed-role-local-fixture"})
    assert response.status_code == 200
    assert response.json()["session_created"] is True
    return {"X-WAIT-CSRF": "1"}


@pytest.mark.parametrize("method", ["bearer", "session"])
def test_client_selection_resolves_its_own_role_and_preserves_directory(mixed_role_client, method) -> None:
    client, _ = mixed_role_client
    auth = _sign_in(client, method)
    for client_id, expected_role in (("alpha", "admin"), ("beta", "viewer")):
        headers = {**auth, "X-WAIT-Client-ID": client_id}
        for endpoint in ("/auth/role", "/auth/session"):
            response = client.get(endpoint, headers=headers)
            assert response.status_code == 200
            assert response.json()["role"] == expected_role
            assert response.json()["client_id"] == client_id
            assert response.json()["client_ids"] == ["alpha", "beta"]
        directory = client.get("/clients", headers=headers)
        assert directory.status_code == 200
        assert {row["client_id"] for row in directory.json()} == {"alpha", "beta"}


@pytest.mark.parametrize("method", ["bearer", "session"])
@pytest.mark.parametrize("hint", ["none", "beta", "alpha"])
def test_viewer_membership_cannot_create_chat_using_another_clients_role(mixed_role_client, method, hint) -> None:
    client, store = mixed_role_client
    headers = _sign_in(client, method)
    if hint != "none":
        headers["X-WAIT-Client-ID"] = hint
    response = client.post("/technician/chat/sessions", headers=headers, json={"client_id": "beta"})
    assert response.status_code == 403
    assert store.list_technician_chat_sessions(client_id="beta") == []


@pytest.mark.parametrize("method", ["bearer", "session"])
def test_selected_administrator_can_work_only_in_selected_client(mixed_role_client, method) -> None:
    client, _ = mixed_role_client
    headers = {**_sign_in(client, method), "X-WAIT-Client-ID": "alpha"}
    response = client.post("/technician/chat/sessions", headers=headers, json={"client_id": "alpha"})
    assert response.status_code == 200
    assert response.json()["client_id"] == "alpha"
    headers["X-WAIT-Client-ID"] = "beta"
    assert client.get("/settings/security", headers=headers).status_code == 403


@pytest.mark.parametrize("hint", [None, "beta", "alpha"])
def test_viewer_membership_cannot_approve_another_clients_action(mixed_role_client, hint) -> None:
    client, store = mixed_role_client
    approval = store.create_approval_request("beta-record", "ticket.assign", {}, client_id="beta")
    headers = _sign_in(client, "bearer")
    if hint:
        headers["X-WAIT-Client-ID"] = hint
    response = client.post(f"/approval-requests/{approval.id}", headers=headers, json={"status": "approved"})
    assert response.status_code == 403
    persisted = store.get_approval_request(approval.id)
    assert persisted is not None
    assert persisted.status == "pending"
    assert persisted.approver_id is None


def test_unselected_mixed_role_context_uses_least_privilege(mixed_role_client) -> None:
    client, _ = mixed_role_client
    response = client.get("/auth/role", headers=_sign_in(client, "bearer"))
    assert response.status_code == 200
    assert response.json()["role"] == "viewer"


def test_conflicting_header_and_query_cannot_choose_a_more_privileged_role(mixed_role_client) -> None:
    client, _ = mixed_role_client
    response = client.get(
        "/settings/security?client_id=beta",
        headers={**_sign_in(client, "bearer"), "X-WAIT-Client-ID": "alpha"},
    )
    assert response.status_code == 400
