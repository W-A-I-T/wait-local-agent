"""Small read-only RMM boundary backed by collected endpoint-agent evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from wait_local_agent.store import Store


@dataclass(frozen=True)
class RmmDevice:
    device_id: str
    name: str
    category: str = ""
    attributes: dict[str, object] = field(default_factory=dict)


class RmmInventoryProvider(Protocol):
    adapter_id: str

    def list_devices(self, client_id: str | None = None) -> list[RmmDevice]:
        """Return read-only device inventory scoped to one tenant."""


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


__all__ = ["LocalCollectorRmmAdapter", "RmmDevice", "RmmInventoryProvider"]
