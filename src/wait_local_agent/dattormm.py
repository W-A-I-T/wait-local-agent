"""Bounded Datto RMM API v2 adapter for the shared RMM contract.

Datto RMM uses OAuth bearer tokens and account-wide API access. WAIT therefore
requires an explicit local client-to-site map and uses a site-scoped endpoint
for device and alert inventory. Quick jobs use the documented device endpoint,
remain tenant-scoped, and are reachable only through the existing approval and
write-action gates.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, cast
from urllib.parse import quote, urlsplit

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

MAX_PAGE_SIZE = 250
MAX_ARGUMENTS = 20
MAX_ID_LENGTH = 120
MAX_TEXT_LENGTH = 500


class DattoRmmError(Exception):
    """Safe, operator-facing Datto RMM adapter error."""


class DattoRmmAdapter:
    """Datto RMM adapter with explicit WAIT tenant scoping and bounded writes."""

    adapter_id = "dattormm"

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
        site_uid = self._site_uid(client_id)
        payload = self._get(f"v2/site/{_path_segment(site_uid)}/devices", client_id=client_id)
        devices: list[RmmDevice] = []
        for row in _rows(payload, "devices", "items", "data", "results", "content"):
            if not _matches_scope(row, site_uid, "siteUid", "siteId", "site_id"):
                continue
            device_id = _first_text(row, "uid", "deviceUid", "id")
            if not device_id:
                continue
            name = _first_text(row, "hostname", "deviceName", "name", "description") or device_id
            category = _first_text(row, "deviceClass", "deviceType", "type")
            attributes = {
                key: row[key]
                for key in (
                    "uid",
                    "siteUid",
                    "deviceClass",
                    "hostname",
                    "operatingSystem",
                    "online",
                    "lastSeen",
                )
                if key in row and _safe_attribute(row[key]) is not None
            }
            devices.append(RmmDevice(device_id, name, category, attributes))
        return devices[:MAX_PAGE_SIZE]

    def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
        site_uid = self._site_uid(client_id)
        payload = self._get(
            f"v2/site/{_path_segment(site_uid)}/alerts/open", client_id=client_id
        )
        alerts: list[RmmAlert] = []
        for row in _rows(payload, "alerts", "items", "data", "results", "content"):
            if not _matches_scope(row, site_uid, "siteUid", "siteId", "site_id"):
                continue
            alert_id = _first_text(row, "alertUid", "uid", "id")
            device_id = _first_text(row, "deviceUid", "deviceId", "nodeId")
            nested_device = row.get("device")
            if not device_id and isinstance(nested_device, Mapping):
                device_id = _first_text(nested_device, "uid", "deviceUid", "id")
            if not alert_id or not device_id:
                continue
            alerts.append(
                RmmAlert(
                    alert_id=alert_id,
                    device_id=device_id,
                    severity=_first_text(row, "severity", "priority") or "unknown",
                    title=_first_text(row, "message", "name", "description", "alertType")
                    or "Datto RMM alert",
                    status="open",
                )
            )
        return alerts[:MAX_PAGE_SIZE]

    def list_scripts(self, client_id: str | None = None) -> list[RmmScript]:
        self._site_uid(client_id)
        payload = self._get("v2/account/components", client_id=client_id)
        scripts: list[RmmScript] = []
        for row in _rows(payload, "components", "items", "data", "results", "content"):
            script_id = _first_text(row, "uid", "componentUid", "id")
            if not script_id:
                continue
            scripts.append(
                RmmScript(
                    script_id=script_id,
                    name=_first_text(row, "name", "componentName", "displayName") or script_id,
                    description=_first_text(row, "description"),
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
            raise DattoRmmError("Datto RMM device is outside the tenant scope")
        scripts = self.list_scripts(client_id)
        if not any(script.script_id == script_id for script in scripts):
            raise DattoRmmError("Datto RMM component was not found")
        return RmmScriptPreview(
            script_id=script_id,
            device_id=device_id,
            arguments=dict(arguments),
            status="preview",
            message=(
                "Datto RMM device and component are validated; execution requires "
                "a completed technician approval"
                if self.settings.allow_write_actions
                else "Datto RMM device and component are validated; execution is blocked "
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
        self._site_uid(client_id)
        if not self.settings.allow_write_actions:
            return RmmScriptExecution(
                script_id=script_id,
                device_id=device_id,
                status="blocked",
                message="Datto RMM quick-job execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true",
            )
        # Validate both identifiers against the operator-controlled tenant map
        # before making the write. The smart-action layer calls this only after
        # a persisted approval has completed.
        self.preview_script(script_id, device_id, arguments, client_id=client_id)
        payload = {
            "jobName": "WAIT approved quick job",
            "jobComponent": {
                "componentUid": script_id.strip(),
                "variables": [
                    {"name": key, "value": value}
                    for key, value in sorted(arguments.items())
                ],
            },
        }
        response = self._request(
            "PUT",
            f"v2/device/{_path_segment(device_id)}/quickjob",
            client_id=client_id,
            json_body=payload,
            include_page_size=False,
        )
        job_id = _first_text(response, "uid", "jobUid", "id")
        if not job_id:
            raise DattoRmmError("Datto RMM quick-job response was malformed")
        if self.store is not None and client_id is not None:
            self.store.record_rmm_execution_scope(
                job_id,
                self.adapter_id,
                script_id.strip(),
                device_id.strip(),
                client_id,
            )
        return RmmScriptExecution(
            script_id=script_id,
            device_id=device_id,
            status="queued",
            message="Datto RMM quick job was queued",
            execution_id=job_id,
        )

    def get_execution(
        self,
        execution_id: str,
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        _validate_id(execution_id, "execution ID")
        self._site_uid(client_id)
        scope = None
        if self.store is not None and client_id is not None:
            scope = self.store.get_rmm_execution_scope(
                execution_id,
                self.adapter_id,
                client_id,
            )
            if scope is None:
                raise DattoRmmError("Datto RMM execution is outside the tenant scope")
        response = self._request(
            "GET",
            f"v2/job/{_path_segment(execution_id)}",
            client_id=client_id,
            include_page_size=False,
        )
        provider_status = _first_text(response, "status").casefold()
        status_map = {
            "active": "queued",
            "queued": "queued",
            "completed": "completed",
            "succeeded": "succeeded",
            "failed": "failed",
        }
        status_value = status_map.get(provider_status)
        if status_value is None:
            raise DattoRmmError("Datto RMM job response was malformed")
        status = cast(
            Literal["blocked", "queued", "completed", "succeeded", "failed"],
            status_value,
        )
        return RmmScriptExecution(
            script_id=scope.script_id if scope is not None else "",
            device_id=scope.device_id if scope is not None else "",
            status=status,
            message=(
                "Datto RMM job is active"
                if status == "queued"
                else "Datto RMM job completed; the API does not expose component output"
                if status == "completed"
                else f"Datto RMM job status: {status}"
            ),
            execution_id=execution_id,
        )

    def _get(self, endpoint: str, *, client_id: str | None) -> object:
        return self._request("GET", endpoint, client_id=client_id)

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        client_id: str | None,
        json_body: object | None = None,
        include_page_size: bool = True,
    ) -> object:
        self._site_uid(client_id)
        if not self.settings.allow_http_probing:
            raise DattoRmmError(
                "Datto RMM live calls are blocked until WAIT_ALLOW_HTTP_PROBING=true"
            )
        if not self.settings.datto_rmm_access_token or not self.settings.datto_rmm_base_url:
            raise DattoRmmError(
                "Datto RMM credentials are incomplete: WAIT_DATTORMM_BASE_URL and "
                "WAIT_DATTORMM_ACCESS_TOKEN"
            )
        base_url = _safe_base_url(self.settings.datto_rmm_base_url)
        safe_endpoint = _safe_endpoint(endpoint)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                request_kwargs: dict[str, Any] = {
                    "headers": {
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.settings.datto_rmm_access_token}",
                    },
                }
                if include_page_size:
                    request_kwargs["params"] = {"max": self._page_size()}
                if json_body is not None:
                    request_kwargs["json"] = json_body
                response = client.request(method, f"{base_url}/{safe_endpoint}", **request_kwargs)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise DattoRmmError("Datto RMM request failed before receiving a response") from exc
        except httpx.HTTPError as exc:
            raise DattoRmmError("Datto RMM request failed") from exc
        if response.status_code >= 400:
            if response.status_code in {401, 403}:
                raise DattoRmmError("Datto RMM request was unauthorized")
            raise DattoRmmError(f"Datto RMM request failed with HTTP {response.status_code}")
        if response.status_code == 204:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise DattoRmmError("Datto RMM returned malformed JSON") from exc

    def _site_uid(self, client_id: str | None) -> str:
        if not client_id or not client_id.strip():
            raise DattoRmmError("Datto RMM operations require an explicit tenant scope")
        try:
            mapping = json.loads(self.settings.datto_rmm_site_map_json or "{}")
        except ValueError as exc:
            raise DattoRmmError("WAIT_DATTORMM_SITE_MAP_JSON is malformed") from exc
        if not isinstance(mapping, dict):
            raise DattoRmmError("WAIT_DATTORMM_SITE_MAP_JSON must be an object")
        value = mapping.get(client_id.strip())
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise DattoRmmError("Datto RMM tenant site mapping is missing")
        site_uid = str(value).strip()
        _validate_id(site_uid, "Datto RMM site mapping")
        return site_uid

    def _page_size(self) -> int:
        return max(1, min(int(self.settings.datto_rmm_page_size), MAX_PAGE_SIZE))


def _rows(payload: object, *keys: str) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)][:MAX_PAGE_SIZE]
    if not isinstance(payload, Mapping):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)][:MAX_PAGE_SIZE]
        if isinstance(value, Mapping):
            nested = _rows(value, *keys)
            if nested:
                return nested
    return []


def _first_text(row: object, *keys: str) -> str:
    if not isinstance(row, Mapping):
        return ""
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (str, int, float)):
            text = str(value).strip()
            if text:
                return text[:MAX_TEXT_LENGTH]
    return ""


def _safe_attribute(value: object) -> object | None:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value if value is None or not isinstance(value, str) else value[:MAX_TEXT_LENGTH]
    return None


def _matches_scope(row: Mapping[str, Any], site_uid: str, *keys: str) -> bool:
    values = [row.get(key) for key in keys if key in row]
    return not values or any(str(value).strip() == site_uid for value in values if value is not None)


def _validate_script_request(script_id: str, device_id: str, arguments: dict[str, str]) -> None:
    _validate_id(script_id, "script ID")
    _validate_id(device_id, "device ID")
    if len(arguments) > MAX_ARGUMENTS:
        raise DattoRmmError("Datto RMM script arguments are too numerous")
    for key, value in arguments.items():
        _validate_id(str(key), "script argument name")
        if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
            raise DattoRmmError("Datto RMM script argument values are invalid")


def _validate_id(value: str, label: str) -> None:
    if not value.strip() or len(value.strip()) > MAX_ID_LENGTH:
        raise DattoRmmError(f"{label} is invalid")


def _path_segment(value: str) -> str:
    _validate_id(value, "Datto RMM path segment")
    return quote(value.strip(), safe="-_.~")


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DattoRmmError("Datto RMM base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DattoRmmError("Datto RMM base URL must not contain credentials or query data")
    return value.strip().rstrip("/")


def _safe_endpoint(value: str) -> str:
    parts = value.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise DattoRmmError("Datto RMM endpoint is invalid")
    if any(not all(character.isalnum() or character in {"-", "_", ".", "%"} for character in part) for part in parts):
        raise DattoRmmError("Datto RMM endpoint contains unsafe characters")
    return "/".join(parts)


__all__ = ["DattoRmmAdapter", "DattoRmmError"]
