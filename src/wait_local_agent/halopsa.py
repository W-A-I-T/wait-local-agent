from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import (
    ConnectorStatusValue,
    HaloAsset,
    HaloCategory,
    HaloClient,
    HaloNote,
    HaloReadResult,
    HaloTicket,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
QueryValue = str | int | float | bool | None | Sequence[str | int | float | bool | None]
Normalizer = Callable[
    [Mapping[str, object]],
    HaloTicket | HaloClient | HaloNote | HaloAsset | HaloCategory | None,
]


@dataclass(frozen=True)
class HaloReadResponse:
    result: HaloReadResult
    items: list[HaloTicket | HaloClient | HaloNote | HaloAsset | HaloCategory]


class HaloPSAReadClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    def health(self) -> HaloReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        try:
            self._access_token()
        except HaloReadError as exc:
            return HaloReadResult("failed", exc.message)
        return HaloReadResult("ready", "HaloPSA token request succeeded.")

    def list_tickets(self, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> HaloReadResponse:
        return self._list("Ticket", _normalize_ticket, page=page, page_size=page_size)

    def get_ticket(self, ticket_id: str) -> HaloReadResponse:
        return self._single(f"Ticket/{ticket_id}", _normalize_ticket)

    def list_ticket_notes(self, ticket_id: str) -> HaloReadResponse:
        response = self._list(f"Ticket/{ticket_id}/Actions", _normalize_note)
        items = [
            item if not isinstance(item, HaloNote) else _note_for_ticket(item, ticket_id)
            for item in response.items
        ]
        return HaloReadResponse(
            HaloReadResult(response.result.status, response.result.message, len(items)),
            items,
        )

    def list_clients(self, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> HaloReadResponse:
        return self._list("Client", _normalize_client, page=page, page_size=page_size)

    def list_client_assets(self, client_id: str) -> HaloReadResponse:
        return self._list("Asset", _normalize_asset, params={"client_id": client_id})

    def list_categories(self) -> HaloReadResponse:
        return self._list("Category", _normalize_category)

    def _list(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        params: dict[str, QueryValue] | None = None,
    ) -> HaloReadResponse:
        blocked_response = self._blocked_response()
        if blocked_response is not None:
            return blocked_response
        missing_response = self._not_configured_response()
        if missing_response is not None:
            return missing_response
        query: dict[str, QueryValue] = {
            "page_no": max(page, 1),
            "page_size": _bounded_page_size(page_size),
        }
        if params:
            query.update(params)
        return self._request_items(endpoint, normalizer, params=query)

    def _single(self, endpoint: str, normalizer: Normalizer) -> HaloReadResponse:
        blocked_response = self._blocked_response()
        if blocked_response is not None:
            return blocked_response
        missing_response = self._not_configured_response()
        if missing_response is not None:
            return missing_response
        return self._request_items(endpoint, normalizer)

    def _request_items(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        params: dict[str, QueryValue] | None = None,
    ) -> HaloReadResponse:
        try:
            payload = self._get(endpoint, params=params)
        except HaloReadError as exc:
            return HaloReadResponse(HaloReadResult("failed", exc.message), [])

        rows = _payload_rows(payload)
        items = [item for row in rows if (item := normalizer(row)) is not None]
        status: ConnectorStatusValue = "ready"
        message = f"HaloPSA read succeeded from {endpoint}."
        return HaloReadResponse(HaloReadResult(status, message, len(items)), items)

    def _get(self, endpoint: str, *, params: dict[str, QueryValue] | None = None) -> object:
        token = self._access_token()
        with self._client() as client:
            response = client.get(
                f"{_api_base_url(self.settings.halopsa_base_url)}/{endpoint.lstrip('/')}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
        if response.status_code >= 400:
            raise HaloReadError(f"HaloPSA GET {endpoint} failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise HaloReadError(f"HaloPSA GET {endpoint} returned malformed JSON.") from exc

    def _access_token(self) -> str:
        with self._client() as client:
            response = client.post(
                _token_url(self.settings),
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.halopsa_client_id,
                    "client_secret": self.settings.halopsa_client_secret,
                    "tenant": self.settings.halopsa_tenant,
                },
            )
        if response.status_code >= 400:
            raise HaloReadError(f"HaloPSA token request failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise HaloReadError("HaloPSA token request returned malformed JSON.") from exc
        token = _string_value(payload, "access_token")
        if not token:
            raise HaloReadError("HaloPSA token response did not include access_token.")
        return token

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=20.0, transport=self.transport)

    def _blocked_result(self) -> HaloReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return HaloReadResult(
            "blocked",
            "HaloPSA live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> HaloReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_HALOPSA_BASE_URL": self.settings.halopsa_base_url,
                "WAIT_HALOPSA_CLIENT_ID": self.settings.halopsa_client_id,
                "WAIT_HALOPSA_CLIENT_SECRET": self.settings.halopsa_client_secret,
                "WAIT_HALOPSA_TENANT": self.settings.halopsa_tenant,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return HaloReadResult(
            "not_configured",
            f"HaloPSA credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> HaloReadResponse | None:
        blocked = self._blocked_result()
        return HaloReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> HaloReadResponse | None:
        missing = self._not_configured_result()
        return HaloReadResponse(missing, []) if missing else None


class HaloReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _api_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    return stripped if stripped.endswith("/api") else f"{stripped}/api"


def _token_url(settings: Settings) -> str:
    if settings.halopsa_token_url:
        return settings.halopsa_token_url
    return f"{_api_base_url(settings.halopsa_base_url)}/auth/token"


def _bounded_page_size(page_size: int) -> int:
    return min(max(page_size, 1), MAX_PAGE_SIZE)


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        keys = (
            "tickets",
            "clients",
            "notes",
            "actions",
            "assets",
            "categories",
            "data",
            "results",
        )
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
        else:
            candidates = [payload]
    else:
        return []
    return [row for row in candidates if isinstance(row, dict)]


def _normalize_ticket(row: Mapping[str, object]) -> HaloTicket | None:
    ticket_id = _id_value(row)
    if not ticket_id:
        return None
    return HaloTicket(
        id=ticket_id,
        summary=_first_string(row, "summary", "title", "subject"),
        status=_first_string(row, "status", "status_name"),
        priority=_first_string(row, "priority", "priority_name"),
        client_id=_first_string(row, "client_id", "customer_id"),
        client_name=_first_string(row, "client_name", "customer", "customer_name"),
    )


def _normalize_client(row: Mapping[str, object]) -> HaloClient | None:
    client_id = _id_value(row)
    if not client_id:
        return None
    return HaloClient(
        id=client_id,
        name=_first_string(row, "name", "client_name", "customer_name"),
        status=_first_string(row, "status", "status_name"),
    )


def _normalize_note(row: Mapping[str, object]) -> HaloNote | None:
    note_id = _id_value(row)
    if not note_id:
        return None
    return HaloNote(
        id=note_id,
        ticket_id=_first_string(row, "ticket_id", "faultid"),
        body=_first_string(row, "body", "note", "details", "outcome"),
        created_at=_first_string(row, "created_at", "datecreated", "datetime"),
        is_private=_bool_value(row, "is_private", "private", "hiddenfromuser"),
    )


def _note_for_ticket(note: HaloNote, ticket_id: str) -> HaloNote:
    return HaloNote(
        id=note.id,
        ticket_id=note.ticket_id or ticket_id,
        body=note.body,
        created_at=note.created_at,
        is_private=note.is_private,
    )


def _normalize_asset(row: Mapping[str, object]) -> HaloAsset | None:
    asset_id = _id_value(row)
    if not asset_id:
        return None
    return HaloAsset(
        id=asset_id,
        client_id=_first_string(row, "client_id", "customer_id"),
        name=_first_string(row, "name", "asset_name", "inventory_number"),
        asset_type=_first_string(row, "asset_type", "type", "asset_type_name"),
        status=_first_string(row, "status", "status_name"),
    )


def _normalize_category(row: Mapping[str, object]) -> HaloCategory | None:
    category_id = _id_value(row)
    if not category_id:
        return None
    return HaloCategory(
        id=category_id,
        name=_first_string(row, "name", "category", "value", "label"),
        parent_id=_first_string(row, "parent_id", "parentid"),
    )


def _id_value(row: Mapping[str, object]) -> str:
    return _first_string(row, "id", "ticket_id", "faultid", "client_id", "category_id")


def _first_string(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return str(value)
    return ""


def _string_value(row: object, key: str) -> str:
    if isinstance(row, dict):
        value = row.get(key)
        return str(value) if value is not None else ""
    return ""


def _bool_value(row: Mapping[str, object], *keys: str) -> bool:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, int):
            return bool(value)
    return False
