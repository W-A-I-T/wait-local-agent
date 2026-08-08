"""Read-only Microsoft Graph identity and group reads through a guarded boundary.

The live connector is intentionally narrower than the cloud inventory adapter:
it looks up bounded user and group context, accepts a bearer token supplied by
the operator's settings/vault boundary, and never creates or mutates Graph data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200
MAX_CURSOR_LENGTH = 4096
MAX_IDENTITY_LENGTH = 320


@dataclass(frozen=True)
class M365GraphUser:
    id: str
    display_name: str
    user_principal_name: str
    mail: str
    account_enabled: bool | None
    job_title: str
    department: str


@dataclass(frozen=True)
class M365GraphGroup:
    id: str
    display_name: str
    mail: str
    mail_nickname: str
    description: str
    mail_enabled: bool | None
    security_enabled: bool | None
    group_types: tuple[str, ...]


@dataclass(frozen=True)
class M365GraphReadResponse:
    result: ConnectorReadResult
    items: list[M365GraphUser]
    next_cursor: str = ""


@dataclass(frozen=True)
class M365GraphGroupReadResponse:
    result: ConnectorReadResult
    items: list[M365GraphGroup]
    next_cursor: str = ""


class M365GraphReadError(Exception):
    """A sanitized live Graph read failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class M365GraphClient:
    """Bounded, read-only Microsoft Graph user and group lookup client."""

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
        response = self.list_users(page_size=1)
        if response.result.status == "ready":
            return ConnectorReadResult("ready", "Microsoft Graph identity and group read prerequisites are ready.")
        return response.result

    def list_users(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphReadResponse:
        try:
            params = _list_params(page_size, cursor)
            if identity is not None:
                safe_identity = _safe_identity(identity)
                escaped = safe_identity.replace("'", "''")
                params["$filter"] = (
                    f"id eq '{escaped}' or userPrincipalName eq '{escaped}'"
                )
        except M365GraphReadError as exc:
            return M365GraphReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_users(params)

    def list_groups(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> M365GraphGroupReadResponse:
        try:
            params = _group_list_params(page_size, cursor)
            if identity is not None:
                safe_identity = _safe_identity(identity)
                escaped = safe_identity.replace("'", "''")
                params["$filter"] = (
                    f"id eq '{escaped}' or mail eq '{escaped}' or "
                    f"mailNickname eq '{escaped}' or displayName eq '{escaped}'"
                )
        except M365GraphReadError as exc:
            return M365GraphGroupReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_groups(params)

    def _request_users(self, params: dict[str, str | int]) -> M365GraphReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            payload = self._get("users", params=params)
        except M365GraphReadError as exc:
            return M365GraphReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [user for row in _payload_rows(payload) if (user := _normalize_user(row)) is not None]
        return M365GraphReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph user identity read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def _request_groups(self, params: dict[str, str | int]) -> M365GraphGroupReadResponse:
        blocked = self._blocked_result()
        if blocked is not None:
            return M365GraphGroupReadResponse(blocked, [])
        missing = self._not_configured_result()
        if missing is not None:
            return M365GraphGroupReadResponse(missing, [])
        try:
            payload = self._get("groups", params=params)
        except M365GraphReadError as exc:
            return M365GraphGroupReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [group for row in _payload_rows(payload) if (group := _normalize_group(row)) is not None]
        return M365GraphGroupReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph group read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def _get(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> object:
        if not self.settings.allow_http_probing:
            raise M365GraphReadError(
                "Microsoft Graph live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise M365GraphReadError(missing.message)
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{_api_base_url(self.settings.m365_graph_base_url)}/{safe_endpoint}",
                    headers={
                        "Authorization": f"Bearer {self.settings.m365_access_token}",
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise M365GraphReadError(
                "Microsoft Graph request failed before receiving a response."
            ) from exc
        except httpx.HTTPError as exc:
            raise M365GraphReadError("Microsoft Graph request failed.") from exc
        if response.status_code >= 400:
            raise M365GraphReadError(_http_error_message(response.status_code, safe_endpoint))
        try:
            return response.json()
        except ValueError as exc:
            raise M365GraphReadError(
                f"Microsoft Graph GET {safe_endpoint} returned malformed JSON."
            ) from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Microsoft Graph live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_M365_GRAPH_BASE_URL": self.settings.m365_graph_base_url,
                "WAIT_M365_ACCESS_TOKEN": self.settings.m365_access_token,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"Microsoft Graph live read credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> M365GraphReadResponse | None:
        blocked = self._blocked_result()
        return M365GraphReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> M365GraphReadResponse | None:
        missing = self._not_configured_result()
        return M365GraphReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise M365GraphReadError("Microsoft Graph base URL contains control characters.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise M365GraphReadError("Microsoft Graph base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise M365GraphReadError(
            "Microsoft Graph base URL must not contain credentials or query data."
        )
    return base_url.rstrip("/")


def _safe_endpoint(endpoint: str) -> str:
    if endpoint not in {"users", "groups"}:
        raise M365GraphReadError("Microsoft Graph endpoint is invalid.")
    return endpoint


def _safe_identity(value: str) -> str:
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > MAX_IDENTITY_LENGTH
        or any(ord(character) < 32 for character in stripped)
    ):
        raise M365GraphReadError("Microsoft Graph identity is invalid.")
    return stripped


def _safe_cursor(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > MAX_CURSOR_LENGTH or any(ord(character) < 32 for character in stripped):
        raise M365GraphReadError("Microsoft Graph cursor is invalid.")
    return stripped


def _bounded_page_size(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise M365GraphReadError("Microsoft Graph page_size must be at least 1.")
    return min(value, MAX_PAGE_SIZE)


def _list_params(page_size: int, cursor: str | None) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "$top": _bounded_page_size(page_size),
        "$select": (
            "id,displayName,userPrincipalName,mail,accountEnabled,jobTitle,department"
        ),
    }
    if cursor is not None:
        params["$skiptoken"] = _safe_cursor(cursor)
    return params


def _group_list_params(page_size: int, cursor: str | None) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "$top": _bounded_page_size(page_size),
        "$select": (
            "id,displayName,mail,mailNickname,description,mailEnabled,securityEnabled,groupTypes"
        ),
    }
    if cursor is not None:
        params["$skiptoken"] = _safe_cursor(cursor)
    return params


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = [value]
        else:
            rows = [payload]
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_user(row: Mapping[str, object]) -> M365GraphUser | None:
    user_id = _string_value(row, "id")
    if not user_id:
        return None
    account_enabled = row.get("accountEnabled")
    return M365GraphUser(
        id=user_id,
        display_name=_string_value(row, "displayName"),
        user_principal_name=_string_value(row, "userPrincipalName"),
        mail=_string_value(row, "mail"),
        account_enabled=account_enabled if isinstance(account_enabled, bool) else None,
        job_title=_string_value(row, "jobTitle"),
        department=_string_value(row, "department"),
    )


def _normalize_group(row: Mapping[str, object]) -> M365GraphGroup | None:
    group_id = _string_value(row, "id")
    if not group_id:
        return None
    group_types = row.get("groupTypes")
    normalized_group_types = (
        tuple(value for value in group_types if isinstance(value, str))
        if isinstance(group_types, list)
        else ()
    )
    mail_enabled = row.get("mailEnabled")
    security_enabled = row.get("securityEnabled")
    return M365GraphGroup(
        id=group_id,
        display_name=_string_value(row, "displayName"),
        mail=_string_value(row, "mail"),
        mail_nickname=_string_value(row, "mailNickname"),
        description=_string_value(row, "description"),
        mail_enabled=mail_enabled if isinstance(mail_enabled, bool) else None,
        security_enabled=security_enabled if isinstance(security_enabled, bool) else None,
        group_types=normalized_group_types,
    )


def _string_value(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _next_cursor(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    next_link = payload.get("@odata.nextLink")
    if not isinstance(next_link, str):
        return ""
    query = parse_qs(urlsplit(next_link).query)
    values = query.get("$skiptoken", [])
    return values[0] if values and len(values[0]) <= MAX_CURSOR_LENGTH else ""


def _http_error_message(status_code: int, endpoint: str) -> str:
    if status_code == 401:
        return f"Microsoft Graph GET {endpoint} returned HTTP 401 (authentication failed)."
    if status_code == 403:
        return f"Microsoft Graph GET {endpoint} returned HTTP 403 (access denied)."
    if status_code == 404:
        return f"Microsoft Graph GET {endpoint} returned HTTP 404 (not found)."
    if status_code == 429:
        return f"Microsoft Graph GET {endpoint} returned HTTP 429 (rate limited)."
    return f"Microsoft Graph GET {endpoint} returned HTTP {status_code}."


__all__ = [
    "M365GraphClient",
    "M365GraphGroup",
    "M365GraphGroupReadResponse",
    "M365GraphReadError",
    "M365GraphReadResponse",
    "M365GraphUser",
]
