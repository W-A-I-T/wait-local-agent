"""Read-only IT Glue documentation adapter.

The adapter intentionally covers organization, document, and document-folder
lookup only. IT Glue exposes writes, but this integration does not call them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_PAGE = 1_000_000


@dataclass(frozen=True)
class ItGlueOrganization:
    id: str
    name: str
    status: str


@dataclass(frozen=True)
class ItGlueDocument:
    id: str
    name: str
    organization_id: str
    folder_id: str
    updated_at: str
    url: str


@dataclass(frozen=True)
class ItGlueFolder:
    id: str
    name: str
    organization_id: str
    parent_id: str


@dataclass(frozen=True)
class ItGlueReadResponse:
    result: ConnectorReadResult
    items: list[ItGlueOrganization | ItGlueDocument | ItGlueFolder]


Normalizer = Callable[
    [Mapping[str, object]],
    ItGlueOrganization | ItGlueDocument | ItGlueFolder | None,
]


class ItGlueClientProtocol(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def list_documents(
        self,
        organization_id: str,
        *,
        folder_id: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ItGlueReadResponse:
        ...


class ItGlueReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ItGlueClient:
    """Bounded, read-only IT Glue JSON:API client."""

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
        response = self.list_organizations(page=1, page_size=1)
        if response.result.status == "ready":
            return ConnectorReadResult("ready", "IT Glue read prerequisites are ready.")
        return response.result

    def list_organizations(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ItGlueReadResponse:
        return self._list("organizations", _normalize_organization, page=page, page_size=page_size)

    def list_documents(
        self,
        organization_id: str,
        *,
        folder_id: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ItGlueReadResponse:
        try:
            safe_organization_id = _safe_segment(organization_id)
        except ItGlueReadError as exc:
            return ItGlueReadResponse(ConnectorReadResult("failed", exc.message), [])
        params: dict[str, str | int] = {}
        if folder_id is not None:
            try:
                params["filter[document_folder_id]"] = _safe_segment(folder_id)
            except ItGlueReadError as exc:
                return ItGlueReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._list(
            f"organizations/{safe_organization_id}/relationships/documents",
            _normalize_document,
            page=page,
            page_size=page_size,
            params=params,
        )

    def get_document(self, document_id: str) -> ItGlueReadResponse:
        try:
            safe_id = _safe_segment(document_id)
        except ItGlueReadError as exc:
            return ItGlueReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._request_items(f"documents/{safe_id}", _normalize_document)

    def list_folders(
        self,
        organization_id: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ItGlueReadResponse:
        try:
            safe_organization_id = _safe_segment(organization_id)
        except ItGlueReadError as exc:
            return ItGlueReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._list(
            f"organizations/{safe_organization_id}/relationships/document_folders",
            _normalize_folder,
            page=page,
            page_size=page_size,
        )

    def _list(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        page: int,
        page_size: int,
        params: dict[str, str | int] | None = None,
    ) -> ItGlueReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            query: dict[str, str | int] = _list_params(page, page_size)
        except ItGlueReadError as exc:
            return ItGlueReadResponse(ConnectorReadResult("failed", exc.message), [])
        if params:
            query.update(params)
        return self._request_items(endpoint, normalizer, params=query)

    def _request_items(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> ItGlueReadResponse:
        try:
            payload = self._get(endpoint, params=params)
        except ItGlueReadError as exc:
            return ItGlueReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return ItGlueReadResponse(
            ConnectorReadResult("ready", f"IT Glue read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> object:
        if not self.settings.allow_http_probing:
            raise ItGlueReadError("IT Glue live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.")
        missing = self._not_configured_result()
        if missing is not None:
            raise ItGlueReadError(missing.message)
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{_api_base_url(self.settings.itglue_base_url)}/{safe_endpoint}",
                    headers={
                        "x-api-key": self.settings.itglue_api_key,
                        "Accept": "application/vnd.api+json",
                    },
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ItGlueReadError("IT Glue request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise ItGlueReadError("IT Glue request failed.") from exc
        if response.status_code >= 400:
            raise ItGlueReadError(_http_error_message(response.status_code, safe_endpoint))
        try:
            return response.json()
        except ValueError as exc:
            raise ItGlueReadError(f"IT Glue GET {safe_endpoint} returned malformed JSON.") from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "IT Glue live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_ITGLUE_BASE_URL": self.settings.itglue_base_url,
                "WAIT_ITGLUE_API_KEY": self.settings.itglue_api_key,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult("not_configured", f"IT Glue credentials are incomplete: {', '.join(missing)}.")

    def _blocked_response(self) -> ItGlueReadResponse | None:
        blocked = self._blocked_result()
        return ItGlueReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> ItGlueReadResponse | None:
        missing = self._not_configured_result()
        return ItGlueReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    return _safe_base_url(base_url).rstrip("/")


def _safe_base_url(base_url: str) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise ItGlueReadError("IT Glue base URL contains control characters.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ItGlueReadError("IT Glue base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ItGlueReadError("IT Glue base URL must not contain credentials or query data.")
    return base_url


def _safe_endpoint(endpoint: str) -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise ItGlueReadError("IT Glue endpoint overrides must be relative paths.")
    parts = endpoint.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise ItGlueReadError("IT Glue endpoint is invalid.")
    if any(
        not all(character.isalnum() or character in {"_", "-"} for character in part)
        for part in parts
    ):
        raise ItGlueReadError("IT Glue endpoint contains unsafe characters.")
    return "/".join(parts)


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > 64 or not all(
        character.isalnum() or character in {"_", "-"} for character in stripped
    ):
        raise ItGlueReadError("IT Glue resource identifiers contain unsafe characters.")
    return stripped


def _bounded_page_size(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise ItGlueReadError("IT Glue page_size must be at least 1.")
    return min(value, MAX_PAGE_SIZE)


def _list_params(page: int, page_size: int) -> dict[str, str | int]:
    if isinstance(page, bool) or page < 1 or page > MAX_PAGE:
        raise ItGlueReadError(f"IT Glue page must be between 1 and {MAX_PAGE}.")
    return {"page[number]": page, "page[size]": _bounded_page_size(page_size)}


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        value = payload.get("data")
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = [value]
        else:
            rows = [payload]
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_organization(row: Mapping[str, object]) -> ItGlueOrganization | None:
    item_id = _string_value(row, "id")
    if not item_id:
        return None
    attributes = _attributes(row)
    return ItGlueOrganization(
        id=item_id,
        name=_string_value(attributes, "name", "organization-name"),
        status=_string_value(attributes, "status", "organization-status"),
    )


def _normalize_document(row: Mapping[str, object]) -> ItGlueDocument | None:
    item_id = _string_value(row, "id")
    if not item_id:
        return None
    attributes = _attributes(row)
    return ItGlueDocument(
        id=item_id,
        name=_string_value(attributes, "name", "title"),
        organization_id=_string_value(attributes, "organization-id", "organization_id"),
        folder_id=_string_value(attributes, "document-folder-id", "document_folder_id"),
        updated_at=_string_value(attributes, "updated-at", "updated_at"),
        url=_string_value(attributes, "resource-url", "resource_url", "url"),
    )


def _normalize_folder(row: Mapping[str, object]) -> ItGlueFolder | None:
    item_id = _string_value(row, "id")
    if not item_id:
        return None
    attributes = _attributes(row)
    return ItGlueFolder(
        id=item_id,
        name=_string_value(attributes, "name"),
        organization_id=_string_value(attributes, "organization-id", "organization_id"),
        parent_id=_string_value(attributes, "parent-id", "parent_id"),
    )


def _attributes(row: Mapping[str, object]) -> Mapping[str, object]:
    value = row.get("attributes")
    return value if isinstance(value, dict) else row


def _string_value(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return str(value)
    return ""


def _http_error_message(status_code: int, endpoint: str) -> str:
    if status_code == 401:
        return f"IT Glue GET {endpoint} was unauthorized (HTTP 401)."
    if status_code == 403:
        return f"IT Glue GET {endpoint} was forbidden (HTTP 403)."
    if status_code == 429:
        return f"IT Glue GET {endpoint} was rate limited (HTTP 429)."
    return f"IT Glue GET {endpoint} failed with HTTP {status_code}."
