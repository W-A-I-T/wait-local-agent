from __future__ import annotations

from typing import Any, cast

import pytest

from wait_local_agent import cloud_connectors
from wait_local_agent.connectors import (
    execute_halopsa_approval_request,
    update_halopsa_approval_fields,
    validate_halopsa_action_fields,
)
from wait_local_agent.models import HaloWriteResult
from wait_local_agent.store import Store


class FakeHaloClient:
    def execute_write(self, request):
        return HaloWriteResult("succeeded", "posted", request.action_type, request.ticket_id)


def test_cloud_inventory_connectors_are_public_exports() -> None:
    expected = [
        "AwsInventoryConnector",
        "AzureInventoryConnector",
        "GCPInventoryConnector",
        "M365InventoryConnector",
    ]

    assert cloud_connectors.__all__ == expected
    assert all(hasattr(cloud_connectors, name) for name in expected)


def test_halopsa_approval_payload_validation_edges(settings) -> None:
    store = Store(settings.data_path)
    wrong_connector = store.create_approval_request(
        "HALO-2",
        "halopsa.add_note",
        {"connector": "hudu", "ticket_id": "HALO-2", "action_type": "add_note", "fields": {}},
    )
    store.update_approval_request(wrong_connector.id or 0, "approved")
    wrong_ticket = store.create_approval_request(
        "HALO-3",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "OTHER", "action_type": "add_note", "fields": {}},
    )
    store.update_approval_request(wrong_ticket.id or 0, "approved")
    unsupported = store.create_approval_request(
        "HALO-4",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "HALO-4", "action_type": "nope", "fields": {}},
    )
    store.update_approval_request(unsupported.id or 0, "approved")
    wrong_action = store.create_approval_request(
        "HALO-5",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "HALO-5",
            "action_type": "update_status",
            "fields": {},
        },
    )
    store.update_approval_request(wrong_action.id or 0, "approved")

    with pytest.raises(ValueError, match="connector"):
        execute_halopsa_approval_request(
            store,
            cast(Any, FakeHaloClient()),
            wrong_connector.id or 0,
        )
    with pytest.raises(ValueError, match="ticket"):
        execute_halopsa_approval_request(
            store,
            cast(Any, FakeHaloClient()),
            wrong_ticket.id or 0,
        )
    with pytest.raises(ValueError, match="unsupported"):
        execute_halopsa_approval_request(
            store,
            cast(Any, FakeHaloClient()),
            unsupported.id or 0,
        )
    with pytest.raises(ValueError, match="action"):
        execute_halopsa_approval_request(
            store,
            cast(Any, FakeHaloClient()),
            wrong_action.id or 0,
        )


def test_halopsa_field_edit_validation_edges(settings) -> None:
    store = Store(settings.data_path)
    non_halo = store.create_approval_request("TCK-1", "ticket.draft_response", {})
    unsupported = store.create_approval_request(
        "HALO-1",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "HALO-1", "action_type": "nope", "fields": {}},
    )

    with pytest.raises(ValueError, match="not a HaloPSA"):
        update_halopsa_approval_fields(store, non_halo.id or 0, {"note": "x"})
    with pytest.raises(ValueError, match="unsupported"):
        update_halopsa_approval_fields(store, unsupported.id or 0, {"note": "x"})
    with pytest.raises(ValueError, match="note or response"):
        validate_halopsa_action_fields("add_note", {})
    with pytest.raises(ValueError, match="status"):
        validate_halopsa_action_fields("update_status", {})
    with pytest.raises(ValueError, match="technician"):
        validate_halopsa_action_fields("assign_technician", {})
    with pytest.raises(ValueError, match="at least one"):
        validate_halopsa_action_fields("update_ticket_fields", {})
    validate_halopsa_action_fields("draft_response", {"response": "ok"})
    validate_halopsa_action_fields("update_status", {"status_id": "1"})
    validate_halopsa_action_fields("assign_technician", {"team_id": "2"})
    validate_halopsa_action_fields("update_ticket_fields", {"custom_field": "value"})
