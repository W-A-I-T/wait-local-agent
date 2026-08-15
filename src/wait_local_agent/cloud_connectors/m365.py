from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Awaitable, Coroutine, Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from wait_local_agent.cloud_connectors._safe import (
    provider_outcome,
    result_errors,
    result_status,
    truncation_outcome,
)


class _FallbackM365Error(Exception):
    """Fallback for test environments where the Graph SDK is not installed yet."""


if TYPE_CHECKING:
    M365ApiError: type[BaseException]
else:
    try:
        from kiota_abstractions.api_error import APIError as M365ApiError
    except ImportError:
        M365ApiError = _FallbackM365Error

M365_ERROR_TYPES: tuple[type[BaseException], ...] = (M365ApiError,)

M365Config = Mapping[str, Any] | None


class M365InventoryConnector:
    """Read-only inventory connector for Microsoft 365 and Entra resources."""

    module_id = "m365-inventory"
    name = "Microsoft 365 Inventory"
    version = "1.0"
    asset_types = [
        "m365-application",
        "m365-conditional-access-policy",
        "m365-group",
        "m365-service-principal",
        "m365-user",
    ]

    def manifest(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": (
                "Read-only inventory of Microsoft 365 users, groups, apps, service principals, and policies."
            ),
            "asset_type": "cloud-resource",
            "asset_types": self.asset_types,
            "read_only": True,
            "dependencies": ["msgraph-sdk"],
            "platforms": ["cloud"],
        }

    def scope(self, config: M365Config = None) -> dict[str, Any]:
        return {
            "read_only": True,
            "stdlib_only": False,
            "paths": [
                "m365:users",
                "m365:groups",
                "m365:applications",
                "m365:service-principals",
                "m365:conditional-access-policies",
            ],
            "operations": [
                "graph.users.list",
                "graph.groups.list",
                "graph.applications.list",
                "graph.service_principals.list",
                "graph.identity.conditional_access.policies.list",
            ],
            "network": True,
            "shell": False,
        }

    def preflight(self, config: M365Config = None) -> None:
        """Verify the tenant with the read-only Microsoft Graph organization endpoint."""
        client = self._client(config)
        organization = getattr(client, "organization", None)
        if organization is None or not callable(getattr(organization, "get", None)):
            raise RuntimeError("Microsoft Graph organization request builder is unavailable")
        self._resolve(organization.get())

    def validate_config(self, config: M365Config = None) -> dict[str, Any]:
        errors: list[str] = []
        if config is not None and not isinstance(config, Mapping):
            errors.append("config must be a mapping when provided")
            return {"ok": False, "errors": errors}

        if isinstance(config, Mapping):
            unsupported_keys = sorted(set(config) - {"client", "credential", "limit", "scopes"})
            if unsupported_keys:
                errors.append(f"unsupported config keys: {', '.join(unsupported_keys)}")

            if "limit" in config:
                limit = config["limit"]
                if not isinstance(limit, int) or limit < 0:
                    errors.append("limit must be a non-negative integer")

            client = config.get("client")
            if client is not None and not self._has_graph_client_shape(client):
                errors.append("client must provide Microsoft Graph collection request builders")

            credential = config.get("credential")
            if credential is not None and not callable(getattr(credential, "get_token", None)):
                errors.append("credential must provide a get_token(*scopes) method")

            if "scopes" in config:
                scopes = config["scopes"]
                if not isinstance(scopes, list) or not scopes or not all(
                    isinstance(scope, str) and scope.strip() for scope in scopes
                ):
                    errors.append("scopes must be a non-empty list of non-empty strings")

        return {"ok": not errors, "errors": errors}

    def preview(self, config: M365Config = None) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation["ok"]:
            return self._invalid_result(validation["errors"])

        return self._collect_result(config, preview=True, default_limit=10)

    def collect(self, config: M365Config = None) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation["ok"]:
            return self._invalid_result(validation["errors"])

        return self._collect_result(config, preview=False, default_limit=None)

    def _collect_result(self, config: M365Config, *, preview: bool, default_limit: int | None) -> dict[str, Any]:
        return self.collect_detailed(config, preview=preview)["result"]

    @staticmethod
    def _config_limit(config: M365Config, default: int | None) -> int | None:
        if isinstance(config, Mapping) and "limit" in config:
            return int(config["limit"])
        return default

    @staticmethod
    def _client(config: M365Config) -> Any:
        if isinstance(config, Mapping) and config.get("client") is not None:
            return config["client"]

        from importlib import import_module

        graph = import_module("msgraph")
        scopes = config.get("scopes") if isinstance(config, Mapping) else None
        if not isinstance(scopes, list):
            scopes = ["https://graph.microsoft.com/.default"]

        credential = config.get("credential") if isinstance(config, Mapping) else None
        if credential is None:
            azure_identity = import_module("azure.identity")
            credential = azure_identity.DefaultAzureCredential()

        return graph.GraphServiceClient(credentials=credential, scopes=scopes)

    @staticmethod
    def _collection(client: Any, collection_name: str) -> Any:
        return getattr(client, collection_name)

    def _user_records(self, client: Any, *, strict: bool = True) -> list[dict[str, Any]]:
        try:
            response = self._collection_response(self._collection(client, "users"))
        except M365_ERROR_TYPES:
            raise

        records: list[dict[str, Any]] = []
        for user in self._response_values(response):
            user_id = str(self._field(user, "id", ""))
            if not user_id:
                continue
            records.append(
                {
                    "asset_type": "m365-user",
                    "asset_id": f"m365:user:{user_id}",
                    "name": self._field(user, "display_name", user_id),
                    "attributes": {
                        "user_id": user_id,
                        "display_name": self._field(user, "display_name", ""),
                        "user_principal_name": self._field(user, "user_principal_name", ""),
                        "mail": self._field(user, "mail", ""),
                        "account_enabled": self._field(user, "account_enabled", ""),
                        "job_title": self._field(user, "job_title", ""),
                        "department": self._field(user, "department", ""),
                        "created_date_time": self._format_value(self._field(user, "created_date_time", "")),
                    },
                }
            )
        return records

    def _group_records(self, client: Any, *, strict: bool = True) -> list[dict[str, Any]]:
        try:
            response = self._collection_response(self._collection(client, "groups"))
        except M365_ERROR_TYPES:
            raise

        records: list[dict[str, Any]] = []
        for group in self._response_values(response):
            group_id = str(self._field(group, "id", ""))
            if not group_id:
                continue
            records.append(
                {
                    "asset_type": "m365-group",
                    "asset_id": f"m365:group:{group_id}",
                    "name": self._field(group, "display_name", group_id),
                    "attributes": {
                        "group_id": group_id,
                        "display_name": self._field(group, "display_name", ""),
                        "mail": self._field(group, "mail", ""),
                        "mail_enabled": self._field(group, "mail_enabled", ""),
                        "security_enabled": self._field(group, "security_enabled", ""),
                        "group_types": self._field(group, "group_types", []),
                        "created_date_time": self._format_value(self._field(group, "created_date_time", "")),
                    },
                }
            )
        return records

    def _application_records(self, client: Any, *, strict: bool = True) -> list[dict[str, Any]]:
        try:
            response = self._collection_response(self._collection(client, "applications"))
        except M365_ERROR_TYPES:
            raise

        records: list[dict[str, Any]] = []
        for application in self._response_values(response):
            application_id = str(self._field(application, "id", ""))
            if not application_id:
                continue
            records.append(
                {
                    "asset_type": "m365-application",
                    "asset_id": f"m365:application:{application_id}",
                    "name": self._field(application, "display_name", application_id),
                    "attributes": {
                        "application_id": application_id,
                        "app_id": self._field(application, "app_id", ""),
                        "display_name": self._field(application, "display_name", ""),
                        "sign_in_audience": self._field(application, "sign_in_audience", ""),
                        "created_date_time": self._format_value(self._field(application, "created_date_time", "")),
                    },
                }
            )
        return records

    def _service_principal_records(self, client: Any, *, strict: bool = True) -> list[dict[str, Any]]:
        try:
            response = self._collection_response(self._collection(client, "service_principals"))
        except M365_ERROR_TYPES:
            raise

        records: list[dict[str, Any]] = []
        for service_principal in self._response_values(response):
            service_principal_id = str(self._field(service_principal, "id", ""))
            if not service_principal_id:
                continue
            records.append(
                {
                    "asset_type": "m365-service-principal",
                    "asset_id": f"m365:service-principal:{service_principal_id}",
                    "name": self._field(service_principal, "display_name", service_principal_id),
                    "attributes": {
                        "service_principal_id": service_principal_id,
                        "app_id": self._field(service_principal, "app_id", ""),
                        "display_name": self._field(service_principal, "display_name", ""),
                        "service_principal_type": self._field(service_principal, "service_principal_type", ""),
                        "account_enabled": self._field(service_principal, "account_enabled", ""),
                        "app_owner_organization_id": self._field(
                            service_principal,
                            "app_owner_organization_id",
                            "",
                        ),
                    },
                }
            )
        return records

    def _conditional_access_policy_records(self, client: Any, *, strict: bool = True) -> list[dict[str, Any]]:
        try:
            conditional_access = self._collection(client, "identity").conditional_access
            response = self._collection_response(conditional_access.policies)
        except M365_ERROR_TYPES:
            raise

        records: list[dict[str, Any]] = []
        for policy in self._response_values(response):
            policy_id = str(self._field(policy, "id", ""))
            if not policy_id:
                continue
            records.append(
                {
                    "asset_type": "m365-conditional-access-policy",
                    "asset_id": f"m365:conditional-access-policy:{policy_id}",
                    "name": self._field(policy, "display_name", policy_id),
                    "attributes": {
                        "policy_id": policy_id,
                        "display_name": self._field(policy, "display_name", ""),
                        "state": self._field(policy, "state", ""),
                        "created_date_time": self._format_value(self._field(policy, "created_date_time", "")),
                        "modified_date_time": self._format_value(self._field(policy, "modified_date_time", "")),
                    },
                }
            )
        return records

    def collect_detailed(self, config: M365Config = None, *, preview: bool = False) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation["ok"]:
            return {"result": self._invalid_result(validation["errors"]), "outcomes": []}
        limit = self._config_limit(config, default=10 if preview else None)
        if limit == 0:
            limit_outcomes = [truncation_outcome(f"{self.module_id}:limit", limit=limit)]
            return {
                "result": self._result([], preview=preview, outcomes=limit_outcomes),
                "outcomes": limit_outcomes,
            }
        client = self._client(config)
        records: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        sources = (
            ("users", lambda: self._user_records(client, strict=True)),
            ("groups", lambda: self._group_records(client, strict=True)),
            ("applications", lambda: self._application_records(client, strict=True)),
            ("service-principals", lambda: self._service_principal_records(client, strict=True)),
            ("conditional-access-policies", lambda: self._conditional_access_policy_records(client, strict=True)),
        )
        for source_id, read_source in sources:
            try:
                records.extend(read_source())
            except Exception as exc:
                outcomes.append(
                    provider_outcome(
                        source_id,
                        exc,
                        permission_hint=(
                            "Grant the Microsoft Graph read-only permissions listed in "
                            "docs/connectors/cloud-permissions-m365.md."
                        ),
                    )
                )
        records.sort(key=lambda record: str(record["asset_id"]))
        truncated = limit is not None and len(records) > limit
        if limit is not None:
            records = records[:limit]
        if truncated and limit is not None:
            outcomes.append(truncation_outcome(f"{self.module_id}:limit", limit=limit))
        return {"result": self._result(records, preview=preview, outcomes=outcomes), "outcomes": outcomes}

    def _collection_response(self, collection: Any) -> Any:
        response = self._resolve(collection.get())
        values = self._response_values(response)
        next_link = self._next_link(response)
        seen_links: set[str] = set()
        while next_link:
            link = str(next_link)
            if link in seen_links:
                raise RuntimeError("provider pagination did not advance")
            seen_links.add(link)
            with_url = getattr(collection, "with_url", None)
            if not callable(with_url):
                raise RuntimeError("provider returned a next page without a supported page request")
            response = self._resolve(with_url(link).get())
            values.extend(self._response_values(response))
            next_link = self._next_link(response)
        return {"value": values}

    @staticmethod
    def _resolve(value: object) -> Any:
        if not inspect.isawaitable(value):
            return value

        coroutine: Coroutine[Any, Any, Any]
        if inspect.iscoroutine(value):
            coroutine = value
        else:
            coroutine = M365InventoryConnector._awaitable_result(value)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        results: list[Any] = []
        errors: list[BaseException] = []

        def _run() -> None:
            try:
                results.append(asyncio.run(coroutine))
            except BaseException as exc:  # pragma: no cover - defensive handoff from worker thread
                errors.append(exc)

        thread = threading.Thread(target=_run)
        thread.start()
        thread.join()
        if errors:
            raise errors[0]
        return results[0] if results else None

    @staticmethod
    async def _awaitable_result(value: Awaitable[Any]) -> Any:
        return await value

    @staticmethod
    def _response_values(response: Any) -> list[Any]:
        if response is None:
            return []
        if isinstance(response, list):
            return response
        if isinstance(response, Mapping):
            value = response.get("value", [])
            return list(value) if isinstance(value, list) else []
        value = getattr(response, "value", [])
        return list(value) if isinstance(value, list) else []

    @staticmethod
    def _next_link(response: Any) -> str | None:
        if isinstance(response, Mapping):
            for key in ("@odata.nextLink", "odata_next_link", "odataNextLink"):
                value = response.get(key)
                if isinstance(value, str) and value:
                    return value
            return None
        for key in ("odata_next_link", "odataNextLink"):
            value = getattr(response, key, None)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _field(record: Any, field_name: str, default: Any) -> Any:
        if isinstance(record, Mapping):
            return record.get(field_name, default)
        return getattr(record, field_name, default)

    @staticmethod
    def _has_collection(client: Any, collection_name: str) -> bool:
        collection = getattr(client, collection_name, None)
        return callable(getattr(collection, "get", None))

    @classmethod
    def _has_graph_client_shape(cls, client: Any) -> bool:
        if not all(
            cls._has_collection(client, collection_name)
            for collection_name in ["users", "groups", "applications", "service_principals"]
        ):
            return False
        identity = getattr(client, "identity", None)
        conditional_access = getattr(identity, "conditional_access", None)
        policies = getattr(conditional_access, "policies", None)
        return callable(getattr(policies, "get", None))

    def _result(
        self,
        records: list[dict[str, Any]],
        *,
        preview: bool,
        outcomes: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        assets = [self._asset(record) for record in records]
        observations = [
            observation
            for record in records
            for observation in self._observations(record)
        ]
        status = result_status(len(assets), outcomes)
        result = {
            "module_id": self.module_id,
            "ok": status in {"success", "empty"},
            "status": status,
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
        errors = result_errors(outcomes)
        if errors:
            result["errors"] = errors
        return result

    @staticmethod
    def _invalid_result(errors: list[str]) -> dict[str, Any]:
        return {
            "module_id": M365InventoryConnector.module_id,
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
