"""Read-only Syncro PSA REST adapter.

The public Syncro API exposes many mutation endpoints. This adapter deliberately
uses only ticket and customer GET endpoints and normalizes the small field set
needed by WAIT's operator surfaces.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

DEFAULT_PAGE = 1
MAX_PAGE = 1_000_000
Normalizer = Callable[[Mapping[str, object]], dict[str, object] | None]


@dataclass(frozen=True)
class SyncroReadResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]


class SyncroReadProvider(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def list_tickets(
        self,
        *,
        page: int = DEFAULT_PAGE,
        query: str | None = None,
        customer_id: str | None = None,
        status: str | None = None,
        since_updated_at: str | None = None,
    ) -> SyncroReadResponse:
        ...

    def get_ticket(self, ticket_id: str) -> SyncroReadResponse:
        ...

    def list_customers(
        self,
        *,
        page: int = DEFAULT_PAGE,
        query: str | None = None,
        business_name: str | None = None,
    ) -> SyncroReadResponse:
        ...

    def get_customer(self, customer_id: str) -> SyncroReadResponse:
        ...


class SyncroReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SyncroClient:
    """Bounded Syncro REST client for read operations only."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    def health(self) -> ConnectorReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        response = self.list_customers(page=DEFAULT_PAGE)
        if response.result.status == "ready":
            return ConnectorReadResult("ready", "Syncro read prerequisites are ready.")
        return response.result

    def list_tickets(
        self,
        *,
        page: int = DEFAULT_PAGE,
        query: str | None = None,
        customer_id: str | None = None,
        status: str | None = None,
        since_updated_at: str | None = None,
    ) -> SyncroReadResponse:
        available = self._unavailable_response()
        if available is not None:
            return available
        try:
            params = _list_params(
                page,
                {
                    "query": query,
                    "customer_id": _safe_id(customer_id) if customer_id is not None else None,
                    "status": status,
                    "since_updated_at": since_updated_at,
                },
            )
        except SyncroReadError as exc:
            return SyncroReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items("tickets", "tickets", _normalize_ticket, params=params)

    def get_ticket(self, ticket_id: str) -> SyncroReadResponse:
        available = self._unavailable_response()
        if available is not None:
            return available
        try:
            safe_id = _safe_id(ticket_id)
        except SyncroReadError as exc:
            return SyncroReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"tickets/{safe_id}", "ticket", _normalize_ticket)

    def list_customers(
        self,
        *,
        page: int = DEFAULT_PAGE,
        query: str | None = None,
        business_name: str | None = None,
    ) -> SyncroReadResponse:
        available = self._unavailable_response()
        if available is not None:
            return available
        try:
            params = _list_params(
                page,
                {"query": query, "business_name": business_name},
            )
        except SyncroReadError as exc:
            return SyncroReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items("customers", "customers", _normalize_customer, params=params)

    def get_customer(self, customer_id: str) -> SyncroReadResponse:
        available = self._unavailable_response()
        if available is not None:
            return available
        try:
            safe_id = _safe_id(customer_id)
        except SyncroReadError as exc:
            return SyncroReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"customers/{safe_id}", "customer", _normalize_customer)

    def _request_items(
        self,
        endpoint: str,
        payload_key: str,
        normalizer: Normalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> SyncroReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            payload = self._get(endpoint, params=params)
        except SyncroReadError as exc:
            return SyncroReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [
            item
            for row in _payload_rows(payload, payload_key)
            if (item := normalizer(row)) is not None
        ]
        return SyncroReadResponse(
            ConnectorReadResult("ready", f"Syncro read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(
        self,
        endpoint: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> object:
        if not self.settings.allow_http_probing:
            raise SyncroReadError(
                "Syncro live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise SyncroReadError(missing.message)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(
                    f"{_api_base_url(_safe_base_url(self.settings.syncro_base_url))}/"
                    f"{_safe_endpoint(endpoint)}",
                    headers={
                        "Authorization": f"Bearer {self.settings.syncro_api_token}",
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise SyncroReadError(
                "Syncro request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise SyncroReadError("Syncro request failed.") from exc
        if response.status_code >= 400:
            raise SyncroReadError(_http_error_message(response.status_code, endpoint))
        try:
            return response.json()
        except ValueError as exc:
            raise SyncroReadError(
                f"Syncro GET {endpoint} returned malformed JSON."
            ) from exc

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
                "WAIT_SYNCRO_API_TOKEN": self.settings.syncro_api_token,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorReadResult(
                "not_configured",
                f"Syncro credentials are incomplete: {', '.join(missing)}.",
            )
        return None

    def _blocked_response(self) -> SyncroReadResponse | None:
        blocked = self._blocked_result()
        return SyncroReadResponse(blocked, []) if blocked else None

    def _unavailable_response(self) -> SyncroReadResponse | None:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        return self._not_configured_response()

    def _not_configured_response(self) -> SyncroReadResponse | None:
        missing = self._not_configured_result()
        return SyncroReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/api/v1"):
        return stripped
    return f"{stripped}/api/v1"


def _safe_base_url(base_url: str) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise SyncroReadError("Syncro base URL contains control characters.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SyncroReadError("Syncro base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SyncroReadError("Syncro base URL must not contain credentials or query data.")
    return base_url


def _safe_endpoint(endpoint: str) -> str:
    if "\x00" in endpoint or "://" in endpoint or endpoint.startswith("//"):
        raise SyncroReadError("Syncro endpoint must be a relative path.")
    parts = endpoint.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise SyncroReadError("Syncro endpoint is invalid.")
    return "/".join(parts)


def _safe_id(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > 20 or not stripped.isdigit():
        raise SyncroReadError("Syncro resource identifiers must be numeric IDs.")
    return stripped


def _safe_filter(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) > 200 or any(ord(character) < 32 for character in stripped):
        raise SyncroReadError("Syncro filters are too long or contain control characters.")
    return stripped or None


def _list_params(page: int, filters: Mapping[str, str | None]) -> dict[str, str | int]:
    if isinstance(page, bool) or page < 1 or page > MAX_PAGE:
        raise SyncroReadError(f"Syncro page must be between 1 and {MAX_PAGE}.")
    params: dict[str, str | int] = {"page": page}
    for key, value in filters.items():
        safe_value = _safe_filter(value)
        if safe_value is not None:
            params[key] = safe_value
    return params


def _payload_rows(payload: object, collection_key: str) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get(collection_key)
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = [value]
        elif isinstance(payload.get("items"), list):
            rows = payload["items"]
        elif "id" in payload:
            rows = [payload]
        else:
            rows = []
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_ticket(row: Mapping[str, object]) -> dict[str, object] | None:
    ticket_id = _first_value(row, "id", "ticket_id")
    if ticket_id in (None, ""):
        return None
    return {
        "id": str(ticket_id),
        "number": _first_value(row, "number", "ticket_number"),
        "subject": _string_value(row, "subject", "title"),
        "status": _string_value(row, "status"),
        "priority": _string_value(row, "priority"),
        "customer_id": _first_value(row, "customer_id", "customerId"),
        "customer_name": _string_value(row, "customer_business_then_name", "customer_name"),
        "problem_type": _string_value(row, "problem_type"),
        "created_at": _string_value(row, "created_at", "createdAt"),
        "updated_at": _string_value(row, "updated_at", "updatedAt"),
    }


def _normalize_customer(row: Mapping[str, object]) -> dict[str, object] | None:
    customer_id = _first_value(row, "id", "customer_id")
    if customer_id in (None, ""):
        return None
    return {
        "id": str(customer_id),
        "name": _string_value(
            row,
            "business_then_name",
            "business_and_full_name",
            "business_name",
            "fullname",
            "name",
        ),
        "email": _string_value(row, "email"),
        "phone": _string_value(row, "phone", "mobile"),
        "disabled": _bool_value(row.get("disabled")),
    }


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _string_value(row: Mapping[str, object], *keys: str) -> str:
    value = _first_value(row, *keys)
    return "" if value is None else str(value)


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else False


def _http_error_message(status_code: int, endpoint: str) -> str:
    if status_code == 401:
        return f"Syncro GET {endpoint} was unauthorized (HTTP 401)."
    if status_code == 403:
        return f"Syncro GET {endpoint} was forbidden (HTTP 403)."
    if status_code == 429:
        return f"Syncro GET {endpoint} was rate limited (HTTP 429)."
    return f"Syncro GET {endpoint} failed with HTTP {status_code}."


__all__ = ["SyncroClient", "SyncroReadError", "SyncroReadProvider", "SyncroReadResponse"]
