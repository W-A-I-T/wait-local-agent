"""Provider-specific ticket response adapters for synchronous ingestion."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from wait_local_agent.models import (
    ConnectWiseReadResponse,
    HaloReadResponse,
    HaloTicket,
    Ticket,
)


class TicketListClient(Protocol):
    def list_tickets(self, *args: object, **kwargs: object) -> object:
        ...


@dataclass(frozen=True)
class ProviderPage:
    """A normalized provider page plus enough envelope metadata for polling."""

    records: list[Ticket]
    provider_status: str
    raw_count: int
    dropped_count: int
    http_status: int | None
    retry_after: float | None


class ProviderTicketAdapter(ABC):
    """Map one provider's normalized ticket response into store tickets."""

    def __init__(self, connector_instance_id: str) -> None:
        normalized = connector_instance_id.strip()
        if not normalized:
            raise ValueError("connector_instance_id must be non-empty")
        self.connector_instance_id = normalized

    @abstractmethod
    def fetch_page(self, client: TicketListClient, *, page: int, page_size: int) -> ProviderPage:
        """Fetch and map one provider page."""

    @staticmethod
    def for_connector(connector_type: str, connector_instance_id: str) -> ProviderTicketAdapter:
        normalized = connector_type.strip().casefold()
        adapter_type = ADAPTER_REGISTRY.get(normalized)
        if adapter_type is None:
            raise ValueError("unsupported connector_type")
        return adapter_type(connector_instance_id)


class HaloTicketAdapter(ProviderTicketAdapter):
    """Adapt the typed HaloPSA ticket response."""

    def fetch_page(self, client: TicketListClient, *, page: int, page_size: int) -> ProviderPage:
        # Halo's client deliberately has a positional page/list-size signature.
        response = cast(HaloReadResponse, client.list_tickets(page, page_size))
        records: list[Ticket] = []
        adapter_dropped = 0
        for item in response.items:
            if not isinstance(item, HaloTicket):
                adapter_dropped += 1
                continue
            external_id = _required_text(item.id)
            external_client_id = _required_text(item.client_id)
            if external_id is None or external_client_id is None:
                adapter_dropped += 1
                continue
            records.append(
                Ticket(
                    id=external_id,
                    client=item.client_name.strip(),
                    subject=item.summary,
                    body="",
                    priority=item.priority,
                    status=item.status,
                    client_id=None,
                    source_system=None,
                    connector_instance_id=self.connector_instance_id,
                    external_id=external_id,
                    external_client_id=external_client_id,
                )
            )
        return _page(response, records, adapter_dropped)


class ConnectWiseTicketAdapter(ProviderTicketAdapter):
    """Adapt the normalized ConnectWise ticket dictionaries."""

    def fetch_page(self, client: TicketListClient, *, page: int, page_size: int) -> ProviderPage:
        # ConnectWise intentionally exposes keyword-only pagination.
        response = cast(
            ConnectWiseReadResponse,
            client.list_tickets(page=page, page_size=page_size),
        )
        records: list[Ticket] = []
        adapter_dropped = 0
        for item in response.items:
            if not isinstance(item, Mapping):
                adapter_dropped += 1
                continue
            external_id = _required_text(item.get("id"))
            external_client_id = _required_text(item.get("company_id"))
            if external_id is None or external_client_id is None:
                adapter_dropped += 1
                continue
            records.append(
                Ticket(
                    id=external_id,
                    client=_text(item.get("company_name")),
                    subject=_text(item.get("summary")),
                    body=_text(item.get("description")),
                    priority=_text(item.get("priority")),
                    status=_text(item.get("status")),
                    client_id=None,
                    source_system=None,
                    connector_instance_id=self.connector_instance_id,
                    external_id=external_id,
                    external_client_id=external_client_id,
                )
            )
        return _page(response, records, adapter_dropped)


def _page(
    response: HaloReadResponse | ConnectWiseReadResponse,
    records: list[Ticket],
    adapter_dropped: int,
) -> ProviderPage:
    return ProviderPage(
        records=records,
        provider_status=response.result.status,
        raw_count=response.raw_count,
        dropped_count=response.dropped_count + adapter_dropped,
        http_status=response.http_status,
        retry_after=response.retry_after,
    )


def _required_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _text(value: object) -> str:
    return "" if value is None else str(value)


ADAPTER_REGISTRY: dict[str, type[ProviderTicketAdapter]] = {
    "halopsa": HaloTicketAdapter,
    "connectwise": ConnectWiseTicketAdapter,
}

# Keep a descriptive alias available to callers that want to inspect the
# registry without depending on the implementation class names.
PROVIDER_ADAPTERS = ADAPTER_REGISTRY


__all__ = [
    "ADAPTER_REGISTRY",
    "ConnectWiseTicketAdapter",
    "HaloTicketAdapter",
    "PROVIDER_ADAPTERS",
    "ProviderPage",
    "ProviderTicketAdapter",
]
