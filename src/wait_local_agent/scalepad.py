"""Bounded, read-only ScalePad Core client adapter.

ScalePad's documented Core API exposes client inventory with an API key and
cursor pagination. WAIT uses a fixed, local WAIT-client-to-ScalePad-client map
and an exact provider filter; returned records are checked against that map
before they leave the connector boundary. No ScalePad writes are exposed here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

DEFAULT_PAGE_SIZE = 1
MAX_PAGE_SIZE = 1
MAX_CLIENT_ID_LENGTH = 120
MAX_PROVIDER_ID_LENGTH = 200
MAX_TEXT_LENGTH = 500
MAX_ENDPOINT_LENGTH = 240


@dataclass(frozen=True)
class ScalePadClientRecord:
    id: str
    name: str
    lifecycle: str
    num_contacts: int | None
    num_hardware_assets: int | None
    record_created_at: str
    record_updated_at: str


@dataclass(frozen=True)
class ScalePadClientResponse:
    result: ConnectorReadResult
    items: list[ScalePadClientRecord]
    next_cursor: str = ""


class ScalePadReadError(Exception):
    """Safe, operator-facing ScalePad adapter error."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ScalePadReadProvider(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def get_client(self, *, client_id: str) -> ScalePadClientResponse:
        ...


class ScalePadClient:
    """Normalize the documented ScalePad Core client-list contract."""

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
            mapping = json.loads(self.settings.scalepad_client_map_json or "{}")
            if not isinstance(mapping, Mapping) or not mapping:
                raise ScalePadReadError(
                    "WAIT_SCALEPAD_CLIENT_MAP_JSON must contain at least one client mapping."
                )
            self._client_mapping(str(next(iter(mapping))))
        except ScalePadReadError as exc:
            return ConnectorReadResult("failed", exc.message)
        return ConnectorReadResult("ready", "ScalePad read prerequisites are ready.")

    def get_client(self, *, client_id: str) -> ScalePadClientResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            provider_id = self._client_mapping(client_id)
            payload = self._get(
                "core/v1/clients",
                params={"filter[id]": f"eq:{provider_id}", "page_size": str(DEFAULT_PAGE_SIZE)},
            )
        except ScalePadReadError as exc:
            return ScalePadClientResponse(ConnectorReadResult("failed", exc.message), [])
        if not isinstance(payload, Mapping):
            return ScalePadClientResponse(
                ConnectorReadResult("failed", "ScalePad returned a malformed response object."),
                [],
            )
        rows = payload.get("data")
        if not isinstance(rows, list):
            return ScalePadClientResponse(
                ConnectorReadResult("failed", "ScalePad returned malformed client data."), []
            )
        items: list[ScalePadClientRecord] = []
        for row in rows[:MAX_PAGE_SIZE]:
            normalized = _normalize_client(row, provider_id)
            if normalized is not None:
                items.append(normalized)
        next_cursor = _optional_provider_id(payload.get("next_cursor"))
        return ScalePadClientResponse(
            ConnectorReadResult("ready", "ScalePad client read succeeded.", len(items)),
            items,
            next_cursor,
        )

    def _get(self, endpoint: str, *, params: Mapping[str, str] | None = None) -> object:
        if not self.settings.allow_http_probing:
            raise ScalePadReadError(
                "ScalePad live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise ScalePadReadError(missing.message)
        url = _endpoint_url(self.settings.scalepad_base_url, endpoint)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(
                    url,
                    headers={"Accept": "application/json", "x-api-key": self.settings.scalepad_api_key.strip()},
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ScalePadReadError("ScalePad request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise ScalePadReadError("ScalePad request failed.") from exc
        if response.status_code in {401, 403}:
            raise ScalePadReadError("ScalePad request was unauthorized.")
        if response.status_code == 402:
            raise ScalePadReadError("ScalePad request requires an enabled API subscription.")
        if response.status_code == 429:
            raise ScalePadReadError("ScalePad request was rate limited.")
        if response.status_code >= 400:
            raise ScalePadReadError(f"ScalePad request failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ScalePadReadError("ScalePad returned malformed JSON.") from exc
        return payload

    def _client_mapping(self, client_id: str) -> str:
        safe_client_id = _safe_client_id(client_id)
        try:
            mapping = json.loads(self.settings.scalepad_client_map_json or "{}")
        except json.JSONDecodeError as exc:
            raise ScalePadReadError("WAIT_SCALEPAD_CLIENT_MAP_JSON is malformed.") from exc
        if not isinstance(mapping, Mapping):
            raise ScalePadReadError("WAIT_SCALEPAD_CLIENT_MAP_JSON must be an object.")
        if safe_client_id not in mapping:
            raise ScalePadReadError("ScalePad client mapping is outside the tenant scope.")
        raw_provider_id = mapping[safe_client_id]
        if not isinstance(raw_provider_id, str) or not raw_provider_id.strip():
            raise ScalePadReadError("ScalePad client mapping must use non-empty strings.")
        return _bounded_provider_id(raw_provider_id)

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "ScalePad live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_SCALEPAD_BASE_URL": self.settings.scalepad_base_url,
                "WAIT_SCALEPAD_API_KEY": self.settings.scalepad_api_key,
                "WAIT_SCALEPAD_CLIENT_MAP_JSON": self.settings.scalepad_client_map_json,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"ScalePad credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> ScalePadClientResponse | None:
        result = self._blocked_result()
        return ScalePadClientResponse(result, []) if result is not None else None

    def _not_configured_response(self) -> ScalePadClientResponse | None:
        result = self._not_configured_result()
        return ScalePadClientResponse(result, []) if result is not None else None


def _normalize_client(row: object, provider_id: str) -> ScalePadClientRecord | None:
    if not isinstance(row, Mapping):
        return None
    record_id = _optional_provider_id(row.get("id"))
    if record_id is None:
        return None
    if record_id != provider_id:
        return None
    return ScalePadClientRecord(
        id=record_id,
        name=_bounded_text(row.get("name")),
        lifecycle=_bounded_text(row.get("lifecycle")),
        num_contacts=_optional_nonnegative_int(row.get("num_contacts")),
        num_hardware_assets=_optional_nonnegative_int(row.get("num_hardware_assets")),
        record_created_at=_bounded_text(row.get("record_created_at")),
        record_updated_at=_bounded_text(row.get("record_updated_at")),
    )


def _safe_client_id(value: str) -> str:
    if not isinstance(value, str):
        raise ScalePadReadError("ScalePad operations require an explicit tenant scope.")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_CLIENT_ID_LENGTH:
        raise ScalePadReadError("ScalePad operations require an explicit tenant scope.")
    return normalized


def _bounded_provider_id(value: object) -> str:
    if not isinstance(value, str):
        raise ScalePadReadError("ScalePad provider client IDs must be non-empty strings.")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_PROVIDER_ID_LENGTH:
        raise ScalePadReadError("ScalePad provider client IDs must be bounded strings.")
    if any(ord(character) < 32 for character in normalized):
        raise ScalePadReadError("ScalePad provider client IDs must not contain control characters.")
    return normalized


def _optional_provider_id(value: object) -> str:
    if value is None or value == "":
        return ""
    return _bounded_provider_id(value)


def _endpoint_url(base_url: str, endpoint: str) -> str:
    if len(base_url) > MAX_ENDPOINT_LENGTH or any(ord(character) < 32 for character in base_url):
        raise ScalePadReadError("ScalePad base URL is invalid.")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ScalePadReadError("ScalePad base URL must be an HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ScalePadReadError("ScalePad base URL must not contain credentials or query data.")
    if endpoint != "core/v1/clients":
        raise ScalePadReadError("ScalePad endpoint is not supported.")
    return f"{base_url.strip().rstrip('/')}/{endpoint}"


def _bounded_text(value: object) -> str:
    return " ".join(str(value).split())[:MAX_TEXT_LENGTH] if value is not None else ""


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


__all__ = [
    "ScalePadClient",
    "ScalePadClientRecord",
    "ScalePadClientResponse",
    "ScalePadReadError",
    "ScalePadReadProvider",
]
