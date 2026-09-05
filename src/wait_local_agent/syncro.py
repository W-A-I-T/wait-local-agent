"""Bounded Syncro PSA REST adapter.

The public Syncro API exposes many mutation endpoints. This adapter deliberately
uses ticket/customer reads and the explicitly approved ticket-comment endpoint.
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
    SyncroWriteRequest,
    SyncroWriteResult,
)
from wait_local_agent.net_security import NetSecurityError, validate_operator_url

DEFAULT_PAGE = 1
MAX_PAGE = 1_000_000
Normalizer = Callable[[Mapping[str, object]], dict[str, object] | None]


@dataclass(frozen=True)
class SyncroReadResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]


@dataclass(frozen=True)
class SyncroCommentsResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]
    meta: dict[str, int]


class SyncroReadProvider(Protocol):
    def health(self) -> ConnectorReadResult: ...

    def list_tickets(
        self,
        *,
        page: int = DEFAULT_PAGE,
        query: str | None = None,
        customer_id: str | None = None,
        status: str | None = None,
        since_updated_at: str | None = None,
    ) -> SyncroReadResponse: ...

    def get_ticket(self, ticket_id: str) -> SyncroReadResponse: ...

    def list_ticket_comments(
        self,
        ticket_id: str,
        *,
        page: int = 1,
        per_page: int = 10,
        sort_by: str = "created_at",
        sort_direction: str = "ASC",
        created_after: str | None = None,
        created_before: str | None = None,
    ) -> SyncroCommentsResponse: ...

    def list_customers(
        self,
        *,
        page: int = DEFAULT_PAGE,
        query: str | None = None,
        business_name: str | None = None,
    ) -> SyncroReadResponse: ...

    def get_customer(self, customer_id: str) -> SyncroReadResponse: ...


class SyncroWriteProvider(Protocol):
    def write_health(self) -> ConnectorReadResult: ...

    def execute_write(self, request: SyncroWriteRequest) -> SyncroWriteResult: ...


class SyncroReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SyncroClient:
    """Bounded Syncro REST client for reads and approved ticket comments."""

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

    def list_ticket_comments(
        self,
        ticket_id: str,
        *,
        page: int = 1,
        per_page: int = 10,
        sort_by: str = "created_at",
        sort_direction: str = "ASC",
        created_after: str | None = None,
        created_before: str | None = None,
    ) -> SyncroCommentsResponse:
        available = self._unavailable_response()
        if available is not None:
            return SyncroCommentsResponse(available.result, [], {})
        try:
            safe_id = _safe_id(ticket_id)
            params = _comment_params(
                page=page,
                per_page=per_page,
                sort_by=sort_by,
                sort_direction=sort_direction,
                created_after=created_after,
                created_before=created_before,
            )
        except SyncroReadError as exc:
            return SyncroCommentsResponse(ConnectorReadResult("failed", exc.message), [], {})
        try:
            payload = self._get(f"tickets/{safe_id}/comments", params=params)
        except SyncroReadError as exc:
            return SyncroCommentsResponse(ConnectorReadResult("failed", exc.message), [], {})
        items = [item for row in _payload_rows(payload, "comments") if (item := _normalize_comment(row)) is not None]
        return SyncroCommentsResponse(
            ConnectorReadResult(
                "ready", f"Syncro ticket comments read succeeded from tickets/{safe_id}/comments.", len(items)
            ),
            items,
            _comment_meta(payload),
        )

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

    def write_health(self) -> ConnectorReadResult:
        blocked = self._write_blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        return ConnectorReadResult("ready", "Syncro ticket write prerequisites are ready.")

    def execute_write(self, request: SyncroWriteRequest) -> SyncroWriteResult:
        blocked = self._write_blocked_write_result(request)
        if blocked is not None:
            return blocked
        missing = self._not_configured_write_result(request)
        if missing is not None:
            return missing
        try:
            safe_id = _safe_id(request.ticket_id)
            payload = _write_payload(request.action_type, request.fields)
            endpoint = f"tickets/{safe_id}/comment"
            response_payload, status_code = self._post(endpoint, payload)
        except SyncroReadError as exc:
            return SyncroWriteResult("failed", exc.message, request.action_type, request.ticket_id)
        return SyncroWriteResult(
            "succeeded",
            f"Syncro {request.action_type} write succeeded.",
            request.action_type,
            request.ticket_id,
            endpoint=endpoint,
            status_code=status_code,
            remote_id=_remote_id(response_payload),
        )

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
        items = [item for row in _payload_rows(payload, payload_key) if (item := normalizer(row)) is not None]
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
            raise SyncroReadError("Syncro live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.")
        missing = self._not_configured_result()
        if missing is not None:
            raise SyncroReadError(missing.message)
        try:
            base_url = _api_base_url(
                _safe_base_url(
                    self.settings.syncro_base_url,
                    allow_insecure_transport=self.settings.allow_insecure_provider_transport,
                )
            )
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(
                    f"{base_url}/"
                    f"{_safe_endpoint(endpoint)}",
                    headers={
                        "Authorization": f"Bearer {self.settings.syncro_api_token}",
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise SyncroReadError("Syncro request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise SyncroReadError("Syncro request failed.") from exc
        if response.status_code >= 400:
            raise SyncroReadError(_http_error_message(response.status_code, endpoint))
        try:
            return response.json()
        except ValueError as exc:
            raise SyncroReadError(f"Syncro GET {endpoint} returned malformed JSON.") from exc

    def _post(self, endpoint: str, payload: dict[str, object]) -> tuple[object, int]:
        if not self.settings.allow_http_probing:
            raise SyncroReadError("Syncro live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true.")
        if not self.settings.allow_write_actions:
            raise SyncroReadError("Syncro live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true.")
        missing = self._not_configured_result()
        if missing is not None:
            raise SyncroReadError(missing.message)
        try:
            base_url = _api_base_url(
                _safe_base_url(
                    self.settings.syncro_base_url,
                    allow_insecure_transport=self.settings.allow_insecure_provider_transport,
                )
            )
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    f"{base_url}/"
                    f"{_safe_endpoint(endpoint)}",
                    headers={
                        "Authorization": f"Bearer {self.settings.syncro_api_token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise SyncroReadError("Syncro POST request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise SyncroReadError("Syncro POST request failed.") from exc
        if response.status_code >= 400:
            raise SyncroReadError(_http_error_message(response.status_code, endpoint, method="POST"))
        if response.status_code not in {200, 201}:
            raise SyncroReadError(f"Syncro POST {endpoint} returned unexpected HTTP {response.status_code}.")
        if not response.content:
            return {}, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise SyncroReadError(f"Syncro POST {endpoint} returned malformed JSON.") from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Syncro live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _write_blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing and self.settings.allow_write_actions:
            return None
        if not self.settings.allow_http_probing:
            return ConnectorReadResult(
                "blocked",
                "Syncro live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
            )
        return ConnectorReadResult(
            "blocked",
            "Syncro live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true.",
        )

    def _write_blocked_write_result(self, request: SyncroWriteRequest) -> SyncroWriteResult | None:
        blocked = self._write_blocked_result()
        if blocked is None:
            return None
        return SyncroWriteResult(
            "blocked",
            blocked.message,
            request.action_type,
            request.ticket_id,
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

    def _not_configured_write_result(self, request: SyncroWriteRequest) -> SyncroWriteResult | None:
        missing = self._not_configured_result()
        if missing is None:
            return None
        return SyncroWriteResult(
            "not_configured",
            missing.message,
            request.action_type,
            request.ticket_id,
        )

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


def _safe_base_url(base_url: str, *, allow_insecure_transport: bool = False) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise SyncroReadError("Syncro base URL contains control characters.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SyncroReadError("Syncro base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SyncroReadError("Syncro base URL must not contain credentials or query data.")
    try:
        validate_operator_url(base_url, allow_insecure_transport=allow_insecure_transport)
    except NetSecurityError as exc:
        raise SyncroReadError(
            "Syncro base URL must use HTTPS; set WAIT_ALLOW_INSECURE_PROVIDER_TRANSPORT=true to allow plain HTTP."
        ) from exc
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
    if len(stripped) > 200 or any(ord(character) < 32 or ord(character) == 127 for character in value):
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


def _comment_params(
    *,
    page: int,
    per_page: int,
    sort_by: str,
    sort_direction: str,
    created_after: str | None,
    created_before: str | None,
) -> dict[str, str | int]:
    if isinstance(page, bool) or page < 1 or page > MAX_PAGE:
        raise SyncroReadError(f"Syncro comment page must be between 1 and {MAX_PAGE}.")
    if isinstance(per_page, bool) or per_page < 1 or per_page > 100:
        raise SyncroReadError("Syncro comment per_page must be between 1 and 100.")
    safe_sort_by = _safe_filter(sort_by)
    if safe_sort_by not in {"created_at", "updated_at"}:
        raise SyncroReadError("Syncro comment sort_by must be created_at or updated_at.")
    safe_direction = _safe_filter(sort_direction)
    if safe_direction is None or safe_direction.upper() not in {"ASC", "DESC"}:
        raise SyncroReadError("Syncro comment sort_direction must be ASC or DESC.")
    params: dict[str, str | int] = {
        "page": page,
        "per_page": per_page,
        "sort_by": safe_sort_by,
        "sort_direction": safe_direction.upper(),
        "comment_format": "plaintext",
    }
    for key, value in {"created_after": created_after, "created_before": created_before}.items():
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


def _normalize_comment(row: Mapping[str, object]) -> dict[str, object] | None:
    comment_id = _first_value(row, "id", "comment_id")
    if comment_id in (None, ""):
        return None
    ticket_id = _first_value(row, "ticket_id", "ticketId")
    return {
        "id": str(comment_id),
        "ticket_id": str(ticket_id) if ticket_id not in (None, "") else "",
        "created_at": _string_value(row, "created_at"),
        "updated_at": _string_value(row, "updated_at"),
        "subject": _bounded_string(row.get("subject"), 250),
        "body": _bounded_string(row.get("body"), 32_000),
        "tech": _bounded_string(row.get("tech"), 250),
        "hidden": _bool_value(row.get("hidden")),
        "user_id": _first_value(row, "user_id", "userId"),
        "is_rich_text": _bool_value(row.get("is_rich_text")),
    }


def _comment_meta(payload: object) -> dict[str, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("meta"), dict):
        return {}
    meta = payload["meta"]
    result: dict[str, int] = {}
    for key in ("total_pages", "page", "per_page"):
        value = meta.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    return result


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _string_value(row: Mapping[str, object], *keys: str) -> str:
    value = _first_value(row, *keys)
    return "" if value is None else str(value)


def _bounded_string(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return value[:maximum]


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else False


def _write_payload(action_type: str, fields: Mapping[str, object]) -> dict[str, object]:
    if action_type != "add_note":
        raise SyncroReadError(f"Syncro write action is unsupported: {action_type}.")
    allowed = {"subject", "body", "hidden", "do_not_email"}
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise SyncroReadError(f"Syncro write fields are unsupported: {', '.join(unknown)}.")
    subject = fields.get("subject")
    body = fields.get("body")
    if not isinstance(subject, str) or not subject.strip() or len(subject.strip()) > 250:
        raise SyncroReadError("Syncro comment subject must be a non-empty string of 250 characters or fewer.")
    if not isinstance(body, str) or not body.strip() or len(body.strip()) > 32_000:
        raise SyncroReadError("Syncro comment body must be a non-empty string of 32000 characters or fewer.")
    if any(ord(character) < 32 for character in subject + body if character not in "\r\n\t"):
        raise SyncroReadError("Syncro comment fields contain control characters.")
    hidden = fields.get("hidden", True)
    do_not_email = fields.get("do_not_email", True)
    if not isinstance(hidden, bool) or not isinstance(do_not_email, bool):
        raise SyncroReadError("Syncro comment visibility and notification flags must be booleans.")
    return {
        "subject": subject.strip(),
        "body": body.strip(),
        "hidden": hidden,
        "do_not_email": do_not_email,
    }


def _remote_id(payload: object) -> str:
    if isinstance(payload, dict):
        for key in ("id", "comment_id"):
            value = payload.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                return str(value)
        for value in payload.values():
            found = _remote_id(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _remote_id(value)
            if found:
                return found
    return ""


def _http_error_message(status_code: int, endpoint: str, *, method: str = "GET") -> str:
    if status_code == 401:
        return f"Syncro {method} {endpoint} was unauthorized (HTTP 401)."
    if status_code == 403:
        return f"Syncro {method} {endpoint} was forbidden (HTTP 403)."
    if status_code == 429:
        return f"Syncro {method} {endpoint} was rate limited (HTTP 429)."
    return f"Syncro {method} {endpoint} failed with HTTP {status_code}."


__all__ = [
    "SyncroClient",
    "SyncroCommentsResponse",
    "SyncroReadError",
    "SyncroReadProvider",
    "SyncroReadResponse",
    "SyncroWriteProvider",
]
