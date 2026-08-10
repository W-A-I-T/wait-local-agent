"""Bounded, read-only Notion documentation adapter.

The adapter uses Notion's documented search and page-markdown endpoints. A
local client-to-page map is required so a shared Notion integration cannot
return another WAIT tenant's pages. No page, database, comment, or property
mutation is exposed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_PAGE_MARKDOWN_LENGTH = 40_000
MAX_MAPPED_PAGES = 100
DEFAULT_NOTION_VERSION = "2026-03-11"


@dataclass(frozen=True)
class NotionPage:
    id: str
    title: str
    url: str
    last_edited_time: str
    archived: bool
    markdown: str


@dataclass(frozen=True)
class NotionReadResponse:
    result: ConnectorReadResult
    items: list[NotionPage]
    next_cursor: str = ""


class NotionReadError(Exception):
    """Safe, operator-facing Notion adapter error."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotionClientProtocol(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def search_pages(
        self,
        *,
        client_id: str,
        query: str = "",
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> NotionReadResponse:
        ...

    def get_page(self, page_id: str, *, client_id: str) -> NotionReadResponse:
        ...


class NotionClient:
    """Read-only Notion API client with explicit local tenant page mapping."""

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
            self._mapped_page_ids("health")
        except NotionReadError as exc:
            return ConnectorReadResult("failed", exc.message)
        response = self.search_pages(client_id="health", query="", page_size=1, _health=True)
        if response.result.status == "ready":
            return ConnectorReadResult("ready", "Notion read prerequisites are ready.")
        return response.result

    def search_pages(
        self,
        *,
        client_id: str,
        query: str = "",
        page_size: int = DEFAULT_PAGE_SIZE,
        _health: bool = False,
    ) -> NotionReadResponse:
        blocked = self._blocked_result()
        if blocked is not None:
            return NotionReadResponse(blocked, [])
        missing = self._not_configured_result()
        if missing is not None:
            return NotionReadResponse(missing, [])
        try:
            scoped_ids = self._mapped_page_ids(client_id)
            if not _health:
                _safe_query(query)
            bounded_size = _bounded_page_size(page_size)
            body: dict[str, object] = {
                "page_size": bounded_size,
                "filter": {"property": "object", "value": "page"},
            }
            if query.strip():
                body["query"] = query.strip()
        except NotionReadError as exc:
            return NotionReadResponse(ConnectorReadResult("failed", exc.message), [])
        response = self._request("POST", "search", body=body)
        if isinstance(response, NotionReadResponse):
            return response
        rows = _payload_rows(response)
        pages = [_normalize_search_page(row) for row in rows]
        filtered = [page for page in pages if page is not None and page.id in scoped_ids]
        return NotionReadResponse(
            ConnectorReadResult("ready", "Notion search succeeded.", len(filtered)),
            filtered,
            _next_cursor(response),
        )

    def get_page(self, page_id: str, *, client_id: str) -> NotionReadResponse:
        blocked = self._blocked_result()
        if blocked is not None:
            return NotionReadResponse(blocked, [])
        missing = self._not_configured_result()
        if missing is not None:
            return NotionReadResponse(missing, [])
        try:
            safe_id = _safe_uuid(page_id)
            scoped_ids = self._mapped_page_ids(client_id)
            if safe_id not in scoped_ids:
                raise NotionReadError("Notion page is outside the tenant scope")
        except NotionReadError as exc:
            return NotionReadResponse(ConnectorReadResult("failed", exc.message), [])
        page_payload = self._request("GET", f"pages/{safe_id}")
        if isinstance(page_payload, NotionReadResponse):
            return page_payload
        page = _normalize_page(page_payload)
        if page is None:
            return NotionReadResponse(
                ConnectorReadResult("failed", "Notion page response was malformed"), []
            )
        markdown_payload = self._request("GET", f"pages/{safe_id}/markdown")
        if isinstance(markdown_payload, NotionReadResponse):
            return markdown_payload
        markdown = _markdown_value(markdown_payload)
        if markdown is None:
            return NotionReadResponse(
                ConnectorReadResult("failed", "Notion page markdown response was malformed"), []
            )
        hydrated = NotionPage(
            page.id,
            page.title,
            page.url,
            page.last_edited_time,
            page.archived,
            markdown,
        )
        return NotionReadResponse(
            ConnectorReadResult("ready", "Notion page retrieval succeeded.", 1),
            [hydrated],
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        body: dict[str, object] | None = None,
    ) -> object | NotionReadResponse:
        blocked = self._blocked_result()
        if blocked is not None:
            return NotionReadResponse(blocked, [])
        missing = self._not_configured_result()
        if missing is not None:
            return NotionReadResponse(missing, [])
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.request(
                    method,
                    f"{_api_base_url(self.settings.notion_base_url)}/{safe_endpoint}",
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.settings.notion_api_token}",
                        "Notion-Version": _safe_version(self.settings.notion_version),
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except NotionReadError as exc:
            return NotionReadResponse(ConnectorReadResult("failed", exc.message), [])
        except (httpx.TimeoutException, httpx.ConnectError):
            return NotionReadResponse(
                ConnectorReadResult("failed", "Notion request failed before receiving a response."), []
            )
        except httpx.HTTPError:
            return NotionReadResponse(ConnectorReadResult("failed", "Notion request failed."), [])
        if response.status_code >= 400:
            return NotionReadResponse(
                ConnectorReadResult("failed", _http_error_message(response.status_code, safe_endpoint)),
                [],
            )
        try:
            return response.json()
        except ValueError:
            return NotionReadResponse(
                ConnectorReadResult("failed", f"Notion {method} {safe_endpoint} returned malformed JSON."),
                [],
            )

    def _mapped_page_ids(self, client_id: str) -> set[str]:
        if not client_id or not client_id.strip():
            raise NotionReadError("Notion operations require an explicit tenant scope")
        try:
            mapping = json.loads(self.settings.notion_client_page_map_json or "{}")
        except ValueError as exc:
            raise NotionReadError("WAIT_NOTION_CLIENT_PAGE_MAP_JSON is malformed") from exc
        if not isinstance(mapping, Mapping):
            raise NotionReadError("WAIT_NOTION_CLIENT_PAGE_MAP_JSON must be an object")
        raw_ids = mapping.get(client_id.strip())
        if client_id == "health" and raw_ids is None:
            raw_ids = next(iter(mapping.values()), None)
        if not isinstance(raw_ids, list) or not raw_ids:
            raise NotionReadError("Notion tenant page mapping is missing")
        if len(raw_ids) > MAX_MAPPED_PAGES:
            raise NotionReadError(
                f"Notion tenant page mapping exceeds {MAX_MAPPED_PAGES} pages"
            )
        normalized: set[str] = set()
        for raw_id in raw_ids:
            if not isinstance(raw_id, str):
                raise NotionReadError("Notion page IDs must be UUIDs")
            try:
                normalized.add(str(UUID(raw_id.strip())))
            except ValueError as exc:
                raise NotionReadError("Notion page IDs must be UUIDs") from exc
        return normalized

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked", "Notion live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_NOTION_API_TOKEN": self.settings.notion_api_token,
                "WAIT_NOTION_CLIENT_PAGE_MAP_JSON": self.settings.notion_client_page_map_json,
            }.items()
            if not value
        ]
        if missing:
            return ConnectorReadResult(
                "not_configured", f"Notion credentials are incomplete: {', '.join(missing)}."
            )
        return None


def _api_base_url(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise NotionReadError("Notion base URL contains control characters")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NotionReadError("Notion base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise NotionReadError("Notion base URL must not contain credentials or query data")
    safe = value.strip().rstrip("/")
    return safe if safe.endswith("/v1") else f"{safe}/v1"


def _safe_version(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 100 or any(ord(char) < 32 for char in normalized):
        raise NotionReadError("Notion-Version must be a bounded header value")
    return normalized


def _safe_endpoint(value: str) -> str:
    parts = value.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise NotionReadError("Notion endpoint is invalid")
    if any(not all(char.isalnum() or char in {"_", "-"} for char in part) for part in parts):
        raise NotionReadError("Notion endpoint contains unsafe characters")
    return "/".join(parts)


def _safe_uuid(value: str) -> str:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise NotionReadError("Notion page ID must be a UUID") from exc


def _safe_query(value: str) -> str:
    if len(value.strip()) > 200 or any(ord(char) < 32 for char in value):
        raise NotionReadError("Notion search query is invalid")
    return value.strip()


def _bounded_page_size(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise NotionReadError("Notion page_size must be at least 1")
    return min(value, MAX_PAGE_SIZE)


def _payload_rows(payload: object) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    rows = payload.get("results")
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _next_cursor(payload: object) -> str:
    if not isinstance(payload, Mapping):
        return ""
    cursor = payload.get("next_cursor")
    return cursor.strip() if isinstance(cursor, str) and len(cursor) <= 4096 else ""


def _normalize_search_page(row: Mapping[str, Any]) -> NotionPage | None:
    page_id = row.get("id")
    if not isinstance(page_id, str):
        return None
    try:
        safe_id = str(UUID(page_id))
    except ValueError:
        return None
    return NotionPage(
        id=safe_id,
        title=_title_from_properties(row.get("properties")),
        url=_text(row.get("url")),
        last_edited_time=_text(row.get("last_edited_time")),
        archived=bool(row.get("archived", False)),
        markdown="",
    )


def _normalize_page(payload: object) -> NotionPage | None:
    if not isinstance(payload, Mapping):
        return None
    page_id = payload.get("id")
    if not isinstance(page_id, str):
        return None
    try:
        safe_id = str(UUID(page_id))
    except ValueError:
        return None
    return NotionPage(
        id=safe_id,
        title=_title_from_properties(payload.get("properties")),
        url=_text(payload.get("url")),
        last_edited_time=_text(payload.get("last_edited_time")),
        archived=bool(payload.get("archived", False)),
        markdown="",
    )


def _markdown_value(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("markdown")
    if not isinstance(value, str):
        return None
    return value[:MAX_PAGE_MARKDOWN_LENGTH]


def _title_from_properties(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    for property_value in value.values():
        if not isinstance(property_value, Mapping):
            continue
        property_type = property_value.get("type")
        if property_type not in {"title", "rich_text"}:
            continue
        rich_value = property_value.get(property_type)
        if not isinstance(rich_value, list):
            continue
        parts = [
            text
            for item in rich_value
            if isinstance(item, Mapping)
            for text in [_text(item.get("plain_text"))]
            if text
        ]
        if parts:
            return "".join(parts)[:500]
    return ""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _http_error_message(status_code: int, endpoint: str) -> str:
    if status_code in {401, 403}:
        return f"Notion {endpoint} request was unauthorized"
    if status_code == 404:
        return f"Notion {endpoint} resource was not found"
    if status_code == 429:
        return f"Notion {endpoint} request was rate limited"
    return f"Notion {endpoint} request failed with HTTP {status_code}"


__all__ = ["NotionClient", "NotionPage", "NotionReadError", "NotionReadResponse"]
