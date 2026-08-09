"""Bounded RMM boundary backed by collected evidence and provider adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Protocol

from wait_local_agent.config import Settings
from wait_local_agent.store import Store


@dataclass(frozen=True)
class RmmDevice:
    device_id: str
    name: str
    category: str = ""
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RmmAlert:
    alert_id: str
    device_id: str
    severity: str
    title: str
    status: str = "open"


@dataclass(frozen=True)
class RmmScript:
    script_id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class RmmScriptPreview:
    script_id: str
    device_id: str
    arguments: dict[str, str]
    status: Literal["preview", "blocked"]
    message: str


@dataclass(frozen=True)
class RmmScriptExecution:
    script_id: str
    device_id: str
    status: Literal["blocked", "queued", "completed", "succeeded", "failed"]
    message: str
    execution_id: str = ""


class RmmInventoryProvider(Protocol):
    adapter_id: str

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        """Return read-only device inventory scoped to one tenant."""

    def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
        """Return bounded alerts scoped to one tenant."""

    def list_scripts(self, client_id: str | None = None) -> list[RmmScript]:
        """Return available scripts without script contents or credentials."""

    def preview_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptPreview:
        """Validate a script request without executing it."""

    def execute_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        """Execute only through a provider-specific, already-approved path."""

    def get_execution(
        self,
        execution_id: str,
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        """Return the bounded status for one provider execution."""


class LocalCollectorRmmAdapter:
    """Normalize persisted endpoint-agent collector assets as RMM devices."""

    adapter_id = "local-collector"

    def __init__(self, store: Store) -> None:
        self.store = store

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        devices: list[RmmDevice] = []
        for asset in self.store.list_canonical_assets(client_id=client_id):
            if asset.asset_type != "endpoint-agent":
                continue
            try:
                raw_attributes = json.loads(asset.attributes_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw_attributes, dict):
                continue
            attributes = {str(key): value for key, value in raw_attributes.items()}
            devices.append(
                RmmDevice(
                    device_id=asset.canonical_id,
                    name=asset.display_name,
                    category=str(attributes.get("category", "")),
                    attributes=attributes,
                )
            )
        return devices

    def list_alerts(self, client_id: str | None = None) -> list[RmmAlert]:
        return []

    def list_scripts(self, client_id: str | None = None) -> list[RmmScript]:
        return []

    def preview_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptPreview:
        return RmmScriptPreview(
            script_id=script_id,
            device_id=device_id,
            arguments=dict(arguments),
            status="blocked",
            message="local collector RMM adapter has no script execution provider",
        )

    def execute_script(
        self,
        script_id: str,
        device_id: str,
        arguments: dict[str, str],
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        return RmmScriptExecution(
            script_id=script_id,
            device_id=device_id,
            status="blocked",
            message="RMM script execution requires a reviewed vendor adapter",
        )

    def get_execution(
        self,
        execution_id: str,
        *,
        client_id: str | None = None,
    ) -> RmmScriptExecution:
        return RmmScriptExecution(
            script_id="",
            device_id="",
            status="blocked",
            message="local collector RMM adapter has no execution provider",
            execution_id=execution_id,
        )


def rmm_provider_from_settings(settings: Settings, store: Store) -> RmmInventoryProvider:
    """Select a configured vendor adapter without making network calls."""
    if settings.ninjaone_base_url or settings.ninjaone_access_token:
        from wait_local_agent.ninjaone import NinjaOneRmmAdapter

        return NinjaOneRmmAdapter(settings)
    if settings.datto_rmm_base_url or settings.datto_rmm_access_token:
        from wait_local_agent.dattormm import DattoRmmAdapter

        return DattoRmmAdapter(settings, store=store)
    if settings.ncentral_base_url or settings.ncentral_access_token:
        from wait_local_agent.ncentral import NCentralRmmAdapter

        return NCentralRmmAdapter(settings, store=store)
    return LocalCollectorRmmAdapter(store)


__all__ = [
    "LocalCollectorRmmAdapter",
    "RmmAlert",
    "RmmDevice",
    "RmmInventoryProvider",
    "RmmScript",
    "RmmScriptExecution",
    "RmmScriptPreview",
    "rmm_provider_from_settings",
]
