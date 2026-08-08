"""Read-only ConnectWise PSA REST API adapter.

The adapter intentionally exposes ticket and company inventory only. ConnectWise
supports write operations, but this integration does not call them; any future
write path must reuse WAIT's approval and execution gates.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping

import httpx

from wait_local_agent.autotask import PsaReadResponse
from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult


class ConnectWiseReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConnectWiseClient:
    """Bounded, read-only ConnectWise PSA client."""

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
            return ConnectorReadResult("ready", "ConnectWise read prerequisites are ready.")
        return response.result

    def list_tickets(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        return self._list("service/tickets", _normalize_ticket, page=page, page_size=page_size)

    def get_ticket(self, ticket_id: str) -> PsaReadResponse:
        try:
            safe_id = _safe_segment(ticket_id)
        except ConnectWiseReadError as exc:
            return PsaReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"service/tickets/{safe_id}", _normalize_ticket)

    def list_companies(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        return self._list("company/companies", _normalize_company, page=page, page_size=page_size)

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
        params = {
            "page": max(page, 1),
            "pageSize": _bounded_page_size(page_size or self.settings.connectwise_page_size),
        }
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
        except ConnectWiseReadError as exc:
            return PsaReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return PsaReadResponse(
            ConnectorReadResult("ready", f"ConnectWise read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(self, endpoint: str, *, params: dict[str, int] | None = None) -> object:
        if not self.settings.allow_http_probing:
            raise ConnectWiseReadError("ConnectWise live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.")
        missing = self._not_configured_result()
        if missing is not None:
            raise ConnectWiseReadError(missing.message)
        credentials = f"{self.settings.connectwise_company_id}+{self.settings.connectwise_public_key}"
        credentials = f"{credentials}:{self.settings.connectwise_private_key}"
        basic_token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        try:
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{self.settings.connectwise_base_url.rstrip('/')}/{_safe_endpoint(endpoint)}",
                    headers={
                        "Authorization": f"Basic {basic_token}",
                        "clientId": self.settings.connectwise_client_id,
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ConnectWiseReadError("ConnectWise request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise ConnectWiseReadError("ConnectWise request failed.") from exc
        if response.status_code >= 400:
            raise ConnectWiseReadError(f"ConnectWise GET {endpoint} failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectWiseReadError(f"ConnectWise GET {endpoint} returned malformed JSON.") from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "ConnectWise live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_CONNECTWISE_BASE_URL": self.settings.connectwise_base_url,
                "WAIT_CONNECTWISE_COMPANY_ID": self.settings.connectwise_company_id,
                "WAIT_CONNECTWISE_PUBLIC_KEY": self.settings.connectwise_public_key,
                "WAIT_CONNECTWISE_PRIVATE_KEY": self.settings.connectwise_private_key,
                "WAIT_CONNECTWISE_CLIENT_ID": self.settings.connectwise_client_id,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"ConnectWise credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> PsaReadResponse | None:
        blocked = self._blocked_result()
        return PsaReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> PsaReadResponse | None:
        missing = self._not_configured_result()
        return PsaReadResponse(missing, []) if missing else None


def _safe_endpoint(endpoint: str) -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise ConnectWiseReadError("ConnectWise endpoint overrides must be relative paths.")
    return endpoint.strip("/")


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or any(character in stripped for character in "/?#"):
        raise ConnectWiseReadError("ConnectWise resource identifiers must be single path segments.")
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
    ticket_id = _first_value(row, "id", "ticketId", "ticket_id")
    if ticket_id in (None, ""):
        return None
    company = _first_value(row, "company", "companyReference")
    board = _first_value(row, "board", "boardReference")
    status = _first_value(row, "status", "statusReference")
    priority = _first_value(row, "priority", "priorityReference")
    return {
        "id": str(ticket_id),
        "summary": _string_value(row, "summary", "subject"),
        "record_type": _string_value(row, "recordType", "type"),
        "company_id": _nested_string(company, "id") or _string_value(row, "companyId", "company_id"),
        "company_name": _nested_string(company, "name"),
        "board_name": _nested_string(board, "name"),
        "status": _nested_string(status, "name"),
        "priority": _nested_string(priority, "name"),
        "date_entered": _string_value(row, "dateEntered", "date_entered"),
    }


def _normalize_company(row: Mapping[str, object]) -> dict[str, object] | None:
    company_id = _first_value(row, "id", "companyId", "company_id")
    if company_id in (None, ""):
        return None
    return {
        "id": str(company_id),
        "name": _string_value(row, "name", "companyName", "company_name"),
        "status": _nested_string(_first_value(row, "status", "statusReference"), "name"),
        "identifier": _string_value(row, "identifier", "companyIdentifier"),
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
