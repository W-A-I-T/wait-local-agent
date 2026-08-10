"""Bounded N-able N-sight RMM Data Extraction API adapter.

N-sight exposes a documented XML Data Extraction API. WAIT uses only the
documented client, site, server, workstation, failing-check, and bounded patch
services here. A local WAIT-client-to-N-sight-client map is mandatory; returned
site, device, alert, and patch records are filtered to that mapping before
entering the shared RMM contract.
The provider's API key is required by the documented query contract but is
never accepted in action payloads, returned in errors, or persisted in audit
records.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree as DefusedElementTree  # type: ignore[import-untyped]

from wait_local_agent.config import Settings
from wait_local_agent.rmm import (
    RmmAlert,
    RmmDevice,
    RmmInventoryProvider,
    RmmScript,
    RmmScriptExecution,
    RmmScriptPreview,
)

MAX_SITES = 25
MAX_DEVICES = 100
MAX_ALERTS = 100
MAX_PATCHES = 100
MAX_PATCH_IDS = 20
MAX_TEXT_LENGTH = 500


class NSightRmmError(Exception):
    """Safe, operator-facing N-sight adapter error."""


@dataclass(frozen=True)
class _Site:
    site_id: int
    name: str


class NSightRmmAdapter(RmmInventoryProvider):
    """Normalize documented N-sight inventory into the shared RMM contract."""

    adapter_id = "n-sight"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        sites = self._list_sites(client_id)
        devices: list[RmmDevice] = []
        for site in sites:
            for service, element_name, category in (
                ("list_servers", "server", "server"),
                ("list_workstations", "workstation", "workstation"),
            ):
                root = self._request(service, {"siteid": str(site.site_id)}, client_id=client_id)
                for row in root.iter(element_name):
                    device_id = _positive_id(
                        _text(row, "serverid" if element_name == "server" else "workstationid")
                    )
                    if device_id is None:
                        continue
                    provider_id = f"{element_name}:{device_id}"
                    attributes = {
                        "provider_id": device_id,
                        "site_id": site.site_id,
                        "site_name": site.name,
                        "online": _text(row, "online"),
                        "status_247": _text(row, "status_247"),
                        "dsc_status": _text(row, "dsc_status"),
                        "missed_247": _text(row, "missed_247"),
                        "os": _text(row, "os"),
                        "agent_version": _text(row, "agent_version"),
                        "ip": _text(row, "ip"),
                        "serial": _text(row, "device_serial"),
                    }
                    devices.append(
                        RmmDevice(
                            provider_id,
                            _bounded_text(_text(row, "name") or provider_id),
                            category,
                            {key: value for key, value in attributes.items() if value not in ("", None)},
                        )
                    )
                    if len(devices) >= MAX_DEVICES:
                        return devices
        return devices

    def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
        provider_client_id = self._client_provider_id(client_id)
        root = self._request(
            "list_failing_checks",
            {"clientid": str(provider_client_id), "check_type": "checks"},
            client_id=client_id,
        )
        return _failing_check_alerts(root, provider_client_id)[:MAX_ALERTS]

    def list_patches(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read documented patch inventory only after a mapped-device recheck."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "patch_list_all",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return _patch_records(root)[:MAX_PATCHES]

    def approve_patches(
        self,
        device_id: str,
        patch_ids: list[str],
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Approve existing patches only after scope and inventory rechecks."""

        if not self.settings.allow_write_actions:
            raise NSightRmmError(
                "N-sight patch approval is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
            )
        normalized_ids = _patch_id_list(patch_ids)
        available_ids = {
            str(item["patch_id"])
            for item in self.list_patches(device_id, client_id=client_id)
            if isinstance(item.get("patch_id"), int)
        }
        if any(patch_id not in available_ids for patch_id in normalized_ids):
            raise NSightRmmError("N-sight patch approval includes a patch outside the device scope")
        root = self._request(
            "patch_approve",
            {
                "deviceid": str(_device_numeric_id(device_id)),
                "patchids": ",".join(normalized_ids),
            },
            client_id=client_id,
        )
        return {
            "status": "accepted",
            "message": _bounded_text(
                _text(root, "msg") or "N-sight accepted the patch approval request."
            ),
            "device_id": device_id,
            "patch_ids": normalized_ids,
        }

    def reprocess_patches(
        self,
        device_id: str,
        patch_ids: list[str],
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Request documented patch reprocessing after scope rechecks."""

        if not self.settings.allow_write_actions:
            raise NSightRmmError(
                "N-sight patch reprocessing is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
            )
        normalized_ids = _patch_id_list(patch_ids)
        available_ids = {
            str(item["patch_id"])
            for item in self.list_patches(device_id, client_id=client_id)
            if isinstance(item.get("patch_id"), int)
        }
        if any(patch_id not in available_ids for patch_id in normalized_ids):
            raise NSightRmmError("N-sight patch reprocessing includes a patch outside the device scope")
        root = self._request(
            "patch_reprocess",
            {
                "deviceid": str(_device_numeric_id(device_id)),
                "patchids": ",".join(normalized_ids),
            },
            client_id=client_id,
        )
        return {
            "status": "accepted",
            "message": _bounded_text(
                _text(root, "msg") or "N-sight accepted the patch reprocessing request."
            ),
            "device_id": device_id,
            "patch_ids": normalized_ids,
        }

    def list_scripts(self, client_id: str | None = None) -> list[RmmScript]:
        del client_id
        return []

    def preview_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptPreview:
        del client_id
        return RmmScriptPreview(
            script_id=script_id,
            device_id=device_id,
            arguments=dict(arguments),
            status="blocked",
            message="N-sight script execution is unavailable; no documented write contract is configured",
        )

    def execute_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        del client_id
        return RmmScriptExecution(
            script_id=script_id,
            device_id=device_id,
            status="blocked",
            message="N-sight script execution is unavailable; no documented write contract is configured",
        )

    def get_execution(
        self,
        execution_id: str,
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        del client_id
        return RmmScriptExecution(
            script_id="",
            device_id="",
            status="blocked",
            message="N-sight execution lookup is unavailable; no documented execution contract is configured",
            execution_id=execution_id,
        )

    def _list_sites(self, client_id: str | None) -> list[_Site]:
        client_provider_id = self._client_provider_id(client_id)
        root = self._request(
            "list_sites",
            {"clientid": str(client_provider_id)},
            client_id=client_id,
        )
        sites: list[_Site] = []
        for row in root.iter("site"):
            site_id = _positive_id(_text(row, "siteid"))
            if site_id is None:
                continue
            sites.append(_Site(site_id, _bounded_text(_text(row, "name") or str(site_id))))
            if len(sites) >= MAX_SITES:
                break
        return sites

    def _request(
        self,
        service: str,
        params: Mapping[str, str],
        *,
        client_id: str | None,
    ) -> Any:
        self._client_provider_id(client_id)
        if not self.settings.allow_http_probing:
            raise NSightRmmError(
                "N-sight live calls are blocked until WAIT_ALLOW_HTTP_PROBING=true"
            )
        base_url = _api_url(self.settings.n_sight_base_url)
        api_key = self.settings.n_sight_api_key.strip()
        if not api_key:
            raise NSightRmmError("N-sight credentials are incomplete: WAIT_NSIGHT_API_KEY")
        query = {"apikey": api_key, "service": service, **params}
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(base_url, params=query)
        except httpx.HTTPError as exc:
            raise NSightRmmError("N-sight request failed before receiving a response") from exc
        if response.status_code == 401 or response.status_code == 403:
            raise NSightRmmError("N-sight request was unauthorized")
        if response.status_code == 429:
            raise NSightRmmError("N-sight request was rate limited")
        if response.status_code >= 400:
            raise NSightRmmError(f"N-sight request failed with HTTP {response.status_code}")
        try:
            root = DefusedElementTree.fromstring(response.text)
        except DefusedElementTree.ParseError as exc:
            raise NSightRmmError("N-sight returned malformed XML") from exc
        status = (root.attrib.get("status") or "OK").strip().lower()
        error = _bounded_text(_text(root, "message"))
        if status not in {"ok", "success"} or root.find(".//error") is not None:
            raise NSightRmmError(error or "N-sight returned an error response")
        return root

    def _client_provider_id(self, client_id: str | None) -> int:
        if not isinstance(client_id, str) or not client_id.strip():
            raise NSightRmmError("N-sight operations require an explicit tenant scope")
        try:
            mapping = json.loads(self.settings.n_sight_client_map_json or "{}")
        except json.JSONDecodeError as exc:
            raise NSightRmmError("WAIT_NSIGHT_CLIENT_MAP_JSON is malformed") from exc
        if not isinstance(mapping, Mapping):
            raise NSightRmmError("WAIT_NSIGHT_CLIENT_MAP_JSON must be an object")
        raw_id = mapping.get(client_id.strip())
        if isinstance(raw_id, bool):
            raise NSightRmmError("N-sight tenant client mapping is missing")
        try:
            provider_id = int(str(raw_id))
        except (TypeError, ValueError) as exc:
            raise NSightRmmError("N-sight tenant client mapping is missing") from exc
        if provider_id <= 0 or provider_id > 2_147_483_647:
            raise NSightRmmError("N-sight client IDs must be positive integers")
        return provider_id


def _api_url(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise NSightRmmError("N-sight base URL contains unsafe characters")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NSightRmmError("N-sight base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise NSightRmmError("N-sight base URL must not contain credentials or query data")
    base = value.strip().rstrip("/")
    return base if base.endswith("/api") else f"{base}/api/"


def _text(element: Any, child: str) -> str:
    value = element.findtext(child)
    return value.strip() if isinstance(value, str) else ""


def _failing_check_alerts(root: Any, provider_client_id: int) -> list[RmmAlert]:
    alerts: list[RmmAlert] = []
    for client in root.iter("client"):
        if _positive_id(_text(client, "clientid")) != provider_client_id:
            continue
        for site in client.findall("site"):
            for element_name, container_name, category in (
                ("workstation", "workstations", "workstation"),
                ("server", "servers", "server"),
            ):
                container = site.find(container_name)
                if container is None:
                    continue
                for device in container.findall(element_name):
                    device_id = _positive_id(_text(device, "id"))
                    if device_id is None:
                        continue
                    scoped_device_id = f"{category}:{device_id}"
                    device_name = _bounded_text(_text(device, "name") or scoped_device_id)
                    for state in ("offline", "overdue", "unreachable"):
                        state_node = device.find(state)
                        if state_node is None:
                            continue
                        description = _bounded_text(_text(state_node, "description") or state)
                        alerts.append(
                            RmmAlert(
                                alert_id=f"{scoped_device_id}:{state}",
                                device_id=scoped_device_id,
                                severity="high",
                                title=_bounded_text(
                                    f"N-sight {device_name} {state}: {description}"
                                ),
                                status="open",
                            )
                        )
                    failed_checks = device.find("failed_checks")
                    if failed_checks is None:
                        continue
                    for check in failed_checks.findall("check"):
                        check_id = _positive_id(_text(check, "checkid"))
                        if check_id is None:
                            continue
                        description = _bounded_text(_text(check, "description") or "failed check")
                        output = _bounded_text(_text(check, "formatted_output"))
                        detail = f": {output}" if output else ""
                        alerts.append(
                            RmmAlert(
                                alert_id=f"{scoped_device_id}:check:{check_id}",
                                device_id=scoped_device_id,
                                severity="high",
                                title=_bounded_text(
                                    f"N-sight {device_name} failed check: {description}{detail}"
                                ),
                                status="open",
                            )
                        )
    return alerts


def _patch_records(root: Any) -> list[dict[str, object]]:
    patches: list[dict[str, object]] = []
    for patch in root.iter("patch"):
        patch_id = _positive_id(_text(patch, "patchid"))
        if patch_id is None:
            continue
        patches.append(
            {
                "patch_id": patch_id,
                "policy": _optional_integer(_text(patch, "policy")),
                "status": _optional_integer(_text(patch, "status")),
                "status_label": _bounded_text(_text(patch, "statusLabel")),
                "title": _bounded_text(_text(patch, "patchTitle")),
                "product": _bounded_text(_text(patch, "product")),
                "severity": _optional_integer(_text(patch, "severity")),
                "severity_label": _bounded_text(_text(patch, "severityLabel")),
                "release_date": _bounded_text(_text(patch, "releaseDateText")),
                "install_date": _bounded_text(_text(patch, "installDateText")),
                "deployable": _optional_flag(_text(patch, "deployable")),
                "uninstallable": _optional_flag(_text(patch, "uninstallable")),
            }
        )
    return patches


def _device_numeric_id(value: str) -> int:
    if not isinstance(value, str):
        raise NSightRmmError("N-sight patch reads require a mapped server or workstation ID")
    category, separator, raw_id = value.strip().partition(":")
    if category not in {"server", "workstation"} or not separator:
        raise NSightRmmError("N-sight patch reads require a mapped server or workstation ID")
    device_id = _positive_id(raw_id)
    if device_id is None:
        raise NSightRmmError("N-sight device ID must be a positive integer")
    return device_id


def _patch_id_list(values: list[str]) -> list[str]:
    if not isinstance(values, list) or not values or len(values) > MAX_PATCH_IDS:
        raise NSightRmmError("N-sight patch approval requires 1 to 20 patch IDs")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise NSightRmmError("N-sight patch IDs must be positive integers")
        patch_id = _positive_id(value.strip())
        if patch_id is None:
            raise NSightRmmError("N-sight patch IDs must be positive integers")
        if str(patch_id) not in normalized:
            normalized.append(str(patch_id))
    return normalized


def _optional_integer(value: str) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if 0 <= parsed <= 2_147_483_647 else None


def _optional_flag(value: str) -> bool | None:
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def _positive_id(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 < parsed <= 2_147_483_647 else None


def _bounded_text(value: str) -> str:
    normalized = " ".join(value.split())
    return normalized[:MAX_TEXT_LENGTH]


__all__ = ["NSightRmmAdapter", "NSightRmmError"]
