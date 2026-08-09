"""Bounded Autotask REST API adapter.

The adapter exposes ticket and company reads plus one approval-gated ticket
note mutation. Mutations remain behind both local write gates and the existing
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
    AutotaskWriteRequest,
    AutotaskWriteResult,
    ConnectorReadResult,
)

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


class AutotaskWriteProvider(Protocol):
    def write_health(self) -> ConnectorReadResult:
        ...

    def execute_write(self, request: AutotaskWriteRequest) -> AutotaskWriteResult:
        ...


class AutotaskReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AutotaskClient:
    """Bounded Autotask REST client for reads and approved ticket notes."""

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

    def write_health(self) -> ConnectorReadResult:
        blocked = self._write_blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        return ConnectorReadResult("ready", "Autotask ticket-note/status write prerequisites are ready.")

    def execute_write(self, request: AutotaskWriteRequest) -> AutotaskWriteResult:
        blocked = self._write_blocked_write_result(request)
        if blocked is not None:
            return blocked
        missing = self._not_configured_write_result(request)
        if missing is not None:
            return missing
        try:
            ticket_id = _safe_numeric_id(request.ticket_id)
            payload = _write_payload(request.action_type, ticket_id, request.fields)
            if request.action_type == "add_note":
                endpoint = "TicketNotes"
                response_payload, status_code = self._post(endpoint, payload)
            else:
                endpoint = "Tickets"
                response_payload, status_code = self._patch(endpoint, payload)
        except AutotaskReadError as exc:
            return AutotaskWriteResult(
                "failed", exc.message, request.action_type, request.ticket_id
            )
        return AutotaskWriteResult(
            "succeeded",
            f"Autotask {request.action_type} write succeeded.",
            request.action_type,
            request.ticket_id,
            endpoint=endpoint,
            status_code=status_code,
            remote_id=_remote_id(response_payload),
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

    def _post(
        self,
        endpoint: str,
        payload: dict[str, object],
    ) -> tuple[object, int]:
        return self._mutate("POST", endpoint, payload)

    def _patch(
        self,
        endpoint: str,
        payload: dict[str, object],
    ) -> tuple[object, int]:
        return self._mutate("PATCH", endpoint, payload)

    def _mutate(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, object],
    ) -> tuple[object, int]:
        if not self.settings.allow_http_probing:
            raise AutotaskReadError(
                "Autotask live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        if not self.settings.allow_write_actions:
            raise AutotaskReadError(
                "Autotask live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
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
                response = client.request(
                    method,
                    f"{_api_base_url(self.settings.autotask_base_url)}/{safe_endpoint}",
                    headers={
                        "Username": self.settings.autotask_username,
                        "Secret": self.settings.autotask_secret,
                        "APIIntegrationcode": self.settings.autotask_integration_code,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise AutotaskReadError(
                "Autotask request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise AutotaskReadError("Autotask request failed.") from exc
        if response.status_code >= 400:
            raise AutotaskReadError(
                f"Autotask {method} {endpoint} failed with HTTP {response.status_code}."
            )
        if response.status_code != 200:
            raise AutotaskReadError(
                f"Autotask {method} {endpoint} returned unexpected HTTP {response.status_code}."
            )
        if not response.content:
            return {}, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise AutotaskReadError(
                f"Autotask {method} {endpoint} returned malformed JSON."
            ) from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Autotask live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
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
                f"Autotask live writes are blocked until {' and '.join(missing_flags)}.",
            )
        return None

    def _write_blocked_write_result(
        self,
        request: AutotaskWriteRequest,
    ) -> AutotaskWriteResult | None:
        blocked = self._write_blocked_result()
        if blocked is None:
            return None
        return AutotaskWriteResult(
            "blocked", blocked.message, request.action_type, request.ticket_id
        )

    def _not_configured_write_result(
        self,
        request: AutotaskWriteRequest,
    ) -> AutotaskWriteResult | None:
        missing = self._not_configured_result()
        if missing is None:
            return None
        return AutotaskWriteResult(
            "not_configured", missing.message, request.action_type, request.ticket_id
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


def _safe_numeric_id(value: str) -> int:
    stripped = value.strip()
    if not stripped or not stripped.isdigit() or len(stripped) > 19 or int(stripped) < 1:
        raise AutotaskReadError("Autotask ticket identifiers must be positive numeric IDs.")
    return int(stripped)


def _write_payload(
    action_type: str,
    ticket_id: int,
    fields: Mapping[str, object],
) -> dict[str, object]:
    if action_type == "update_status":
        if set(fields) != {"status"}:
            raise AutotaskReadError("Autotask update_status requires only a status field.")
        value = fields["status"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AutotaskReadError("Autotask ticket status must be a non-negative integer.")
        return {"id": ticket_id, "status": value}
    if action_type == "update_resolution":
        if set(fields) != {"resolution"}:
            raise AutotaskReadError("Autotask update_resolution requires only a resolution field.")
        value = fields["resolution"]
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > 32_000
            or any(ord(character) < 32 for character in value)
        ):
            raise AutotaskReadError("Autotask ticket resolution is invalid.")
        return {"id": ticket_id, "resolution": value.strip()}
    if action_type != "add_note":
        raise AutotaskReadError(f"Autotask ticket action is not supported: {action_type}.")
    allowed = {"description", "note_type", "publish", "title"}
    if set(fields) - allowed or not {"description", "note_type", "publish"} <= set(fields):
        raise AutotaskReadError(
            "Autotask add_note requires description, note_type, and publish fields."
        )
    description = fields["description"]
    title = fields.get("title", "")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description.strip()) > 32_000
        or any(ord(character) < 32 for character in description)
    ):
        raise AutotaskReadError("Autotask note description is invalid.")
    if not isinstance(title, str) or len(title.strip()) > 250 or any(
        ord(character) < 32 for character in title
    ):
        raise AutotaskReadError("Autotask note title is invalid.")
    values: dict[str, object] = {"ticketID": ticket_id, "description": description.strip()}
    for source, target in (("note_type", "noteType"), ("publish", "publish")):
        value = fields[source]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AutotaskReadError(f"Autotask note field {source} must be a non-negative integer.")
        values[target] = value
    if title.strip():
        values["title"] = title.strip()
    return values


def _remote_id(payload: object) -> str:
    if not isinstance(payload, Mapping):
        return ""
    value = payload.get("itemId")
    if isinstance(value, bool):
        return ""
    if isinstance(value, int) and value >= 0:
        return str(value)
    if isinstance(value, str) and value.strip().isdigit():
        return value.strip()
    return ""


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
    "AutotaskWriteProvider",
]
