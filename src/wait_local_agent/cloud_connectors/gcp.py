from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from importlib import import_module
from typing import Any


class _FallbackGcpError(Exception):
    """Fallback for test environments where Google Cloud SDKs are not installed yet."""


try:
    from google.api_core import exceptions as _google_api_exceptions
    from google.auth import exceptions as _google_auth_exceptions
except ImportError:
    GoogleAPICallError: type[BaseException] = _FallbackGcpError
    RetryError: type[BaseException] = _FallbackGcpError
    DefaultCredentialsError: type[BaseException] = _FallbackGcpError
    RefreshError: type[BaseException] = _FallbackGcpError
else:
    GoogleAPICallError = _google_api_exceptions.GoogleAPICallError
    RetryError = _google_api_exceptions.RetryError
    DefaultCredentialsError = _google_auth_exceptions.DefaultCredentialsError
    RefreshError = _google_auth_exceptions.RefreshError

GCP_ERROR_TYPES: tuple[type[BaseException], ...] = (
    GoogleAPICallError,
    RetryError,
    DefaultCredentialsError,
    RefreshError,
)

GcpConfig = Mapping[str, Any] | None


class _GoogleCloudSession:
    def client(self, service_name: str) -> Any:
        if service_name == "resource-manager":
            resource_manager = import_module("google.cloud.resourcemanager_v3")
            return resource_manager.ProjectsClient()
        if service_name == "compute":
            compute = import_module("google.cloud.compute_v1")
            return compute.InstancesClient()
        if service_name == "storage":
            storage = import_module("google.cloud.storage")
            return storage.Client()
        if service_name == "iam":
            iam = import_module("google.cloud.iam_admin_v1")
            return iam.IAMClient()
        raise ValueError(f"unsupported GCP service: {service_name}")


class GCPInventoryConnector:
    """Read-only inventory connector for GCP project resources."""

    module_id = "gcp-inventory"
    name = "GCP Inventory"
    version = "1.0"
    asset_types = [
        "cloud-bucket",
        "cloud-iam-service-account",
        "cloud-instance",
        "cloud-project",
    ]

    def manifest(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": "Read-only inventory of GCP projects, Compute Engine, Cloud Storage, and IAM resources.",
            "asset_type": "cloud-resource",
            "asset_types": self.asset_types,
            "read_only": True,
            "dependencies": [
                "google-cloud-compute",
                "google-cloud-iam",
                "google-cloud-resource-manager",
                "google-cloud-storage",
            ],
            "platforms": ["cloud"],
        }

    def scope(self, config: GcpConfig = None) -> dict[str, Any]:
        return {
            "read_only": True,
            "stdlib_only": False,
            "paths": ["gcp:resourcemanager", "gcp:compute", "gcp:storage", "gcp:iam"],
            "operations": [
                "resourcemanager.projects.search",
                "compute.instances.aggregated_list",
                "storage.buckets.list",
                "iam.serviceAccounts.list",
            ],
            "network": True,
            "shell": False,
        }

    def validate_config(self, config: GcpConfig = None) -> dict[str, Any]:
        errors: list[str] = []
        if config is not None and not isinstance(config, Mapping):
            errors.append("config must be a mapping when provided")
            return {"ok": False, "errors": errors}

        if isinstance(config, Mapping):
            unsupported_keys = sorted(set(config) - {"limit", "project_id", "session", "zone"})
            if unsupported_keys:
                errors.append(f"unsupported config keys: {', '.join(unsupported_keys)}")

            if "limit" in config:
                limit = config["limit"]
                if not isinstance(limit, int) or limit < 0:
                    errors.append("limit must be a non-negative integer")

            if "project_id" in config and (
                not isinstance(config["project_id"], str) or not config["project_id"].strip()
            ):
                errors.append("project_id must be a non-empty string")

            if "zone" in config and (not isinstance(config["zone"], str) or not config["zone"].strip()):
                errors.append("zone must be a non-empty string")

            session = config.get("session")
            if session is not None and not callable(getattr(session, "client", None)):
                errors.append("session must provide a client(service_name) method")

        return {"ok": not errors, "errors": errors}

    def preview(self, config: GcpConfig = None) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation["ok"]:
            return self._invalid_result(validation["errors"])

        return self._collect_result(config, preview=True, default_limit=10)

    def collect(self, config: GcpConfig = None) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation["ok"]:
            return self._invalid_result(validation["errors"])

        return self._collect_result(config, preview=False, default_limit=None)

    def _collect_result(self, config: GcpConfig, *, preview: bool, default_limit: int | None) -> dict[str, Any]:
        limit = self._config_limit(config, default=default_limit)
        if limit == 0:
            return self._result([], preview=preview)

        session = self._session(config)
        project_records = self._project_records(session)
        project_ids = self._project_ids(config, project_records)
        records = [
            *project_records,
            *[
                record
                for project_id in project_ids
                for record in (
                    *self._compute_instance_records(session, config, project_id),
                    *self._storage_bucket_records(session, project_id),
                    *self._iam_service_account_records(session, project_id),
                )
            ],
        ]
        records.sort(key=lambda record: str(record["asset_id"]))
        if limit is not None:
            records = records[:limit]
        return self._result(records, preview=preview)

    @staticmethod
    def _config_limit(config: GcpConfig, default: int | None) -> int | None:
        if isinstance(config, Mapping) and "limit" in config:
            return int(config["limit"])
        return default

    @staticmethod
    def _session(config: GcpConfig) -> Any:
        if isinstance(config, Mapping) and config.get("session") is not None:
            return config["session"]

        return _GoogleCloudSession()

    @staticmethod
    def _client(session: Any, service_name: str) -> Any:
        return session.client(service_name)

    def _project_records(self, session: Any) -> list[dict[str, Any]]:
        try:
            resource_manager = self._client(session, "resource-manager")
            response = resource_manager.search_projects()
        except GCP_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for project in self._iterable(response):
            project_id = self._text(self._get(project, "project_id", ""))
            if not project_id:
                continue
            display_name = self._text(self._get(project, "display_name", "")) or project_id
            records.append(
                {
                    "asset_type": "cloud-project",
                    "asset_id": f"gcp:project:{project_id}",
                    "name": display_name,
                    "attributes": {
                        "project_id": project_id,
                        "display_name": display_name,
                        "name": self._text(self._get(project, "name", "")),
                        "state": self._format_value(self._get(project, "state", "")),
                    },
                }
            )
        return records

    def _compute_instance_records(self, session: Any, config: GcpConfig, project_id: str) -> list[dict[str, Any]]:
        try:
            compute = self._client(session, "compute")
            zone = config.get("zone") if isinstance(config, Mapping) else None
            if isinstance(zone, str):
                response = compute.list(project=project_id, zone=zone)
                zone_instances = [(zone, response)]
            else:
                response = compute.aggregated_list(project=project_id)
                zone_instances = [
                    (self._zone_name(zone_name), self._get(scoped_list, "instances", []) or [])
                    for zone_name, scoped_list in self._iter_aggregated(response)
                ]
        except GCP_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for zone, instances in zone_instances:
            for instance in self._iterable(instances):
                instance_id = self._text(self._get(instance, "id", ""))
                name = self._text(self._get(instance, "name", ""))
                if not instance_id and not name:
                    continue
                asset_id = instance_id or name
                records.append(
                    {
                        "asset_type": "cloud-instance",
                        "asset_id": f"gcp:compute:{project_id}:{zone}:{asset_id}",
                        "name": name or asset_id,
                        "attributes": {
                            "project_id": project_id,
                            "instance_id": instance_id,
                            "name": name,
                            "machine_type": self._resource_basename(self._get(instance, "machine_type", "")),
                            "status": self._format_value(self._get(instance, "status", "")),
                            "zone": zone,
                            "private_ip": self._private_ip(instance),
                        },
                    }
                )
        return records

    def _storage_bucket_records(self, session: Any, project_id: str) -> list[dict[str, Any]]:
        try:
            storage = self._client(session, "storage")
            response = storage.list_buckets(project=project_id)
        except GCP_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for bucket in self._iterable(response):
            name = self._text(self._get(bucket, "name", ""))
            if not name:
                continue
            records.append(
                {
                    "asset_type": "cloud-bucket",
                    "asset_id": f"gcp:storage:{name}",
                    "name": name,
                    "attributes": {
                        "project_id": project_id,
                        "name": name,
                        "location": self._format_value(self._get(bucket, "location", "")),
                        "storage_class": self._format_value(self._get(bucket, "storage_class", "")),
                        "time_created": self._format_value(self._get(bucket, "time_created", "")),
                    },
                }
            )
        return records

    def _iam_service_account_records(self, session: Any, project_id: str) -> list[dict[str, Any]]:
        try:
            iam = self._client(session, "iam")
            response = iam.list_service_accounts(name=f"projects/{project_id}")
        except GCP_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for account in self._iterable(response):
            email = self._text(self._get(account, "email", ""))
            if not email:
                continue
            records.append(
                {
                    "asset_type": "cloud-iam-service-account",
                    "asset_id": f"gcp:iam:{email}",
                    "name": email,
                    "attributes": {
                        "project_id": project_id,
                        "email": email,
                        "unique_id": self._text(self._get(account, "unique_id", "")),
                        "display_name": self._text(self._get(account, "display_name", "")),
                        "disabled": self._format_value(self._get(account, "disabled", False)),
                    },
                }
            )
        return records

    @staticmethod
    def _project_ids(config: GcpConfig, project_records: list[dict[str, Any]]) -> list[str]:
        project_ids: list[str] = []
        if isinstance(config, Mapping) and isinstance(config.get("project_id"), str):
            project_ids.append(str(config["project_id"]))
        for record in project_records:
            project_id = str(record["attributes"]["project_id"])
            if project_id not in project_ids:
                project_ids.append(project_id)
        return project_ids

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
            "module_id": GCPInventoryConnector.module_id,
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
    def _get(value: Any, key: str, default: Any = None) -> Any:
        if isinstance(value, Mapping):
            return value.get(key, default)
        return getattr(value, key, default)

    @staticmethod
    def _iterable(value: Any) -> Iterable[Any]:
        if value is None:
            return []
        if isinstance(value, Mapping):
            for key in ("items", "projects", "buckets", "accounts", "service_accounts"):
                rows = value.get(key)
                if rows is not None:
                    return rows
            return value.values()
        return value

    def _iter_aggregated(self, response: Any) -> Iterable[tuple[str, Any]]:
        if isinstance(response, Mapping):
            items = response.get("items", response)
            if isinstance(items, Mapping):
                return items.items()
        return self._iterable(response)

    @staticmethod
    def _zone_name(zone_name: Any) -> str:
        zone = str(zone_name)
        return zone.rsplit("/", maxsplit=1)[-1]

    @staticmethod
    def _resource_basename(value: Any) -> str:
        resource = str(value) if value is not None else ""
        return resource.rsplit("/", maxsplit=1)[-1]

    def _private_ip(self, instance: Any) -> str:
        network_interfaces = self._get(instance, "network_interfaces", []) or []
        for network_interface in self._iterable(network_interfaces):
            private_ip = self._text(self._get(network_interface, "network_i_p", ""))
            if not private_ip:
                private_ip = self._text(self._get(network_interface, "networkIP", ""))
            if private_ip:
                return private_ip
        return ""

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _format_value(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        to_datetime = getattr(value, "ToDatetime", None)
        if callable(to_datetime):
            return to_datetime().isoformat()
        enum_name = getattr(value, "name", None)
        if isinstance(enum_name, str):
            return enum_name
        return value
