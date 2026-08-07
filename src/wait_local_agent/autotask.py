"""Bounded, read-only Autotask REST API adapter.

Autotask supports mutations, but this public adapter deliberately exposes only
GET-based ticket and company reads. Any future mutation must use the existing
approval and execution gates.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_PAGE = 1_000_000
Normalizer = Callable[[Mapping[str, object]], dict[str, object] | None]


@dataclass(frozen=True)
class AutotaskReadResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]


class AutotaskReadProvider(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def list_tickets(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> AutotaskReadResponse:
        ...

    def get_ticket(self, ticket_id: str) -> AutotaskReadResponse:
        ...

    def list_companies(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> AutotaskReadResponse:
        ...

    def get_company(self, company_id: str) -> AutotaskReadResponse:
        ...


class AutotaskReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AutotaskClient:
    """Read-only Autotask REST client with bounded request inputs."""

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
        try:
            self._get("Tickets/entityInformation")
        except AutotaskReadError as exc:
            return ConnectorReadResult("failed", exc.message)
        return ConnectorReadResult("ready", "Autotask read prerequisites are ready.")

    def list_tickets(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> AutotaskReadResponse:
        return self._list(
            "Tickets/query",
            "tickets",
            _normalize_ticket,
            page=page,
            page_size=page_size,
        )

    def get_company(self, company_id: str) -> AutotaskReadResponse:
        return self._get_record("Companies", company_id, "companies", _normalize_company)

    def get_ticket(self, ticket_id: str) -> AutotaskReadResponse:
        return self._get_record("Tickets", ticket_id, "tickets", _normalize_ticket)

    def list_companies(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> AutotaskReadResponse:
        return self._list(
            "Companies/query",
            "companies",
            _normalize_company,
            page=page,
            page_size=page_size,
        )

    def _list(
        self,
        endpoint: str,
        label: str,
        normalizer: Normalizer,
        *,
        page: int,
        page_size: int,
    ) -> AutotaskReadResponse:
        unavailable = self._unavailable_response()
        if unavailable is not None:
            return unavailable
        try:
            params = _list_params(page, page_size)
        except AutotaskReadError as exc:
            return AutotaskReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(endpoint, label, normalizer, params=params)

    def _get_record(
        self,
        entity: str,
        record_id: str,
        label: str,
        normalizer: Normalizer,
    ) -> AutotaskReadResponse:
        unavailable = self._unavailable_response()
        if unavailable is not None:
            return unavailable
        try:
            safe_id = _safe_segment(record_id)
            endpoint = _safe_endpoint(f"{entity}/{safe_id}")
        except AutotaskReadError as exc:
            return AutotaskReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(endpoint, label, normalizer)

    def _request_items(
        self,
        endpoint: str,
        label: str,
        normalizer: Normalizer,
        *,
        params: dict[str, int] | None = None,
    ) -> AutotaskReadResponse:
        unavailable = self._unavailable_response()
        if unavailable is not None:
            return unavailable
        try:
            payload = self._get(endpoint, params=params)
        except AutotaskReadError as exc:
            return AutotaskReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [
            item
            for row in _payload_rows(payload)
            if (item := normalizer(row)) is not None
        ]
        return AutotaskReadResponse(
            ConnectorReadResult(
                "ready",
                f"Autotask read succeeded from {endpoint}.",
                len(items),
            ),
            items,
        )

    def _get(
        self,
        endpoint: str,
        *,
        params: dict[str, int] | None = None,
    ) -> object:
        if not self.settings.allow_http_probing:
            raise AutotaskReadError(
                "Autotask live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise AutotaskReadError(missing.message)
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(
                    f"{_api_base_url(self.settings.autotask_base_url)}/{safe_endpoint}",
                    headers={
                        "Username": self.settings.autotask_username,
                        "Secret": self.settings.autotask_secret,
                        "APIIntegrationcode": self.settings.autotask_integration_code,
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise AutotaskReadError(
                "Autotask request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise AutotaskReadError("Autotask request failed.") from exc
        if response.status_code >= 400:
            raise AutotaskReadError(
                _http_error_message(response.status_code, safe_endpoint)
            )
        try:
            return response.json()
        except ValueError as exc:
            raise AutotaskReadError(
                f"Autotask GET {safe_endpoint} returned malformed JSON."
            ) from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Autotask live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_AUTOTASK_BASE_URL": self.settings.autotask_base_url,
                "WAIT_AUTOTASK_USERNAME": self.settings.autotask_username,
                "WAIT_AUTOTASK_SECRET": self.settings.autotask_secret,
                "WAIT_AUTOTASK_INTEGRATION_CODE": self.settings.autotask_integration_code,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorReadResult(
                "not_configured",
                f"Autotask credentials are incomplete: {', '.join(missing)}.",
            )
        return None

    def _unavailable_response(self) -> AutotaskReadResponse | None:
        blocked = self._blocked_result()
        if blocked is not None:
            return AutotaskReadResponse(blocked, [])
        missing = self._not_configured_result()
        return AutotaskReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    stripped = _safe_base_url(base_url).rstrip("/")
    if stripped.endswith("/atservicesrest/v1.0"):
        return stripped
    if stripped.endswith("/atservicesrest"):
        return f"{stripped}/v1.0"
    return f"{stripped}/atservicesrest/v1.0"


def _safe_base_url(base_url: str) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise AutotaskReadError("Autotask base URL contains control characters.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AutotaskReadError("Autotask base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AutotaskReadError(
            "Autotask base URL must not contain credentials or query data."
        )
    return base_url


def _safe_endpoint(endpoint: str) -> str:
    if endpoint.startswith("//") or "://" in endpoint:
        raise AutotaskReadError("Autotask endpoint must be a relative path.")
    parts = endpoint.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise AutotaskReadError("Autotask endpoint is invalid.")
    if any(
        not all(character.isalnum() or character in {"_", "-"} for character in part)
        for part in parts
    ):
        raise AutotaskReadError("Autotask endpoint contains unsafe characters.")
    return "/".join(parts)


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > 64 or not all(
        character.isalnum() or character in {"_", "-"} for character in stripped
    ):
        raise AutotaskReadError(
            "Autotask resource identifiers contain unsafe characters."
        )
    return stripped


def _bounded_page_size(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise AutotaskReadError("Autotask page_size must be at least 1.")
    return min(value, MAX_PAGE_SIZE)


def _list_params(page: int, page_size: int) -> dict[str, int]:
    if isinstance(page, bool) or page < 1 or page > MAX_PAGE:
        raise AutotaskReadError(f"Autotask page must be between 1 and {MAX_PAGE}.")
    return {"page": page, "pageSize": _bounded_page_size(page_size)}


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get("items")
        if isinstance(value, list):
            rows = value
        elif "id" in payload or "ticketID" in payload or "companyID" in payload:
            rows = [payload]
        else:
            rows = []
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_ticket(row: Mapping[str, object]) -> dict[str, object] | None:
    ticket_id = _first_value(row, "id", "ticketID", "ticketId")
    if ticket_id in (None, ""):
        return None
    return {
        "id": str(ticket_id),
        "ticket_number": _string_value(row, "ticketNumber", "ticket_number"),
        "title": _string_value(row, "title", "subject"),
        "description": _string_value(row, "description", "descriptionPlainText"),
        "status": _reference_value(_first_value(row, "status", "statusName")),
        "priority": _reference_value(_first_value(row, "priority", "priorityName")),
        "company_id": _string_value(row, "companyID", "companyId", "company_id"),
        "created_at": _string_value(row, "createDate", "create_date"),
    }


def _normalize_company(row: Mapping[str, object]) -> dict[str, object] | None:
    company_id = _first_value(row, "id", "companyID", "companyId")
    if company_id in (None, ""):
        return None
    return {
        "id": str(company_id),
        "name": _string_value(row, "companyName", "name"),
        "active": _bool_value(_first_value(row, "isActive", "active")),
    }


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _string_value(row: Mapping[str, object], *keys: str) -> str:
    value = _first_value(row, *keys)
    return "" if value is None else str(value)


def _reference_value(value: object) -> str:
    if isinstance(value, dict):
        for key in ("displayValue", "display_value", "value", "name"):
            if value.get(key) not in (None, ""):
                return str(value[key])
        return ""
    return "" if value is None else str(value)


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else False


def _http_error_message(status_code: int, endpoint: str) -> str:
    if status_code == 401:
        return f"Autotask GET {endpoint} was unauthorized (HTTP 401)."
    if status_code == 403:
        return f"Autotask GET {endpoint} was forbidden (HTTP 403)."
    if status_code == 429:
        return f"Autotask GET {endpoint} was rate limited (HTTP 429)."
    return f"Autotask GET {endpoint} failed with HTTP {status_code}."


__all__ = [
    "AutotaskClient",
    "AutotaskReadError",
    "AutotaskReadProvider",
    "AutotaskReadResponse",
]
