"""Read-first RMM contracts and the initial NinjaOne adapter.

The adapter intentionally stops at inventory, alerts, scripts, and safe script
previews.  It does not execute scripts or expose management endpoints.  Those
operations can be added later behind the existing approval and write-action
gates once credential scope and execution history are defined.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

RmmItem = dict[str, object]
RmmNormalizer = Callable[[Mapping[str, object]], RmmItem | None]


@dataclass(frozen=True)
class RmmReadResponse:
    result: ConnectorReadResult
    items: list[RmmItem]


class RmmReadError(Exception):
    """A sanitized RMM adapter failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RmmClient(Protocol):
    """Read-first contract shared by future RMM vendor adapters."""

    def health(self) -> ConnectorReadResult:
        ...

    def list_devices(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse:
        ...

    def get_device(self, device_id: str) -> RmmReadResponse:
        ...

    def list_alerts(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse:
        ...

    def list_scripts(self) -> RmmReadResponse:
        ...

    def preview_script(
        self,
        device_id: str,
        script_id: str,
        variables: Mapping[str, object] | None = None,
    ) -> RmmReadResponse:
        ...


class NinjaOneClient:
    """Small read-only NinjaOne Public API adapter."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self._cached_token: str | None = None
        self._cached_token_expires_at = 0.0

    def health(self) -> ConnectorReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        try:
            self._access_token()
        except RmmReadError as exc:
            return ConnectorReadResult("failed", exc.message)
        return ConnectorReadResult("ready", "NinjaOne monitoring token request succeeded.")

    def list_devices(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse:
        params: dict[str, str | int] = {"pageSize": _bounded_page_size(page_size or self.settings.ninjaone_page_size)}
        if after:
            params["after"] = after
        return self._list("devices", _normalize_device, params=params)

    def get_device(self, device_id: str) -> RmmReadResponse:
        return self._single(f"device/{_safe_segment(device_id)}", _normalize_device)

    def list_alerts(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse:
        params: dict[str, str | int] = {"pageSize": _bounded_page_size(page_size or self.settings.ninjaone_page_size)}
        if after:
            params["after"] = after
        return self._list("alerts", _normalize_alert, params=params)

    def list_scripts(self) -> RmmReadResponse:
        return self._list("automation/scripts", _normalize_script)

    def preview_script(
        self,
        device_id: str,
        script_id: str,
        variables: Mapping[str, object] | None = None,
    ) -> RmmReadResponse:
        """Return a redacted execution proposal without calling a write endpoint."""

        try:
            normalized_device_id = _safe_segment(device_id)
            normalized_script_id = _safe_segment(script_id)
        except RmmReadError as exc:
            return RmmReadResponse(ConnectorReadResult("failed", exc.message), [])
        variable_names = sorted(
            key for key in (variables or {}) if isinstance(key, str) and key.strip()
        )
        return RmmReadResponse(
            ConnectorReadResult(
                "ready",
                "NinjaOne script execution preview created; no script was executed.",
            ),
            [
                {
                    "device_id": normalized_device_id,
                    "script_id": normalized_script_id,
                    "operation": "script.run",
                    "approval_required": True,
                    "execution_enabled": False,
                    "variable_names": variable_names,
                }
            ],
        )

    def _list(
        self,
        endpoint: str,
        normalizer: RmmNormalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> RmmReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        return self._request_items(endpoint, normalizer, params=params)

    def _single(self, endpoint: str, normalizer: RmmNormalizer) -> RmmReadResponse:
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
        normalizer: RmmNormalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> RmmReadResponse:
        try:
            payload = self._get(endpoint, params=params)
        except RmmReadError as exc:
            return RmmReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return RmmReadResponse(
            ConnectorReadResult("ready", f"NinjaOne read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> object:
        token = self._access_token()
        try:
            with self._client() as client:
                response = client.get(
                    f"{_api_base_url(self.settings.ninjaone_base_url)}/{_safe_endpoint(endpoint)}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise RmmReadError("NinjaOne request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise RmmReadError("NinjaOne request failed.") from exc
        if response.status_code >= 400:
            raise RmmReadError(f"NinjaOne GET {endpoint} failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise RmmReadError(f"NinjaOne GET {endpoint} returned malformed JSON.") from exc

    def _access_token(self) -> str:
        now = monotonic()
        if self._cached_token and now < self._cached_token_expires_at:
            return self._cached_token
        missing = self._not_configured_result()
        if missing is not None:
            raise RmmReadError(missing.message)
        try:
            with self._client() as client:
                response = client.post(
                    _token_url(self.settings.ninjaone_base_url),
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.settings.ninjaone_client_id,
                        "client_secret": self.settings.ninjaone_client_secret,
                        "scope": self.settings.ninjaone_scope,
                    },
                    headers={"Accept": "application/json"},
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise RmmReadError("NinjaOne token request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise RmmReadError("NinjaOne token request failed.") from exc
        if response.status_code >= 400:
            raise RmmReadError(f"NinjaOne token request failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RmmReadError("NinjaOne token response was malformed JSON.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RmmReadError("NinjaOne token response did not contain an access token.")
        expires_in = payload.get("expires_in", 3600)
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            expires_in = 3600
        self._cached_token = payload["access_token"]
        self._cached_token_expires_at = now + max(float(expires_in) - 30.0, 1.0)
        return self._cached_token

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport)

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "NinjaOne live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_NINJAONE_BASE_URL": self.settings.ninjaone_base_url,
                "WAIT_NINJAONE_CLIENT_ID": self.settings.ninjaone_client_id,
                "WAIT_NINJAONE_CLIENT_SECRET": self.settings.ninjaone_client_secret,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"NinjaOne credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> RmmReadResponse | None:
        blocked = self._blocked_result()
        return RmmReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> RmmReadResponse | None:
        missing = self._not_configured_result()
        return RmmReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/api/v2") or stripped.endswith("/v2"):
        return stripped
    if stripped.endswith("/api"):
        return f"{stripped}/v2"
    return f"{stripped}/api/v2"


def _token_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    for suffix in ("/api/v2", "/api", "/v2"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    return f"{stripped}/ws/oauth/token"


def _safe_endpoint(endpoint: str) -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise RmmReadError("NinjaOne endpoint overrides must be relative paths.")
    return endpoint.strip("/")


def _safe_segment(value: str) -> str:
    stripped = value.strip()
    if not stripped or any(character in stripped for character in "/?#"):
        raise RmmReadError("NinjaOne resource identifiers must be single path segments.")
    return stripped


def _bounded_page_size(value: int) -> int:
    return max(1, min(value, 100))


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    candidates: list[object]
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = []
        found_list = False
        for key in ("data", "results", "devices", "alerts", "scripts", "automationScripts"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                found_list = True
                break
        if not found_list:
            candidates = [payload]
    else:
        return []
    return [row for row in candidates if isinstance(row, dict)]


def _normalize_device(row: Mapping[str, object]) -> RmmItem | None:
    device_id = _first_value(row, "id", "deviceId", "device_id")
    if device_id in (None, ""):
        return None
    return {
        "id": str(device_id),
        "organization_id": _string_value(row, "organizationId", "organization_id"),
        "location_id": _string_value(row, "locationId", "location_id"),
        "display_name": _string_value(row, "displayName", "display_name", "systemName", "system_name"),
        "system_name": _string_value(row, "systemName", "system_name"),
        "node_class": _string_value(row, "nodeClass", "node_class"),
        "offline": _bool_value(row, "offline"),
        "approval_status": _string_value(row, "approvalStatus", "approval_status"),
        "last_contact": _string_value(row, "lastContact", "last_contact"),
    }


def _normalize_alert(row: Mapping[str, object]) -> RmmItem | None:
    alert_id = _first_value(row, "uid", "id", "alertId", "alert_id")
    if alert_id in (None, ""):
        return None
    return {
        "id": str(alert_id),
        "device_id": _string_value(row, "deviceId", "device_id"),
        "organization_id": _string_value(row, "organizationId", "organization_id"),
        "severity": _string_value(row, "severity", "priority"),
        "message": _string_value(row, "message", "condition", "description"),
        "created_at": _string_value(row, "created", "createdAt", "created_at"),
    }


def _normalize_script(row: Mapping[str, object]) -> RmmItem | None:
    script_id = _first_value(row, "id", "scriptId", "script_id")
    if script_id in (None, ""):
        return None
    return {
        "id": str(script_id),
        "name": _string_value(row, "name", "displayName", "display_name"),
        "language": _string_value(row, "language"),
        "type": _string_value(row, "type", "scriptType", "script_type"),
    }


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _string_value(row: Mapping[str, object], *keys: str) -> str:
    value = _first_value(row, *keys)
    return "" if value is None else str(value)


def _bool_value(row: Mapping[str, object], *keys: str) -> bool:
    value = _first_value(row, *keys)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else False
