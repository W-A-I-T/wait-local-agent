from __future__ import annotations

from dataclasses import replace
from email.message import EmailMessage
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.communication import (
    CommunicationDelivery,
    CommunicationDeliveryError,
    CommunicationMessage,
    ConfiguredCommunicationProvider,
    EmailPreviewAdapter,
    PreviewCommunicationProvider,
    SlackPreviewAdapter,
    SmsPreviewAdapter,
    TeamsPreviewAdapter,
)
from wait_local_agent.rbac import Role
from wait_local_agent.smart_actions import (
    ActionContext,
    CommunicationPreviewAction,
    CommunicationSendAction,
    SmartActionService,
)
from wait_local_agent.store import Store


@pytest.mark.parametrize(
    ("channel", "adapter_type"),
    [
        ("email", EmailPreviewAdapter),
        ("teams", TeamsPreviewAdapter),
        ("slack", SlackPreviewAdapter),
        ("sms", SmsPreviewAdapter),
    ],
)
def test_preview_adapters_are_channel_specific(channel, adapter_type) -> None:
    adapter = adapter_type()
    draft = adapter.draft(
        CommunicationMessage(
            channel=channel,
            recipient="destination",
            subject="Subject" if channel != "sms" else "",
            body="Hello",
        )
    )

    assert draft.adapter_id == f"preview-{channel}"
    assert draft.delivery_mode == "preview"
    assert draft.sendable is False
    with pytest.raises(ValueError, match="does not match"):
        adapter.draft(
            CommunicationMessage(
                channel="sms" if channel != "sms" else "email",
                recipient="destination",
                body="Hello",
            )
        )


def test_preview_provider_routes_all_supported_channels() -> None:
    provider = PreviewCommunicationProvider()

    for channel in ("email", "teams", "slack", "sms"):
        draft = provider.draft(
            CommunicationMessage(channel=channel, recipient="destination", body="Hello")
        )
        assert draft.channel == channel
        assert draft.sendable is False

    with pytest.raises(ValueError, match="unsupported"):
        provider.draft(
            CommunicationMessage(
                channel=cast(Any, "pager"), recipient="destination", body="Hello"
            )
        )


def test_communication_action_requires_tenant_and_never_sends(settings) -> None:
    store = Store(settings.data_path)
    action = CommunicationPreviewAction()

    missing_tenant = action.run(
        _context(store, settings),
        {"channel": "email", "recipient": "user@example.com", "body": "Hello"},
    )
    assert missing_tenant.status == "failed"
    assert "tenant" in missing_tenant.error_detail

    preview = action.run(
        _context(store, settings, client_id="acme"),
        {
            "channel": "slack",
            "recipient": "#helpdesk",
            "body": "Ticket update",
        },
    )
    assert preview.status == "success"
    assert preview.output["delivery_mode"] == "preview"
    assert preview.output["sendable"] is False
    assert preview.output["approval_required"] is True

    invalid_sms = action.run(
        _context(store, settings, client_id="acme"),
        {
            "channel": "sms",
            "recipient": "+15551234567",
            "subject": "not supported",
            "body": "Ticket update",
        },
    )
    assert invalid_sms.status == "failed"
    assert "subject" in invalid_sms.error_detail


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"channel": "pager", "recipient": "x", "body": "x"}, "channel"),
        ({"channel": "email", "recipient": "", "body": "x"}, "recipient"),
        ({"channel": "email", "recipient": "x", "body": ""}, "body"),
        ({"channel": "email", "recipient": "x", "body": "x", "subject": 1}, "subject"),
        ({"channel": "email", "recipient": "x", "body": "x", "ticket_id": 1}, "ticket_id"),
        ({"channel": "email", "recipient": "x", "body": "x", "ticket_id": "missing"}, "existing"),
    ],
)
def test_communication_action_rejects_malformed_or_unscoped_inputs(settings, payload, message) -> None:
    store = Store(settings.data_path)
    result = CommunicationPreviewAction().run(
        _context(store, settings, client_id="acme"), payload
    )
    assert result.status == "failed"
    assert message in result.error_detail


class _ValueErrorProvider:
    def draft(self, message):
        raise ValueError("provider rejected message")


class _RuntimeErrorProvider:
    def draft(self, message):
        raise RuntimeError("unexpected provider failure")


@pytest.mark.parametrize(
    "provider, expected",
    [(_ValueErrorProvider(), "rejected"), (_RuntimeErrorProvider(), "failed")],
)
def test_communication_action_sanitizes_provider_failures(settings, provider, expected) -> None:
    store = Store(settings.data_path)
    context = _context(store, settings, client_id="acme")
    context.communication_provider = provider

    result = CommunicationPreviewAction().run(
        context,
        {"channel": "email", "recipient": "user@example.com", "body": "Hello"},
    )

    assert result.status == "failed"
    assert expected in result.error_detail


def test_configured_webhook_delivery_requires_flags_and_never_returns_body(settings) -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "json": request.read().decode()})
        return httpx.Response(202, request=request, text='{"secret":"do-not-expose"}')

    active = replace(
        settings,
        allow_write_actions=True,
        allow_http_probing=True,
        communication_slack_webhook_url="https://hooks.example.test/wait",
    )
    provider = ConfiguredCommunicationProvider(active, transport=httpx.MockTransport(handler))
    message = CommunicationMessage(
        channel="slack",
        recipient="#helpdesk",
        body="Ticket update",
        client_id="acme",
    )

    preview = provider.draft(message)
    delivery = provider.send(message)

    assert preview.sendable is False
    assert delivery.delivery_mode == "sent"
    assert delivery.sendable is True
    assert "do-not-expose" not in delivery.message
    assert calls == [
        {
            "url": "https://hooks.example.test/wait",
            "json": '{"text":"Ticket update"}',
        }
    ]
    with pytest.raises(CommunicationDeliveryError, match="blocked"):
        ConfiguredCommunicationProvider(settings).send(message)


def test_approved_communication_send_creates_local_ticket_note(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    active = replace(settings, allow_write_actions=True)
    service = SmartActionService(store, active)

    pending = service.invoke(
        "communication-send",
        {
            "channel": "ticket_note",
            "ticket_id": "TCK-1001",
            "body": "Technician has been notified.",
        },
        "requester",
        client_id="acme",
    )
    assert pending.status == "pending_approval"
    assert pending.approval_id is not None

    approved = service.update_approval(
        pending.approval_id,
        "approved",
        approver="technician",
        approver_role=Role.TECHNICIAN,
    )
    notes = store.list_ticket_notes("TCK-1001", client_id="acme")

    assert approved.status == "approved"
    assert len(notes) == 1
    assert notes[0].body == "Technician has been notified."


def test_communication_delivery_rejects_unsafe_endpoint_and_missing_ticket(settings) -> None:
    active = replace(
        settings,
        allow_write_actions=True,
        allow_http_probing=True,
        communication_teams_webhook_url="https://hooks.example.test/wait?token=secret",
    )
    provider = ConfiguredCommunicationProvider(active)
    with pytest.raises(CommunicationDeliveryError, match="endpoint"):
        provider.send(
            CommunicationMessage(channel="teams", recipient="team", body="Hello")
        )

    result = CommunicationPreviewAction().run(
        _context(Store(settings.data_path), settings, client_id="acme"),
        {"channel": "ticket_note", "body": "Hello"},
    )
    assert result.status == "failed"
    assert "ticket_id" in result.error_detail


def test_api_communication_approval_and_ticket_note_view(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    client = TestClient(
        create_app(
            replace(
                settings,
                allow_write_actions=True,
                demo_mode=False,
                tech_token="technician-token",
                admin_token="admin-token",
                client_id="acme",
            )
        )
    )

    pending = client.post(
        "/smart-actions/communication-send/invoke",
        json={
            "client_id": "acme",
            "payload": {
                "channel": "ticket_note",
                "ticket_id": "TCK-1001",
                "body": "Approved local note",
            },
        },
        headers={"Authorization": "Bearer technician-token"},
    )
    approval_id = pending.json()["approval_id"]
    approved = client.post(
        f"/approval-requests/{approval_id}",
        json={"status": "approved", "comment": "Reviewed"},
        headers={"Authorization": "Bearer admin-token"},
    )
    notes = client.get(
        "/tickets/TCK-1001/notes",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert pending.status_code == 200
    assert pending.json()["status"] == "pending_approval"
    assert approved.status_code == 200
    assert notes.status_code == 200
    assert notes.json()[0]["body"] == "Approved local note"


def test_preview_provider_cannot_send(settings) -> None:
    with pytest.raises(ValueError, match="not configured"):
        PreviewCommunicationProvider().send(
            CommunicationMessage(channel="email", recipient="user@example.com", body="Hello")
        )


@pytest.mark.parametrize(
    ("channel", "field"),
    [
        ("teams", "communication_teams_webhook_url"),
        ("slack", "communication_slack_webhook_url"),
        ("sms", "communication_sms_webhook_url"),
    ],
)
def test_webhook_channels_require_their_own_configuration(settings, channel, field) -> None:
    provider = ConfiguredCommunicationProvider(
        replace(settings, allow_write_actions=True, allow_http_probing=True)
    )
    with pytest.raises(CommunicationDeliveryError, match=field.removeprefix("communication_").upper()):
        provider.send(
            CommunicationMessage(channel=channel, recipient="destination", body="Hello")
        )


def test_webhook_delivery_supports_subject_and_sms_auth(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    active = replace(
        settings,
        allow_write_actions=True,
        allow_http_probing=True,
        communication_sms_webhook_url="https://sms.example.test/send",
        communication_sms_auth_token="sms-secret",
    )
    delivery = ConfiguredCommunicationProvider(
        active, transport=httpx.MockTransport(handler)
    ).send(
        CommunicationMessage(
            channel="sms",
            recipient="+15551234567",
            body="Hello",
            subject="",
        )
    )

    assert delivery.adapter_id == "webhook-sms"
    assert requests[0].headers["Authorization"] == "Bearer sms-secret"


def test_webhook_delivery_includes_subject_and_ticket_note_send_is_not_external(settings) -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.read().decode())
        return httpx.Response(200, request=request)

    active = replace(
        settings,
        allow_write_actions=True,
        allow_http_probing=True,
        communication_teams_webhook_url="https://hooks.example.test/wait",
    )
    ConfiguredCommunicationProvider(active, transport=httpx.MockTransport(handler)).send(
        CommunicationMessage(
            channel="teams",
            recipient="team",
            subject="Subject",
            body="Hello",
        )
    )
    assert '"text":"Subject\\n\\nHello"' in captured[0]
    with pytest.raises(CommunicationDeliveryError, match="local ticket-note"):
        ConfiguredCommunicationProvider(active).send(
            CommunicationMessage(channel="ticket_note", recipient="ticket:TCK-1", body="Hello")
        )


@pytest.mark.parametrize(
    ("response_or_error", "message"),
    [
        (httpx.Response(500), "HTTP 500"),
        (httpx.ConnectError("offline"), "before receiving"),
        (httpx.ReadError("broken"), "delivery failed"),
    ],
)
def test_webhook_delivery_sanitizes_transport_failures(settings, response_or_error, message) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(response_or_error, Exception):
            raise response_or_error
        return httpx.Response(response_or_error.status_code, request=request)

    active = replace(
        settings,
        allow_write_actions=True,
        allow_http_probing=True,
        communication_teams_webhook_url="https://hooks.example.test/wait",
    )
    with pytest.raises(CommunicationDeliveryError, match=message):
        ConfiguredCommunicationProvider(
            active, transport=httpx.MockTransport(handler)
        ).send(CommunicationMessage(channel="teams", recipient="team", body="Hello"))


class _FakeSMTP:
    def __init__(self, *args, **kwargs) -> None:
        self.started_tls = False
        self.logged_in = False
        self.messages: list[EmailMessage] = []

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in = username == "mailer" and password == "password"

    def send_message(self, message: EmailMessage) -> None:
        self.messages.append(message)


def test_email_delivery_uses_tls_auth_and_redacted_result(settings) -> None:
    smtp = _FakeSMTP()
    active = replace(
        settings,
        allow_write_actions=True,
        allow_http_probing=True,
        communication_email_host="smtp.example.test",
        communication_email_username="mailer",
        communication_email_password="password",
        communication_email_from="agent@example.test",
    )
    delivery = ConfiguredCommunicationProvider(active, smtp_factory=lambda *args, **kwargs: smtp).send(
        CommunicationMessage(
            channel="email",
            recipient="user@example.test",
            subject="Subject",
            body="Body",
        )
    )
    assert delivery.adapter_id == "smtp-email"
    assert smtp.started_tls is True
    assert smtp.logged_in is True
    assert smtp.messages[0]["To"] == "user@example.test"


def test_email_delivery_supports_plain_smtp_without_auth(settings) -> None:
    smtp = _FakeSMTP()
    active = replace(
        settings,
        allow_write_actions=True,
        allow_http_probing=True,
        communication_email_host="smtp.example.test",
        communication_email_from="agent@example.test",
        communication_email_tls=False,
    )
    ConfiguredCommunicationProvider(active, smtp_factory=lambda *args, **kwargs: smtp).send(
        CommunicationMessage(channel="email", recipient="user@example.test", body="Hello")
    )
    assert smtp.started_tls is False
    assert smtp.logged_in is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"communication_email_from": ""}, "WAIT_COMMUNICATION_EMAIL_FROM"),
        ({"communication_email_host": ""}, "WAIT_COMMUNICATION_EMAIL_HOST"),
        ({"communication_email_from": "agent@example.test"}, "recipient is invalid"),
    ],
)
def test_email_delivery_validates_configuration_and_recipient(settings, overrides, message) -> None:
    values = {
        "allow_write_actions": True,
        "allow_http_probing": True,
        "communication_email_host": "smtp.example.test",
        "communication_email_from": "agent@example.test",
        **overrides,
    }
    active = replace(settings, **values)
    recipient = "not-an-email" if "recipient" in message else "user@example.test"
    with pytest.raises(CommunicationDeliveryError, match=message):
        ConfiguredCommunicationProvider(active, smtp_factory=_FakeSMTP).send(
            CommunicationMessage(channel="email", recipient=recipient, body="Hello")
        )


def test_communication_endpoint_and_email_validation_reject_injection(settings) -> None:
    active = replace(settings, allow_write_actions=True, allow_http_probing=True)
    with pytest.raises(CommunicationDeliveryError, match="HTTP"):
        ConfiguredCommunicationProvider(
            replace(active, communication_teams_webhook_url="file:///tmp/send")
        ).send(CommunicationMessage(channel="teams", recipient="team", body="Hello"))
    with pytest.raises(CommunicationDeliveryError, match="query"):
        ConfiguredCommunicationProvider(
            replace(
                active,
                communication_teams_webhook_url="https://hooks.example.test/wait?secret=bad",
            )
        ).send(CommunicationMessage(channel="teams", recipient="team", body="Hello"))
    with pytest.raises(CommunicationDeliveryError, match="control"):
        ConfiguredCommunicationProvider(
            replace(
                active,
                communication_email_host="smtp.example.test",
                communication_email_from="agent@example.test",
            ),
            smtp_factory=_FakeSMTP,
        ).send(
            CommunicationMessage(channel="email", recipient="user@example.test\nBcc:bad", body="Hello")
        )
    with pytest.raises(CommunicationDeliveryError, match="HTTP_PROBING"):
        ConfiguredCommunicationProvider(
            replace(active, allow_write_actions=True, allow_http_probing=False)
        ).send(CommunicationMessage(channel="teams", recipient="team", body="Hello"))


@pytest.mark.parametrize(
    "payload",
    [
        {"channel": "pager", "body": "Hello"},
        {"channel": "email", "recipient": "x", "body": ""},
        {"channel": "email", "recipient": "x", "body": "Hello", "subject": 1},
        {"channel": "email", "recipient": "", "body": "Hello"},
        {"channel": "ticket_note", "body": "Hello"},
        {"channel": "email", "recipient": "x", "body": "Hello", "ticket_id": "missing"},
        {"channel": "sms", "recipient": "x", "body": "Hello", "subject": "bad"},
    ],
)
def test_communication_send_validates_payload(settings, payload) -> None:
    result = CommunicationSendAction().run(
        ActionContext(store=Store(settings.data_path), settings=settings, client_id="acme"),
        payload,
    )
    assert result.status == "failed"


class _SuccessfulSender:
    def send(self, message):
        return CommunicationDelivery(
            channel=message.channel,
            recipient=message.recipient,
            subject=message.subject,
            adapter_id="fake",
            delivery_mode="sent",
            sendable=True,
            message="sent",
        )


class _DeliveryErrorSender:
    def send(self, message):
        raise CommunicationDeliveryError("provider secret=hidden rejected")


class _UnexpectedSender:
    def send(self, message):
        raise RuntimeError("unexpected")


class _BrokenDraftProvider:
    def draft(self, message):
        raise RuntimeError("broken")


@pytest.mark.parametrize(
    ("sender", "status", "detail"),
    [
        (_SuccessfulSender(), "success", ""),
        (_DeliveryErrorSender(), "failed", "redacted"),
        (_UnexpectedSender(), "failed", "delivery failed"),
    ],
)
def test_communication_send_uses_approved_sender(settings, sender, status, detail) -> None:
    action = CommunicationSendAction()
    result = action.run(
        ActionContext(
            store=Store(settings.data_path),
            settings=settings,
            client_id="acme",
            communication_sender=sender,
        ),
        {
            "channel": "email",
            "recipient": "user@example.test",
            "body": "Hello",
            "_approval_completed": True,
        },
    )
    assert result.status == status
    if detail:
        assert detail in result.error_detail


def test_communication_send_preview_failure_and_blocked_local_note(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    action = CommunicationSendAction()
    preview_failure = action.run(
        ActionContext(
            store=store,
            settings=settings,
            client_id="acme",
            communication_provider=_BrokenDraftProvider(),
        ),
        {"channel": "email", "recipient": "user@example.test", "body": "Hello"},
    )
    blocked_note = action.run(
        ActionContext(store=store, settings=settings, client_id="acme"),
        {
            "channel": "ticket_note",
            "ticket_id": "TCK-1001",
            "body": "Hello",
            "_approval_completed": True,
        },
    )
    no_tenant_note = action.run(
        ActionContext(store=store, settings=replace(settings, allow_write_actions=True)),
        {
            "channel": "ticket_note",
            "ticket_id": "TCK-1001",
            "body": "Hello",
            "_approval_completed": True,
        },
    )
    assert preview_failure.error_detail == "communication preview failed"
    assert "blocked" in blocked_note.error_detail
    assert "tenant-scoped" in no_tenant_note.error_detail


def test_store_ticket_note_scope_and_validation(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    assert store.get_ticket_for_client("TCK-1001", "acme") is not None
    with pytest.raises(ValueError, match="client scope"):
        store.create_ticket_note("TCK-1001", client_id="", author="a", body="b")
    with pytest.raises(ValueError, match="author and body"):
        store.create_ticket_note("TCK-1001", client_id="acme", author="", body="b")
    assert store.create_ticket_note(
        "TCK-1001", client_id="other", author="a", body="b"
    ) is None
    assert store.list_ticket_notes("missing", client_id="acme") == []


def _context(store: Store, settings, *, client_id: str | None = None):
    from wait_local_agent.smart_actions import ActionContext

    return ActionContext(store=store, settings=settings, client_id=client_id)
