"""Read-only Autotask REST API adapter.

The adapter deliberately exposes inventory and ticket lookup only.  Autotask
supports writes, but this integration does not call them; write behavior must
be added through the existing approval records and execution gates first.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult


@dataclass(frozen=True)
class PsaReadResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]


class PsaClient(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def list_tickets(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        ...

    def get_ticket(self, ticket_id: str) -> PsaReadResponse:
        ...

    def list_companies(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        ...


class AutotaskReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AutotaskClient:
    """Bounded, read-only Autotask REST client."""

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
        try:
            self._get("Tickets/entityInformation")
        except AutotaskReadError as exc:
            return ConnectorReadResult("failed", exc.message)
        return ConnectorReadResult("ready", "Autotask read prerequisites are ready.")

    def list_tickets(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        return self._list("Tickets/query", _normalize_ticket, page=page, page_size=page_size)

    def get_ticket(self, ticket_id: str) -> PsaReadResponse:
        try:
            safe_id = _safe_segment(ticket_id)
        except AutotaskReadError as exc:
            return PsaReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"Tickets/{safe_id}", _normalize_ticket)

    def list_companies(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        return self._list("Companies/query", _normalize_company, page=page, page_size=page_size)

    def _list(
        self,
        endpoint: str,
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
        params = {"page": max(page, 1), "pageSize": _bounded_page_size(page_size or self.settings.autotask_page_size)}
        return self._request_items(endpoint, normalizer, params=params)

    def _request_items(
        self,
        endpoint: str,
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
        except AutotaskReadError as exc:
            return PsaReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return PsaReadResponse(
            ConnectorReadResult("ready", f"Autotask read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(self, endpoint: str, *, params: dict[str, int] | None = None) -> object:
        if not self.settings.allow_http_probing:
            raise AutotaskReadError("Autotask live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.")
        missing = self._not_configured_result()
        if missing is not None:
            raise AutotaskReadError(missing.message)
        try:
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{_api_base_url(self.settings.autotask_base_url)}/{_safe_endpoint(endpoint)}",
                    headers={
                        "Username": self.settings.autotask_username,
                        "Secret": self.settings.autotask_secret,
                        "APIIntegrationcode": self.settings.autotask_integration_code,
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise AutotaskReadError("Autotask request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise AutotaskReadError("Autotask request failed.") from exc
        if response.status_code >= 400:
            raise AutotaskReadError(f"Autotask GET {endpoint} failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise AutotaskReadError(f"Autotask GET {endpoint} returned malformed JSON.") from exc

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
        if not missing:
            return None
        return ConnectorReadResult("not_configured", f"Autotask credentials are incomplete: {', '.join(missing)}.")

    def _blocked_response(self) -> PsaReadResponse | None:
        blocked = self._blocked_result()
        return PsaReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> PsaReadResponse | None:
        missing = self._not_configured_result()
        return PsaReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/atservicesrest/v1.0"):
        return stripped
    if stripped.endswith("/atservicesrest"):
        return f"{stripped}/v1.0"
    return f"{stripped}/atservicesrest/v1.0"


def _safe_endpoint(endpoint: str) -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise AutotaskReadError("Autotask endpoint overrides must be relative paths.")
    return endpoint.strip("/")


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or any(character in stripped for character in "/?#"):
        raise AutotaskReadError("Autotask resource identifiers must be single path segments.")
    return stripped


def _bounded_page_size(value: int) -> int:
    return max(1, min(value, 100))


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get("items")
        rows = value if isinstance(value, list) else [payload]
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
        "status": _string_value(row, "status", "statusName"),
        "priority": _string_value(row, "priority", "priorityName"),
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
        "active": _bool_value(row, "isActive", "active"),
    }


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _string_value(row: Mapping[str, object], *keys: str) -> str:
    value = _first_value(row, *keys)
    return "" if value is None else str(value)


def _bool_value(row: Mapping[str, object], *keys: str) -> bool:
    value = _first_value(row, *keys)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else False
