"""Bounded RMM boundary backed by collected evidence and provider adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from wait_local_agent.client_scope import AllClients
from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorInstance
from wait_local_agent.store import Store

RMM_INSTANCE_TYPES = frozenset({"ninjaone", "dattormm", "ncentral"})


class RmmProviderResolutionError(Exception):
    """Raised when an RMM provider cannot be selected without guessing."""


class RmmInstanceStore(Protocol):
    def list_connector_instances(self) -> list[ConnectorInstance]:
        ...

    def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstance | None:
        ...


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
    tier = "environment"

    def __init__(self, store: Store) -> None:
        self.store = store

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        devices: list[RmmDevice] = []
        for asset in self.store.list_canonical_assets(
            client_id=client_id if client_id is not None else AllClients()
        ):
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


def rmm_provider_from_settings(
    settings: Settings,
    store: RmmInstanceStore,
    client_id: str | None = None,
    vault: Any | None = None,
    *,
    allow_msp_wide: bool = False,
) -> RmmInventoryProvider:
    """Select a vendor adapter without crossing a requested client boundary."""
    normalized_client_id = client_id.strip() if isinstance(client_id, str) else ""
    if normalized_client_id or allow_msp_wide:
        try:
            instances = store.list_connector_instances()
        except Exception as exc:
            raise RmmProviderResolutionError("RMM connector instances could not be loaded") from exc
        active_rmm = [
            instance
            for instance in instances
            if str(instance.status).strip().casefold() == "active"
            and str(instance.connector_type).strip().casefold() in RMM_INSTANCE_TYPES
        ]
        client_instances = [
            instance
            for instance in active_rmm
            if isinstance(instance.client_id, str) and instance.client_id.strip() == normalized_client_id
        ]
        candidates = client_instances
        tier: Literal["client-scoped", "MSP-wide"] = "client-scoped"
        if not candidates and normalized_client_id and not allow_msp_wide:
            raise RmmProviderResolutionError(
                f"no active client-scoped RMM connector instance found for client {normalized_client_id}"
            )
        if not candidates:
            candidates = [
                instance
                for instance in active_rmm
                if instance.client_id is None or not str(instance.client_id).strip()
            ]
            tier = "MSP-wide"
        if len(candidates) > 1:
            raise RmmProviderResolutionError(
                f"ambiguous active RMM connector instances at the {tier} tier for client "
                f"{normalized_client_id}"
            )
        if candidates:
            from wait_local_agent.connector_factory import ConnectorFactoryError, build_read_client_for

            try:
                provider = build_read_client_for(
                    store,
                    candidates[0].connector_instance_id,
                    base_settings=settings,
                    vault=vault,
                )
            except ConnectorFactoryError as exc:
                raise RmmProviderResolutionError(str(exc)) from exc
            try:
                cast(Any, provider).tier = tier
            except (AttributeError, TypeError) as exc:
                raise RmmProviderResolutionError("RMM provider does not expose a resolution tier") from exc
            return provider  # type: ignore[return-value]

    if settings.ninjaone_base_url or settings.ninjaone_access_token:
        from wait_local_agent.ninjaone import NinjaOneRmmAdapter

        ninjaone_provider = NinjaOneRmmAdapter(settings)
        cast(Any, ninjaone_provider).tier = "environment"
        return ninjaone_provider
    if settings.datto_rmm_base_url or settings.datto_rmm_access_token:
        from wait_local_agent.dattormm import DattoRmmAdapter

        datto_provider = DattoRmmAdapter(settings, store=cast(Store, store))
        cast(Any, datto_provider).tier = "environment"
        return datto_provider
    if settings.ncentral_base_url or settings.ncentral_access_token:
        from wait_local_agent.ncentral import NCentralRmmAdapter

        ncentral_provider = NCentralRmmAdapter(settings, store=cast(Store, store))
        cast(Any, ncentral_provider).tier = "environment"
        return ncentral_provider
    if settings.n_sight_base_url or settings.n_sight_api_key:
        from wait_local_agent.nsight import NSightRmmAdapter

        nsight_provider = NSightRmmAdapter(settings)
        cast(Any, nsight_provider).tier = "environment"
        return nsight_provider
    if (
        settings.kaseya_rmm_base_url
        or settings.kaseya_rmm_token_id
        or settings.kaseya_rmm_token_secret
    ):
        from wait_local_agent.kaseya import KaseyaRmmAdapter

        kaseya_provider = KaseyaRmmAdapter(settings, store=cast(Store, store))
        cast(Any, kaseya_provider).tier = "environment"
        return kaseya_provider
    if (
        settings.screenconnect_base_url
        or settings.screenconnect_extension_id
        or settings.screenconnect_auth_secret
    ):
        from wait_local_agent.screenconnect import ScreenConnectRmmAdapter

        screenconnect_provider = ScreenConnectRmmAdapter(settings)
        cast(Any, screenconnect_provider).tier = "environment"
        return screenconnect_provider
    return LocalCollectorRmmAdapter(cast(Store, store))


__all__ = [
    "LocalCollectorRmmAdapter",
    "RmmAlert",
    "RmmDevice",
    "RmmInventoryProvider",
    "RmmScript",
    "RmmScriptExecution",
    "RmmScriptPreview",
    "RMM_INSTANCE_TYPES",
    "RmmProviderResolutionError",
    "rmm_provider_from_settings",
]
