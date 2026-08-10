"""Bounded N-able N-sight RMM Data Extraction API adapter.

N-sight exposes a documented XML Data Extraction API. WAIT uses only the
documented client, site, server, workstation, check-inventory,
    performance-history, asset-details, failing-check, outage, antivirus-threat,
    monitoring-details, backup-session, bounded patch, check-configuration,
    antivirus-scan, antivirus-scan-start, antivirus-scan-cancel,
    antivirus-quarantine, antivirus-product, antivirus-definition, and automated-task
    services here. A local
WAIT-client-to-N-sight-client map is mandatory; returned site, device, alert,
outage, backup-session, and patch records are filtered to that mapping before
entering the shared RMM contract.
The provider's API key is required by the documented query contract but is
never accepted in action payloads, returned in errors, or persisted in audit
records.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree as DefusedElementTree  # type: ignore[import-untyped]

from wait_local_agent.config import Settings
from wait_local_agent.reports.renderers import redact_value
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
MAX_CHECKS = 100
MAX_PERFORMANCE_RECORDS = 100
MAX_PERFORMANCE_POINTS = 100
MAX_ASSET_ITEMS = 100
MAX_MONITORING_RECORDS = 100
MAX_PATCHES = 100
MAX_PATCH_IDS = 20
MAX_ANTIVIRUS_THREATS = 100
MAX_ANTIVIRUS_PRODUCTS = 100
MAX_ANTIVIRUS_DEFINITIONS = 20
MAX_OUTAGES = 100
MAX_BACKUP_SESSIONS = 100
MAX_BACKUP_CHECKS = 25
MAX_BACKUP_HISTORY_DAYS = 60
MAX_CHECK_CONFIG_DEPTH = 6
MAX_CHECK_CONFIG_FIELDS = 50
MAX_CHECK_CONFIG_LIST_ITEMS = 25
MAX_ANTIVIRUS_SCANS = 50
MAX_ANTIVIRUS_SCAN_THREATS = 25
MAX_ANTIVIRUS_QUARANTINE = 100
MAX_ANTIVIRUS_QUARANTINE_IDS = 20
MAX_TEXT_LENGTH = 500
MAX_METRIC_INTEGER = 9_223_372_036_854_775_807
PATCH_POLICY_SERVICES = {
    "do_nothing": "patch_do_nothing",
    "ignore": "patch_ignore",
    "inherit": "patch_inherit",
    "retry": "patch_retry",
}


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

    def list_supported_antivirus_products(
        self,
        *,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read the documented supported-antivirus product catalog in tenant scope."""

        root = self._request("list_supported_av_products", {}, client_id=client_id)
        return _antivirus_product_records(root)[:MAX_ANTIVIRUS_PRODUCTS]

    def list_antivirus_definitions(
        self,
        product_id: str,
        *,
        max_results: int = MAX_ANTIVIRUS_DEFINITIONS,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read recent definitions only for a supported mapped antivirus product."""

        if (
            not isinstance(product_id, str)
            or not product_id.strip()
            or len(product_id.strip()) > MAX_TEXT_LENGTH
        ):
            raise NSightRmmError(
                "N-sight antivirus product ID must be a non-empty string of at most 500 characters"
            )
        if (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or not 1 <= max_results <= MAX_ANTIVIRUS_DEFINITIONS
        ):
            raise NSightRmmError("N-sight antivirus definitions require 1 to 20 results")
        clean_product_id = product_id.strip()
        products = self.list_supported_antivirus_products(client_id=client_id)
        if not any(product.get("id") == clean_product_id for product in products):
            raise NSightRmmError(
                "N-sight antivirus product is not in the supported product catalog"
            )
        root = self._request(
            "list_av_definitions",
            {"product": clean_product_id, "max_results": str(max_results)},
            client_id=client_id,
        )
        return _antivirus_definition_records(root)[:max_results]

    def list_checks(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read documented check inventory only after a mapped-device recheck."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "list_checks",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return _check_records(root)[:MAX_CHECKS]

    def get_check_config(
        self,
        device_id: str,
        check_id: int,
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Read one documented check configuration after a mapped-device recheck."""

        _device_numeric_id(device_id)
        numeric_check_id = _positive_id(str(check_id))
        if numeric_check_id is None:
            raise NSightRmmError("N-sight check ID must be a positive integer")
        checks = self.list_checks(device_id, client_id=client_id)
        matching = next(
            (check for check in checks if check.get("check_id") == numeric_check_id),
            None,
        )
        if matching is None:
            raise NSightRmmError("N-sight check is outside the mapped device scope")
        root = self._request(
            "list_check_config",
            {"checkid": str(numeric_check_id)},
            client_id=client_id,
        )
        check_config = root.find(".//check_config")
        if check_config is None:
            raise NSightRmmError("N-sight returned malformed check configuration")
        configuration = _xml_config_value(check_config, depth=0)
        if not isinstance(configuration, dict):
            raise NSightRmmError("N-sight returned malformed check configuration")
        return cast(
            dict[str, object],
            redact_value(
                {
                    "device_id": device_id,
                    "check_id": numeric_check_id,
                    "check_type": matching.get("check_type"),
                    "description": matching.get("description"),
                    "configuration": configuration,
                }
            )
        )

    def list_performance_history(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read bounded documented performance history for one mapped device."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "list_performance_history",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return _performance_history_records(root)[:MAX_PERFORMANCE_RECORDS]

    def list_asset_details(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Read documented asset details and bounded hardware/software inventory."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "list_device_asset_details",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return _asset_detail_records(root)

    def list_monitoring_details(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Read bounded documented monitoring details for one mapped device."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "list_device_monitoring_details",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return _monitoring_detail_records(root)

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

    def list_antivirus_threats(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read documented managed-antivirus threats for one mapped device."""

        _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "list_mav_threats",
            {"deviceid": str(_device_numeric_id(device_id)), "v": "2"},
            client_id=client_id,
        )
        return _antivirus_threat_records(root)[:MAX_ANTIVIRUS_THREATS]

    def list_antivirus_quarantine(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read documented managed-antivirus quarantine records for one mapped device."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "mav_quarantine_list",
            {"deviceid": str(numeric_device_id), "v": "2"},
            client_id=client_id,
        )
        return _antivirus_quarantine_records(root)[:MAX_ANTIVIRUS_QUARANTINE]

    def release_antivirus_quarantine(
        self,
        device_id: str,
        guids: list[str],
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Release mapped quarantine items through the documented service."""

        return self._mutate_antivirus_quarantine(
            device_id,
            guids,
            service="mav_quarantine_release",
            operation="release",
            client_id=client_id,
        )

    def remove_antivirus_quarantine(
        self,
        device_id: str,
        guids: list[str],
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Remove mapped quarantine items through the documented service."""

        return self._mutate_antivirus_quarantine(
            device_id,
            guids,
            service="mav_quarantine_remove",
            operation="remove",
            client_id=client_id,
        )

    def _mutate_antivirus_quarantine(
        self,
        device_id: str,
        guids: list[str],
        *,
        service: str,
        operation: str,
        client_id: str | None,
    ) -> dict[str, object]:
        if not self.settings.allow_write_actions:
            raise NSightRmmError(
                f"N-sight antivirus quarantine {operation} is blocked until "
                "WAIT_ALLOW_WRITE_ACTIONS=true"
            )
        normalized_guids = _quarantine_guid_list(guids)
        available_guids = {
            str(item["quarantine_id"])
            for item in self.list_antivirus_quarantine(device_id, client_id=client_id)
            if isinstance(item.get("quarantine_id"), str)
        }
        if any(guid not in available_guids for guid in normalized_guids):
            raise NSightRmmError(
                f"N-sight quarantine {operation} includes an item outside the device scope"
            )
        root = self._request(
            service,
            {
                "deviceid": str(_device_numeric_id(device_id)),
                "guids": ",".join(normalized_guids),
            },
            client_id=client_id,
        )
        return {
            "status": "accepted",
            "operation": operation,
            "device_id": device_id,
            "guids": normalized_guids,
            "message": _bounded_text(
                _text(root, "msg")
                or f"N-sight accepted the antivirus quarantine {operation} request."
            ),
        }

    def list_antivirus_scans(
        self,
        device_id: str,
        *,
        include_details: bool = False,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read documented managed-antivirus scan history for one mapped device."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "list_mav_scans",
            {
                "deviceid": str(numeric_device_id),
                "details": "YES" if include_details else "NO",
                "v": "2",
            },
            client_id=client_id,
        )
        return _antivirus_scan_records(root, include_details=include_details)[:MAX_ANTIVIRUS_SCANS]

    def start_antivirus_scan(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Start one documented managed-antivirus scan for a mapped device."""

        if not self.settings.allow_write_actions:
            raise NSightRmmError(
                "N-sight antivirus scan start is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
            )
        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "mav_scan_start",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return {
            "status": "accepted",
            "device_id": device_id,
            "message": _bounded_text(
                _text(root, "msg") or "N-sight accepted the antivirus scan request."
            ),
        }

    def cancel_antivirus_scan(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Cancel one documented managed-antivirus scan for a mapped device."""

        if not self.settings.allow_write_actions:
            raise NSightRmmError(
                "N-sight antivirus scan cancellation is blocked until "
                "WAIT_ALLOW_WRITE_ACTIONS=true"
            )
        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "mav_scan_cancel",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return {
            "status": "accepted",
            "device_id": device_id,
            "message": _bounded_text(
                _text(root, "msg") or "N-sight accepted the antivirus scan cancellation."
            ),
        }

    def list_outages(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read documented open/recent outages for one mapped device."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "list_outages",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return _outage_records(root)[:MAX_OUTAGES]

    def list_backup_sessions(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Read documented Backup & Recovery sessions for one mapped device."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "list_mob_sessions",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return _backup_session_records(root)[:MAX_BACKUP_SESSIONS]

    def list_backup_history(
        self,
        device_id: str,
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Read documented 60-day backup-check history for one mapped device."""

        numeric_device_id = _device_numeric_id(device_id)
        mapped_devices = self.list_devices(client_id)
        if not any(device.device_id == device_id for device in mapped_devices):
            raise NSightRmmError("N-sight device is outside the mapped client scope")
        root = self._request(
            "list_backup_history",
            {"deviceid": str(numeric_device_id)},
            client_id=client_id,
        )
        return _backup_history_records(root)

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

    def apply_patch_policy(
        self,
        device_id: str,
        patch_ids: list[str],
        operation: str,
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Apply one documented, allowlisted patch policy operation."""

        service = PATCH_POLICY_SERVICES.get(operation)
        if service is None:
            raise NSightRmmError("N-sight patch policy operation is not supported")
        if not self.settings.allow_write_actions:
            raise NSightRmmError(
                "N-sight patch policy is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
            )
        normalized_ids = _patch_id_list(patch_ids)
        available_ids = {
            str(item["patch_id"])
            for item in self.list_patches(device_id, client_id=client_id)
            if isinstance(item.get("patch_id"), int)
        }
        if any(patch_id not in available_ids for patch_id in normalized_ids):
            raise NSightRmmError("N-sight patch policy includes a patch outside the device scope")
        root = self._request(
            service,
            {
                "deviceid": str(_device_numeric_id(device_id)),
                "patchids": ",".join(normalized_ids),
            },
            client_id=client_id,
        )
        return {
            "status": "accepted",
            "operation": operation,
            "message": _bounded_text(
                _text(root, "msg") or f"N-sight accepted the {operation} patch policy request."
            ),
            "device_id": device_id,
            "patch_ids": normalized_ids,
        }

    def run_task_now(
        self,
        device_id: str,
        check_id: int,
        *,
        client_id: str | None = None,
    ) -> dict[str, object]:
        """Run one mapped automated task through the documented task service.

        N-sight exposes only the automated-task check ID to this mutation. WAIT
        requires the caller to provide the mapped device as well so the check
        can be re-read and proven to belong to the tenant-scoped device before
        the write is sent.
        """

        if not self.settings.allow_write_actions:
            raise NSightRmmError(
                "N-sight task execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true"
            )
        _device_numeric_id(device_id)
        numeric_check_id = _positive_id(str(check_id))
        if numeric_check_id is None:
            raise NSightRmmError("N-sight automated task ID must be a positive integer")
        checks = self.list_checks(device_id, client_id=client_id)
        matching = next(
            (check for check in checks if check.get("check_id") == numeric_check_id),
            None,
        )
        if matching is None:
            raise NSightRmmError("N-sight automated task is outside the mapped device scope")
        if matching.get("check_type") != 1023:
            raise NSightRmmError("N-sight check is not a documented automated task")
        root = self._request(
            "task_run_now",
            {"checkid": str(numeric_check_id)},
            client_id=client_id,
        )
        message = root.find(".//message")
        minutes = _optional_integer(message.attrib.get("time", "")) if message is not None else None
        if minutes is None:
            raise NSightRmmError("N-sight returned malformed automated-task response")
        return {
            "status": "accepted",
            "device_id": device_id,
            "check_id": numeric_check_id,
            "minutes_until_run": minutes,
            "message": _bounded_text(
                (message.text or "") if message is not None else ""
            ),
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


def _check_records(root: Any) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for check in root.iter("check"):
        check_id = _positive_id(_text(check, "checkid"))
        if check_id is None:
            continue
        checks.append(
            {
                "check_id": check_id,
                "uid": _optional_integer(_text(check, "uid")),
                "sync_status": _optional_integer(_text(check, "sync_status")),
                "description": _bounded_text(_text(check, "description")),
                "status_id": _optional_integer(_text(check, "statusid")),
                "date": _bounded_text(_text(check, "date")),
                "time": _bounded_text(_text(check, "time")),
                "utc_run": _bounded_text(_text(check, "utc_run")),
                "email_alerts": _optional_flag(_text(check, "email")),
                "sms_alerts": _optional_flag(_text(check, "sms")),
                "check_type": _optional_integer(_text(check, "check_type")),
                "dsc_247": _optional_integer(_text(check, "dsc_247")),
                "consecutive_fails": _optional_integer(
                    _text(check, "consecutive_fails")
                ),
            }
        )
        if len(checks) >= MAX_CHECKS:
            break
    return checks


def _xml_config_value(element: Any, *, depth: int) -> object:
    """Convert bounded provider XML configuration into redaction-friendly data."""

    if depth > MAX_CHECK_CONFIG_DEPTH:
        return "[truncated]"
    children = list(element)
    attributes = {
        _bounded_text(str(key)): _bounded_text(str(value))
        for key, value in list(element.attrib.items())[:MAX_CHECK_CONFIG_FIELDS]
    }
    if not children:
        text = _bounded_text(element.text or "")
        if attributes:
            return {"@attributes": attributes, "value": text}
        return text
    result: dict[str, object] = {}
    if attributes:
        result["@attributes"] = attributes
    for child in children[:MAX_CHECK_CONFIG_FIELDS]:
        key = _bounded_text(str(child.tag))
        if not key:
            continue
        value = _xml_config_value(child, depth=depth + 1)
        previous = result.get(key)
        if previous is None:
            result[key] = value
        elif isinstance(previous, list):
            if len(previous) < MAX_CHECK_CONFIG_LIST_ITEMS:
                previous.append(value)
        else:
            result[key] = [previous, value]
    return result


_PERFORMANCE_TARGET_FIELDS = {
    "bandwidth": ("name", "host"),
    "disk_load": ("disk",),
    "network_usage": ("adapter",),
}
_PERFORMANCE_THRESHOLD_FIELDS = {
    "bandwidth": ("receive", "transmit"),
    "disk_load": ("read_queue_length", "write_queue_length", "average_disk_time"),
    "cpu_queue": ("average_length",),
    "cpu_load": ("average_load",),
    "network_usage": ("average_usage",),
    "memory_usage": (
        "available_min",
        "average_pages",
        "average_page_file",
        "non_paged_pool",
        "average_commit",
    ),
}
_PERFORMANCE_HISTORY_FIELDS = {
    "start",
    "end",
    "receive",
    "transmit",
    "disk_time_average",
    "disk_time_max",
    "read_queue_average",
    "read_queue_max",
    "write_queue_average",
    "write_queue_max",
    "queue_average",
    "queue_max",
    "load_average",
    "load_max",
    "bandwidth",
    "total_average",
    "total_max",
    "transmit_average",
    "transmit_max",
    "receive_average",
    "receive_max",
    "available_average",
    "available_min",
    "commit_charge_average",
    "commit_charge_max",
    "page_faults_average",
    "page_faults_max",
    "file_usage_average",
    "file_usage_max",
    "non_paged",
    "total",
}


def _performance_history_records(root: Any) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for category, element_name in (
        ("bandwidth", "host"),
        ("disk_load", "disk"),
        ("cpu_queue", None),
        ("cpu_load", None),
        ("network_usage", "interface"),
        ("memory_usage", None),
    ):
        container = root.find(category)
        if container is None:
            continue
        elements = container.findall(element_name) if element_name else [container]
        for element in elements:
            check_id = _positive_id(_text(element, "check_id"))
            if check_id is None:
                continue
            target = {
                field: _bounded_text(_text(element, field))
                for field in _PERFORMANCE_TARGET_FIELDS.get(category, ())
                if _text(element, field)
            }
            thresholds = {
                field: _optional_number(_text(element, field))
                for field in _PERFORMANCE_THRESHOLD_FIELDS.get(category, ())
                if _text(element, field) and _optional_number(_text(element, field)) is not None
            }
            history = _performance_data_records(element.find("history"))
            records.append(
                {
                    "category": category,
                    "check_id": check_id,
                    "target": target,
                    "thresholds": thresholds,
                    "history": history,
                }
            )
            if len(records) >= MAX_PERFORMANCE_RECORDS:
                return records
    return records


def _performance_data_records(history: Any) -> list[dict[str, object]]:
    if history is None:
        return []
    records: list[dict[str, object]] = []
    for data in history.findall("data")[:MAX_PERFORMANCE_POINTS]:
        values: dict[str, object] = {}
        for child in list(data):
            if child.tag == "cpu":
                cpus = values.setdefault("cpus", [])
                if not isinstance(cpus, list) or len(cpus) >= 4:
                    continue
                cpu_id = _optional_integer(_text(child, "cpu_id"))
                if cpu_id is None:
                    continue
                cpus.append(
                    {
                        "cpu_id": cpu_id,
                        "load_average": _optional_number(_text(child, "load_average")),
                        "load_max": _optional_number(_text(child, "load_max")),
                    }
                )
                continue
            if child.tag not in _PERFORMANCE_HISTORY_FIELDS:
                continue
            raw = _text(data, child.tag)
            if not raw:
                continue
            values[child.tag] = (
                _bounded_text(raw)
                if child.tag in {"start", "end"}
                else _optional_number(raw)
            )
        if values:
            records.append(values)
    return records


_ASSET_DETAIL_FIELDS = (
    "client",
    "chassistype",
    "ip",
    "mac1",
    "mac2",
    "mac3",
    "user",
    "manufacturer",
    "model",
    "os",
    "osinstalldate",
    "serialnumber",
    "role",
    "servicepack",
    "ram",
    "scantime",
)
_ASSET_INTEGER_FIELDS = {"chassistype", "role", "servicepack", "ram"}


def _asset_detail_records(root: Any) -> dict[str, object]:
    details: dict[str, object] = {}
    for field in _ASSET_DETAIL_FIELDS:
        raw = _text(root, field)
        if not raw:
            continue
        if field in _ASSET_INTEGER_FIELDS:
            value = _optional_metric_integer(raw)
            if value is not None:
                details[field] = value
        else:
            details[field] = _bounded_text(raw)

    hardware: list[dict[str, object]] = []
    hardware_container = root.find("hardware")
    if hardware_container is not None:
        for item in hardware_container.findall("item")[:MAX_ASSET_ITEMS]:
            hardware_id = _positive_id(_text(item, "hardwareid"))
            if hardware_id is None:
                continue
            hardware.append(
                {
                    "hardware_id": hardware_id,
                    "name": _bounded_text(_text(item, "name")),
                    "type": _optional_integer(_text(item, "type")),
                    "manufacturer": _bounded_text(_text(item, "manufacturer")),
                    "details": _bounded_text(_text(item, "details")),
                    "status": _bounded_text(_text(item, "status")),
                    "deleted": _optional_flag(_text(item, "deleted")),
                    "modified": _optional_flag(_text(item, "modified")),
                }
            )

    software: list[dict[str, object]] = []
    software_container = root.find("software")
    if software_container is not None:
        for item in software_container.findall("item")[:MAX_ASSET_ITEMS]:
            software_id = _positive_id(_text(item, "softwareid"))
            if software_id is None:
                continue
            software.append(
                {
                    "software_id": software_id,
                    "name": _bounded_text(_text(item, "name")),
                    "version": _bounded_text(_text(item, "version")),
                    "install_date": _bounded_text(_text(item, "install_date")),
                    "type": _bounded_text(_text(item, "type")),
                    "deleted": _optional_flag(_text(item, "deleted")),
                    "modified": _optional_flag(_text(item, "modified")),
                }
            )
    return {"details": details, "hardware": hardware, "software": software}


_MONITORING_DEVICE_FIELDS = (
    "name",
    "description",
    "username",
    "guid",
    "os",
    "agent",
    "lastresponse",
    "lastboot",
)
_MONITORING_CHECK_TEXT_FIELDS = (
    "description",
    "checkstatus",
    "extra",
    "datetime",
    "servertime",
)
_MONITORING_CHECK_INTEGER_FIELDS = ("dsc_247", "consecutive_fails")
_MONITORING_CHECK_FLAG_FIELDS = (
    "emailalerts",
    "smsalerts",
    "emailrecoveryalerts",
    "smsrecoveryalerts",
)
_MONITORING_OUTAGE_TEXT_FIELDS = (
    "clearcheck",
    "checkstatusicon",
    "frequencyicon",
    "typeicon",
    "description",
    "duration",
    "psaticketstatus",
    "startdate",
    "enddate",
    "failreason",
)
_MONITORING_OUTAGE_INTEGER_FIELDS = (
    "checkid",
    "descriptorid",
    "psaticketstatusid",
)
_MONITORING_OUTAGE_FLAG_FIELDS = ("isclosed",)
_MONITORING_NOTE_TEXT_FIELDS = (
    "created",
    "description",
    "devicename",
    "checkdescriptorid",
    "checkdescription",
    "note",
    "public_note",
)


def _monitoring_detail_records(root: Any) -> dict[str, object]:
    device_node: Any | None = None
    device_type = ""
    for candidate in ("server", "workstation"):
        node = root.find(candidate)
        if node is not None:
            device_node = node
            device_type = candidate
            break
    if device_node is None:
        return {"device": {}, "checks": [], "outages": [], "notes": [], "features": {}}

    device: dict[str, object] = {"type": device_type}
    device_id = _positive_id(_text(device_node, "id"))
    if device_id is not None:
        device["id"] = device_id
    for field in _MONITORING_DEVICE_FIELDS:
        raw = _text(device_node, field)
        if raw:
            device[field] = _bounded_text(raw)

    checks: list[dict[str, object]] = []
    checks_container = device_node.find("checks")
    if checks_container is not None:
        for check in checks_container.findall("check")[:MAX_MONITORING_RECORDS]:
            check_id = _positive_id(_text(check, "checkid"))
            if check_id is None:
                continue
            record: dict[str, object] = {"check_id": check_id}
            for field in _MONITORING_CHECK_INTEGER_FIELDS:
                value = _optional_integer(_text(check, field))
                if value is not None:
                    record[field] = value
            for field in _MONITORING_CHECK_FLAG_FIELDS:
                value = _optional_flag(_text(check, field))
                if value is not None:
                    record[field] = value
            for field in _MONITORING_CHECK_TEXT_FIELDS:
                raw = _text(check, field)
                if raw:
                    record[field] = _bounded_text(raw)
            checks.append(record)

    outages: list[dict[str, object]] = []
    outages_container = device_node.find("outages")
    if outages_container is not None:
        for outage in outages_container.findall("outage")[:MAX_MONITORING_RECORDS]:
            outage_id = _positive_id(_text(outage, "id"))
            if outage_id is None:
                continue
            record = {"id": outage_id}
            for field in _MONITORING_OUTAGE_INTEGER_FIELDS:
                value = _optional_integer(_text(outage, field))
                if value is not None:
                    record[field] = value
            for field in _MONITORING_OUTAGE_FLAG_FIELDS:
                value = _optional_flag(_text(outage, field))
                if value is not None:
                    record[field] = value
            for field in _MONITORING_OUTAGE_TEXT_FIELDS:
                raw = _text(outage, field)
                if raw:
                    record[field] = _bounded_text(raw)
            outages.append(record)

    notes: list[dict[str, object]] = []
    notes_container = device_node.find("notes")
    if notes_container is not None:
        for note in notes_container.findall("note")[:MAX_MONITORING_RECORDS]:
            note_id = _positive_id(_text(note, "noteid"))
            if note_id is None:
                continue
            record = {"note_id": note_id}
            for field in _MONITORING_NOTE_TEXT_FIELDS:
                raw = _text(note, field)
                if raw:
                    record[field] = _bounded_text(raw)
            notes.append(record)

    features: dict[str, bool] = {}
    for field in ("takecontrol", "patch", "mav", "mob", "systray", "mavbreck"):
        value = _optional_flag(_text(device_node, field))
        if value is not None:
            features[field] = value
    return {
        "device": device,
        "checks": checks,
        "outages": outages,
        "notes": notes,
        "features": features,
    }


def _antivirus_threat_records(root: Any) -> list[dict[str, object]]:
    threats: list[dict[str, object]] = []
    for threat in root.iter("threat"):
        name = _bounded_text(_text(threat, "name"))
        category = _bounded_text(_text(threat, "category"))
        if not name or not category:
            continue
        threats.append(
            {
                "name": name,
                "category": category,
                "last_event": _bounded_text(_text(threat, "last_event")),
                "last_status": _bounded_text(_text(threat, "last_status")),
                "last_scan_type": _bounded_text(_text(threat, "last_scan_type")),
                "last_trace_count": _optional_integer(_text(threat, "last_trace_count")),
                "engine": _bounded_text(_text(threat, "engine")),
            }
        )
    return threats


def _antivirus_product_records(root: Any) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []
    for product in root.iter("product"):
        product_id = _bounded_text(_text(product, "id"))
        name = _bounded_text(_text(product, "name"))
        if not product_id or not name:
            continue
        products.append({"id": product_id, "name": name})
        if len(products) >= MAX_ANTIVIRUS_PRODUCTS:
            return products
    return products


def _antivirus_definition_records(root: Any) -> list[dict[str, object]]:
    definitions: list[dict[str, object]] = []
    for definition in root.iter("definition"):
        product_id = _bounded_text(_text(definition, "product"))
        version = _bounded_text(_text(definition, "version"))
        released = _bounded_text(_text(definition, "date"))
        if not product_id or not version or not released:
            continue
        definitions.append(
            {"product": product_id, "version": version, "date": released}
        )
        if len(definitions) >= MAX_ANTIVIRUS_DEFINITIONS:
            return definitions
    return definitions


def _antivirus_quarantine_records(root: Any) -> list[dict[str, object]]:
    quarantine: list[dict[str, object]] = []
    for item in root.iter("quarantine"):
        quarantine_id = _bounded_text(_text(item, "quarantineguid"))
        if not quarantine_id:
            continue
        quarantine.append(
            {
                "quarantine_id": quarantine_id,
                "status_id": _optional_integer(_text(item, "statusid")),
                "group": _optional_integer(_text(item, "group")),
                "status": _bounded_text(_text(item, "quarantineStatus")),
                "event_date": _bounded_text(_text(item, "eventDate")),
                "threat_name": _bounded_text(_text(item, "threatName")),
                "trace_count": _optional_integer(_text(item, "traces")),
                "event_type": _bounded_text(_text(item, "eventtype")),
                "engine": _bounded_text(_text(item, "engine")),
            }
        )
    return quarantine


def _antivirus_scan_records(root: Any, *, include_details: bool) -> list[dict[str, object]]:
    scans: list[dict[str, object]] = []
    text_fields = ("type", "status", "start", "end", "engine")
    integer_fields = (
        "cookies_scanned",
        "registry_scanned",
        "files_scanned",
        "folders_scanned",
        "processes_scanned",
    )
    for scan in root.iter("scan"):
        scan_type = _bounded_text(_text(scan, "type"))
        status = _bounded_text(_text(scan, "status"))
        start = _bounded_text(_text(scan, "start"))
        if not scan_type or not status or not start:
            continue
        record: dict[str, object] = {
            "type": scan_type,
            "status": status,
            "start": start,
        }
        for field in text_fields[3:]:
            value = _bounded_text(_text(scan, field))
            if value:
                record[field] = value
        for field in integer_fields:
            integer_value = _optional_integer(_text(scan, field))
            if integer_value is not None:
                record[field] = integer_value
        if include_details:
            threats: list[dict[str, object]] = []
            for threat in scan.iter("threat"):
                threat_record: dict[str, object] = {}
                for field in ("name", "category", "status", "last_status"):
                    value = _bounded_text(_text(threat, field))
                    if value:
                        threat_record[field] = value
                if threat_record and len(threats) < MAX_ANTIVIRUS_SCAN_THREATS:
                    threats.append(threat_record)
            if threats:
                record["threats"] = threats
        scans.append(record)
        if len(scans) >= MAX_ANTIVIRUS_SCANS:
            break
    return scans


def _outage_records(root: Any) -> list[dict[str, object]]:
    outages: list[dict[str, object]] = []
    for outage in root.iter("outage"):
        outage_id = _positive_id(_text(outage, "outage_id"))
        reason = _bounded_text(_text(outage, "reason"))
        state = _bounded_text(_text(outage, "state"))
        if outage_id is None or not reason or not state:
            continue
        outages.append(
            {
                "outage_id": outage_id,
                "reason": reason,
                "state": state,
                "utc_start": _bounded_text(_text(outage, "utc_start")),
                "utc_end": _bounded_text(_text(outage, "utc_end")),
                "check_id": _optional_integer(_text(outage, "check_id")),
                "check_type": _optional_integer(_text(outage, "check_type")),
                "check_description": _bounded_text(_text(outage, "check_description")),
                "check_status": _bounded_text(_text(outage, "check_status")),
                "check_frequency": _bounded_text(_text(outage, "check_frequency")),
                "cause": _bounded_text(_text(outage, "cause")),
            }
        )
    return outages


def _backup_session_records(root: Any) -> list[dict[str, object]]:
    sessions: list[dict[str, object]] = []
    for session in root.iter("session"):
        session_id = _positive_id(_text(session, "session_id"))
        if session_id is None:
            continue
        sessions.append(
            {
                "session_id": session_id,
                "type": _bounded_text(_text(session, "type")),
                "storage_account_id": _positive_id(_text(session, "storage_account_id")),
                "plugin": _bounded_text(_text(session, "plugin")),
                "start": _bounded_text(_text(session, "start")),
                "end": _bounded_text(_text(session, "end")),
                "selection_size": _optional_metric_integer(_text(session, "selection_size")),
                "selection_item_count": _optional_metric_integer(
                    _text(session, "selection_item_count")
                ),
                "size_change": _optional_metric_integer(_text(session, "size_change")),
                "item_count_change": _optional_metric_integer(
                    _text(session, "item_count_change")
                ),
                "removed_item_count": _optional_metric_integer(
                    _text(session, "removed_item_count")
                ),
                "processed_size": _optional_metric_integer(_text(session, "processed_size")),
                "processed_item_count": _optional_metric_integer(
                    _text(session, "processed_item_count")
                ),
                "transferred_size": _optional_metric_integer(
                    _text(session, "transferred_size")
                ),
                "error_count": _optional_metric_integer(_text(session, "error_count")),
                "status": _bounded_text(_text(session, "status")),
            }
        )
    return sessions


def _backup_history_records(root: Any) -> dict[str, object]:
    checks: list[str] = []
    for checks_node in root.iter("checks"):
        for name in checks_node.findall("name"):
            value = _bounded_text(name.text.strip() if isinstance(name.text, str) else "")
            if value and value not in checks:
                checks.append(value)
            if len(checks) >= MAX_BACKUP_CHECKS:
                break
        if len(checks) >= MAX_BACKUP_CHECKS:
            break

    days: list[dict[str, str]] = []
    for days_node in root.iter("days"):
        for day in days_node.findall("day"):
            date = _bounded_text(_text(day, "date"))
            status = _bounded_text(_text(day, "status"))
            if not date or not status:
                continue
            days.append({"date": date, "status": status})
            if len(days) >= MAX_BACKUP_HISTORY_DAYS:
                return {"checks": checks, "days": days}
    return {"checks": checks, "days": days}


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


def _quarantine_guid_list(values: list[str]) -> list[str]:
    if not isinstance(values, list) or not values or len(values) > MAX_ANTIVIRUS_QUARANTINE_IDS:
        raise NSightRmmError("N-sight quarantine mutation requires 1 to 20 quarantine IDs")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise NSightRmmError("N-sight quarantine IDs must be non-empty strings")
        guid = value.strip()
        if not guid or len(guid) > 200:
            raise NSightRmmError("N-sight quarantine IDs must be non-empty strings")
        if guid not in normalized:
            normalized.append(guid)
    return normalized


def _optional_integer(value: str) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if 0 <= parsed <= 2_147_483_647 else None


def _optional_metric_integer(value: str) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if 0 <= parsed <= MAX_METRIC_INTEGER else None


def _optional_number(value: str) -> int | float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not math.isfinite(parsed) or abs(parsed) > MAX_METRIC_INTEGER:
        return None
    return int(parsed) if parsed.is_integer() else parsed


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
