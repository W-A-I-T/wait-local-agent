"""Bounded Kaseya VSA X v3 adapter for the shared RMM contract.

The public VSA X API documents Basic authentication with an API token ID and
secret, organization-scoped device and device-notification reads, and
approval-compatible automation script operations. WAIT keeps its tenant scope
in a local client-to-organization map, validates devices and script input
variables before writes, and persists execution scope for safe polling.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.rmm import RmmAlert, RmmDevice, RmmScript, RmmScriptExecution, RmmScriptPreview
from wait_local_agent.store import Store

MAX_PAGE_SIZE = 100


class KaseyaRmmError(Exception):
    """Safe, operator-facing Kaseya VSA X adapter error."""


class KaseyaRmmAdapter:
    """Tenant-scoped VSA X inventory and approval-gated script adapter."""

    adapter_id = "kaseya-vsa-x"

    def __init__(
        self,
        settings: Settings,
        *,
        store: Store | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.transport = transport

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        organization_id = self._organization_id(client_id)
        payload = self._get(
            "devices",
            client_id=client_id,
            params={
                "$top": self._page_size(),
                "$skip": 0,
                "$filter": f"OrganizationId eq {organization_id}",
            },
        )
        devices: list[RmmDevice] = []
        for row in _rows(payload):
            if _int_value(row.get("OrganizationId")) != organization_id:
                continue
            device_id = _first_text(row, "Identifier")
            if not device_id:
                continue
            name = _first_text(row, "Name") or device_id
            attributes = {
                key: row[key]
                for key in (
                    "Identifier",
                    "GroupId",
                    "GroupName",
                    "SiteId",
                    "SiteName",
                    "OrganizationId",
                    "OrganizationName",
                    "IsAgentInstalled",
                    "IsMdmEnrolled",
                )
                if key in row and _safe_attribute(row[key]) is not None
            }
            devices.append(RmmDevice(device_id, name, "device", attributes))
        return devices[: self._page_size()]

    def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
        alerts: list[RmmAlert] = []
        for device in self.list_devices(client_id):
            payload = self._get(
                f"devices/{_path_segment(device.device_id)}/notifications",
                client_id=client_id,
                params={"$top": self._page_size(), "$skip": 0},
            )
            for row in _rows(payload):
                alert_id = _first_text(row, "Id")
                if not alert_id:
                    continue
                alerts.append(
                    RmmAlert(
                        alert_id=alert_id,
                        device_id=device.device_id,
                        severity=_first_text(row, "Priority") or "unknown",
                        title=_first_text(row, "Message") or "Kaseya VSA X notification",
                        status="open",
                    )
                )
                if len(alerts) >= self._page_size():
                    return alerts
        return alerts

    def list_scripts(self, client_id: str | None = None) -> list[RmmScript]:
        self._organization_id(client_id)
        payload = self._get(
            "automation/scripts",
            client_id=client_id,
            params={"$top": self._page_size(), "$skip": 0},
        )
        scripts: list[RmmScript] = []
        for row in _rows(payload):
            script_id = _first_text(row, "Id")
            if not script_id:
                continue
            scripts.append(
                RmmScript(
                    script_id=script_id,
                    name=_first_text(row, "Name") or script_id,
                    description=_first_text(row, "Description"),
                )
            )
        return scripts[: self._page_size()]

    def preview_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptPreview:
        safe_script_id, safe_device_id, safe_arguments = self._validate_script_request(
            script_id, device_id, arguments, client_id=client_id
        )
        return RmmScriptPreview(
            script_id=safe_script_id,
            device_id=safe_device_id,
            arguments=safe_arguments,
            status="preview",
            message=(
                "Kaseya VSA X script and device are validated; execution requires a completed technician approval"
                if self.settings.allow_write_actions
                else "Kaseya VSA X script and device are validated; execution is blocked "
                "until WAIT_ALLOW_WRITE_ACTIONS=true"
            ),
        )

    def execute_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        safe_script_id, safe_device_id, safe_arguments = self._validate_script_request(
            script_id, device_id, arguments, client_id=client_id
        )
        if not self.settings.allow_write_actions:
            return RmmScriptExecution(
                script_id=safe_script_id,
                device_id=safe_device_id,
                status="blocked",
                message="Kaseya VSA X script execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true",
            )
        payload = self._post(
            f"automation/scripts/{_path_segment(safe_script_id)}/run",
            client_id=client_id,
            payload={
                "DeviceIdentifier": safe_device_id,
                "Variables": [{"Id": int(key), "Value": value} for key, value in sorted(safe_arguments.items())],
            },
        )
        data = _data(payload)
        execution_id = _first_text(data, "ExecutionId")
        if not execution_id:
            raise KaseyaRmmError("Kaseya VSA X script response was malformed")
        if self.store is not None and client_id is not None:
            self.store.record_rmm_execution_scope(
                execution_id,
                self.adapter_id,
                safe_script_id,
                safe_device_id,
                client_id,
            )
        return RmmScriptExecution(
            script_id=safe_script_id,
            device_id=safe_device_id,
            status="queued",
            message="Kaseya VSA X accepted the script execution request",
            execution_id=execution_id,
        )

    def get_execution(
        self,
        execution_id: str,
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        safe_execution_id = _path_segment(execution_id)
        self._organization_id(client_id)
        if self.store is None or client_id is None:
            raise KaseyaRmmError("Kaseya VSA X execution lookup requires local execution scope")
        scope = self.store.get_rmm_execution_scope(
            safe_execution_id,
            self.adapter_id,
            client_id,
        )
        if scope is None:
            raise KaseyaRmmError("Kaseya VSA X execution is outside the tenant scope")
        devices = self.list_devices(client_id)
        if not any(device.device_id == scope.device_id for device in devices):
            raise KaseyaRmmError("Kaseya VSA X execution device is outside the tenant scope")
        payload = self._get(
            "automation/scripts/"
            f"{_path_segment(scope.script_id)}/device/{_path_segment(scope.device_id)}/executions/"
            f"{safe_execution_id}",
            client_id=client_id,
            params={},
        )
        data = _data(payload)
        returned_id = _first_text(data, "Id")
        if returned_id and returned_id != safe_execution_id:
            raise KaseyaRmmError("Kaseya VSA X execution response was outside the requested scope")
        status_value = _execution_status(_first_text(data, "State"))
        if status_value is None:
            raise KaseyaRmmError("Kaseya VSA X execution response was malformed")
        return RmmScriptExecution(
            script_id=scope.script_id,
            device_id=scope.device_id,
            status=status_value,
            message=(
                "Kaseya VSA X script execution is still running"
                if status_value == "queued"
                else f"Kaseya VSA X script execution status: {status_value}"
            ),
            execution_id=safe_execution_id,
        )

    def _get(
        self,
        endpoint: str,
        *,
        client_id: str | None,
        params: dict[str, str | int],
    ) -> object:
        return self._request("GET", endpoint, client_id=client_id, params=params)

    def _post(
        self,
        endpoint: str,
        *,
        client_id: str | None,
        payload: dict[str, object],
    ) -> object:
        return self._request("POST", endpoint, client_id=client_id, json_body=payload)

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        client_id: str | None,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        self._organization_id(client_id)
        if not self.settings.allow_http_probing:
            raise KaseyaRmmError("Kaseya VSA X live calls are blocked until WAIT_ALLOW_HTTP_PROBING=true")
        if not self.settings.kaseya_rmm_base_url:
            raise KaseyaRmmError("Kaseya VSA X credentials are incomplete: WAIT_KASEYA_RMM_BASE_URL")
        if not self.settings.kaseya_rmm_token_id or not self.settings.kaseya_rmm_token_secret:
            raise KaseyaRmmError(
                "Kaseya VSA X credentials are incomplete: WAIT_KASEYA_RMM_TOKEN_ID and WAIT_KASEYA_RMM_TOKEN_SECRET"
            )
        base_url = _safe_base_url(self.settings.kaseya_rmm_base_url)
        safe_endpoint = _safe_endpoint(endpoint)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.request(
                    method,
                    f"{base_url}/{safe_endpoint}",
                    auth=(self.settings.kaseya_rmm_token_id, self.settings.kaseya_rmm_token_secret),
                    headers={"Accept": "application/json"},
                    params=params,
                    json=json_body,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise KaseyaRmmError("Kaseya VSA X request failed before receiving a response") from exc
        except httpx.HTTPError as exc:
            raise KaseyaRmmError("Kaseya VSA X request failed") from exc
        if response.status_code >= 400:
            if response.status_code in {401, 403}:
                raise KaseyaRmmError("Kaseya VSA X request was unauthorized")
            raise KaseyaRmmError(f"Kaseya VSA X request failed with HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise KaseyaRmmError("Kaseya VSA X returned malformed JSON") from exc

    def _organization_id(self, client_id: str | None) -> int:
        if not client_id or not client_id.strip():
            raise KaseyaRmmError("Kaseya VSA X operations require an explicit tenant scope")
        try:
            mapping = json.loads(self.settings.kaseya_rmm_organization_map_json or "{}")
        except ValueError as exc:
            raise KaseyaRmmError("WAIT_KASEYA_RMM_ORGANIZATION_MAP_JSON is malformed") from exc
        if not isinstance(mapping, dict):
            raise KaseyaRmmError("WAIT_KASEYA_RMM_ORGANIZATION_MAP_JSON must be an object")
        raw_id = mapping.get(client_id.strip())
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
            raise KaseyaRmmError("Kaseya VSA X tenant organization mapping is missing")
        try:
            organization_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise KaseyaRmmError("Kaseya VSA X organization IDs must be integers") from exc
        if organization_id < 1:
            raise KaseyaRmmError("Kaseya VSA X organization ID must be positive")
        return organization_id

    def _page_size(self) -> int:
        return min(max(self.settings.kaseya_rmm_page_size, 1), MAX_PAGE_SIZE)

    def _validate_script_request(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None,
    ) -> tuple[str, str, dict[str, str]]:
        self._organization_id(client_id)
        safe_script_id = _path_segment(script_id)
        safe_device_id = _path_segment(device_id)
        if len(arguments) > 20:
            raise KaseyaRmmError("Kaseya VSA X script arguments exceed 20 values")
        safe_arguments: dict[str, str] = {}
        for key, value in arguments.items():
            variable_id = _variable_id(key)
            if not isinstance(value, str) or len(value) > 500:
                raise KaseyaRmmError("Kaseya VSA X script argument values must be strings of at most 500 characters")
            safe_arguments[str(variable_id)] = value
        if not any(device.device_id == safe_device_id for device in self.list_devices(client_id)):
            raise KaseyaRmmError("Kaseya VSA X device is outside the tenant scope")
        script = _data(
            self._get(
                f"automation/scripts/{_path_segment(safe_script_id)}",
                client_id=client_id,
                params={},
            )
        )
        if _first_text(script, "Id") != safe_script_id:
            raise KaseyaRmmError("Kaseya VSA X script was not found")
        raw_variables = script.get("InputVariables")
        if not isinstance(raw_variables, list):
            raise KaseyaRmmError("Kaseya VSA X script response was malformed")
        allowed_ids = {
            variable_id
            for item in raw_variables
            if isinstance(item, Mapping)
            for variable_id in [_int_value(item.get("Id"))]
            if variable_id is not None and variable_id > 0
        }
        if any(int(key) not in allowed_ids for key in safe_arguments):
            raise KaseyaRmmError("Kaseya VSA X script argument is not an input variable")
        return safe_script_id, safe_device_id, safe_arguments


def _rows(payload: object) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    value = payload.get("Data")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    return []


def _data(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    value = payload.get("Data")
    return value if isinstance(value, Mapping) else {}


def _first_text(row: Mapping[str, Any], key: str) -> str:
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


def _safe_attribute(value: object) -> object | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise KaseyaRmmError("Kaseya VSA X base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise KaseyaRmmError("Kaseya VSA X base URL must not contain credentials or query data")
    return value.strip().rstrip("/")


def _safe_endpoint(value: str) -> str:
    parts = value.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise KaseyaRmmError("Kaseya VSA X endpoint is invalid")
    if any(not all(character.isalnum() or character in {"-", "_"} for character in part) for part in parts):
        raise KaseyaRmmError("Kaseya VSA X endpoint contains unsafe characters")
    return "/".join(parts)


def _path_segment(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if not value.strip() or any(character not in allowed for character in value):
        raise KaseyaRmmError("Kaseya VSA X device identifier is invalid")
    return value


def _variable_id(value: object) -> int:
    if not isinstance(value, str) or not value.strip() or not value.strip().isdigit():
        raise KaseyaRmmError("Kaseya VSA X script argument keys must be positive variable IDs")
    parsed = int(value.strip())
    if parsed < 1 or parsed > 2_147_483_647:
        raise KaseyaRmmError("Kaseya VSA X script variable IDs must be positive 32-bit integers")
    return parsed


def _execution_status(value: str) -> Literal["queued", "succeeded", "failed"] | None:
    return cast(
        Literal["queued", "succeeded", "failed"] | None,
        {
            "running": "queued",
            "successful": "succeeded",
            "failed": "failed",
            "stopped": "failed",
        }.get(value.casefold()),
    )


__all__ = ["KaseyaRmmAdapter", "KaseyaRmmError"]
