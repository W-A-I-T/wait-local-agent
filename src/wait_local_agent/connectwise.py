"""Bounded ConnectWise PSA adapter.

This adapter intentionally normalizes only the ticket and company fields used
by the local agent. Ticket mutations use a small, explicit JSON-patch field map
and remain behind both local write gates and the approval system. Credentials
stay in the settings boundary rather than request payloads.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import (
    ConnectorReadResult,
    ConnectWiseWriteRequest,
    ConnectWiseWriteResult,
)

QueryValue = str | int | None
Normalizer = Callable[[Mapping[str, object]], dict[str, object] | None]
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class ConnectWiseReadResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]


class ConnectWiseReadProvider(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def list_tickets(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        conditions: str | None = None,
    ) -> ConnectWiseReadResponse:
        ...

    def get_ticket(self, ticket_id: str) -> ConnectWiseReadResponse:
        ...

    def list_companies(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        conditions: str | None = None,
    ) -> ConnectWiseReadResponse:
        ...


class ConnectWiseWriteProvider(Protocol):
    def write_health(self) -> ConnectorReadResult:
        ...

    def execute_write(self, request: ConnectWiseWriteRequest) -> ConnectWiseWriteResult:
        ...


class ConnectWiseReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConnectWiseClient:
    """Bounded ConnectWise PSA REST client for reads and approved ticket writes."""

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
        response = self.list_companies(page=1, page_size=1)
        if response.result.status == "ready":
            return ConnectorReadResult("ready", "ConnectWise PSA read prerequisites are ready.")
        return response.result

    def write_health(self) -> ConnectorReadResult:
        blocked = self._write_blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        return ConnectorReadResult("ready", "ConnectWise PSA write prerequisites are ready.")

    def list_tickets(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        conditions: str | None = None,
    ) -> ConnectWiseReadResponse:
        return self._list(
            "service/tickets",
            _normalize_ticket,
            page=page,
            page_size=page_size,
            conditions=conditions,
        )

    def get_ticket(self, ticket_id: str) -> ConnectWiseReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            safe_id = _safe_segment(ticket_id)
        except ConnectWiseReadError as exc:
            return ConnectWiseReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"service/tickets/{safe_id}", _normalize_ticket)

    def execute_write(self, request: ConnectWiseWriteRequest) -> ConnectWiseWriteResult:
        blocked = self._write_blocked_write_result(request)
        if blocked is not None:
            return blocked
        missing = self._not_configured_write_result(request)
        if missing is not None:
            return missing
        try:
            endpoint, patch = _write_endpoint_and_patch(request)
            response_payload, status_code = self._patch(endpoint, patch)
        except ConnectWiseReadError as exc:
            return ConnectWiseWriteResult(
                "failed", exc.message, request.action_type, request.ticket_id
            )
        return ConnectWiseWriteResult(
            "succeeded",
            f"ConnectWise PSA {request.action_type} write succeeded.",
            request.action_type,
            request.ticket_id,
            endpoint=endpoint,
            status_code=status_code,
            remote_id=_remote_id(response_payload),
        )

    def list_companies(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        conditions: str | None = None,
    ) -> ConnectWiseReadResponse:
        return self._list(
            "company/companies",
            _normalize_company,
            page=page,
            page_size=page_size,
            conditions=conditions,
        )

    def _list(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        page: int,
        page_size: int,
        conditions: str | None,
    ) -> ConnectWiseReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            params = _list_params(page, page_size, conditions)
        except ConnectWiseReadError as exc:
            return ConnectWiseReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(endpoint, normalizer, params=params)

    def _request_items(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        params: dict[str, QueryValue] | None = None,
    ) -> ConnectWiseReadResponse:
        try:
            payload = self._get(endpoint, params=params)
        except ConnectWiseReadError as exc:
            return ConnectWiseReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return ConnectWiseReadResponse(
            ConnectorReadResult("ready", f"ConnectWise PSA read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(
        self,
        endpoint: str,
        *,
        params: dict[str, QueryValue] | None = None,
    ) -> object:
        if not self.settings.allow_http_probing:
            raise ConnectWiseReadError(
                "ConnectWise PSA live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise ConnectWiseReadError(missing.message)
        try:
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{_api_base_url(self.settings.connectwise_base_url)}/{_safe_endpoint(endpoint)}",
                    headers=self._headers(),
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ConnectWiseReadError(
                "ConnectWise PSA request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectWiseReadError("ConnectWise PSA request failed.") from exc
        if response.status_code >= 400:
            raise ConnectWiseReadError(
                f"ConnectWise PSA GET {endpoint} failed with HTTP {response.status_code}."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectWiseReadError(
                f"ConnectWise PSA GET {endpoint} returned malformed JSON."
            ) from exc

    def _patch(self, endpoint: str, payload: list[dict[str, object]]) -> tuple[object, int]:
        if not self.settings.allow_http_probing:
            raise ConnectWiseReadError(
                "ConnectWise PSA live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        if not self.settings.allow_write_actions:
            raise ConnectWiseReadError(
                "ConnectWise PSA live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise ConnectWiseReadError(missing.message)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.patch(
                    f"{_api_base_url(self.settings.connectwise_base_url)}/{_safe_endpoint(endpoint)}",
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ConnectWiseReadError(
                "ConnectWise PSA request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectWiseReadError("ConnectWise PSA request failed.") from exc
        if response.status_code >= 400:
            raise ConnectWiseReadError(
                f"ConnectWise PSA PATCH {endpoint} failed with HTTP {response.status_code}."
            )
        if not response.content:
            return {}, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise ConnectWiseReadError(
                f"ConnectWise PSA PATCH {endpoint} returned malformed JSON."
            ) from exc

    def _headers(self) -> dict[str, str]:
        credentials = (
            f"{self.settings.connectwise_company}+{self.settings.connectwise_public_key}:"
            f"{self.settings.connectwise_private_key}"
        )
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        version = _safe_version(self.settings.connectwise_api_version)
        return {
            "Authorization": f"Basic {encoded}",
            "ClientID": self.settings.connectwise_client_id,
            "Accept": f"application/vnd.connectwise.com+json; version={version}",
        }

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "ConnectWise PSA live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _write_blocked_result(self) -> ConnectorReadResult | None:
        missing_flags = []
        if not self.settings.allow_http_probing:
            missing_flags.append("WAIT_ALLOW_HTTP_PROBING=true")
        if not self.settings.allow_write_actions:
            missing_flags.append("WAIT_ALLOW_WRITE_ACTIONS=true")
        if missing_flags:
            return ConnectorReadResult(
                "blocked",
                f"ConnectWise PSA live writes are blocked until {' and '.join(missing_flags)}.",
            )
        return None

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_CONNECTWISE_BASE_URL": self.settings.connectwise_base_url,
                "WAIT_CONNECTWISE_COMPANY": self.settings.connectwise_company,
                "WAIT_CONNECTWISE_PUBLIC_KEY": self.settings.connectwise_public_key,
                "WAIT_CONNECTWISE_PRIVATE_KEY": self.settings.connectwise_private_key,
                "WAIT_CONNECTWISE_CLIENT_ID": self.settings.connectwise_client_id,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorReadResult(
                "not_configured",
                f"ConnectWise PSA credentials are incomplete: {', '.join(missing)}.",
            )
        return None

    def _blocked_response(self) -> ConnectWiseReadResponse | None:
        blocked = self._blocked_result()
        return ConnectWiseReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> ConnectWiseReadResponse | None:
        missing = self._not_configured_result()
        return ConnectWiseReadResponse(missing, []) if missing else None

    def _write_blocked_write_result(
        self, request: ConnectWiseWriteRequest
    ) -> ConnectWiseWriteResult | None:
        blocked = self._write_blocked_result()
        if blocked is None:
            return None
        return ConnectWiseWriteResult(
            "blocked", blocked.message, request.action_type, request.ticket_id
        )

    def _not_configured_write_result(
        self, request: ConnectWiseWriteRequest
    ) -> ConnectWiseWriteResult | None:
        missing = self._not_configured_result()
        if missing is None:
            return None
        return ConnectWiseWriteResult(
            "not_configured", missing.message, request.action_type, request.ticket_id
        )


def _api_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    suffix = "/v4_6_release/apis/3.0"
    if stripped.endswith(suffix):
        return stripped
    return f"{stripped}{suffix}"


def _safe_endpoint(endpoint: str) -> str:
    if "\x00" in endpoint or "://" in endpoint or endpoint.startswith("//"):
        raise ConnectWiseReadError("ConnectWise PSA endpoint must be a relative path.")
    parts = endpoint.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise ConnectWiseReadError("ConnectWise PSA endpoint is invalid.")
    return "/".join(parts)


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or any(character in stripped for character in "/?#"):
        raise ConnectWiseReadError("ConnectWise PSA resource identifiers must be single path segments.")
    return stripped


def _safe_version(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > 20 or any(character not in "0123456789." for character in stripped):
        raise ConnectWiseReadError("ConnectWise PSA API version is invalid.")
    return stripped


def _list_params(page: int, page_size: int, conditions: str | None) -> dict[str, QueryValue]:
    if isinstance(page, bool) or page < 1:
        raise ConnectWiseReadError("ConnectWise PSA page must be at least 1.")
    if isinstance(page_size, bool) or page_size < 1:
        raise ConnectWiseReadError("ConnectWise PSA page_size must be at least 1.")
    if conditions is not None:
        if len(conditions) > 500 or any(ord(character) < 32 for character in conditions):
            raise ConnectWiseReadError("ConnectWise PSA conditions are too long or contain control characters.")
    params: dict[str, QueryValue] = {
        "page": page,
        "pageSize": min(page_size, MAX_PAGE_SIZE),
    }
    if conditions and conditions.strip():
        params["conditions"] = conditions.strip()
    return params


_CONNECTWISE_WRITE_FIELDS = {
    "summary": "/summary",
    "description": "/initialDescription",
    "status_id": "/status/id",
    "priority_id": "/priority/id",
    "board_id": "/board/id",
    "owner_id": "/owner/id",
    "team_id": "/team/id",
}


def _write_endpoint_and_patch(
    request: ConnectWiseWriteRequest,
) -> tuple[str, list[dict[str, object]]]:
    safe_id = _safe_segment(request.ticket_id)
    action_type = request.action_type.strip()
    if action_type not in {"update_status", "assign_technician", "update_ticket_fields"}:
        raise ConnectWiseReadError(f"unsupported ConnectWise PSA action type: {action_type}")
    fields = request.fields
    if not isinstance(fields, dict) or not fields:
        raise ConnectWiseReadError(f"ConnectWise PSA {action_type} requires ticket fields.")
    if action_type == "update_status":
        allowed = {"status_id"}
    elif action_type == "assign_technician":
        allowed = {"owner_id", "team_id"}
    else:
        allowed = set(_CONNECTWISE_WRITE_FIELDS)
    unknown = set(fields) - allowed
    if unknown:
        raise ConnectWiseReadError("ConnectWise PSA ticket fields contain unsupported keys.")
    patch: list[dict[str, object]] = []
    for field, path in _CONNECTWISE_WRITE_FIELDS.items():
        if field not in fields:
            continue
        value = fields[field]
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ConnectWiseReadError(f"ConnectWise PSA field {field} must be text or a number.")
        if isinstance(value, str):
            value = value.strip()
            if not value or len(value) > 2000 or any(ord(character) < 32 for character in value):
                raise ConnectWiseReadError(f"ConnectWise PSA field {field} is invalid.")
        patch.append({"op": "replace", "path": path, "value": value})
    return f"service/tickets/{safe_id}", patch


def _remote_id(payload: object) -> str:
    if isinstance(payload, dict):
        value = payload.get("id")
        if value not in (None, ""):
            return str(value)
    return ""


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
    ticket_id = _first_value(row, "id", "ticketNumber")
    if ticket_id in (None, ""):
        return None
    return {
        "id": str(ticket_id),
        "summary": _string_value(row, "summary", "subject"),
        "description": _string_value(row, "initialDescription", "description"),
        "status": _nested_name(row.get("status")),
        "priority": _nested_name(row.get("priority")),
        "company_id": _nested_value(row.get("company"), "id"),
        "company_name": _nested_value(row.get("company"), "name"),
        "board": _nested_name(row.get("board")),
    }


def _normalize_company(row: Mapping[str, object]) -> dict[str, object] | None:
    company_id = _first_value(row, "id", "identifier")
    if company_id in (None, ""):
        return None
    return {
        "id": str(company_id),
        "name": _string_value(row, "name", "companyName"),
        "status": _nested_name(row.get("status")) or _string_value(row, "status"),
    }


def _nested_name(value: object) -> str:
    if isinstance(value, dict):
        return _string_value(value, "name", "value", "id")
    return "" if value is None else str(value)


def _nested_value(value: object, key: str) -> str:
    if not isinstance(value, dict):
        return ""
    item = value.get(key)
    return "" if item is None else str(item)


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _string_value(row: Mapping[str, object], *keys: str) -> str:
    value = _first_value(row, *keys)
    return "" if value is None else str(value)


__all__ = [
    "ConnectWiseClient",
    "ConnectWiseReadError",
    "ConnectWiseReadProvider",
    "ConnectWiseReadResponse",
    "ConnectWiseWriteProvider",
    "ConnectWiseWriteResult",
]
