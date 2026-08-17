from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest

from wait_local_agent.models import (
    ConnectorReadResult,
    ConnectWiseReadResponse,
    HaloClient,
    HaloReadResponse,
    HaloReadResult,
    HaloTicket,
)
from wait_local_agent.provider_adapters import (
    ConnectWiseTicketAdapter,
    HaloTicketAdapter,
    ProviderTicketAdapter,
)


@dataclass
class _HaloClient:
    response: HaloReadResponse
    calls: list[tuple[object, object]]

    def list_tickets(self, *args: object, **kwargs: object) -> HaloReadResponse:
        self.calls.append((args, kwargs))
        return self.response


@dataclass
class _ConnectWiseClient:
    response: ConnectWiseReadResponse
    calls: list[tuple[object, object]]

    def list_tickets(self, *args: object, **kwargs: object) -> ConnectWiseReadResponse:
        self.calls.append((args, kwargs))
        return self.response


def test_halo_adapter_maps_fields_and_uses_positional_pagination() -> None:
    client = _HaloClient(
        HaloReadResponse(
            HaloReadResult("ready", "ok", 1),
            [HaloTicket(" h-1 ", "Subject", "Open", "High", " company-1 ", "Acme")],
            raw_count=1,
            http_status=200,
            retry_after=0.5,
        ),
        [],
    )

    page = HaloTicketAdapter("instance-h").fetch_page(client, page=2, page_size=25)

    assert client.calls == [((2, 25), {})]
    assert page.provider_status == "ready"
    assert page.raw_count == 1
    assert page.dropped_count == 0
    assert page.http_status == 200
    assert page.retry_after == 0.5
    assert page.records[0].id == "h-1"
    assert page.records[0].external_id == "h-1"
    assert page.records[0].external_client_id == "company-1"
    assert page.records[0].client_id is None
    assert page.records[0].source_system is None
    assert page.records[0].connector_instance_id == "instance-h"
    assert page.records[0].body == ""


def test_halo_adapter_drops_blank_external_ids_and_client_ids() -> None:
    client = _HaloClient(
        HaloReadResponse(
            HaloReadResult("ready", "ok", 0),
            [
                HaloTicket(" ", "bad", "Open", "Low", "company", "Acme"),
                HaloTicket("h-2", "bad", "Open", "Low", " ", "Acme"),
            ],
            raw_count=2,
            dropped_count=0,
            http_status=200,
        ),
        [],
    )

    page = HaloTicketAdapter("instance-h").fetch_page(client, page=1, page_size=25)

    assert page.records == []
    assert page.raw_count == 2
    assert page.dropped_count == 2


def test_connectwise_adapter_maps_fields_and_uses_keyword_pagination() -> None:
    client = _ConnectWiseClient(
        ConnectWiseReadResponse(
            ConnectorReadResult("ready", "ok", 1),
            [
                {
                    "id": " cw-1 ",
                    "company_id": " company-2 ",
                    "summary": "Subject",
                    "description": "Body",
                    "company_name": "Beta",
                    "priority": "Medium",
                    "status": "New",
                }
            ],
            raw_count=1,
            http_status=200,
        ),
        [],
    )

    page = ConnectWiseTicketAdapter("instance-cw").fetch_page(client, page=3, page_size=50)

    assert client.calls == [((), {"page": 3, "page_size": 50})]
    assert page.records[0].id == "cw-1"
    assert page.records[0].client == "Beta"
    assert page.records[0].subject == "Subject"
    assert page.records[0].body == "Body"
    assert page.records[0].client_id is None
    assert page.records[0].connector_instance_id == "instance-cw"


def test_connectwise_adapter_adds_local_drops_to_response_drops() -> None:
    client = _ConnectWiseClient(
        ConnectWiseReadResponse(
            ConnectorReadResult("ready", "ok", 1),
            [{"id": "cw-1", "company_id": "company"}, {"id": "cw-2", "company_id": " "}],
            raw_count=2,
            dropped_count=3,
            http_status=200,
        ),
        [],
    )

    page = ConnectWiseTicketAdapter("instance-cw").fetch_page(client, page=1, page_size=25)

    assert len(page.records) == 1
    assert page.dropped_count == 4


def test_adapter_registry_is_case_folded() -> None:
    assert isinstance(ProviderTicketAdapter.for_connector(" HaLoPsA ", "instance"), HaloTicketAdapter)
    assert isinstance(ProviderTicketAdapter.for_connector("CONNECTWISE", "instance"), ConnectWiseTicketAdapter)


def test_adapter_rejects_blank_instance_and_unknown_connector() -> None:
    with pytest.raises(ValueError, match="connector_instance_id"):
        HaloTicketAdapter(" ")
    with pytest.raises(ValueError, match="unsupported"):
        ProviderTicketAdapter.for_connector("unknown", "instance")


def test_adapters_count_unexpected_item_shapes_and_missing_values() -> None:
    halo = _HaloClient(
        HaloReadResponse(
            HaloReadResult("ready", "ok", 0),
            [HaloClient("client", "Acme", "active")],
            raw_count=1,
            http_status=200,
        ),
        [],
    )
    assert HaloTicketAdapter("instance").fetch_page(halo, page=1, page_size=1).dropped_count == 1

    connectwise = _ConnectWiseClient(
        ConnectWiseReadResponse(
            ConnectorReadResult("ready", "ok", 0),
            [{"company_id": "company"}, {"id": "ticket"}, cast(Any, object())],
            raw_count=3,
            http_status=200,
        ),
        [],
    )
    assert ConnectWiseTicketAdapter("instance").fetch_page(connectwise, page=1, page_size=1).dropped_count == 3
