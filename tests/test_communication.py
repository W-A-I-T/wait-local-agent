from __future__ import annotations

from typing import Any, cast

import pytest

from wait_local_agent.communication import (
    CommunicationMessage,
    EmailPreviewAdapter,
    PreviewCommunicationProvider,
    SlackPreviewAdapter,
    SmsPreviewAdapter,
    TeamsPreviewAdapter,
)
from wait_local_agent.smart_actions import CommunicationPreviewAction
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


def _context(store: Store, settings, *, client_id: str | None = None):
    from wait_local_agent.smart_actions import ActionContext

    return ActionContext(store=store, settings=settings, client_id=client_id)
