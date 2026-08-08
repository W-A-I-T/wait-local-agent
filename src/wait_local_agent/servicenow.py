"""Read-only ServiceNow Table API adapter.

Only incident and company inventory reads are exposed. The Table API can
mutate records, but this client intentionally constructs GET requests only and
keeps the returned field set narrow.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping

import httpx

from wait_local_agent.autotask import PsaReadResponse
from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult


class ServiceNowReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ServiceNowClient:
    """Bounded, read-only ServiceNow Table API client."""

    _TICKET_FIELDS = "sys_id,number,short_description,company,state,priority,opened_at,sys_updated_on"
    _COMPANY_FIELDS = "sys_id,name,phone,city,state"

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
            return ConnectorReadResult("ready", "ServiceNow read prerequisites are ready.")
        return response.result

    def list_tickets(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        return self._list(
            "incident",
            self._TICKET_FIELDS,
            _normalize_ticket,
            page=page,
            page_size=page_size,
        )

    def get_ticket(self, ticket_id: str) -> PsaReadResponse:
        try:
            safe_id = _safe_segment(ticket_id)
        except ServiceNowReadError as exc:
            return PsaReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"incident/{safe_id}", self._TICKET_FIELDS, _normalize_ticket)

    def list_companies(self, *, page: int = 1, page_size: int | None = None) -> PsaReadResponse:
        return self._list(
            "core_company",
            self._COMPANY_FIELDS,
            _normalize_company,
            page=page,
            page_size=page_size,
        )

    def _list(
        self,
        table: str,
        fields: str,
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
        bounded_size = _bounded_page_size(page_size or self.settings.servicenow_page_size)
        params: dict[str, int | str] = {
            "sysparm_limit": bounded_size,
            "sysparm_offset": max(page - 1, 0) * bounded_size,
            "sysparm_fields": fields,
            "sysparm_display_value": "true",
        }
        return self._request_items(table, fields, normalizer, params=params)

    def _request_items(
        self,
        endpoint: str,
        fields: str,
        normalizer,
        *,
        params: dict[str, int | str] | None = None,
    ) -> PsaReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            payload = self._get(endpoint, fields, params=params)
        except ServiceNowReadError as exc:
            return PsaReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return PsaReadResponse(
            ConnectorReadResult("ready", f"ServiceNow read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(
        self,
        endpoint: str,
        fields: str,
        *,
        params: dict[str, int | str] | None = None,
    ) -> object:
        if not self.settings.allow_http_probing:
            raise ServiceNowReadError("ServiceNow live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.")
        missing = self._not_configured_result()
        if missing is not None:
            raise ServiceNowReadError(missing.message)
        credentials = f"{self.settings.servicenow_username}:{self.settings.servicenow_password}"
        token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        query = dict(params or {})
        if "sysparm_fields" not in query:
            query["sysparm_fields"] = fields
        query.setdefault("sysparm_display_value", "true")
        try:
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{self.settings.servicenow_base_url.rstrip('/')}/api/now/table/{_safe_endpoint(endpoint)}",
                    headers={
                        "Authorization": f"Basic {token}",
                        "Accept": "application/json",
                    },
                    params=query,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ServiceNowReadError("ServiceNow request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise ServiceNowReadError("ServiceNow request failed.") from exc
        if response.status_code >= 400:
            raise ServiceNowReadError(f"ServiceNow GET {endpoint} failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise ServiceNowReadError(f"ServiceNow GET {endpoint} returned malformed JSON.") from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "ServiceNow live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_SERVICENOW_BASE_URL": self.settings.servicenow_base_url,
                "WAIT_SERVICENOW_USERNAME": self.settings.servicenow_username,
                "WAIT_SERVICENOW_PASSWORD": self.settings.servicenow_password,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult("not_configured", f"ServiceNow credentials are incomplete: {', '.join(missing)}.")

    def _blocked_response(self) -> PsaReadResponse | None:
        blocked = self._blocked_result()
        return PsaReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> PsaReadResponse | None:
        missing = self._not_configured_result()
        return PsaReadResponse(missing, []) if missing else None


def _safe_endpoint(endpoint: str) -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise ServiceNowReadError("ServiceNow endpoint overrides must be relative paths.")
    return endpoint.strip("/")


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or any(character in stripped for character in "/?#"):
        raise ServiceNowReadError("ServiceNow resource identifiers must be single path segments.")
    return stripped


def _bounded_page_size(value: int) -> int:
    return max(1, min(value, 100))


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, dict):
        return []
    value = payload.get("result")
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        rows = [value]
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_ticket(row: Mapping[str, object]) -> dict[str, object] | None:
    ticket_id = _first_value(row, "sys_id", "id")
    if ticket_id in (None, ""):
        return None
    company = _first_value(row, "company", "company_id")
    return {
        "id": str(ticket_id),
        "number": _string_value(row, "number"),
        "summary": _string_value(row, "short_description", "subject"),
        "company_id": _reference_value(company, "value") or _string_value(row, "company_id"),
        "company_name": _reference_value(company, "display_value") or _reference_value(company, "name"),
        "status": _string_value(row, "state", "status"),
        "priority": _string_value(row, "priority"),
        "opened_at": _string_value(row, "opened_at", "created_at"),
        "updated_at": _string_value(row, "sys_updated_on", "updated_at"),
    }


def _normalize_company(row: Mapping[str, object]) -> dict[str, object] | None:
    company_id = _first_value(row, "sys_id", "id")
    if company_id in (None, ""):
        return None
    return {
        "id": str(company_id),
        "name": _string_value(row, "name", "company_name"),
        "phone": _string_value(row, "phone"),
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
    if isinstance(value, Mapping):
        return _reference_value(value, "display_value") or _reference_value(value, "name")
    return "" if value is None else str(value)


def _reference_value(value: object, key: str) -> str:
    if isinstance(value, Mapping):
        nested = value.get(key)
        return "" if nested is None else str(nested)
    return "" if value is None else str(value)
