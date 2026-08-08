from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_end_user_support_is_optional_scoped_and_status_only(settings) -> None:
    enabled = replace(
        settings,
        demo_mode=False,
        end_user_support_enabled=True,
        end_user_token="end-user-token",
        end_user_client_id="acme",
        end_user_user_id="user-1",
        tech_token="tech-token",
    )
    client = TestClient(create_app(enabled))

    created = client.post(
        "/end-user/tickets",
        headers=_auth("end-user-token"),
        json={"subject": "Cannot sign in", "body": "MFA is blocked; password=do-not-store"},
    )
    ticket_id = created.json()["ticket_id"]
    status = client.get(f"/end-user/tickets/{ticket_id}", headers=_auth("end-user-token"))
    escalated = client.post(
        f"/end-user/tickets/{ticket_id}/escalate",
        headers=_auth("end-user-token"),
    )
    technician = client.post(
        "/end-user/tickets",
        headers=_auth("tech-token"),
        json={"subject": "not allowed", "body": "not allowed"},
    )

    assert created.status_code == 200
    assert created.json()["status"] == "new"
    assert created.json()["priority"] == "normal"
    assert "password=do-not-store" not in created.text
    assert status.status_code == 200
    assert status.json()["ticket_id"] == ticket_id
    assert escalated.status_code == 200
    assert escalated.json()["status"] == "escalated"
    assert technician.status_code == 403

    stored = Store(enabled.data_path).get_ticket(ticket_id, client_id="acme")
    assert stored is not None
    assert stored.requester_id == "user-1"


def test_end_user_support_prevents_requester_cross_access_and_is_disabled_by_default(settings) -> None:
    enabled = replace(
        settings,
        demo_mode=False,
        end_user_support_enabled=True,
        end_user_token="end-user-token",
        end_user_client_id="acme",
        end_user_user_id="user-1",
    )
    client = TestClient(create_app(enabled))
    created = client.post(
        "/end-user/tickets",
        headers=_auth("end-user-token"),
        json={"subject": "Printer issue", "body": "Printer is offline"},
    )
    ticket_id = created.json()["ticket_id"]

    other_identity = replace(enabled, end_user_token="other-token", end_user_user_id="user-2")
    other_client = TestClient(create_app(other_identity))
    hidden = other_client.get(f"/end-user/tickets/{ticket_id}", headers=_auth("other-token"))
    malformed = client.get("/end-user/tickets/not a ticket", headers=_auth("end-user-token"))
    missing_ticket_escalation = client.post(
        "/end-user/tickets/EUS-missing/escalate",
        headers=_auth("end-user-token"),
    )
    malformed_escalation = client.post(
        "/end-user/tickets/not a ticket/escalate",
        headers=_auth("end-user-token"),
    )

    disabled = TestClient(create_app(settings))
    disabled_response = disabled.post(
        "/end-user/tickets",
        json={"subject": "Disabled", "body": "Disabled"},
    )
    unscoped = TestClient(
        create_app(
            replace(
                enabled,
                end_user_client_id="",
                end_user_user_id="",
                end_user_token="unscoped-token",
            )
        )
    )
    unscoped_response = unscoped.post(
        "/end-user/tickets",
        headers=_auth("unscoped-token"),
        json={"subject": "Unscoped", "body": "Unscoped"},
    )
    unscoped_status = unscoped.get(
        "/end-user/tickets/EUS-missing",
        headers=_auth("unscoped-token"),
    )
    unscoped_escalation = unscoped.post(
        "/end-user/tickets/EUS-missing/escalate",
        headers=_auth("unscoped-token"),
    )

    assert created.status_code == 200
    assert hidden.status_code == 404
    assert malformed.status_code == 404
    assert missing_ticket_escalation.status_code == 404
    assert malformed_escalation.status_code == 404
    assert disabled_response.status_code == 403
    assert unscoped_response.status_code == 403
    assert unscoped_status.status_code == 404
    assert unscoped_escalation.status_code == 403


def test_end_user_store_rejects_unscoped_creation_and_missing_owned_ticket(settings) -> None:
    store = Store(settings.data_path)

    try:
        store.create_end_user_ticket(
            client_id="",
            requester_id="user-1",
            subject="subject",
            body="body",
        )
    except ValueError as exc:
        assert "client scope" in str(exc)
    else:
        raise AssertionError("unscoped end-user ticket creation should fail")
    try:
        store.create_end_user_ticket(
            client_id="acme",
            requester_id=" ",
            subject="subject",
            body="body",
        )
    except ValueError as exc:
        assert "requester identity" in str(exc)
    else:
        raise AssertionError("unidentified end-user ticket creation should fail")

    assert store.get_end_user_ticket(
        "EUS-missing", client_id="acme", requester_id="user-1"
    ) is None
    assert store.escalate_end_user_ticket(
        "EUS-missing", client_id="acme", requester_id="user-1"
    ) is None


def test_end_user_store_reports_unreadable_persistence(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    monkeypatch.setattr(store, "get_ticket", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="not persisted"):
        store.create_end_user_ticket(
            client_id="acme",
            requester_id="user-1",
            subject="subject",
            body="body",
        )
