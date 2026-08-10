"""Bounded ConnectWise ScreenConnect session lookup adapter.

The official RESTful API Manager extension documents read endpoints such as
``GetSessionDetailsBySessionID`` and requires an instance URL, extension ID,
trusted Origin, and extension authentication secret. WAIT keeps the tenant
boundary local by requiring an explicit client-to-session-ID map. The adapter
does not guess session groups, execute commands, or expose alert/script
operations without a documented and separately governed provider contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.rmm import RmmAlert, RmmDevice, RmmScript, RmmScriptExecution, RmmScriptPreview

MAX_SESSIONS = 100


class ScreenConnectRmmError(Exception):
    """Safe, operator-facing ScreenConnect adapter error."""


class ScreenConnectRmmAdapter:
    """Read-only ScreenConnect session/device adapter."""

    adapter_id = "screenconnect"

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        session_ids = self._session_ids(client_id)
        devices: list[RmmDevice] = []
        for session_id in session_ids:
            payload = self._request(
                "GetSessionDetailsBySessionID",
                [session_id],
                client_id=client_id,
            )
            rows = _session_rows(payload)
            for row in rows[:1]:
                resolved_id = _first_text(row, "SessionID", "sessionID", "Id", "id") or session_id
                name = _first_text(row, "Name", "name", "SessionName", "sessionName") or resolved_id
                attributes = {
                    key: value
                    for key in (
                        "SessionID",
                        "SessionType",
                        "Host",
                        "IsPublic",
                        "HostConnectedCount",
                        "GuestConnectedCount",
                    )
                    if (value := _safe_scalar(row.get(key))) is not None
                }
                devices.append(RmmDevice(resolved_id, name, "screenconnect-session", attributes))
        return devices[:MAX_SESSIONS]

    def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
        self._session_ids(client_id)
        raise ScreenConnectRmmError(
            "ScreenConnect alert lookup is unavailable: the documented RESTful API "
            "Manager contract exposes session reads, not alert reads"
        )

    def list_scripts(self, client_id: str | None = None) -> list[RmmScript]:
        self._session_ids(client_id)
        raise ScreenConnectRmmError(
            "ScreenConnect script catalog is unavailable: the documented RESTful API "
            "Manager contract does not expose a script catalog"
        )

    def preview_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptPreview:
        self._session_ids(client_id)
        raise ScreenConnectRmmError(
            "ScreenConnect command execution is unavailable until a reviewed script "
            "catalog and approval contract are configured"
        )

    def execute_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        self._session_ids(client_id)
        raise ScreenConnectRmmError(
            "ScreenConnect command execution is unavailable until a reviewed script "
            "catalog and approval contract are configured"
        )

    def get_execution(
        self,
        execution_id: str,
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        self._session_ids(client_id)
        raise ScreenConnectRmmError(
            "ScreenConnect command polling is unavailable because command execution is not enabled"
        )

    def _session_ids(self, client_id: str | None) -> list[str]:
        if not client_id or not client_id.strip():
            raise ScreenConnectRmmError("ScreenConnect operations require an explicit tenant scope")
        try:
            mapping = json.loads(self.settings.screenconnect_client_sessions_map_json or "{}")
        except ValueError as exc:
            raise ScreenConnectRmmError("WAIT_SCREENCONNECT_CLIENT_SESSIONS_MAP_JSON is malformed") from exc
        if not isinstance(mapping, Mapping):
            raise ScreenConnectRmmError("WAIT_SCREENCONNECT_CLIENT_SESSIONS_MAP_JSON must be an object")
        raw_ids = mapping.get(client_id.strip())
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ScreenConnectRmmError("ScreenConnect tenant session mapping is missing")
        if len(raw_ids) > MAX_SESSIONS:
            raise ScreenConnectRmmError(f"ScreenConnect tenant session mapping exceeds {MAX_SESSIONS} sessions")
        session_ids: list[str] = []
        for raw_id in raw_ids:
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise ScreenConnectRmmError("ScreenConnect session IDs must be non-empty strings")
            try:
                session_ids.append(str(UUID(raw_id.strip())))
            except ValueError as exc:
                raise ScreenConnectRmmError("ScreenConnect session IDs must be UUIDs") from exc
        return session_ids

    def _request(self, operation: str, body: list[str], *, client_id: str | None) -> object:
        self._session_ids(client_id)
        if not self.settings.allow_http_probing:
            raise ScreenConnectRmmError(
                "ScreenConnect live calls are blocked until WAIT_ALLOW_HTTP_PROBING=true"
            )
        base_url = _safe_base_url(self.settings.screenconnect_base_url)
        extension_id = _extension_id(self.settings.screenconnect_extension_id)
        origin = _safe_origin(self.settings.screenconnect_origin)
        if not self.settings.screenconnect_auth_secret:
            raise ScreenConnectRmmError("ScreenConnect credentials are incomplete: WAIT_SCREENCONNECT_AUTH_SECRET")
        endpoint = f"{base_url}/App_Extensions/{extension_id}/Service.ashx/{operation}"
        try:
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    endpoint,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "CTRLAuthHeader": self.settings.screenconnect_auth_secret,
                        "Origin": origin,
                    },
                    json=body,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ScreenConnectRmmError("ScreenConnect request failed before receiving a response") from exc
        except httpx.HTTPError as exc:
            raise ScreenConnectRmmError("ScreenConnect request failed") from exc
        if response.status_code >= 400:
            if response.status_code in {401, 403}:
                raise ScreenConnectRmmError("ScreenConnect request was unauthorized")
            raise ScreenConnectRmmError(f"ScreenConnect request failed with HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ScreenConnectRmmError("ScreenConnect returned malformed JSON") from exc


def _session_rows(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("Sessions", "sessions", "Data", "data", "Result", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
    if any(key in payload for key in ("SessionID", "sessionID", "Name", "name")):
        return [payload]
    return []


def _first_text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _safe_scalar(value: object) -> object | None:
    return value if value is None or isinstance(value, (str, int, float, bool)) else None


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ScreenConnectRmmError("ScreenConnect base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ScreenConnectRmmError("ScreenConnect base URL must not contain credentials or query data")
    return value.strip().rstrip("/")


def _safe_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ScreenConnectRmmError("ScreenConnect Origin must be an HTTP(S) origin")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ScreenConnectRmmError("ScreenConnect Origin must not contain a path or query data")
    return value.strip().rstrip("/")


def _extension_id(value: str) -> str:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise ScreenConnectRmmError("ScreenConnect extension ID must be a UUID") from exc


__all__ = ["ScreenConnectRmmAdapter", "ScreenConnectRmmError"]
