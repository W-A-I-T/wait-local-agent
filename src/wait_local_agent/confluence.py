"""Read-only Confluence Cloud documentation adapter.

The adapter intentionally exposes page listing and page detail only. It uses
the documented Confluence Cloud REST API v2 and never sends a mutation.
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
MAX_PAGE_SIZE = 100
MAX_CURSOR_LENGTH = 4096


@dataclass(frozen=True)
class ConfluencePage:
    id: str
    title: str
    space_id: str
    status: str
    version: str
    updated_at: str
    url: str
    body: str


@dataclass(frozen=True)
class ConfluenceReadResponse:
    result: ConnectorReadResult
    items: list[ConfluencePage]
    next_cursor: str = ""


class ConfluenceClientProtocol(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def list_pages(
        self,
        *,
        space_id: str | None = None,
        title: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ConfluenceReadResponse:
        ...


class ConfluenceReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


Normalizer = Callable[[Mapping[str, object]], ConfluencePage | None]


class ConfluenceClient:
    """Bounded, read-only Confluence Cloud REST API v2 client."""

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
        response = self.list_pages(page_size=1)
        if response.result.status == "ready":
            return ConnectorReadResult("ready", "Confluence read prerequisites are ready.")
        return response.result

    def list_pages(
        self,
        *,
        space_id: str | None = None,
        title: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ConfluenceReadResponse:
        params: dict[str, str | int] = {}
        try:
            params["limit"] = _bounded_page_size(page_size)
            if space_id is not None:
                params["space-id"] = _safe_segment(space_id)
            if title is not None:
                params["title"] = _safe_title(title)
            if cursor is not None:
                params["cursor"] = _safe_cursor(cursor)
        except ConfluenceReadError as exc:
            return ConfluenceReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items("pages", _normalize_page, params=params)

    def get_page(self, page_id: str) -> ConfluenceReadResponse:
        try:
            safe_id = _safe_segment(page_id)
        except ConfluenceReadError as exc:
            return ConfluenceReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"pages/{safe_id}", _normalize_page)

    def _request_items(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> ConfluenceReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            payload = self._get(endpoint, params=params)
        except ConfluenceReadError as exc:
            return ConfluenceReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return ConfluenceReadResponse(
            ConnectorReadResult("ready", f"Confluence read succeeded from {endpoint}.", len(items)),
            items,
            _next_cursor(payload),
        )

    def _get(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> object:
        if not self.settings.allow_http_probing:
            raise ConfluenceReadError(
                "Confluence live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise ConfluenceReadError(missing.message)
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{_api_base_url(self.settings.confluence_base_url)}/{safe_endpoint}",
                    auth=(self.settings.confluence_email, self.settings.confluence_api_token),
                    headers={"Accept": "application/json"},
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ConfluenceReadError("Confluence request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise ConfluenceReadError("Confluence request failed.") from exc
        if response.status_code >= 400:
            raise ConfluenceReadError(_http_error_message(response.status_code, safe_endpoint))
        try:
            return response.json()
        except ValueError as exc:
            raise ConfluenceReadError(f"Confluence GET {safe_endpoint} returned malformed JSON.") from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Confluence live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_CONFLUENCE_BASE_URL": self.settings.confluence_base_url,
                "WAIT_CONFLUENCE_EMAIL": self.settings.confluence_email,
                "WAIT_CONFLUENCE_API_TOKEN": self.settings.confluence_api_token,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"Confluence credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> ConfluenceReadResponse | None:
        blocked = self._blocked_result()
        return ConfluenceReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> ConfluenceReadResponse | None:
        missing = self._not_configured_result()
        return ConfluenceReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    safe = _safe_base_url(base_url).rstrip("/")
    if safe.endswith("/wiki/api/v2"):
        return safe
    if safe.endswith("/wiki"):
        return f"{safe}/api/v2"
    return f"{safe}/wiki/api/v2"


def _safe_base_url(base_url: str) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise ConfluenceReadError("Confluence base URL contains control characters.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfluenceReadError("Confluence base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfluenceReadError("Confluence base URL must not contain credentials or query data.")
    return base_url


def _safe_endpoint(endpoint: str) -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise ConfluenceReadError("Confluence endpoint overrides must be relative paths.")
    parts = endpoint.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise ConfluenceReadError("Confluence endpoint is invalid.")
    if any(
        not all(character.isalnum() or character in {"_", "-"} for character in part)
        for part in parts
    ):
        raise ConfluenceReadError("Confluence endpoint contains unsafe characters.")
    return "/".join(parts)


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > 64 or not all(
        character.isalnum() or character in {"_", "-"} for character in stripped
    ):
        raise ConfluenceReadError("Confluence resource identifiers contain unsafe characters.")
    return stripped


def _safe_title(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > 500 or any(ord(character) < 32 for character in stripped):
        raise ConfluenceReadError("Confluence page title is invalid.")
    return stripped


def _safe_cursor(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > MAX_CURSOR_LENGTH or any(ord(character) < 32 for character in stripped):
        raise ConfluenceReadError("Confluence cursor is invalid.")
    return stripped


def _bounded_page_size(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise ConfluenceReadError("Confluence page_size must be at least 1.")
    return min(value, MAX_PAGE_SIZE)


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get("results", payload.get("data"))
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = [value]
        else:
            rows = [payload]
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_page(row: Mapping[str, object]) -> ConfluencePage | None:
    page_id = _string_value(row, "id")
    title = _string_value(row, "title")
    if not page_id or not title:
        return None
    version_value = row.get("version")
    version = _string_value(version_value, "number") if isinstance(version_value, dict) else ""
    links = row.get("_links")
    url = _string_value(links, "webui") if isinstance(links, dict) else ""
    if not url and isinstance(links, dict):
        url = _string_value(links, "base")
    body = row.get("body")
    body_text = ""
    if isinstance(body, dict):
        storage = body.get("storage")
        if isinstance(storage, dict):
            body_text = _string_value(storage, "value")
        if not body_text:
            atlas_doc_format = body.get("atlas_doc_format")
            if isinstance(atlas_doc_format, dict):
                body_text = _string_value(atlas_doc_format, "value")
    return ConfluencePage(
        id=page_id,
        title=title,
        space_id=_string_value(row, "spaceId") or _string_value(row, "space_id"),
        status=_string_value(row, "status"),
        version=version,
        updated_at=_string_value(row, "updatedAt") or _string_value(row, "createdAt"),
        url=url,
        body=body_text,
    )


def _string_value(value: object, key: str) -> str:
    if not isinstance(value, dict):
        return ""
    item = value.get(key)
    return item.strip() if isinstance(item, str) else str(item) if isinstance(item, (int, float)) else ""


def _next_cursor(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    links = payload.get("_links")
    if not isinstance(links, dict):
        return ""
    next_link = links.get("next")
    if not isinstance(next_link, str):
        return ""
    values = parse_qs(urlsplit(next_link).query).get("cursor", [])
    return values[0] if values and len(values[0]) <= MAX_CURSOR_LENGTH else ""


def _http_error_message(status_code: int, endpoint: str) -> str:
    if status_code == 401:
        return f"Confluence GET {endpoint} returned HTTP 401 (authentication failed)."
    if status_code == 403:
        return f"Confluence GET {endpoint} returned HTTP 403 (access denied)."
    if status_code == 404:
        return f"Confluence GET {endpoint} returned HTTP 404 (not found)."
    if status_code == 429:
        return f"Confluence GET {endpoint} returned HTTP 429 (rate limited)."
    return f"Confluence GET {endpoint} returned HTTP {status_code}."
