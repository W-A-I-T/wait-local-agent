"""Bounded ServiceNow Table API adapter.

Incident and company reads plus two approval-gated incident mutations are
exposed. Mutations remain behind both local write gates and the existing
smart-action approval runtime.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import (
    ConnectorReadResult,
    ServiceNowWriteRequest,
    ServiceNowWriteResult,
)

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_PAGE = 1_000_000
Normalizer = Callable[[Mapping[str, object]], dict[str, object] | None]


@dataclass(frozen=True)
class ServiceNowReadResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]


class ServiceNowReadProvider(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def list_incidents(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        query: str | None = None,
    ) -> ServiceNowReadResponse:
        ...

    def get_incident(self, sys_id: str) -> ServiceNowReadResponse:
        ...

    def list_companies(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        query: str | None = None,
    ) -> ServiceNowReadResponse:
        ...

    def get_company(self, sys_id: str) -> ServiceNowReadResponse:
        ...


class ServiceNowWriteProvider(Protocol):
    def write_health(self) -> ConnectorReadResult:
        ...

    def execute_write(self, request: ServiceNowWriteRequest) -> ServiceNowWriteResult:
        ...


class ServiceNowReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ServiceNowClient:
    """Bounded ServiceNow Table API client for reads and approved writes."""

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
            return ConnectorReadResult("ready", "ServiceNow read prerequisites are ready.")
        return response.result

    def list_incidents(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        query: str | None = None,
    ) -> ServiceNowReadResponse:
        return self._list(
            "incident",
            "incidents",
            _normalize_incident,
            page=page,
            page_size=page_size,
            query=query,
        )

    def get_incident(self, sys_id: str) -> ServiceNowReadResponse:
        return self._get_record("incident", sys_id, "incidents", _normalize_incident)

    def list_companies(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        query: str | None = None,
    ) -> ServiceNowReadResponse:
        return self._list(
            "core_company",
            "companies",
            _normalize_company,
            page=page,
            page_size=page_size,
            query=query,
        )

    def get_company(self, sys_id: str) -> ServiceNowReadResponse:
        return self._get_record("core_company", sys_id, "companies", _normalize_company)

    def write_health(self) -> ConnectorReadResult:
        blocked = self._write_blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        return ConnectorReadResult("ready", "ServiceNow incident write prerequisites are ready.")

    def execute_write(self, request: ServiceNowWriteRequest) -> ServiceNowWriteResult:
        blocked = self._write_blocked_write_result(request)
        if blocked is not None:
            return blocked
        missing = self._not_configured_write_result(request)
        if missing is not None:
            return missing
        try:
            safe_id = _safe_sys_id(request.ticket_id)
            fields = _write_fields(request.action_type, request.fields)
            endpoint = f"incident/{safe_id}"
            response_payload, status_code = self._patch(endpoint, fields)
        except ServiceNowReadError as exc:
            return ServiceNowWriteResult(
                "failed", exc.message, request.action_type, request.ticket_id
            )
        return ServiceNowWriteResult(
            "succeeded",
            f"ServiceNow {request.action_type} write succeeded.",
            request.action_type,
            request.ticket_id,
            endpoint=endpoint,
            status_code=status_code,
            remote_id=_remote_id(response_payload),
        )

    def _list(
        self,
        table: str,
        label: str,
        normalizer: Normalizer,
        *,
        page: int,
        page_size: int,
        query: str | None,
    ) -> ServiceNowReadResponse:
        unavailable = self._unavailable_response()
        if unavailable is not None:
            return unavailable
        try:
            params = _list_params(table, page, page_size, query)
        except ServiceNowReadError as exc:
            return ServiceNowReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(table, label, normalizer, params=params)

    def _get_record(
        self,
        table: str,
        sys_id: str,
        label: str,
        normalizer: Normalizer,
    ) -> ServiceNowReadResponse:
        unavailable = self._unavailable_response()
        if unavailable is not None:
            return unavailable
        try:
            safe_id = _safe_sys_id(sys_id)
        except ServiceNowReadError as exc:
            return ServiceNowReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(
            f"{table}/{safe_id}",
            label,
            normalizer,
        )

    def _request_items(
        self,
        endpoint: str,
        label: str,
        normalizer: Normalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> ServiceNowReadResponse:
        unavailable = self._unavailable_response()
        if unavailable is not None:
            return unavailable
        try:
            payload = self._get(endpoint, params=params)
        except ServiceNowReadError as exc:
            return ServiceNowReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [
            item
            for row in _payload_rows(payload)
            if (item := normalizer(row)) is not None
        ]
        return ServiceNowReadResponse(
            ConnectorReadResult(
                "ready",
                f"ServiceNow read succeeded from {endpoint}.",
                len(items),
            ),
            items,
        )

    def _get(
        self,
        endpoint: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> object:
        if not self.settings.allow_http_probing:
            raise ServiceNowReadError(
                "ServiceNow live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise ServiceNowReadError(missing.message)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(
                    f"{_api_base_url(self.settings.servicenow_base_url, self.settings.servicenow_api_version)}"
                    f"/{_safe_endpoint(endpoint)}",
                    auth=(self.settings.servicenow_username, self.settings.servicenow_password),
                    headers={"Accept": "application/json"},
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ServiceNowReadError(
                "ServiceNow request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise ServiceNowReadError("ServiceNow request failed.") from exc
        if response.status_code >= 400:
            raise ServiceNowReadError(_http_error_message(response.status_code, endpoint))
        try:
            return response.json()
        except ValueError as exc:
            raise ServiceNowReadError(
                f"ServiceNow GET {endpoint} returned malformed JSON."
            ) from exc

    def _patch(
        self,
        endpoint: str,
        fields: dict[str, object],
    ) -> tuple[object, int]:
        if not self.settings.allow_http_probing:
            raise ServiceNowReadError(
                "ServiceNow live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        if not self.settings.allow_write_actions:
            raise ServiceNowReadError(
                "ServiceNow live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise ServiceNowReadError(missing.message)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.patch(
                    f"{_api_base_url(self.settings.servicenow_base_url, self.settings.servicenow_api_version)}"
                    f"/{_safe_endpoint(endpoint)}",
                    auth=(self.settings.servicenow_username, self.settings.servicenow_password),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json=fields,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ServiceNowReadError(
                "ServiceNow request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise ServiceNowReadError("ServiceNow request failed.") from exc
        if response.status_code >= 400:
            raise ServiceNowReadError(
                f"ServiceNow PATCH {endpoint} failed with HTTP {response.status_code}."
            )
        if not response.content:
            return {}, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise ServiceNowReadError(
                f"ServiceNow PATCH {endpoint} returned malformed JSON."
            ) from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "ServiceNow live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
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
                f"ServiceNow live writes are blocked until {' and '.join(missing_flags)}.",
            )
        return None

    def _write_blocked_write_result(
        self,
        request: ServiceNowWriteRequest,
    ) -> ServiceNowWriteResult | None:
        blocked = self._write_blocked_result()
        if blocked is None:
            return None
        return ServiceNowWriteResult(
            "blocked", blocked.message, request.action_type, request.ticket_id
        )

    def _not_configured_write_result(
        self,
        request: ServiceNowWriteRequest,
    ) -> ServiceNowWriteResult | None:
        missing = self._not_configured_result()
        if missing is None:
            return None
        return ServiceNowWriteResult(
            "not_configured", missing.message, request.action_type, request.ticket_id
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
        if missing:
            return ConnectorReadResult(
                "not_configured",
                f"ServiceNow credentials are incomplete: {', '.join(missing)}.",
            )
        return None

    def _unavailable_response(self) -> ServiceNowReadResponse | None:
        blocked = self._blocked_result()
        if blocked is not None:
            return ServiceNowReadResponse(blocked, [])
        missing = self._not_configured_result()
        return ServiceNowReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str, api_version: str = "") -> str:
    stripped = _safe_base_url(base_url).rstrip("/")
    suffix = "/api/now"
    if stripped.endswith(suffix):
        root = stripped
    elif "/api/now/" in stripped:
        root = stripped.rsplit("/api/now/", 1)[0] + suffix
    else:
        root = f"{stripped}{suffix}"
    version = api_version.strip().strip("/")
    if version:
        return f"{root}/{_safe_version(version)}"
    return root


def _safe_base_url(base_url: str) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise ServiceNowReadError("ServiceNow base URL contains control characters.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ServiceNowReadError("ServiceNow base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ServiceNowReadError(
            "ServiceNow base URL must not contain credentials or query data."
        )
    return base_url


def _safe_version(value: str) -> str:
    if not value or len(value) > 20 or not value.replace("_", "").isalnum():
        raise ServiceNowReadError("ServiceNow API version is invalid.")
    return value


def _safe_endpoint(endpoint: str) -> str:
    parts = endpoint.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise ServiceNowReadError("ServiceNow endpoint is invalid.")
    if any(not all(character.isalnum() or character in {"_", "-"} for character in part) for part in parts):
        raise ServiceNowReadError("ServiceNow endpoint contains unsafe characters.")
    return "/".join(parts)


def _safe_sys_id(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > 64 or not all(
        character.isalnum() or character in {"_", "-"} for character in stripped
    ):
        raise ServiceNowReadError("ServiceNow record identifiers contain unsafe characters.")
    return stripped


def _write_fields(action_type: str, fields: Mapping[str, object]) -> dict[str, object]:
    if action_type == "add_work_note":
        if set(fields) != {"work_notes"}:
            raise ServiceNowReadError(
                "ServiceNow add_work_note requires only the work_notes field."
            )
        value = fields["work_notes"]
        if not isinstance(value, str) or not value.strip() or len(value) > 4_000:
            raise ServiceNowReadError(
                "ServiceNow work_notes must be non-empty text of at most 4000 characters."
            )
        return {"work_notes": value.strip()}
    if action_type == "update_state":
        if set(fields) != {"incident_state"}:
            raise ServiceNowReadError(
                "ServiceNow update_state requires only the incident_state field."
            )
        value = fields["incident_state"]
        if not isinstance(value, str) or not value.strip() or len(value) > 20:
            raise ServiceNowReadError(
                "ServiceNow incident_state must be non-empty text of at most 20 characters."
            )
        return {"incident_state": value.strip()}
    if action_type == "update_resolution":
        if set(fields) != {"close_code", "close_notes"}:
            raise ServiceNowReadError(
                "ServiceNow update_resolution requires close_code and close_notes."
            )
        close_code = fields["close_code"]
        close_notes = fields["close_notes"]
        if (
            not isinstance(close_code, str)
            or not close_code.strip()
            or len(close_code) > 128
            or any(ord(character) < 32 for character in close_code)
        ):
            raise ServiceNowReadError(
                "ServiceNow close_code must be non-empty text of at most 128 characters."
            )
        if (
            not isinstance(close_notes, str)
            or not close_notes.strip()
            or len(close_notes) > 4_000
            or any(ord(character) < 32 for character in close_notes)
        ):
            raise ServiceNowReadError(
                "ServiceNow close_notes must be non-empty text of at most 4000 characters."
            )
        return {"close_code": close_code.strip(), "close_notes": close_notes.strip()}
    if action_type == "assign_incident":
        if set(fields) not in ({"assigned_to"}, {"assignment_group"}):
            raise ServiceNowReadError(
                "ServiceNow assign_incident requires exactly one of assigned_to or assignment_group."
            )
        field, value = next(iter(fields.items()))
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise ServiceNowReadError(
                f"ServiceNow {field} must be a non-empty reference of at most 64 characters."
            )
        if not all(character.isalnum() or character in {"_", "-"} for character in value.strip()):
            raise ServiceNowReadError(f"ServiceNow {field} contains unsafe characters.")
        return {field: value.strip()}
    raise ServiceNowReadError(f"ServiceNow incident action is not supported: {action_type}.")


def _remote_id(payload: object) -> str:
    if not isinstance(payload, Mapping):
        return ""
    result = payload.get("result", payload)
    if not isinstance(result, Mapping):
        return ""
    value = result.get("sys_id")
    return value.strip() if isinstance(value, str) and len(value) <= 64 else ""


def _safe_query(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) > 500 or any(ord(character) < 32 for character in stripped):
        raise ServiceNowReadError(
            "ServiceNow queries are too long or contain control characters."
        )
    return stripped or None


def _list_params(
    table: str,
    page: int,
    page_size: int,
    query: str | None,
) -> dict[str, str | int]:
    if isinstance(page, bool) or page < 1 or page > MAX_PAGE:
        raise ServiceNowReadError(f"ServiceNow page must be between 1 and {MAX_PAGE}.")
    if isinstance(page_size, bool) or page_size < 1:
        raise ServiceNowReadError("ServiceNow page_size must be at least 1.")
    safe_query = _safe_query(query)
    fields = {
        "incident": (
            "sys_id,number,short_description,description,state,priority,urgency,"
            "company,caller_id,assigned_to,sys_created_on,sys_updated_on"
        ),
        "core_company": "sys_id,name,active,sys_created_on,sys_updated_on",
    }.get(table)
    if fields is None:
        raise ServiceNowReadError("ServiceNow table is not enabled for reads.")
    params: dict[str, str | int] = {
        "sysparm_limit": min(page_size, MAX_PAGE_SIZE),
        "sysparm_offset": (page - 1) * min(page_size, MAX_PAGE_SIZE),
        "sysparm_fields": fields,
        "sysparm_display_value": "true",
    }
    if safe_query is not None:
        params["sysparm_query"] = safe_query
    return params


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get("result")
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = [value]
        elif "sys_id" in payload:
            rows = [payload]
        else:
            rows = []
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_incident(row: Mapping[str, object]) -> dict[str, object] | None:
    sys_id = row.get("sys_id")
    if sys_id in (None, ""):
        return None
    return {
        "sys_id": str(sys_id),
        "number": _string_value(row, "number"),
        "short_description": _string_value(row, "short_description"),
        "description": _string_value(row, "description"),
        "state": _reference_value(row.get("state")),
        "priority": _reference_value(row.get("priority")),
        "urgency": _reference_value(row.get("urgency")),
        "company": _reference_value(row.get("company")),
        "caller": _reference_value(row.get("caller_id")),
        "assigned_to": _reference_value(row.get("assigned_to")),
        "created_at": _string_value(row, "sys_created_on"),
        "updated_at": _string_value(row, "sys_updated_on"),
    }


def _normalize_company(row: Mapping[str, object]) -> dict[str, object] | None:
    sys_id = row.get("sys_id")
    if sys_id in (None, ""):
        return None
    return {
        "sys_id": str(sys_id),
        "name": _string_value(row, "name"),
        "active": _bool_value(row.get("active")),
        "created_at": _string_value(row, "sys_created_on"),
        "updated_at": _string_value(row, "sys_updated_on"),
    }


def _string_value(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value)


def _reference_value(value: object) -> str:
    if isinstance(value, dict):
        for key in ("display_value", "value", "name"):
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
        return f"ServiceNow GET {endpoint} was unauthorized (HTTP 401)."
    if status_code == 403:
        return f"ServiceNow GET {endpoint} was forbidden (HTTP 403)."
    if status_code == 429:
        return f"ServiceNow GET {endpoint} was rate limited (HTTP 429)."
    return f"ServiceNow GET {endpoint} failed with HTTP {status_code}."


__all__ = [
    "ServiceNowClient",
    "ServiceNowReadError",
    "ServiceNowReadProvider",
    "ServiceNowReadResponse",
]
