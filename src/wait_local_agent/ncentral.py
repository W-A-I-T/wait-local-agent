"""Bounded N-able N-central adapter for the shared RMM contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.rmm import (
    RmmAlert,
    RmmDevice,
    RmmScript,
    RmmScriptExecution,
    RmmScriptPreview,
)
from wait_local_agent.store import Store

MAX_PAGE_SIZE = 100
MAX_ORG_UNITS = 50
MAX_ARGUMENTS = 20
MAX_ID_LENGTH = 120
MAX_TEXT_LENGTH = 500


class NCentralRmmError(Exception):
    """Safe, operator-facing N-central adapter error."""


class NCentralRmmAdapter:
    """Normalize N-central inventory and governed direct-task operations.

    N-central organization-unit IDs are intentionally mapped from WAIT client
    IDs in local configuration. Writes are limited to existing numeric task
    items and devices returned for that tenant; WAIT never uploads script
    source or accepts provider credentials in an action payload.
    """

    adapter_id = "ncentral"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        store: Store | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.store = store

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        org_unit_ids = self._org_unit_ids(client_id)
        payload = self._get(
            "api/devices",
            params={"pageNumber": 1, "pageSize": self._page_size()},
            client_id=client_id,
        )
        devices: list[RmmDevice] = []
        for row in _rows(payload, "devices", "items", "data", "results"):
            if not _in_scope(row, org_unit_ids):
                continue
            device_id = _first_text(row, "deviceId", "deviceID", "id")
            if not device_id:
                continue
            extra = row.get("_extra")
            extra_map = extra if isinstance(extra, Mapping) else {}
            name = (
                _first_text(row, "deviceName", "name", "hostname")
                or _first_text(extra_map, "deviceName", "name")
                or device_id
            )
            attributes = {
                key: value
                for key in (
                    "deviceClass",
                    "deviceStatus",
                    "orgUnitId",
                    "customerId",
                    "siteId",
                    "lastContact",
                    "serialNumber",
                )
                if (value := _safe_value(row.get(key))) is not None
            }
            devices.append(RmmDevice(device_id, name, _first_text(row, "deviceClass"), attributes))
        return devices[:MAX_PAGE_SIZE]

    def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
        org_unit_ids = self._org_unit_ids(client_id)
        alerts: list[RmmAlert] = []
        for org_unit_id in org_unit_ids:
            payload = self._get(
                f"api/org-units/{org_unit_id}/active-issues",
                params={"pageNumber": 1, "pageSize": self._page_size()},
                client_id=client_id,
            )
            for row in _rows(payload, "data", "items", "results", "issues"):
                if not _in_scope(row, (org_unit_id,)):
                    continue
                device_id = _first_text(row, "deviceId", "deviceID")
                service_id = _first_text(row, "serviceId", "serviceID")
                task_id = _first_text(row, "taskId", "taskID")
                if not device_id or not service_id:
                    continue
                extra = row.get("_extra")
                extra_map = extra if isinstance(extra, Mapping) else {}
                alert_id = _first_text(row, "issueId", "issueID", "id") or (
                    f"{org_unit_id}:{device_id}:{service_id}:{task_id or 'active'}"
                )
                title = (
                    _first_text(row, "serviceName", "name")
                    or _first_text(extra_map, "serviceName", "deviceName")
                    or "N-central active issue"
                )
                alerts.append(
                    RmmAlert(
                        alert_id=alert_id,
                        device_id=device_id,
                        severity=_severity(row.get("notificationState")),
                        title=title,
                        status="open",
                    )
                )
        return alerts[:MAX_PAGE_SIZE]

    def list_scripts(self, client_id: str | None = None) -> list[RmmScript]:
        org_unit_ids = self._org_unit_ids(client_id)
        payload = self._get(
            "api/scheduled-tasks",
            params={"pageNumber": 1, "pageSize": self._page_size()},
            client_id=client_id,
        )
        scripts: list[RmmScript] = []
        for row in _rows(payload, "data", "tasks", "items", "results"):
            if not _in_scope(row, org_unit_ids):
                continue
            task_id = _first_text(row, "taskId", "taskID", "id")
            if not task_id:
                continue
            task_type = _first_text(row, "taskType", "type")
            description = f"N-central {task_type} task" if task_type else "N-central scheduled task"
            scripts.append(
                RmmScript(
                    script_id=task_id,
                    name=_first_text(row, "name", "taskName", "displayName") or task_id,
                    description=description,
                )
            )
        return scripts[:MAX_PAGE_SIZE]

    def preview_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptPreview:
        _validate_script_request(script_id, device_id, arguments)
        devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in devices):
            raise NCentralRmmError("N-central device is outside the tenant scope")
        scripts = self.list_scripts(client_id)
        if not any(script.script_id == script_id for script in scripts):
            raise NCentralRmmError("N-central scheduled task was not found")
        return RmmScriptPreview(
            script_id=script_id,
            device_id=device_id,
            arguments=dict(arguments),
            status="preview",
            message=(
                "N-central device and scheduled task are in scope; execution requires "
                "a completed technician approval"
                if self.settings.allow_write_actions
                else "N-central device and scheduled task are in scope; execution is blocked "
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
        _validate_script_request(script_id, device_id, arguments)
        if not self.settings.allow_write_actions:
            return RmmScriptExecution(
                script_id=script_id,
                device_id=device_id,
                status="blocked",
                message="N-central direct-task execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true",
            )
        device = self._scoped_device(device_id, client_id)
        self._scoped_script(script_id, client_id)
        customer_id = _numeric_id(device.attributes.get("customerId"), "customer")
        payload = {
            "name": _task_name(script_id, device_id, arguments),
            "itemId": _numeric_id(script_id, "script"),
            "taskType": "Script",
            "customerId": customer_id,
            "deviceId": _numeric_id(device_id, "device"),
            "parameters": [
                {"name": key, "value": value, "type": "string"}
                for key, value in sorted(arguments.items())
            ],
        }
        response = self._post("api/scheduled-tasks/direct", payload, client_id=client_id)
        execution_id = _first_nested_text(response, "taskId", "taskID", "id")
        if not execution_id or not _is_numeric_id(execution_id):
            raise NCentralRmmError("N-central direct-task response was malformed")
        if self.store is not None and client_id is not None:
            self.store.record_rmm_execution_scope(
                execution_id,
                self.adapter_id,
                script_id.strip(),
                device_id.strip(),
                client_id,
            )
        return RmmScriptExecution(
            script_id=script_id,
            device_id=device_id,
            status="queued",
            message="N-central direct task was queued",
            execution_id=execution_id,
        )

    def get_execution(
        self,
        execution_id: str,
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        if not execution_id.strip() or len(execution_id) > MAX_ID_LENGTH:
            raise NCentralRmmError("N-central execution ID is invalid")
        normalized_id = execution_id.strip()
        if not _is_numeric_id(normalized_id):
            raise NCentralRmmError("N-central execution ID is invalid")
        self._org_unit_ids(client_id)
        if self.store is None or client_id is None:
            return RmmScriptExecution(
                script_id="",
                device_id="",
                status="blocked",
                message="N-central execution scope is unavailable locally",
                execution_id=normalized_id,
            )
        scope = self.store.get_rmm_execution_scope(
            normalized_id,
            self.adapter_id,
            client_id,
        )
        if scope is None:
            return RmmScriptExecution(
                script_id="",
                device_id="",
                status="blocked",
                message="N-central execution is outside the tenant scope",
                execution_id=normalized_id,
            )
        response = self._get(
            f"api/scheduled-tasks/{normalized_id}/status",
            params={},
            client_id=client_id,
        )
        status = _status_from_response(response)
        return RmmScriptExecution(
            script_id=scope.script_id,
            device_id=scope.device_id,
            status=status,
            message=(
                "N-central task is still running"
                if status == "queued"
                else "N-central task completed"
                if status in {"completed", "succeeded"}
                else "N-central task failed"
            ),
            execution_id=normalized_id,
        )

    def _scoped_device(self, device_id: str, client_id: str | None) -> RmmDevice:
        for device in self.list_devices(client_id):
            if device.device_id == device_id:
                return device
        raise NCentralRmmError("N-central device is outside the tenant scope")

    def _scoped_script(self, script_id: str, client_id: str | None) -> RmmScript:
        for script in self.list_scripts(client_id):
            if script.script_id == script_id:
                return script
        raise NCentralRmmError("N-central scheduled task was not found")

    def _get(
        self,
        endpoint: str,
        *,
        params: dict[str, int],
        client_id: str | None,
    ) -> object:
        return self._request(endpoint, params=params, client_id=client_id)

    def _post(self, endpoint: str, payload: object, *, client_id: str | None) -> object:
        return self._request(endpoint, params={}, client_id=client_id, method="POST", payload=payload)

    def _request(
        self,
        endpoint: str,
        *,
        params: dict[str, int],
        client_id: str | None,
        method: str = "GET",
        payload: object | None = None,
    ) -> object:
        self._org_unit_ids(client_id)
        if not self.settings.allow_http_probing:
            raise NCentralRmmError(
                "N-central live calls are blocked until WAIT_ALLOW_HTTP_PROBING=true"
            )
        if not self.settings.ncentral_base_url or not self.settings.ncentral_access_token:
            raise NCentralRmmError(
                "N-central credentials are incomplete: WAIT_NCENTRAL_BASE_URL and "
                "WAIT_NCENTRAL_ACCESS_TOKEN"
            )
        base_url = _safe_base_url(self.settings.ncentral_base_url)
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
                        "Authorization": f"Bearer {self.settings.ncentral_access_token}",
                    },
                    params=params,
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise NCentralRmmError("N-central request failed before receiving a response") from exc
        except httpx.HTTPError as exc:
            raise NCentralRmmError("N-central request failed") from exc
        if response.status_code in {401, 403}:
            raise NCentralRmmError("N-central request was unauthorized")
        if response.status_code == 429:
            raise NCentralRmmError("N-central request was rate limited")
        if response.status_code >= 400:
            raise NCentralRmmError(f"N-central request failed with HTTP {response.status_code}")
        if response.status_code == 204:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise NCentralRmmError("N-central returned malformed JSON") from exc
        if isinstance(payload, Mapping) and payload.get("errorMessage"):
            raise NCentralRmmError("N-central returned an error response")
        return payload

    def _org_unit_ids(self, client_id: str | None) -> tuple[int, ...]:
        if not client_id or not client_id.strip():
            raise NCentralRmmError("N-central operations require an explicit tenant scope")
        try:
            mapping = json.loads(self.settings.ncentral_org_unit_map_json or "{}")
        except ValueError as exc:
            raise NCentralRmmError("WAIT_NCENTRAL_ORG_UNIT_MAP_JSON is malformed") from exc
        if not isinstance(mapping, dict):
            raise NCentralRmmError("WAIT_NCENTRAL_ORG_UNIT_MAP_JSON must be an object")
        raw_ids = mapping.get(client_id.strip())
        if raw_ids is None:
            raise NCentralRmmError("N-central tenant organization mapping is missing")
        values = raw_ids if isinstance(raw_ids, list) else [raw_ids]
        if not values or len(values) > MAX_ORG_UNITS:
            raise NCentralRmmError("N-central tenant organization mapping is missing")
        normalized: list[int] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                raise NCentralRmmError("N-central organization IDs must be positive integers")
            try:
                organization_id = int(value)
            except (TypeError, ValueError) as exc:
                raise NCentralRmmError("N-central organization IDs must be positive integers") from exc
            if organization_id < 1:
                raise NCentralRmmError("N-central organization IDs must be positive integers")
            if organization_id not in normalized:
                normalized.append(organization_id)
        return tuple(normalized)

    def _page_size(self) -> int:
        return min(max(self.settings.ncentral_page_size, 1), MAX_PAGE_SIZE)


def _rows(payload: object, *keys: str) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def _first_text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:MAX_TEXT_LENGTH]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def _first_nested_text(payload: object, *keys: str) -> str:
    if isinstance(payload, Mapping):
        value = _first_text(payload, *keys)
        if value:
            return value
        for nested_key in ("data", "result", "payload"):
            nested = payload.get(nested_key)
            value = _first_nested_text(nested, *keys)
            if value:
                return value
    return ""


def _is_numeric_id(value: str) -> bool:
    return bool(value) and value.isascii() and value.isdigit() and int(value) > 0


def _numeric_id(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise NCentralRmmError(f"N-central {label} ID is invalid")
    normalized = str(value).strip() if isinstance(value, (int, str)) else ""
    if not _is_numeric_id(normalized):
        raise NCentralRmmError(f"N-central {label} ID is invalid")
    return int(normalized)


def _task_name(script_id: str, device_id: str, arguments: Mapping[str, str]) -> str:
    fingerprint = hashlib.sha256(
        json.dumps(
            {"script": script_id, "device": device_id, "arguments": dict(sorted(arguments.items()))},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"WAIT-NC-{script_id.strip()}-{device_id.strip()}-{fingerprint}"[:MAX_TEXT_LENGTH]


def _status_from_response(payload: object) -> Literal["queued", "completed", "succeeded", "failed"]:
    provider_status = _first_nested_text(payload, "status", "taskStatus", "state").casefold()
    status_map = {
        "pending": "queued",
        "queued": "queued",
        "scheduled": "queued",
        "running": "queued",
        "in progress": "queued",
        "active": "queued",
        "completed": "completed",
        "complete": "completed",
        "succeeded": "succeeded",
        "success": "succeeded",
        "failed": "failed",
        "failure": "failed",
        "error": "failed",
    }
    if provider_status in status_map:
        return cast(Literal["queued", "completed", "succeeded", "failed"], status_map[provider_status])

    counts = _status_counts(payload)
    if counts["failed"]:
        return "failed"
    if counts["active"]:
        return "queued"
    if counts["completed"]:
        return "completed"
    raise NCentralRmmError("N-central task status response was malformed")


def _status_counts(payload: object) -> dict[str, int]:
    counts = {"active": 0, "completed": 0, "failed": 0}
    if not isinstance(payload, Mapping):
        return counts
    raw_counts = payload.get("statusCounts")
    if not isinstance(raw_counts, Mapping):
        data = payload.get("data")
        raw_counts = data.get("statusCounts") if isinstance(data, Mapping) else None
    if not isinstance(raw_counts, Mapping):
        return counts
    for key, value in raw_counts.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        normalized = str(key).casefold().replace("_", " ").replace("-", " ")
        bucket = (
            "failed"
            if any(token in normalized for token in ("fail", "error"))
            else "completed"
            if "complete" in normalized
            else "active"
            if any(token in normalized for token in ("pending", "queue", "schedul", "run", "progress", "active"))
            else None
        )
        if bucket:
            counts[bucket] += max(0, int(value))
    return counts


def _in_scope(row: Mapping[str, Any], org_unit_ids: tuple[int, ...]) -> bool:
    value = row.get("orgUnitId", row.get("org_unit_id"))
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return False
    try:
        return int(value) in org_unit_ids
    except (TypeError, ValueError):
        return False


def _safe_value(value: object) -> object | None:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
        return value[:20]
    return None


def _severity(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip().casefold()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"state-{int(value)}"
    return "unknown"


def _validate_script_request(script_id: str, device_id: str, arguments: dict[str, str]) -> None:
    for label, value in (("script", script_id), ("device", device_id)):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > MAX_ID_LENGTH
            or any(ord(character) < 32 or character.isspace() for character in value)
        ):
            raise NCentralRmmError(f"N-central {label} ID is invalid")
    if not isinstance(arguments, dict) or len(arguments) > MAX_ARGUMENTS:
        raise NCentralRmmError("N-central script arguments are limited to 20 entries")
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or len(key) > MAX_TEXT_LENGTH
        or len(value) > MAX_TEXT_LENGTH
        or any(ord(character) < 32 for character in key + value)
        for key, value in arguments.items()
    ):
        raise NCentralRmmError("N-central script arguments must be bounded text")


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NCentralRmmError("N-central base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise NCentralRmmError("N-central base URL must not contain credentials or query data")
    return value.strip().rstrip("/")


def _safe_endpoint(value: str) -> str:
    parts = value.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise NCentralRmmError("N-central endpoint is invalid")
    if any(not all(character.isalnum() or character in {"-", "_"} for character in part) for part in parts):
        raise NCentralRmmError("N-central endpoint contains unsafe characters")
    return "/".join(parts)


__all__ = ["NCentralRmmAdapter", "NCentralRmmError"]
