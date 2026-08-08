"""Read-only SharePoint document metadata adapter through Microsoft Graph.

The adapter deliberately exposes site metadata and bounded drive-item metadata.
It does not download file contents or issue mutations. Callers supply a
delegated or application bearer token through the settings/vault boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200
MAX_CURSOR_LENGTH = 4096
MAX_SEGMENT_LENGTH = 256


@dataclass(frozen=True)
class SharePointSite:
    id: str
    name: str
    display_name: str
    web_url: str


@dataclass(frozen=True)
class SharePointDocument:
    id: str
    name: str
    site_id: str
    parent_id: str
    size: int
    updated_at: str
    web_url: str
    is_folder: bool


@dataclass(frozen=True)
class SharePointReadResponse:
    result: ConnectorReadResult
    items: list[SharePointSite | SharePointDocument]
    next_cursor: str = ""


class SharePointClientProtocol(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def list_documents(
        self,
        site_id: str,
        *,
        parent_item_id: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SharePointReadResponse:
        ...


class SharePointReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


Normalizer = Callable[[Mapping[str, object]], SharePointSite | SharePointDocument | None]


class SharePointClient:
    """Bounded, read-only SharePoint Graph metadata client."""

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
        response = self.list_sites(page_size=1)
        if response.result.status == "ready":
            return ConnectorReadResult("ready", "SharePoint read prerequisites are ready.")
        return response.result

    def list_sites(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SharePointReadResponse:
        try:
            params = _list_params(page_size, cursor)
        except SharePointReadError as exc:
            return SharePointReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items("sites", _normalize_site, params=params)

    def get_site(self, site_id: str) -> SharePointReadResponse:
        try:
            safe_site_id = _safe_segment(site_id)
        except SharePointReadError as exc:
            return SharePointReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"sites/{safe_site_id}", _normalize_site)

    def list_documents(
        self,
        site_id: str,
        *,
        parent_item_id: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SharePointReadResponse:
        try:
            safe_site_id = _safe_segment(site_id)
            parent = "root" if parent_item_id is None else _safe_segment(parent_item_id)
            params = _list_params(page_size, cursor)
        except SharePointReadError as exc:
            return SharePointReadResponse(ConnectorReadResult("failed", exc.message), [])
        endpoint = f"sites/{safe_site_id}/drive/root/children"
        if parent_item_id is not None:
            endpoint = f"sites/{safe_site_id}/drive/items/{parent}/children"
        return self._request_items(endpoint, lambda row: _normalize_document(row, site_id), params=params)

    def get_document(self, site_id: str, item_id: str) -> SharePointReadResponse:
        try:
            safe_site_id = _safe_segment(site_id)
            safe_item_id = _safe_segment(item_id)
        except SharePointReadError as exc:
            return SharePointReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(
            f"sites/{safe_site_id}/drive/items/{safe_item_id}",
            lambda row: _normalize_document(row, site_id),
        )

    def _request_items(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> SharePointReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            payload = self._get(endpoint, params=params)
        except SharePointReadError as exc:
            return SharePointReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return SharePointReadResponse(
            ConnectorReadResult("ready", f"SharePoint read succeeded from {endpoint}.", len(items)),
            items,
            _next_cursor(payload),
        )

    def _get(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> object:
        if not self.settings.allow_http_probing:
            raise SharePointReadError(
                "SharePoint live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise SharePointReadError(missing.message)
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{_api_base_url(self.settings.sharepoint_base_url)}/{safe_endpoint}",
                    headers={
                        "Authorization": f"Bearer {self.settings.sharepoint_access_token}",
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise SharePointReadError("SharePoint request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise SharePointReadError("SharePoint request failed.") from exc
        if response.status_code >= 400:
            raise SharePointReadError(_http_error_message(response.status_code, safe_endpoint))
        try:
            return response.json()
        except ValueError as exc:
            raise SharePointReadError(f"SharePoint GET {safe_endpoint} returned malformed JSON.") from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "SharePoint live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_SHAREPOINT_BASE_URL": self.settings.sharepoint_base_url,
                "WAIT_SHAREPOINT_ACCESS_TOKEN": self.settings.sharepoint_access_token,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult("not_configured", f"SharePoint credentials are incomplete: {', '.join(missing)}.")

    def _blocked_response(self) -> SharePointReadResponse | None:
        blocked = self._blocked_result()
        return SharePointReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> SharePointReadResponse | None:
        missing = self._not_configured_result()
        return SharePointReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    return _safe_base_url(base_url).rstrip("/")


def _safe_base_url(base_url: str) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise SharePointReadError("SharePoint base URL contains control characters.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SharePointReadError("SharePoint base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SharePointReadError("SharePoint base URL must not contain credentials or query data.")
    return base_url


def _safe_endpoint(endpoint: str) -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise SharePointReadError("SharePoint endpoint overrides must be relative paths.")
    parts = endpoint.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise SharePointReadError("SharePoint endpoint is invalid.")
    if any(
        not all(character.isalnum() or character in {"_", "-", ",", ".", "!"} for character in part)
        for part in parts
    ):
        raise SharePointReadError("SharePoint endpoint contains unsafe characters.")
    return "/".join(parts)


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > MAX_SEGMENT_LENGTH or not all(
        character.isalnum() or character in {"_", "-", ",", ".", "!"} for character in stripped
    ):
        raise SharePointReadError("SharePoint resource identifiers contain unsafe characters.")
    if stripped in {".", ".."}:
        raise SharePointReadError("SharePoint resource identifiers contain unsafe characters.")
    return stripped


def _safe_cursor(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > MAX_CURSOR_LENGTH or any(ord(character) < 32 for character in stripped):
        raise SharePointReadError("SharePoint cursor is invalid.")
    return stripped


def _bounded_page_size(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise SharePointReadError("SharePoint page_size must be at least 1.")
    return min(value, MAX_PAGE_SIZE)


def _list_params(page_size: int, cursor: str | None) -> dict[str, str | int]:
    params: dict[str, str | int] = {"$top": _bounded_page_size(page_size)}
    if cursor is not None:
        params["$skiptoken"] = _safe_cursor(cursor)
    return params


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get("value", payload.get("data"))
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = [value]
        else:
            rows = [payload]
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_site(row: Mapping[str, object]) -> SharePointSite | None:
    site_id = _string_value(row, "id")
    if not site_id:
        return None
    return SharePointSite(
        id=site_id,
        name=_string_value(row, "name"),
        display_name=_string_value(row, "displayName"),
        web_url=_string_value(row, "webUrl"),
    )


def _normalize_document(row: Mapping[str, object], site_id: str) -> SharePointDocument | None:
    item_id = _string_value(row, "id")
    if not item_id:
        return None
    parent_reference = row.get("parentReference")
    parent_id = _string_value(parent_reference, "id") if isinstance(parent_reference, dict) else ""
    folder = row.get("folder")
    is_folder = isinstance(folder, dict)
    size = row.get("size")
    return SharePointDocument(
        id=item_id,
        name=_string_value(row, "name"),
        site_id=site_id,
        parent_id=parent_id,
        size=int(size) if isinstance(size, (int, float)) else 0,
        updated_at=_string_value(row, "lastModifiedDateTime"),
        web_url=_string_value(row, "webUrl"),
        is_folder=is_folder,
    )


def _string_value(value: object, key: str) -> str:
    if not isinstance(value, dict):
        return ""
    item = value.get(key)
    return item.strip() if isinstance(item, str) else str(item) if isinstance(item, (int, float)) else ""


def _next_cursor(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    next_link = payload.get("@odata.nextLink")
    if not isinstance(next_link, str):
        return ""
    values = parse_qs(urlsplit(next_link).query).get("$skiptoken", [])
    return values[0] if values and len(values[0]) <= MAX_CURSOR_LENGTH else ""


def _http_error_message(status_code: int, endpoint: str) -> str:
    if status_code == 401:
        return f"SharePoint GET {endpoint} returned HTTP 401 (authentication failed)."
    if status_code == 403:
        return f"SharePoint GET {endpoint} returned HTTP 403 (access denied)."
    if status_code == 404:
        return f"SharePoint GET {endpoint} returned HTTP 404 (not found)."
    if status_code == 429:
        return f"SharePoint GET {endpoint} returned HTTP 429 (rate limited)."
    return f"SharePoint GET {endpoint} returned HTTP {status_code}."
