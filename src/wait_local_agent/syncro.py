"""Read-only SyncroMSP REST API adapter.

Syncro's documented API-key authentication uses an ``api_key`` query
parameter. The adapter keeps the key in the request layer, never includes it
in audit messages or error text, and exposes only ticket/customer reads.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from wait_local_agent.autotask import PsaReadResponse
from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult


class SyncroReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SyncroClient:
    """Bounded, read-only SyncroMSP client."""

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def health(self) -> ConnectorReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        response = self.list_tickets(page=1, page_size=1)
        if response.result.status == "ready":
            return ConnectorReadResult("ready", "Syncro read prerequisites are ready.")
        return response.result

    def list_tickets(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        return self._list("tickets", "tickets", _normalize_ticket, page=page, page_size=page_size)

    def get_ticket(self, ticket_id: str) -> PsaReadResponse:
        try:
            safe_id = _safe_segment(ticket_id)
        except SyncroReadError as exc:
            return PsaReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"tickets/{safe_id}", "tickets", _normalize_ticket)

    def list_companies(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        return self._list("customers", "customers", _normalize_company, page=page, page_size=page_size)

    def _list(
        self,
        endpoint: str,
        collection_key: str,
        normalizer,
        *,
        page: int,
        page_size: int | None,
    ) -> PsaReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        params = {
            "page": max(page, 1),
            "page_size": _bounded_page_size(page_size or self.settings.syncro_page_size),
        }
        return self._request_items(endpoint, collection_key, normalizer, params=params)

    def _request_items(
        self,
        endpoint: str,
        collection_key: str,
        normalizer,
        *,
        params: dict[str, int] | None = None,
    ) -> PsaReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            payload = self._get(endpoint, params=params)
        except SyncroReadError as exc:
            return PsaReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [
            item
            for row in _payload_rows(payload, collection_key)
            if (item := normalizer(row)) is not None
        ]
        return PsaReadResponse(
            ConnectorReadResult("ready", f"Syncro read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(self, endpoint: str, *, params: dict[str, int] | None = None) -> object:
        if not self.settings.allow_http_probing:
            raise SyncroReadError("Syncro live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.")
        missing = self._not_configured_result()
        if missing is not None:
            raise SyncroReadError(missing.message)
        query: dict[str, str | int] = {"api_key": self.settings.syncro_api_key}
        if params:
            query.update(params)
        try:
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{self.settings.syncro_base_url.rstrip('/')}/{_safe_endpoint(endpoint)}",
                    headers={"Accept": "application/json"},
                    params=query,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise SyncroReadError("Syncro request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise SyncroReadError("Syncro request failed.") from exc
        if response.status_code >= 400:
            raise SyncroReadError(f"Syncro GET {endpoint} failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise SyncroReadError(f"Syncro GET {endpoint} returned malformed JSON.") from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Syncro live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_SYNCRO_BASE_URL": self.settings.syncro_base_url,
                "WAIT_SYNCRO_API_KEY": self.settings.syncro_api_key,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult("not_configured", f"Syncro credentials are incomplete: {', '.join(missing)}.")

    def _blocked_response(self) -> PsaReadResponse | None:
        blocked = self._blocked_result()
        return PsaReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> PsaReadResponse | None:
        missing = self._not_configured_result()
        return PsaReadResponse(missing, []) if missing else None


def _safe_endpoint(endpoint: str) -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise SyncroReadError("Syncro endpoint overrides must be relative paths.")
    return endpoint.strip("/")


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or any(character in stripped for character in "/?#"):
        raise SyncroReadError("Syncro resource identifiers must be single path segments.")
    return stripped


def _bounded_page_size(value: int) -> int:
    return max(1, min(value, 100))


def _payload_rows(payload: object, collection_key: str) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get(collection_key)
        if not isinstance(value, list):
            value = payload.get("data", payload.get("items"))
        rows = value if isinstance(value, list) else [payload]
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_ticket(row: Mapping[str, object]) -> dict[str, object] | None:
    ticket_id = _first_value(row, "id", "ticket_id", "ticketId")
    if ticket_id in (None, ""):
        return None
    customer = _first_value(row, "customer", "customer_ref")
    status = _first_value(row, "status", "status_name")
    priority = _first_value(row, "priority", "priority_name")
    return {
        "id": str(ticket_id),
        "number": _string_value(row, "number", "ticket_number"),
        "subject": _string_value(row, "subject", "title"),
        "customer_id": _nested_string(customer, "id") or _string_value(row, "customer_id"),
        "customer_name": _nested_string(customer, "business_name")
        or _nested_string(customer, "name")
        or _string_value(row, "customer_name"),
        "status": _nested_string(status, "name") or _string_value(row, "status"),
        "priority": _nested_string(priority, "name") or _string_value(row, "priority"),
        "created_at": _string_value(row, "created_at", "createdAt"),
        "updated_at": _string_value(row, "updated_at", "updatedAt"),
    }


def _normalize_company(row: Mapping[str, object]) -> dict[str, object] | None:
    company_id = _first_value(row, "id", "customer_id", "customerId")
    if company_id in (None, ""):
        return None
    return {
        "id": str(company_id),
        "name": _string_value(row, "business_name", "name", "customer_name"),
        "phone": _string_value(row, "phone", "phone_number"),
        "city": _string_value(row, "city"),
        "state": _string_value(row, "state"),
    }


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _string_value(row: Mapping[str, object], *keys: str) -> str:
    value = _first_value(row, *keys)
    return "" if value is None or isinstance(value, dict) else str(value)


def _nested_string(value: object, key: str) -> str:
    if isinstance(value, Mapping):
        nested = value.get(key)
        return "" if nested is None else str(nested)
    return "" if value is None else str(value)
