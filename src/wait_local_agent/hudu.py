from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult, HuduArticle, HuduCompany, HuduFolder

QueryValue = str | int | float | bool | None
Normalizer = Callable[[Mapping[str, object]], HuduCompany | HuduArticle | HuduFolder | None]


@dataclass(frozen=True)
class HuduReadResponse:
    result: ConnectorReadResult
    items: list[HuduCompany | HuduArticle | HuduFolder]


class HuduClient:
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
            return ConnectorReadResult("ready", "Hudu read prerequisites are ready.")
        return response.result

    def list_companies(self, page: int = 1, page_size: int | None = None) -> HuduReadResponse:
        return self._list(
            "companies",
            _normalize_company,
            page=page,
            page_size=page_size,
        )

    def list_articles(
        self,
        company_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> HuduReadResponse:
        params: dict[str, QueryValue] = {}
        if company_id:
            params["company_id"] = company_id
        return self._list(
            "articles",
            _normalize_article,
            page=page,
            page_size=page_size,
            params=params,
        )

    def get_article(self, article_id: str) -> HuduReadResponse:
        return self._single(f"articles/{article_id}", _normalize_article)

    def list_folders(
        self,
        company_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> HuduReadResponse:
        params: dict[str, QueryValue] = {}
        if company_id:
            params["company_id"] = company_id
        return self._list(
            "folders",
            _normalize_folder,
            page=page,
            page_size=page_size,
            params=params,
        )

    def _list(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        page: int = 1,
        page_size: int | None = None,
        params: dict[str, QueryValue] | None = None,
    ) -> HuduReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        query: dict[str, QueryValue] = {
            "page": max(page, 1),
            "page_size": page_size or self.settings.hudu_page_size,
        }
        if params:
            query.update(params)
        return self._request_items(endpoint, normalizer, params=query)

    def _single(self, endpoint: str, normalizer: Normalizer) -> HuduReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        return self._request_items(endpoint, normalizer)

    def _request_items(
        self,
        endpoint: str,
        normalizer: Normalizer,
        *,
        params: dict[str, QueryValue] | None = None,
    ) -> HuduReadResponse:
        try:
            payload = self._get(endpoint, params=params)
        except HuduReadError as exc:
            return HuduReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return HuduReadResponse(
            ConnectorReadResult("ready", f"Hudu read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(self, endpoint: str, *, params: dict[str, QueryValue] | None = None) -> object:
        with self._client() as client:
            try:
                response = client.get(
                    f"{_api_base_url(self.settings.hudu_base_url)}/{_safe_endpoint(endpoint)}",
                    headers={"x-api-key": self.settings.hudu_api_key},
                    params=params,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise HuduReadError("Hudu request failed before receiving a response.") from exc
            except httpx.HTTPError as exc:
                raise HuduReadError("Hudu request failed.") from exc
        if response.status_code >= 400:
            raise HuduReadError(f"Hudu GET {endpoint} failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise HuduReadError(f"Hudu GET {endpoint} returned malformed JSON.") from exc

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.settings.connector_timeout_seconds,
            transport=self.transport,
        )

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Hudu live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_HUDU_BASE_URL": self.settings.hudu_base_url,
                "WAIT_HUDU_API_KEY": self.settings.hudu_api_key,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"Hudu credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> HuduReadResponse | None:
        blocked = self._blocked_result()
        return HuduReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> HuduReadResponse | None:
        missing = self._not_configured_result()
        return HuduReadResponse(missing, []) if missing else None


class HuduReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _api_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/api/v1"):
        return stripped
    if stripped.endswith("/api"):
        return f"{stripped}/v1"
    return f"{stripped}/api/v1"


def _safe_endpoint(endpoint: str) -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise HuduReadError("Hudu endpoint overrides must be relative paths.")
    return endpoint.strip("/")


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in ("companies", "articles", "folders", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
        else:
            candidates = [payload]
    else:
        return []
    return [row for row in candidates if isinstance(row, dict)]


def _normalize_company(row: Mapping[str, object]) -> HuduCompany | None:
    item_id = _id_value(row)
    if not item_id:
        return None
    return HuduCompany(
        id=item_id,
        name=_first_string(row, "name", "company_name"),
        archived=_bool_value(row, "archived"),
    )


def _normalize_article(row: Mapping[str, object]) -> HuduArticle | None:
    item_id = _id_value(row)
    if not item_id:
        return None
    return HuduArticle(
        id=item_id,
        name=_first_string(row, "name", "title"),
        company_id=_first_string(row, "company_id"),
        folder_id=_first_string(row, "folder_id"),
        updated_at=_first_string(row, "updated_at", "updated"),
        url=_first_string(row, "url", "public_url"),
    )


def _normalize_folder(row: Mapping[str, object]) -> HuduFolder | None:
    item_id = _id_value(row)
    if not item_id:
        return None
    return HuduFolder(
        id=item_id,
        name=_first_string(row, "name", "title"),
        company_id=_first_string(row, "company_id"),
        parent_folder_id=_first_string(row, "parent_folder_id", "parent_id"),
    )


def _id_value(row: Mapping[str, object]) -> str:
    return _first_string(row, "id", "company_id", "article_id", "folder_id")


def _first_string(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return str(value)
    return ""


def _bool_value(row: Mapping[str, object], *keys: str) -> bool:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, int):
            return bool(value)
    return False
