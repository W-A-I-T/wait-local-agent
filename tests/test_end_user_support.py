from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from wait_local_agent.api.app import _halopsa_client_mapping, _safe_external_ticket_id, create_app
from wait_local_agent.halopsa import HaloReadResponse
from wait_local_agent.models import HaloReadResult, HaloTicket, HaloWriteResult
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
        end_user_brand_name="Acme Support",
        end_user_brand_tagline="Help for Acme teams",
        end_user_brand_logo_data_uri="data:image/png;base64,AA==",
        end_user_brand_accent_color="#123456",
        end_user_brand_surface_color="#abcdef",
        client_id="acme",
        admin_token="admin-token",
        tech_token="tech-token",
    )
    client = TestClient(create_app(enabled))

    branding = client.get("/end-user/config", headers=_auth("end-user-token"))

    created = client.post(
        "/end-user/tickets",
        headers=_auth("end-user-token"),
        json={"subject": "Cannot sign in", "body": "MFA is blocked; password=do-not-store"},
    )
    ticket_id = created.json()["ticket_id"]
    status = client.get(f"/end-user/tickets/{ticket_id}", headers=_auth("end-user-token"))
    message = client.post(
        f"/end-user/tickets/{ticket_id}/messages",
        headers=_auth("end-user-token"),
        json={"body": "Please call me after 3pm"},
    )
    messages = client.get(
        f"/end-user/tickets/{ticket_id}/messages",
        headers=_auth("end-user-token"),
    )
    escalated = client.post(
        f"/end-user/tickets/{ticket_id}/escalate",
        headers=_auth("end-user-token"),
    )
    technician = client.post(
        "/end-user/tickets",
        headers=_auth("tech-token"),
        json={"subject": "not allowed", "body": "not allowed"},
    )
    conversation = client.get(
        f"/tickets/{ticket_id}/end-user-messages",
        headers=_auth("tech-token"),
    )
    support_reply = client.post(
        f"/tickets/{ticket_id}/end-user-messages",
        headers=_auth("tech-token"),
        json={"body": "A technician is reviewing this request."},
    )
    refreshed_messages = client.get(
        f"/end-user/tickets/{ticket_id}/messages",
        headers=_auth("end-user-token"),
    )

    assert created.status_code == 200
    assert branding.status_code == 200
    assert branding.json() == {
        "brand_name": "Acme Support",
        "brand_tagline": "Help for Acme teams",
        "brand_logo_data_uri": "data:image/png;base64,AA==",
        "brand_accent_color": "#123456",
        "brand_surface_color": "#abcdef",
    }
    assert "client_id" not in branding.json()
    assert created.json()["status"] == "new"
    assert created.json()["priority"] == "normal"
    assert created.json()["body"] == "MFA is blocked; password=[redacted]"
    assert "client_id" not in created.json()
    assert "password=do-not-store" not in created.text
    assert status.status_code == 200
    assert status.json()["ticket_id"] == ticket_id
    assert status.json()["body"] == "MFA is blocked; password=[redacted]"
    assert "client_id" not in status.json()
    assert message.status_code == 200
    assert message.json()["body"] == "Please call me after 3pm"
    assert messages.status_code == 200
    assert [item["body"] for item in messages.json()] == ["Please call me after 3pm"]
    assert escalated.status_code == 200
    assert escalated.json()["status"] == "escalated"
    assert technician.status_code == 403
    assert conversation.status_code == 200
    assert [item["role"] for item in conversation.json()] == ["requester"]
    assert support_reply.status_code == 200
    assert support_reply.json()["role"] == "support"
    assert [item["body"] for item in refreshed_messages.json()] == [
        "Please call me after 3pm",
        "A technician is reviewing this request.",
    ]
    stored = Store(enabled.data_path).get_ticket(ticket_id, client_id="acme")
    assert stored is not None
    assert stored.requester_id == "user-1"


def test_end_user_branding_rejects_remote_assets_and_invalid_colors(settings) -> None:
    enabled = replace(
        settings,
        demo_mode=False,
        end_user_support_enabled=True,
        end_user_token="end-user-token",
        end_user_client_id="acme",
        end_user_user_id="user-1",
        admin_token="admin-token",
        end_user_brand_logo_data_uri="https://example.com/logo.png",
        end_user_brand_accent_color="red",
        end_user_brand_surface_color="var(--unsafe)",
    )
    branding = TestClient(create_app(enabled)).get(
        "/end-user/config",
        headers=_auth("end-user-token"),
    )

    assert branding.status_code == 200
    assert branding.json()["brand_logo_data_uri"] == ""
    assert branding.json()["brand_accent_color"] == "#1f6f55"
    assert branding.json()["brand_surface_color"] == "#f3f5f2"


def test_end_user_message_can_create_approved_halopsa_sync(settings, monkeypatch) -> None:
    executed = []

    class FakeHaloClient:
        def __init__(self, _settings) -> None:
            pass

        def get_ticket(self, ticket_id: str) -> HaloReadResponse:
            return HaloReadResponse(
                HaloReadResult("ready", "verified", 1),
                [HaloTicket(ticket_id, "Cannot sign in", "Open", "High", "halo-acme", "Acme")],
            )

        def execute_write(self, request):
            executed.append(request)
            return HaloWriteResult("succeeded", "posted", request.action_type, request.ticket_id)

    enabled = replace(
        settings,
        allow_write_actions=True,
        demo_mode=False,
        end_user_support_enabled=True,
        end_user_token="end-user-token",
        end_user_client_id="acme",
        end_user_user_id="user-1",
        client_id="acme",
        admin_token="admin-token",
        tech_token="tech-token",
        halopsa_client_map_json='{"acme":"halo-acme"}',
    )
    monkeypatch.setattr(app_module, "HaloPSAClient", FakeHaloClient)
    client = TestClient(create_app(enabled))

    created = client.post(
        "/end-user/tickets",
        headers=_auth("end-user-token"),
        json={"subject": "Cannot sign in", "body": "Please investigate this login issue."},
    )
    ticket_id = created.json()["ticket_id"]
    message = client.post(
        f"/end-user/tickets/{ticket_id}/messages",
        headers=_auth("end-user-token"),
        json={"body": "Please investigate this login issue."},
    )
    message_id = message.json()["id"]

    draft = client.post(
        f"/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts",
        headers=_auth("admin-token"),
        json={"external_ticket_id": "HALO-42"},
    )
    duplicate = client.post(
        f"/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts",
        headers=_auth("admin-token"),
        json={"external_ticket_id": "HALO-42"},
    )
    approval_id = draft.json()["approval_request_id"]
    approved = client.post(
        f"/approval-requests/{approval_id}",
        headers=_auth("admin-token"),
        json={"status": "approved", "comment": "Verified against the Acme HaloPSA ticket."},
    )

    assert created.status_code == 200
    assert message.status_code == 200
    assert draft.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["approval_request_id"] == approval_id
    assert draft.json()["payload"]["fields"] == {
        "hiddenfromuser": False,
        "note": "Please investigate this login issue.",
    }
    assert approved.status_code == 200
    assert approved.json()["execution_status"] == "succeeded"
    assert len(executed) == 1
    assert executed[0].ticket_id == "HALO-42"
    assert executed[0].fields["hiddenfromuser"] is False


def test_end_user_halopsa_sync_rejects_invalid_or_out_of_scope_targets(settings, monkeypatch) -> None:
    class FakeHaloClient:
        def __init__(self, _settings) -> None:
            pass

        def get_ticket(self, ticket_id: str) -> HaloReadResponse:
            if ticket_id == "HALO-NOT-READY":
                return HaloReadResponse(HaloReadResult("failed", "provider unavailable", 0), [])
            return HaloReadResponse(
                HaloReadResult("ready", "verified", 1),
                [HaloTicket(ticket_id, "Other ticket", "Open", "Low", "halo-other", "Other")],
            )

    enabled = replace(
        settings,
        demo_mode=False,
        end_user_support_enabled=True,
        end_user_token="end-user-token",
        end_user_client_id="acme",
        end_user_user_id="user-1",
        client_id="acme",
        admin_token="admin-token",
        tech_token="tech-token",
        halopsa_client_map_json='{"acme":"halo-acme"}',
    )
    monkeypatch.setattr(app_module, "HaloPSAClient", FakeHaloClient)
    client = TestClient(create_app(enabled))
    created = client.post(
        "/end-user/tickets",
        headers=_auth("end-user-token"),
        json={"subject": "Sync target checks", "body": "Requester message"},
    )
    ticket_id = created.json()["ticket_id"]
    message_id = client.post(
        f"/end-user/tickets/{ticket_id}/messages",
        headers=_auth("end-user-token"),
        json={"body": "Requester message"},
    ).json()["id"]

    invalid_id = client.post(
        f"/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts",
        headers=_auth("tech-token"),
        json={"external_ticket_id": "HALO/42"},
    )
    mismatch = client.post(
        f"/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts",
        headers=_auth("tech-token"),
        json={"external_ticket_id": "HALO-OTHER"},
    )
    unavailable = client.post(
        f"/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts",
        headers=_auth("tech-token"),
        json={"external_ticket_id": "HALO-NOT-READY"},
    )
    missing_message = client.post(
        f"/tickets/{ticket_id}/end-user-messages/999/halopsa-drafts",
        headers=_auth("tech-token"),
        json={"external_ticket_id": "HALO-42"},
    )
    unmapped = TestClient(create_app(replace(enabled, halopsa_client_map_json=""))).post(
        f"/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts",
        headers=_auth("tech-token"),
        json={"external_ticket_id": "HALO-42"},
    )
    foreign = TestClient(create_app(replace(enabled, client_id="other", tech_token="other-tech"))).post(
        f"/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts",
        headers=_auth("other-tech"),
        json={"external_ticket_id": "HALO-42"},
    )

    assert created.status_code == 200
    assert invalid_id.status_code == 422
    assert mismatch.status_code == 403
    assert unavailable.status_code == 409
    assert missing_message.status_code == 404
    assert unmapped.status_code == 409
    assert foreign.status_code == 404


def test_halopsa_sync_mapping_and_ticket_id_validation(settings) -> None:
    assert _safe_external_ticket_id("HALO-42") is True
    assert _safe_external_ticket_id("") is False
    assert _safe_external_ticket_id("  ") is False
    assert _safe_external_ticket_id("HALO/42") is False
    assert _safe_external_ticket_id("HALO\n42") is False
    assert _safe_external_ticket_id("x" * 101) is False
    assert _halopsa_client_mapping(replace(settings, halopsa_client_map_json='{"acme":"12345"}'), "acme") == "12345"
    assert _halopsa_client_mapping(replace(settings, halopsa_client_map_json="not-json"), "acme") is None
    assert _halopsa_client_mapping(replace(settings, halopsa_client_map_json="[]"), "acme") is None
    assert _halopsa_client_mapping(replace(settings, halopsa_client_map_json='{"acme":true}'), "acme") is None
    assert _halopsa_client_mapping(replace(settings, halopsa_client_map_json='{"acme":[]}'), "acme") is None
    assert _halopsa_client_mapping(replace(settings, halopsa_client_map_json='{"acme":"  "}'), "acme") is None
    assert _halopsa_client_mapping(settings, "") is None

def test_end_user_support_prevents_requester_cross_access_and_is_disabled_by_default(settings) -> None:
    enabled = replace(
        settings,
        demo_mode=False,
        end_user_support_enabled=True,
        end_user_token="end-user-token",
        end_user_client_id="acme",
        end_user_user_id="user-1",
        admin_token="admin-token",
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
    hidden_messages = other_client.get(
        f"/end-user/tickets/{ticket_id}/messages",
        headers=_auth("other-token"),
    )
    malformed = client.get("/end-user/tickets/not a ticket", headers=_auth("end-user-token"))
    missing_ticket_escalation = client.post(
        "/end-user/tickets/EUS-missing/escalate",
        headers=_auth("end-user-token"),
    )
    malformed_escalation = client.post(
        "/end-user/tickets/not a ticket/escalate",
        headers=_auth("end-user-token"),
    )
    missing_messages = client.get(
        "/end-user/tickets/EUS-missing/messages",
        headers=_auth("end-user-token"),
    )
    malformed_messages = client.get(
        "/end-user/tickets/not a ticket/messages",
        headers=_auth("end-user-token"),
    )
    malformed_message_create = client.post(
        "/end-user/tickets/not a ticket/messages",
        headers=_auth("end-user-token"),
        json={"body": "not delivered"},
    )

    disabled = TestClient(create_app(settings))
    disabled_response = disabled.post(
        "/end-user/tickets",
        json={"subject": "Disabled", "body": "Disabled"},
    )
    disabled_branding = disabled.get("/end-user/config")
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
    unscoped_branding = unscoped.get(
        "/end-user/config",
        headers=_auth("unscoped-token"),
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
    unscoped_messages = unscoped.get(
        "/end-user/tickets/EUS-missing/messages",
        headers=_auth("unscoped-token"),
    )
    unscoped_message_create = unscoped.post(
        "/end-user/tickets/EUS-missing/messages",
        headers=_auth("unscoped-token"),
        json={"body": "Unscoped"},
    )

    assert created.status_code == 200
    assert hidden.status_code == 404
    assert hidden_messages.status_code == 404
    assert malformed.status_code == 404
    assert missing_ticket_escalation.status_code == 404
    assert malformed_escalation.status_code == 404
    assert missing_messages.status_code == 404
    assert malformed_messages.status_code == 404
    assert malformed_message_create.status_code == 404
    assert disabled_response.status_code == 403
    assert disabled_branding.status_code == 403
    assert unscoped_branding.status_code == 403
    assert unscoped_response.status_code == 403
    assert unscoped_status.status_code == 404
    assert unscoped_escalation.status_code == 403
    assert unscoped_messages.status_code == 404
    assert unscoped_message_create.status_code == 403


def test_end_user_messages_do_not_expose_internal_ticket_notes(settings) -> None:
    enabled = replace(
        settings,
        demo_mode=False,
        end_user_support_enabled=True,
        end_user_token="end-user-token",
        end_user_client_id="acme",
        end_user_user_id="user-1",
        admin_token="admin-token",
    )
    client = TestClient(create_app(enabled))
    created = client.post(
        "/end-user/tickets",
        headers=_auth("end-user-token"),
        json={"subject": "VPN issue", "body": "VPN is unavailable"},
    )
    ticket_id = created.json()["ticket_id"]
    Store(enabled.data_path).create_ticket_note(
        ticket_id,
        client_id="acme",
        author="technician",
        body="Internal diagnostic note",
    )
    client.post(
        f"/end-user/tickets/{ticket_id}/messages",
        headers=_auth("end-user-token"),
        json={"body": "Customer follow-up"},
    )

    response = client.get(
        f"/end-user/tickets/{ticket_id}/messages",
        headers=_auth("end-user-token"),
    )

    assert response.status_code == 200
    assert [item["body"] for item in response.json()] == ["Customer follow-up"]


def test_end_user_message_operator_routes_preserve_tenant_and_role_boundaries(settings) -> None:
    enabled = replace(
        settings,
        demo_mode=False,
        end_user_support_enabled=True,
        end_user_token="end-user-token",
        end_user_client_id="acme",
        end_user_user_id="user-1",
        client_id="acme",
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
    )
    client = TestClient(create_app(enabled))
    created = client.post(
        "/end-user/tickets",
        headers=_auth("end-user-token"),
        json={"subject": "Laptop issue", "body": "Laptop will not connect"},
    )
    ticket_id = created.json()["ticket_id"]

    requester_message = client.post(
        f"/end-user/tickets/{ticket_id}/messages",
        headers=_auth("end-user-token"),
        json={"body": "Here is an additional detail for the technician."},
    )

    viewer_reply = client.post(
        f"/tickets/{ticket_id}/end-user-messages",
        headers=_auth("viewer-token"),
        json={"body": "Viewer must not reply"},
    )
    wrong_ticket = client.get(
        "/tickets/EUS-missing/end-user-messages",
        headers=_auth("tech-token"),
    )
    missing_reply = client.post(
        "/tickets/EUS-missing/end-user-messages",
        headers=_auth("tech-token"),
        json={"body": "No ticket"},
    )
    operator_messages = client.get(
        f"/tickets/{ticket_id}/end-user-messages",
        headers=_auth("viewer-token"),
    )
    admin_messages = client.get(
        f"/tickets/{ticket_id}/end-user-messages",
        headers=_auth("admin-token"),
    )
    admin_reply = client.post(
        f"/tickets/{ticket_id}/end-user-messages",
        headers=_auth("admin-token"),
        json={"body": "Administrator reply"},
    )

    assert viewer_reply.status_code == 403
    assert requester_message.status_code == 200
    assert missing_reply.status_code == 404
    assert wrong_ticket.status_code == 200
    assert wrong_ticket.json() == []
    assert operator_messages.status_code == 200
    assert [item["role"] for item in operator_messages.json()] == ["requester"]
    assert admin_messages.status_code == 200
    assert [item["role"] for item in admin_messages.json()] == ["requester"]
    assert admin_reply.status_code == 200
    assert admin_reply.json()["role"] == "support"


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


def test_end_user_store_rejects_invalid_messages_and_missing_tickets(settings) -> None:
    store = Store(settings.data_path)
    with pytest.raises(ValueError, match="client scope"):
        store.create_end_user_message(
            "EUS-missing", client_id="", requester_id="user-1", body="body"
        )
    with pytest.raises(ValueError, match="requester identity"):
        store.create_end_user_message(
            "EUS-missing", client_id="acme", requester_id=" ", body="body"
        )
    with pytest.raises(ValueError, match="body"):
        store.create_end_user_message(
            "EUS-missing", client_id="acme", requester_id="user-1", body=" "
        )

    assert store.create_end_user_message(
        "EUS-missing", client_id="acme", requester_id="user-1", body="body"
    ) is None
    assert store.list_end_user_messages(
        "EUS-missing", client_id="acme", requester_id="user-1"
    ) == []
    assert store.list_end_user_messages(
        "EUS-missing", client_id="", requester_id="user-1"
    ) == []

    with pytest.raises(ValueError, match="client scope"):
        store.create_support_end_user_message(
            "EUS-missing", client_id="", author_id="tech", body="body"
        )
    with pytest.raises(ValueError, match="author identity"):
        store.create_support_end_user_message(
            "EUS-missing", client_id="acme", author_id=" ", body="body"
        )
    with pytest.raises(ValueError, match="body"):
        store.create_support_end_user_message(
            "EUS-missing", client_id="acme", author_id="tech", body=" "
        )
    assert store.create_support_end_user_message(
        "EUS-missing", client_id="acme", author_id="tech", body="body"
    ) is None
