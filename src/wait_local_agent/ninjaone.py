"""Bounded NinjaOne Public API v2 adapter for the shared RMM contract.

The adapter uses documented OAuth bearer authentication and keeps WAIT tenant
scope separate from NinjaOne organization IDs through an explicit local map.
It never accepts credentials or organization IDs in smart-action payloads.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.net_security import NetSecurityError, validate_operator_url
from wait_local_agent.rmm import (
    RmmAlert,
    RmmDevice,
    RmmScript,
    RmmScriptExecution,
    RmmScriptPreview,
)

MAX_PAGE_SIZE = 100
MAX_ARGUMENTS = 20


class NinjaOneRmmError(Exception):
    """Safe, operator-facing NinjaOne adapter error."""


class NinjaOneRmmAdapter:
    adapter_id = "ninjaone"

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        organization_id = self._organization_id(client_id)
        payload = self._get(
            "devices",
            client_id=client_id,
            params={"df": f"org = {organization_id}", "pageSize": self._page_size()},
        )
        devices: list[RmmDevice] = []
        for row in _rows(payload):
            if _int_value(row.get("organizationId")) != organization_id:
                continue
            device_id = _int_string(row.get("id"))
            if not device_id:
                continue
            name = _first_string(row, "displayName", "systemName", "dnsName") or device_id
            category = _first_string(row, "nodeClass")
            attributes = {
                key: row[key]
                for key in (
                    "organizationId",
                    "locationId",
                    "nodeClass",
                    "approvalStatus",
                    "offline",
                    "systemName",
                    "dnsName",
                    "lastContact",
                    "tags",
                )
                if key in row
            }
            devices.append(RmmDevice(device_id, name, category, attributes))
        return devices

    def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
        organization_id = self._organization_id(client_id)
        payload = self._get(
            "alerts",
            client_id=client_id,
            params={"df": f"org = {organization_id}", "pageSize": self._page_size()},
        )
        alerts: list[RmmAlert] = []
        for row in _rows(payload):
            if _int_value(row.get("organizationId")) != organization_id:
                continue
            alert_id = _first_string(row, "uid", "id")
            device_id = _int_string(row.get("deviceId")) or _int_string(row.get("nodeId"))
            if not alert_id or not device_id:
                continue
            alerts.append(
                RmmAlert(
                    alert_id=alert_id,
                    device_id=device_id,
                    severity=_first_string(row, "severity", "priority") or "unknown",
                    title=_first_string(row, "message", "conditionName", "name") or "NinjaOne alert",
                    status=_first_string(row, "status") or "open",
                )
            )
        return alerts

    def list_scripts(self, client_id: str | None = None) -> list[RmmScript]:
        self._organization_id(client_id)
        payload = self._get(
            "automation/scripts",
            client_id=client_id,
            params={"pageSize": self._page_size()},
        )
        scripts: list[RmmScript] = []
        for row in _rows(payload):
            script_id = _int_string(row.get("id"))
            if not script_id:
                continue
            scripts.append(
                RmmScript(
                    script_id=script_id,
                    name=_first_string(row, "name", "displayName") or script_id,
                    description=_first_string(row, "description"),
                )
            )
        return scripts

    def preview_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptPreview:
        self._validate_script_request(script_id, device_id, arguments)
        devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in devices):
            raise NinjaOneRmmError("NinjaOne device is outside the tenant scope")
        scripts = self.list_scripts(client_id)
        if not any(script.script_id == script_id for script in scripts):
            raise NinjaOneRmmError("NinjaOne script was not found")
        return RmmScriptPreview(
            script_id=script_id,
            device_id=device_id,
            arguments=dict(arguments),
            status="preview",
            message="NinjaOne script request is ready for approval",
        )

    def execute_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        self._validate_script_request(script_id, device_id, arguments)
        self.preview_script(script_id, device_id, arguments, client_id=client_id)
        try:
            script_number = int(script_id)
            device_number = int(device_id)
        except ValueError as exc:
            raise NinjaOneRmmError("NinjaOne script and device IDs must be integers") from exc
        response = self._post(
            f"device/{device_number}/script/run",
            client_id=client_id,
            payload={
                "type": "SCRIPT",
                "id": script_number,
                "parameters": json.dumps(arguments, sort_keys=True, separators=(",", ":")),
            },
        )
        execution_id = _first_string(response, "id", "jobId", "uid")
        return RmmScriptExecution(
            script_id=script_id,
            device_id=device_id,
            status="queued",
            message="NinjaOne accepted the script execution request",
            execution_id=execution_id,
        )

    def get_execution(
        self,
        execution_id: str,
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        if not execution_id.strip() or len(execution_id) > 100:
            raise NinjaOneRmmError("NinjaOne execution ID is invalid")
        organization_id = self._organization_id(client_id)
        payload = self._get(
            "jobs",
            client_id=client_id,
            params={
                "df": f"org = {organization_id}",
                "pageSize": self._page_size(),
            },
        )
        for row in _rows(payload):
            if _first_string(row, "id", "jobId", "uid") != execution_id:
                continue
            row_organization_id = _int_value(row.get("organizationId"))
            device_id = _int_string(row.get("deviceId")) or _int_string(row.get("nodeId"))
            if row_organization_id is not None and row_organization_id != organization_id:
                continue
            if row_organization_id is None:
                if not device_id:
                    continue
                if not any(device.device_id == device_id for device in self.list_devices(client_id)):
                    continue
            return RmmScriptExecution(
                script_id=_int_string(row.get("scriptId")),
                device_id=device_id,
                status=_job_status(row),
                message="NinjaOne execution status retrieved",
                execution_id=execution_id,
            )
        raise NinjaOneRmmError("NinjaOne execution was not found in the active job list")

    def _get(self, endpoint: str, *, client_id: str | None, params: dict[str, str | int]) -> object:
        return self._request("GET", endpoint, client_id=client_id, params=params)

    def _post(self, endpoint: str, *, client_id: str | None, payload: dict[str, object]) -> Mapping[str, object]:
        result = self._request("POST", endpoint, client_id=client_id, payload=payload)
        return result if isinstance(result, Mapping) else {}

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        client_id: str | None,
        params: dict[str, str | int] | None = None,
        payload: dict[str, object] | None = None,
    ) -> object:
        self._organization_id(client_id)
        if not self.settings.allow_http_probing:
            raise NinjaOneRmmError(
                "NinjaOne live calls are blocked until WAIT_ALLOW_HTTP_PROBING=true"
            )
        if not self.settings.ninjaone_access_token or not self.settings.ninjaone_base_url:
            raise NinjaOneRmmError(
                "NinjaOne credentials are incomplete: WAIT_NINJAONE_BASE_URL and WAIT_NINJAONE_ACCESS_TOKEN"
            )
        base_url = _safe_base_url(
            self.settings.ninjaone_base_url,
            allow_insecure_transport=self.settings.allow_insecure_provider_transport,
        )
        safe_endpoint = _safe_endpoint(endpoint)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.request(
                    method,
                    f"{base_url}/{safe_endpoint}",
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.settings.ninjaone_access_token}",
                    },
                    params=params,
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise NinjaOneRmmError("NinjaOne request failed before receiving a response") from exc
        except httpx.HTTPError as exc:
            raise NinjaOneRmmError("NinjaOne request failed") from exc
        if response.status_code >= 400:
            if response.status_code in {401, 403}:
                raise NinjaOneRmmError("NinjaOne request was unauthorized")
            raise NinjaOneRmmError(f"NinjaOne request failed with HTTP {response.status_code}")
        if response.status_code == 204:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise NinjaOneRmmError("NinjaOne returned malformed JSON") from exc

    def _organization_id(self, client_id: str | None) -> int:
        if not client_id or not client_id.strip():
            raise NinjaOneRmmError("NinjaOne operations require an explicit tenant scope")
        try:
            mapping = json.loads(self.settings.ninjaone_organization_map_json or "{}")
        except ValueError as exc:
            raise NinjaOneRmmError("WAIT_NINJAONE_ORGANIZATION_MAP_JSON is malformed") from exc
        if not isinstance(mapping, dict):
            raise NinjaOneRmmError("WAIT_NINJAONE_ORGANIZATION_MAP_JSON must be an object")
        raw_id = mapping.get(client_id.strip())
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
            raise NinjaOneRmmError("NinjaOne tenant organization mapping is missing")
        try:
            organization_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise NinjaOneRmmError("NinjaOne organization IDs must be integers") from exc
        if organization_id < 1:
            raise NinjaOneRmmError("NinjaOne organization ID must be positive")
        return organization_id

    def _page_size(self) -> int:
        return min(max(self.settings.ninjaone_page_size, 1), MAX_PAGE_SIZE)

    @staticmethod
    def _validate_script_request(script_id: str, device_id: str, arguments: dict[str, str]) -> None:
        if not script_id.isdigit() or not device_id.isdigit():
            raise NinjaOneRmmError("NinjaOne script and device IDs must be integers")
        if len(arguments) > MAX_ARGUMENTS:
            raise NinjaOneRmmError("NinjaOne script arguments are limited to 20 entries")
        if any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or len(key) > 100
            or len(value) > 500
            or any(ord(character) < 32 for character in key + value)
            for key, value in arguments.items()
        ):
            raise NinjaOneRmmError("NinjaOne script arguments must be bounded text")


def _rows(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def _first_string(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def _int_value(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_string(value: object) -> str:
    number = _int_value(value)
    return str(number) if number is not None and number > 0 else ""


def _job_status(row: Mapping[str, Any]) -> Literal["queued", "succeeded", "failed"]:
    status = _first_string(row, "status", "state").casefold()
    if status in {"completed", "succeeded", "success"}:
        return "succeeded"
    if status in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    return "queued"


def _safe_base_url(value: str, *, allow_insecure_transport: bool = False) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NinjaOneRmmError("NinjaOne base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise NinjaOneRmmError("NinjaOne base URL must not contain credentials or query data")
    try:
        validate_operator_url(value, allow_insecure_transport=allow_insecure_transport)
    except NetSecurityError as exc:
        raise NinjaOneRmmError(
            "NinjaOne base URL must use HTTPS; set "
            "WAIT_ALLOW_INSECURE_PROVIDER_TRANSPORT=true to allow plain HTTP"
        ) from exc
    return value.strip().rstrip("/")


def _safe_endpoint(value: str) -> str:
    parts = value.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise NinjaOneRmmError("NinjaOne endpoint is invalid")
    if any(not all(character.isalnum() or character in {"-", "_"} for character in part) for part in parts):
        raise NinjaOneRmmError("NinjaOne endpoint contains unsafe characters")
    return "/".join(parts)


__all__ = ["NinjaOneRmmAdapter", "NinjaOneRmmError"]
