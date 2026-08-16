from __future__ import annotations

from dataclasses import replace
from typing import Literal, cast

import pytest
from fastapi.testclient import TestClient

import wait_local_agent.store as store_module
from wait_local_agent.api.app import create_app
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_tickets(store: Store) -> None:
    with store._connect() as connection:  # noqa: SLF001
        connection.executemany(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("TCK-ACME", "Acme", "MFA reset", "Sign-in blocked", "High", "Open", "acme"),
                ("TCK-BETA", "Beta", "MFA reset", "Sign-in blocked", "High", "Open", "beta"),
            ],
        )


def test_chat_session_store_is_tenant_and_principal_scoped_and_redacted(settings) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    session = store.create_technician_chat_session(
        client_id="acme",
        principal_id="technician-1",
        ticket_id="TCK-ACME",
    )

    assert session.id.startswith("TCS-")
    assert store.get_technician_chat_session(
        session.id, client_id="acme", principal_id="technician-1"
    ) is not None
    assert store.get_technician_chat_session(
        session.id, client_id="beta", principal_id="technician-1"
    ) is None
    assert store.get_technician_chat_session(
        session.id, client_id="acme", principal_id="technician-2"
    ) is None

    user_message = store.add_technician_chat_message(
        session.id,
        role="user",
        message="triage TCK-ACME token=should-not-leak",
        status="received",
        ticket_id="TCK-ACME",
        client_id="acme",
        principal_id="technician-1",
    )
    assistant_message = store.add_technician_chat_message(
        session.id,
        role="assistant",
        message="Triage completed",
        action_id="ticket-triage",
        status="success",
        ticket_id="TCK-ACME",
        client_id="acme",
        principal_id="technician-1",
    )

    assert user_message.message == "triage TCK-ACME token=[redacted]"
    assert assistant_message.action_id == "ticket-triage"
    assert len(store.list_technician_chat_messages(session.id, client_id="beta")) == 0
    assert store.update_technician_chat_session_ticket(
        session.id,
        client_id="acme",
        ticket_id="TCK-BETA",
        principal_id="technician-1",
    ) is None

    closed = store.close_technician_chat_session(
        session.id,
        client_id="acme",
        principal_id="technician-1",
    )
    assert closed is not None and closed.status == "closed"
    with pytest.raises(ValueError, match="closed"):
        store.add_technician_chat_message(
            session.id,
            role="user",
            message="triage TCK-ACME",
            status="received",
            client_id="acme",
            principal_id="technician-1",
        )


def test_chat_session_store_rejects_unscoped_or_invalid_inputs(settings) -> None:
    store = Store(settings.data_path)
    with pytest.raises(ValueError, match="client scope"):
        store.create_technician_chat_session(client_id="", principal_id="tech")
    with pytest.raises(ValueError, match="principal"):
        store.create_technician_chat_session(client_id="acme", principal_id="")
    with pytest.raises(LookupError):
        store.create_technician_chat_session(
            client_id="acme", principal_id="tech", ticket_id="TCK-MISSING"
        )
    session = store.create_technician_chat_session(client_id="acme", principal_id="tech")
    with pytest.raises(ValueError, match="role is invalid"):
        store.add_technician_chat_message(
            session.id,
            role=cast(Literal["user", "assistant"], "system"),
            message="unsupported",
            status="received",
            client_id="acme",
            principal_id="tech",
        )


def test_chat_session_store_covers_scope_and_message_limits(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    _seed_tickets(store)
    session = store.create_technician_chat_session(client_id="acme", principal_id="tech")

    assert store.get_technician_chat_session(session.id) is not None
    assert store.get_technician_chat_session(session.id, client_id="acme") is not None
    assert store.get_technician_chat_session(session.id, principal_id="tech") is not None
    assert store.get_technician_chat_session("TCS-MISSING") is None
    assert store.list_technician_chat_sessions()
    assert store.list_technician_chat_sessions(client_id="acme")
    assert store.list_technician_chat_sessions(principal_id="tech")

    assert store.update_technician_chat_session_ticket(
        session.id,
        client_id="",
        ticket_id="TCK-ACME",
    ) is None
    assert store.update_technician_chat_session_ticket(
        "TCS-MISSING",
        client_id="acme",
        ticket_id="TCK-ACME",
    ) is None
    assert store.close_technician_chat_session("TCS-MISSING") is None
    with pytest.raises(LookupError):
        store.add_technician_chat_message(
            "TCS-MISSING",
            role="user",
            message="help",
            status="received",
        )
    with pytest.raises(ValueError, match="require message"):
        store.add_technician_chat_message(
            session.id,
            role="user",
            message=" ",
            status="received",
            client_id="acme",
            principal_id="tech",
        )
    with pytest.raises(ValueError, match="require message"):
        store.add_technician_chat_message(
            session.id,
            role="assistant",
            message="help",
            status=" ",
            client_id="acme",
            principal_id="tech",
        )
    with pytest.raises(ValueError, match="too long"):
        store.add_technician_chat_message(
            session.id,
            role="user",
            message="x" * 4001,
            status="received",
            client_id="acme",
            principal_id="tech",
        )
    with pytest.raises(ValueError, match="too long"):
        store.add_technician_chat_message(
            session.id,
            role="user",
            message="help",
            status="x" * 81,
            client_id="acme",
            principal_id="tech",
        )
    with pytest.raises(ValueError, match="too long"):
        store.add_technician_chat_message(
            session.id,
            role="user",
            message="help",
            status="received",
            action_id="x" * 121,
            client_id="acme",
            principal_id="tech",
        )
    monkeypatch.setattr(store_module, "MAX_TECHNICIAN_CHAT_MESSAGES", 0)
    with pytest.raises(ValueError, match="limit"):
        store.add_technician_chat_message(
            session.id,
            role="user",
            message="help",
            status="received",
            client_id="acme",
            principal_id="tech",
        )


def test_chat_session_api_persists_follow_up_context_and_enforces_rbac(settings, monkeypatch) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        client_id="acme",
    )
    store = Store(secure_settings.data_path)
    _seed_tickets(store)
    store.create_principal("acme-technician", kind="staff")
    store.add_principal_credential("acme-technician", "acme-technician-token")
    store.add_principal_client_role("acme-technician", "acme", "technician")
    client = TestClient(create_app(secure_settings))

    created = client.post(
        "/technician/chat/sessions",
        headers=_auth("acme-technician-token"),
        json={"ticket_id": "TCK-ACME"},
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    assert created.json()["messages"] == []

    triage = client.post(
        f"/technician/chat/sessions/{session_id}/messages",
        headers=_auth("acme-technician-token"),
        json={"message": "triage"},
    )
    follow_up = client.post(
        f"/technician/chat/sessions/{session_id}/messages",
        headers=_auth("acme-technician-token"),
        json={"message": "triage again"},
    )
    history = client.get(
        f"/technician/chat/sessions/{session_id}",
        headers=_auth("acme-technician-token"),
    )
    listed = client.get("/technician/chat/sessions", headers=_auth("acme-technician-token"))

    assert triage.status_code == 200
    assert triage.json()["session_id"] == session_id
    assert triage.json()["result"]["output"]["ticket_id"] == "TCK-ACME"
    assert follow_up.status_code == 200
    assert follow_up.json()["result"]["output"]["ticket_id"] == "TCK-ACME"
    assert history.status_code == 200
    assert len(history.json()["messages"]) == 4
    assert listed.status_code == 200 and len(listed.json()) == 1

    help_response = client.post(
        f"/technician/chat/sessions/{session_id}/messages",
        headers=_auth("acme-technician-token"),
        json={"message": "help"},
    )
    assert help_response.status_code == 200
    assert help_response.json()["session_id"] == session_id

    script = client.post(
        f"/technician/chat/sessions/{session_id}/messages",
        headers=_auth("acme-technician-token"),
        json={"message": "run approved script script-1 on device device-1"},
    )
    assert script.status_code == 200
    assert script.json()["action_id"] == "rmm-script-execute"
    assert script.json()["result"]["output"]["script_id"] == "script-1"

    invalid = client.post(
        f"/technician/chat/sessions/{session_id}/messages",
        headers=_auth("acme-technician-token"),
        json={"message": "run arbitrary shell command"},
    )
    history_after_invalid = client.get(
        f"/technician/chat/sessions/{session_id}",
        headers=_auth("acme-technician-token"),
    )
    assert invalid.status_code == 422
    assert history_after_invalid.json()["messages"][-1]["status"] == "failed"

    missing_ticket = client.post(
        f"/technician/chat/sessions/{session_id}/messages",
        headers=_auth("acme-technician-token"),
        json={"message": "triage", "ticket_id": "TCK-MISSING"},
    )
    assert missing_ticket.status_code == 404

    viewer = client.get(
        "/technician/chat/sessions",
        headers=_auth("viewer-token"),
    )
    assert viewer.status_code == 403

    def unavailable(*args, **kwargs):
        raise KeyError("missing action")

    monkeypatch.setattr(SmartActionService, "invoke", unavailable)
    unavailable_action = client.post(
        f"/technician/chat/sessions/{session_id}/messages",
        headers=_auth("acme-technician-token"),
        json={"message": "triage"},
    )
    assert unavailable_action.status_code == 404

    closed = client.post(
        f"/technician/chat/sessions/{session_id}/close",
        headers=_auth("acme-technician-token"),
    )
    rejected = client.post(
        f"/technician/chat/sessions/{session_id}/messages",
        headers=_auth("acme-technician-token"),
        json={"message": "help"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert rejected.status_code == 409


def test_chat_session_api_admin_can_scope_and_cross_tenant_access_is_hidden(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        client_id="acme",
    )
    store = Store(secure_settings.data_path)
    _seed_tickets(store)
    store.create_principal("acme-technician", kind="staff")
    store.add_principal_credential("acme-technician", "acme-technician-token")
    store.add_principal_client_role("acme-technician", "acme", "technician")
    client = TestClient(create_app(secure_settings))

    beta = client.post(
        "/technician/chat/sessions",
        headers=_auth("admin-token"),
        json={"client_id": "beta", "ticket_id": "TCK-BETA"},
    )
    assert beta.status_code == 200
    beta_id = beta.json()["id"]

    no_scope = client.post(
        "/technician/chat/sessions",
        headers=_auth("admin-token"),
        json={},
    )
    tech_cross_tenant = client.get(
        f"/technician/chat/sessions/{beta_id}",
        headers=_auth("acme-technician-token"),
    )
    admin_list = client.get(
        "/technician/chat/sessions",
        headers=_auth("admin-token"),
    )
    admin_get = client.get(
        f"/technician/chat/sessions/{beta_id}",
        headers=_auth("admin-token"),
    )
    missing_get = client.get(
        "/technician/chat/sessions/TCS-MISSING",
        headers=_auth("admin-token"),
    )
    admin_close = client.post(
        f"/technician/chat/sessions/{beta_id}/close",
        headers=_auth("admin-token"),
    )
    missing_close = client.post(
        "/technician/chat/sessions/TCS-MISSING/close",
        headers=_auth("admin-token"),
    )

    assert no_scope.status_code == 403
    assert tech_cross_tenant.status_code == 404
    assert admin_list.status_code == 200
    assert len(admin_list.json()) == 1
    assert admin_get.status_code == 200
    assert missing_get.status_code == 404
    assert admin_close.status_code == 200
    assert admin_close.json()["status"] == "closed"
    assert missing_close.status_code == 404
