from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date, datetime
from importlib import import_module
from typing import Any


class _FallbackAzureError(Exception):
    """Fallback for test environments where Azure SDK packages are not installed yet."""


try:
    _azure_exceptions = import_module("azure.core.exceptions")
except ImportError:
    AzureError: type[BaseException] = _FallbackAzureError
    ClientAuthenticationError: type[BaseException] = _FallbackAzureError
    HttpResponseError: type[BaseException] = _FallbackAzureError
else:
    AzureError = _azure_exceptions.AzureError
    ClientAuthenticationError = _azure_exceptions.ClientAuthenticationError
    HttpResponseError = _azure_exceptions.HttpResponseError

AZURE_ERROR_TYPES: tuple[type[BaseException], ...] = (AzureError, ClientAuthenticationError, HttpResponseError)

AzureConfig = Mapping[str, Any] | None


class AzureInventoryConnector:
    """Read-only inventory connector for Azure subscription resources."""

    module_id = "azure-inventory"
    name = "Azure Inventory"
    version = "1.0"
    asset_types = [
        "cloud-iam-assignment",
        "cloud-instance",
        "cloud-security-group",
        "cloud-storage-account",
    ]

    def manifest(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": (
                "Read-only inventory of Azure VM, storage account, network security group, and IAM resources."
            ),
            "asset_type": "cloud-resource",
            "asset_types": self.asset_types,
            "read_only": True,
            "dependencies": [
                "azure-identity",
                "azure-mgmt-authorization",
                "azure-mgmt-compute",
                "azure-mgmt-network",
                "azure-mgmt-storage",
            ],
            "platforms": ["cloud"],
        }

    def scope(self, config: AzureConfig = None) -> dict[str, Any]:
        return {
            "read_only": True,
            "stdlib_only": False,
            "paths": ["azure:compute", "azure:storage", "azure:network", "azure:authorization"],
            "operations": [
                "compute.virtual_machines.list_all",
                "storage.storage_accounts.list",
                "network.network_security_groups.list_all",
                "authorization.role_assignments.list_for_subscription",
            ],
            "network": True,
            "shell": False,
        }

    def validate_config(self, config: AzureConfig = None) -> dict[str, Any]:
        errors: list[str] = []
        if config is not None and not isinstance(config, Mapping):
            errors.append("config must be a mapping when provided")
            return {"ok": False, "errors": errors}

        if isinstance(config, Mapping):
            unsupported_keys = sorted(set(config) - {"credential", "limit", "session", "subscription_id"})
            if unsupported_keys:
                errors.append(f"unsupported config keys: {', '.join(unsupported_keys)}")

            if "limit" in config:
                limit = config["limit"]
                if not isinstance(limit, int) or limit < 0:
                    errors.append("limit must be a non-negative integer")

            if "subscription_id" in config and (
                not isinstance(config["subscription_id"], str) or not config["subscription_id"].strip()
            ):
                errors.append("subscription_id must be a non-empty string")

            session = config.get("session")
            if session is not None and not callable(getattr(session, "client", None)):
                errors.append("session must provide a client(service_name) method")

        return {"ok": not errors, "errors": errors}

    def preview(self, config: AzureConfig = None) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation["ok"]:
            return self._invalid_result(validation["errors"])

        return self._collect_result(config, preview=True, default_limit=10)

    def collect(self, config: AzureConfig = None) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation["ok"]:
            return self._invalid_result(validation["errors"])

        return self._collect_result(config, preview=False, default_limit=None)

    def _collect_result(self, config: AzureConfig, *, preview: bool, default_limit: int | None) -> dict[str, Any]:
        limit = self._config_limit(config, default=default_limit)
        if limit == 0:
            return self._result([], preview=preview)

        session = self._session(config)
        records = [
            *self._virtual_machine_records(session),
            *self._storage_account_records(session),
            *self._network_security_group_records(session),
            *self._role_assignment_records(session),
        ]
        records.sort(key=lambda record: str(record["asset_id"]))
        if limit is not None:
            records = records[:limit]
        return self._result(records, preview=preview)

    @staticmethod
    def _config_limit(config: AzureConfig, default: int | None) -> int | None:
        if isinstance(config, Mapping) and "limit" in config:
            return int(config["limit"])
        return default

    @staticmethod
    def _session(config: AzureConfig) -> Any:
        if isinstance(config, Mapping) and config.get("session") is not None:
            return config["session"]

        credential = config.get("credential") if isinstance(config, Mapping) else None
        if credential is None:
            credential = import_module("azure.identity").DefaultAzureCredential()

        subscription_id = config.get("subscription_id") if isinstance(config, Mapping) else None
        if not isinstance(subscription_id, str) or not subscription_id.strip():
            subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")

        return _AzureSdkSession(credential=credential, subscription_id=subscription_id)

    @staticmethod
    def _client(session: Any, service_name: str) -> Any:
        return session.client(service_name)

    def _virtual_machine_records(self, session: Any) -> list[dict[str, Any]]:
        try:
            compute = self._client(session, "compute")
            response = compute.virtual_machines.list_all()
        except AZURE_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for virtual_machine in response:
            resource_id = str(self._value(virtual_machine, "id", ""))
            name = str(self._value(virtual_machine, "name", ""))
            identifier = resource_id or name
            if not identifier:
                continue

            hardware_profile = self._value(virtual_machine, "hardware_profile", None)
            records.append(
                {
                    "asset_type": "cloud-instance",
                    "asset_id": f"azure:compute:{identifier}",
                    "name": name or identifier,
                    "attributes": {
                        "resource_id": resource_id,
                        "name": name,
                        "vm_size": self._value(hardware_profile, "vm_size", ""),
                        "location": self._value(virtual_machine, "location", ""),
                        "provisioning_state": self._value(virtual_machine, "provisioning_state", ""),
                        "resource_group": self._resource_group(resource_id),
                    },
                }
            )
        return records

    def _storage_account_records(self, session: Any) -> list[dict[str, Any]]:
        try:
            storage = self._client(session, "storage")
            response = storage.storage_accounts.list()
        except AZURE_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for storage_account in response:
            resource_id = str(self._value(storage_account, "id", ""))
            name = str(self._value(storage_account, "name", ""))
            identifier = resource_id or name
            if not identifier:
                continue

            sku = self._value(storage_account, "sku", None)
            records.append(
                {
                    "asset_type": "cloud-storage-account",
                    "asset_id": f"azure:storage:{identifier}",
                    "name": name or identifier,
                    "attributes": {
                        "resource_id": resource_id,
                        "name": name,
                        "location": self._value(storage_account, "location", ""),
                        "kind": self._value(storage_account, "kind", ""),
                        "sku": self._value(sku, "name", ""),
                    },
                }
            )
        return records

    def _network_security_group_records(self, session: Any) -> list[dict[str, Any]]:
        try:
            network = self._client(session, "network")
            response = network.network_security_groups.list_all()
        except AZURE_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for security_group in response:
            resource_id = str(self._value(security_group, "id", ""))
            name = str(self._value(security_group, "name", ""))
            identifier = resource_id or name
            if not identifier:
                continue

            security_rules = self._value(security_group, "security_rules", [])
            records.append(
                {
                    "asset_type": "cloud-security-group",
                    "asset_id": f"azure:nsg:{identifier}",
                    "name": name or identifier,
                    "attributes": {
                        "resource_id": resource_id,
                        "name": name,
                        "location": self._value(security_group, "location", ""),
                        "security_rule_count": len(security_rules or []),
                    },
                }
            )
        return records

    def _role_assignment_records(self, session: Any) -> list[dict[str, Any]]:
        try:
            authorization = self._client(session, "authorization")
            response = authorization.role_assignments.list_for_subscription()
        except AZURE_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for assignment in response:
            assignment_id = str(self._value(assignment, "id", ""))
            name = str(self._value(assignment, "name", ""))
            identifier = assignment_id or name
            if not identifier:
                continue

            records.append(
                {
                    "asset_type": "cloud-iam-assignment",
                    "asset_id": f"azure:role-assignment:{identifier}",
                    "name": name or identifier,
                    "attributes": {
                        "assignment_id": assignment_id,
                        "name": name,
                        "principal_id": self._value(assignment, "principal_id", ""),
                        "role_definition_id": self._value(assignment, "role_definition_id", ""),
                        "scope": self._value(assignment, "scope", ""),
                    },
                }
            )
        return records

    def _result(self, records: list[dict[str, Any]], *, preview: bool) -> dict[str, Any]:
        assets = [self._asset(record) for record in records]
        observations = [
            observation
            for record in records
            for observation in self._observations(record)
        ]
        return {
            "module_id": self.module_id,
            "ok": True,
            "preview": preview,
            "assets": assets,
            "observations": observations,
            "items": [
                {
                    "canonical_asset": asset,
                    "observations": self._observations(record),
                }
                for asset, record in zip(assets, records, strict=False)
            ],
            "count": len(assets),
        }

    @staticmethod
    def _invalid_result(errors: list[str]) -> dict[str, Any]:
        return {
            "module_id": AzureInventoryConnector.module_id,
            "ok": False,
            "errors": errors,
            "assets": [],
            "observations": [],
        }

    @staticmethod
    def _asset(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "asset_type": record["asset_type"],
            "asset_id": record["asset_id"],
            "name": record["name"],
            "attributes": record["attributes"],
        }

    def _observations(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        asset_type = str(record["asset_type"])
        asset_id = str(record["asset_id"])
        return [
            {
                "asset_type": asset_type,
                "asset_id": asset_id,
                "key": f"cloud.{key}",
                "value": self._format_value(value),
            }
            for key, value in record["attributes"].items()
        ]

    @staticmethod
    def _format_value(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return value

    @staticmethod
    def _resource_group(resource_id: str) -> str:
        segments = [segment for segment in resource_id.split("/") if segment]
        for index, segment in enumerate(segments):
            if segment.lower() == "resourcegroups" and index + 1 < len(segments):
                return segments[index + 1]
        return ""

    @staticmethod
    def _value(source: Any, key: str, default: Any = "") -> Any:
        if isinstance(source, Mapping):
            return source.get(key, default)
        return getattr(source, key, default)


class _AzureSdkSession:
    def __init__(self, *, credential: Any, subscription_id: str) -> None:
        self.credential = credential
        self.subscription_id = subscription_id

    def client(self, service_name: str) -> Any:
        if service_name == "compute":
            return import_module("azure.mgmt.compute").ComputeManagementClient(
                self.credential,
                self.subscription_id,
            )
        if service_name == "storage":
            return import_module("azure.mgmt.storage").StorageManagementClient(
                self.credential,
                self.subscription_id,
            )
        if service_name == "network":
            return import_module("azure.mgmt.network").NetworkManagementClient(
                self.credential,
                self.subscription_id,
            )
        if service_name == "authorization":
            return import_module("azure.mgmt.authorization").AuthorizationManagementClient(
                self.credential,
                self.subscription_id,
            )
        raise ValueError(f"unsupported Azure service: {service_name}")
