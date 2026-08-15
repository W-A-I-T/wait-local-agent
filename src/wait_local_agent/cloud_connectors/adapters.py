"""Governed typed adapters for the optional cloud inventory connectors."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from wait_local_agent.cloud_connectors.aws import AwsInventoryConnector
from wait_local_agent.cloud_connectors.azure import AzureInventoryConnector
from wait_local_agent.cloud_connectors.gcp import GCPInventoryConnector
from wait_local_agent.cloud_connectors.m365 import M365InventoryConnector
from wait_local_agent.models import AssetObservationWrite
from wait_local_agent.vault import SecretVault, SecretVaultError

if TYPE_CHECKING:
    from wait_local_agent.collectors import (
        CollectionStatus,
        CollectorAssetWrite,
        CollectorManifest,
        CollectorPreview,
        CollectorResult,
        CollectorValidationResult,
        SourceOutcome,
    )


def _load_collector_contracts() -> None:
    if "CollectionStatus" not in globals():
        from wait_local_agent.collectors import (
            CollectionStatus as _CollectionStatus,
        )
        from wait_local_agent.collectors import (
            CollectorAssetWrite as _CollectorAssetWrite,
        )
        from wait_local_agent.collectors import (
            CollectorManifest as _CollectorManifest,
        )
        from wait_local_agent.collectors import (
            CollectorPreview as _CollectorPreview,
        )
        from wait_local_agent.collectors import (
            CollectorResult as _CollectorResult,
        )
        from wait_local_agent.collectors import (
            CollectorValidationResult as _CollectorValidationResult,
        )
        from wait_local_agent.collectors import (
            SourceOutcome as _SourceOutcome,
        )

        globals().update(
            {
                "CollectionStatus": _CollectionStatus,
                "CollectorAssetWrite": _CollectorAssetWrite,
                "CollectorManifest": _CollectorManifest,
                "CollectorPreview": _CollectorPreview,
                "CollectorResult": _CollectorResult,
                "CollectorValidationResult": _CollectorValidationResult,
                "SourceOutcome": _SourceOutcome,
            }
        )


class CloudCredentialError(RuntimeError):
    """Raised internally when a vault reference cannot produce a provider client."""


RuntimeConfigFactory = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class CloudAdapterSpec:
    module_id: str
    name: str
    description: str
    scopes: tuple[str, ...]
    config_fields: tuple[dict[str, Any], ...]
    provider_keys: frozenset[str]
    permission_hint: str


class CloudConnectorAdapter:
    """Adapt a legacy cloud connector to the governed collector contract."""

    connector_type: type[Any]
    spec: CloudAdapterSpec

    def __init__(
        self,
        connector: Any | None = None,
        *,
        vault: SecretVault | None = None,
        runtime_config_factory: RuntimeConfigFactory | None = None,
    ) -> None:
        _load_collector_contracts()
        self.connector = connector or self.connector_type()
        self.vault = vault
        self.runtime_config_factory = runtime_config_factory
        provider_manifest = self.connector.manifest()
        self.manifest = CollectorManifest(
            id=self.spec.module_id,
            name=self.spec.name,
            version=str(provider_manifest.get("version", "1.0")),
            description=self.spec.description,
            capabilities=("cloud_inventory", "safe_read_only"),
            scopes=self.spec.scopes,
            report_types=("collector_bundle",),
            platforms=("cloud",),
            config_schema=self.spec.config_fields,
        )

    def validate_config(self, config: dict[str, Any]) -> CollectorValidationResult:
        if not isinstance(config, dict):
            return self._invalid_validation("collector config must be a mapping", ["config must be a mapping"])

        errors: list[str] = []
        credential_ref = config.get("credential_ref")
        if not isinstance(credential_ref, str) or not credential_ref.strip():
            errors.append("credential_ref must be a non-empty vault reference")
        for field in self.spec.config_fields:
            name = field.get("name")
            if field.get("required") and name != "credential_ref" and name not in config:
                errors.append(f"{name} is required")
        vault_path = config.get("vault_path")
        if vault_path is not None and (not isinstance(vault_path, str) or not vault_path.strip()):
            errors.append("vault_path must be a non-empty path when provided")
        unsupported = sorted(set(config) - (self.spec.provider_keys | {"credential_ref", "vault_path"}))
        if unsupported:
            errors.append(f"unsupported config keys: {', '.join(unsupported)}")
        provider_config = {key: value for key, value in config.items() if key in self.spec.provider_keys}
        provider_validation = self.connector.validate_config(provider_config)
        errors.extend(str(error) for error in provider_validation.get("errors", []))
        if errors:
            return self._invalid_validation("collector configuration is invalid", errors)

        normalized = {
            key: config[key]
            for key in ("credential_ref", "vault_path", *sorted(self.spec.provider_keys))
            if key in config
        }
        preflight = self._preflight(normalized)
        status = preflight.status.value
        message = f"ok; preflight={status}"
        if preflight.remediation_hint:
            message = f"{message}; {preflight.remediation_hint}"
        return CollectorValidationResult(
            module_id=self.manifest.id,
            passed=True,
            message=message,
            normalized_config=normalized,
        )

    def preview(self, config: dict[str, Any]) -> CollectorPreview:
        validation = self.validate_config(config)
        if not validation.passed:
            raise ValueError(validation.message)
        normalized = validation.normalized_config
        preflight = self._preflight(normalized)
        warnings: list[str] = []
        if preflight.status is not CollectionStatus.SUCCESS:
            warnings.append(preflight.remediation_hint or "Cloud credential preflight did not succeed.")
            return CollectorPreview(
                module_id=self.manifest.id,
                source_name=self.manifest.id,
                scopes=list(self.manifest.scopes),
                estimated_assets=0,
                estimated_observations=0,
                expected_reports=list(self.manifest.report_types),
                warnings=warnings,
                metadata={"status": preflight.status.value},
            )
        detailed = self._collect_detailed(normalized, preview=True)
        records = detailed.get("result", {}).get("assets", [])
        outcomes = self._outcomes(detailed.get("outcomes", []))
        outcomes = self._include_result_outcome(detailed.get("result", {}), outcomes)
        warnings.extend(
            outcome.remediation_hint or outcome.error_detail or "Cloud source unavailable." for outcome in outcomes
        )
        return CollectorPreview(
            module_id=self.manifest.id,
            source_name=self.manifest.id,
            scopes=list(self.manifest.scopes),
            estimated_assets=len(records),
            estimated_observations=len(detailed.get("result", {}).get("observations", [])),
            expected_reports=list(self.manifest.report_types),
            warnings=warnings,
            metadata={"status": self._status_for_outcomes(len(records), outcomes).value},
        )

    def collect(self, config: dict[str, Any]) -> CollectorResult:
        validation = self.validate_config(config)
        if not validation.passed:
            raise ValueError(validation.message)
        normalized = validation.normalized_config
        preflight = self._preflight(normalized)
        if preflight.status is not CollectionStatus.SUCCESS:
            return CollectorResult(status=preflight.status, source_outcomes=(preflight,))
        detailed = self._collect_detailed(normalized, preview=False)
        raw_result = detailed.get("result", {})
        outcomes = self._outcomes(detailed.get("outcomes", []))
        outcomes = self._include_result_outcome(raw_result, outcomes)
        records = raw_result.get("assets", [])
        assets = [
            CollectorAssetWrite(
                canonical_id=str(asset["asset_id"]),
                asset_type=str(asset["asset_type"]),
                display_name=str(asset.get("name") or asset["asset_id"]),
                attributes=dict(asset.get("attributes", {})),
                source_module=self.manifest.id,
                source_id=str(asset["asset_id"]),
            )
            for asset in records
        ]
        observations = [
            AssetObservationWrite(
                canonical_id=str(observation["asset_id"]),
                observation_type=f"{self.manifest.id}.metadata",
                payload={
                    "asset_type": observation.get("asset_type", ""),
                    "key": observation.get("key", "value"),
                    "value": observation.get("value"),
                },
            )
            for observation in raw_result.get("observations", [])
        ]
        status = self._status_for_outcomes(len(assets), outcomes)
        return CollectorResult(
            assets=assets,
            observations=observations,
            metadata={"provider": self.connector.module_id, "status": status.value},
            status=status,
            source_outcomes=outcomes,
        )

    def _collect_detailed(self, config: dict[str, Any], *, preview: bool) -> dict[str, Any]:
        try:
            runtime = self._runtime_config(config)
            detailed = getattr(self.connector, "collect_detailed", None)
            if callable(detailed):
                return detailed(runtime, preview=preview)
            result = self.connector.preview(runtime) if preview else self.connector.collect(runtime)
            return {"result": result, "outcomes": self._legacy_result_outcomes(result)}
        except Exception as exc:
            outcome = self._outcome_from_exception("collection", exc)
            safe_result = {
                "module_id": self.manifest.id,
                "ok": False,
                "status": outcome.status.value,
                "assets": [],
                "observations": [],
                "errors": [f"{outcome.error_code}: {outcome.error_detail}"],
            }
            return {"result": safe_result, "outcomes": [asdict(outcome)]}

    def _preflight(self, config: dict[str, Any]) -> SourceOutcome:
        try:
            runtime = self._runtime_config(config)
            preflight = getattr(self.connector, "preflight", None)
            if not callable(preflight):
                raise RuntimeError("provider connector does not implement credential preflight")
            preflight(runtime)
        except Exception as exc:
            return self._outcome_from_exception("preflight", exc)
        return SourceOutcome(source_id=f"{self.manifest.id}:preflight", status=CollectionStatus.SUCCESS)

    def _runtime_config(self, config: dict[str, Any]) -> dict[str, Any]:
        credential_ref = str(config["credential_ref"])
        secret = self._read_secret(config, credential_ref)
        provider_config = {key: config[key] for key in self.spec.provider_keys if key in config}
        if self.runtime_config_factory is not None:
            try:
                factory_result = self.runtime_config_factory(MappingProxyType(dict(provider_config)))
            except Exception as exc:
                raise CloudCredentialError("runtime configuration factory failed") from exc
            if not isinstance(factory_result, Mapping):
                raise CloudCredentialError("runtime configuration factory must return a mapping")
            allowed_runtime_keys = {"client", "credential", "session"}
            if set(factory_result) - allowed_runtime_keys:
                raise CloudCredentialError("runtime configuration factory returned unsupported fields")
            if self._contains_secret(factory_result, secret):
                raise CloudCredentialError("runtime configuration factory returned credential material")
            provider_config.update(dict(factory_result))
            self._validate_runtime_config(provider_config)
            return provider_config
        if self.manifest.id == "cloud-aws":
            provider_config["session"] = self._aws_session(secret, provider_config)
        elif self.manifest.id == "cloud-azure":
            provider_config["credential"] = self._azure_credential(secret)
        elif self.manifest.id == "cloud-gcp":
            provider_config["session"] = self._gcp_session(secret, provider_config)
        elif self.manifest.id == "cloud-m365":
            provider_config["credential"] = self._azure_credential(secret)
        return provider_config

    def _validate_runtime_config(self, runtime: dict[str, Any]) -> None:
        validation = self.connector.validate_config(runtime)
        if not validation.get("ok"):
            raise CloudCredentialError("runtime configuration factory returned invalid configuration")

    @staticmethod
    def _contains_secret(value: Any, secret: str) -> bool:
        if isinstance(value, str):
            return bool(secret) and secret in value
        if isinstance(value, Mapping):
            return any(
                CloudConnectorAdapter._contains_secret(key, secret)
                or CloudConnectorAdapter._contains_secret(item, secret)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple, set, frozenset)):
            return any(CloudConnectorAdapter._contains_secret(item, secret) for item in value)
        return False

    def _read_secret(self, config: dict[str, Any], credential_ref: str) -> str:
        vault = self.vault or SecretVault(
            Path(str(config.get("vault_path") or os.getenv("WAIT_VAULT_PATH", ".wait-local-agent/vault")))
        )
        try:
            secret = vault.get(credential_ref)
        except (SecretVaultError, ValueError) as exc:
            raise CloudCredentialError("credential reference could not be read") from exc
        if not secret:
            raise CloudCredentialError("credential reference was not found")
        return secret

    @staticmethod
    def _secret_mapping(secret: str) -> dict[str, Any]:
        try:
            value = json.loads(secret)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CloudCredentialError("credential value is not valid JSON") from exc
        if not isinstance(value, dict):
            raise CloudCredentialError("credential value must be a JSON object")
        return value

    @classmethod
    def _aws_session(cls, secret: str, config: dict[str, Any]) -> Any:
        boto3 = import_module("boto3")
        values = cls._secret_mapping(secret)
        allowed: dict[str, Any] = {
            key: values[key]
            for key in ("aws_access_key_id", "aws_secret_access_key", "aws_session_token")
            if key in values
        }
        if not allowed:
            raise CloudCredentialError("AWS credential value has no supported fields")
        if "region_name" not in allowed and isinstance(config.get("region"), str):
            allowed["region_name"] = config["region"]
        return boto3.Session(**allowed)

    @classmethod
    def _azure_credential(cls, secret: str) -> Any:
        values = cls._secret_mapping(secret)
        required = ("tenant_id", "client_id", "client_secret")
        if any(not isinstance(values.get(key), str) or not values[key] for key in required):
            raise CloudCredentialError("client credential value is incomplete")
        credential_type = import_module("azure.identity").ClientSecretCredential
        return credential_type(
            tenant_id=values["tenant_id"],
            client_id=values["client_id"],
            client_secret=values["client_secret"],
        )

    @classmethod
    def _gcp_session(cls, secret: str, config: dict[str, Any]) -> Any:
        values = cls._secret_mapping(secret)
        credentials_type = import_module("google.oauth2.service_account").Credentials
        credentials = credentials_type.from_service_account_info(values)
        from wait_local_agent.cloud_connectors.gcp import _GoogleCloudSession

        return _GoogleCloudSession(credentials=credentials, project_id=config.get("project_id", ""))

    def _outcomes(self, raw_outcomes: Any) -> tuple[SourceOutcome, ...]:
        outcomes: list[SourceOutcome] = []
        if not isinstance(raw_outcomes, list):
            return ()
        for raw in raw_outcomes:
            if not isinstance(raw, Mapping):
                continue
            source_id = str(raw.get("source_id", self.manifest.id))
            error = raw.get("exception")
            if isinstance(error, BaseException):
                outcomes.append(self._outcome_from_exception(source_id, error))
                continue
            status = self._status_from_value(raw.get("status"))
            outcomes.append(
                SourceOutcome(
                    source_id=source_id,
                    status=status,
                    record_count=int(raw.get("record_count", 0)),
                    error_code=str(raw["error_code"]) if raw.get("error_code") else None,
                    error_detail=str(raw["error_detail"]) if raw.get("error_detail") else None,
                    remediation_hint=str(raw["remediation_hint"]) if raw.get("remediation_hint") else None,
                )
            )
        return tuple(outcomes)

    def _legacy_result_outcomes(self, result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, Mapping):
            return [
                {
                    "source_id": self.manifest.id,
                    "status": "unavailable",
                    "error_code": "invalid_result",
                    "error_detail": "provider returned an invalid collection result",
                }
            ]
        status = str(result.get("status", ""))
        if result.get("ok") is False or status not in {"", "success", "empty"}:
            return [
                {
                    "source_id": self.manifest.id,
                    "status": status if status in {"not_authorized", "unavailable", "partial"} else "unavailable",
                    "error_code": "collection_failed",
                    "error_detail": "provider collection did not complete successfully",
                }
            ]
        return []

    def _include_result_outcome(
        self, result: Any, outcomes: tuple[SourceOutcome, ...]
    ) -> tuple[SourceOutcome, ...]:
        if outcomes or not isinstance(result, Mapping):
            return outcomes
        raw = self._legacy_result_outcomes(result)
        return self._outcomes(raw)

    def _outcome_from_exception(self, source_id: str, exc: BaseException) -> SourceOutcome:
        status = self._classify_exception(exc)
        if status is CollectionStatus.NOT_AUTHORIZED:
            return SourceOutcome(
                source_id=f"{self.manifest.id}:{source_id}",
                status=status,
                error_code="permission_denied",
                error_detail="provider authorization was rejected",
                remediation_hint=self.spec.permission_hint,
            )
        if isinstance(exc, (ImportError, ModuleNotFoundError)):
            return SourceOutcome(
                source_id=f"{self.manifest.id}:{source_id}",
                status=CollectionStatus.UNAVAILABLE,
                error_code="sdk_unavailable",
                error_detail="the provider SDK is not installed",
                remediation_hint="Install the optional provider SDK and retry.",
            )
        return SourceOutcome(
            source_id=f"{self.manifest.id}:{source_id}",
            status=CollectionStatus.UNAVAILABLE,
            error_code="collection_unavailable",
            error_detail="provider service was unavailable",
            remediation_hint="Verify provider connectivity and retry.",
        )

    @staticmethod
    def _classify_exception(exc: BaseException) -> CollectionStatus:
        if isinstance(exc, PermissionError):
            return CollectionStatus.NOT_AUTHORIZED
        name = exc.__class__.__name__.lower()
        status_code = getattr(exc, "status_code", None) or getattr(exc, "response_status_code", None)
        if status_code in {401, 403} or any(
            token in name for token in ("auth", "credential", "permission", "accessdenied")
        ):
            return CollectionStatus.NOT_AUTHORIZED
        error_code = getattr(exc, "code", None)
        error = getattr(exc, "error", None)
        if error_code is None and error is not None:
            error_code = getattr(error, "code", None)
        if str(error_code) in {"401", "403", "AccessDenied", "UnauthorizedOperation", "InvalidClientTokenId"}:
            return CollectionStatus.NOT_AUTHORIZED
        response = getattr(exc, "response", None)
        if isinstance(response, Mapping):
            error = response.get("Error") or response.get("error")
            if isinstance(error, Mapping) and (
                error.get("Code") in {"AccessDenied", "UnauthorizedOperation", "InvalidClientTokenId"}
            ):
                return CollectionStatus.NOT_AUTHORIZED
        return CollectionStatus.UNAVAILABLE

    @staticmethod
    def _status_from_value(value: Any) -> CollectionStatus:
        try:
            return CollectionStatus(str(value))
        except ValueError:
            return CollectionStatus.UNAVAILABLE

    @staticmethod
    def _status_for_outcomes(record_count: int, outcomes: tuple[SourceOutcome, ...]) -> CollectionStatus:
        failures = tuple(outcome for outcome in outcomes if outcome.status is not CollectionStatus.SUCCESS)
        if not failures:
            return CollectionStatus.SUCCESS if record_count else CollectionStatus.EMPTY
        if record_count:
            return CollectionStatus.PARTIAL
        statuses = {outcome.status for outcome in failures}
        if statuses == {CollectionStatus.NOT_AUTHORIZED}:
            return CollectionStatus.NOT_AUTHORIZED
        if statuses == {CollectionStatus.UNAVAILABLE}:
            return CollectionStatus.UNAVAILABLE
        return CollectionStatus.PARTIAL

    def _invalid_validation(self, message: str, errors: list[str]) -> CollectorValidationResult:
        return CollectorValidationResult(module_id=self.manifest.id, passed=False, message=message, errors=errors)


class AwsCloudAdapter(CloudConnectorAdapter):
    connector_type = AwsInventoryConnector
    spec = CloudAdapterSpec(
        module_id="cloud-aws",
        name="AWS Cloud Inventory",
        description="Governed read-only AWS inventory through a vault-backed credential reference.",
        scopes=("aws:ec2", "aws:s3", "aws:iam"),
        provider_keys=frozenset({"limit", "region"}),
        config_fields=(
            {
                "name": "credential_ref",
                "label": "Vault credential",
                "help": (
                    "Vault key containing the AWS read-only credential JSON. "
                    "See docs/connectors/cloud-permissions-aws.md."
                ),
                "type": "secret_ref",
                "required": True,
                "default": None,
            },
            {
                "name": "region",
                "label": "AWS region",
                "help": "Optional AWS region override.",
                "type": "string",
                "required": False,
                "default": None,
            },
            {
                "name": "vault_path",
                "label": "Vault path",
                "help": "Optional path to the local credential vault.",
                "type": "string",
                "required": False,
                "default": None,
            },
            {
                "name": "limit",
                "label": "Maximum resources",
                "help": "Optional maximum number of resources returned after the full read-only scan.",
                "type": "number",
                "required": False,
                "default": None,
            },
        ),
        permission_hint="Grant the AWS read-only permissions listed in docs/connectors/cloud-permissions-aws.md.",
    )


class AzureCloudAdapter(CloudConnectorAdapter):
    connector_type = AzureInventoryConnector
    spec = CloudAdapterSpec(
        module_id="cloud-azure",
        name="Azure Cloud Inventory",
        description="Governed read-only Azure inventory through a vault-backed credential reference.",
        scopes=("azure:compute", "azure:storage", "azure:network", "azure:authorization"),
        provider_keys=frozenset({"limit", "subscription_id"}),
        config_fields=(
            {
                "name": "credential_ref",
                "label": "Vault credential",
                "help": (
                    "Vault key containing the Azure client credential JSON. "
                    "See docs/connectors/cloud-permissions-azure.md."
                ),
                "type": "secret_ref",
                "required": True,
                "default": None,
            },
            {
                "name": "subscription_id",
                "label": "Subscription",
                "help": "Azure subscription to inventory.",
                "type": "string",
                "required": True,
                "default": None,
            },
            {
                "name": "vault_path",
                "label": "Vault path",
                "help": "Optional path to the local credential vault.",
                "type": "string",
                "required": False,
                "default": None,
            },
            {
                "name": "limit",
                "label": "Maximum resources",
                "help": "Optional maximum number of resources returned after the full read-only scan.",
                "type": "number",
                "required": False,
                "default": None,
            },
        ),
        permission_hint=(
            "Grant the Azure read-only role and permissions listed in "
            "docs/connectors/cloud-permissions-azure.md."
        ),
    )


class GcpCloudAdapter(CloudConnectorAdapter):
    connector_type = GCPInventoryConnector
    spec = CloudAdapterSpec(
        module_id="cloud-gcp",
        name="GCP Cloud Inventory",
        description="Governed read-only GCP inventory through a vault-backed credential reference.",
        scopes=("gcp:resourcemanager", "gcp:compute", "gcp:storage", "gcp:iam"),
        provider_keys=frozenset({"limit", "project_id", "zone"}),
        config_fields=(
            {
                "name": "credential_ref",
                "label": "Vault credential",
                "help": (
                    "Vault key containing the GCP service-account JSON. "
                    "See docs/connectors/cloud-permissions-gcp.md."
                ),
                "type": "secret_ref",
                "required": True,
                "default": None,
            },
            {
                "name": "project_id",
                "label": "Project",
                "help": "Optional project to inventory; omit to discover accessible projects.",
                "type": "string",
                "required": False,
                "default": None,
            },
            {
                "name": "vault_path",
                "label": "Vault path",
                "help": "Optional path to the local credential vault.",
                "type": "string",
                "required": False,
                "default": None,
            },
            {
                "name": "zone",
                "label": "Compute zone",
                "help": "Optional Compute Engine zone filter.",
                "type": "string",
                "required": False,
                "default": None,
            },
            {
                "name": "limit",
                "label": "Maximum resources",
                "help": "Optional maximum number of resources returned after the full read-only scan.",
                "type": "number",
                "required": False,
                "default": None,
            },
        ),
        permission_hint="Grant the GCP read-only roles listed in docs/connectors/cloud-permissions-gcp.md.",
    )


class M365CloudAdapter(CloudConnectorAdapter):
    connector_type = M365InventoryConnector
    spec = CloudAdapterSpec(
        module_id="cloud-m365",
        name="Microsoft 365 Cloud Inventory",
        description="Governed read-only Microsoft 365 inventory through a vault-backed credential reference.",
        scopes=(
            "m365:users",
            "m365:groups",
            "m365:applications",
            "m365:service-principals",
            "m365:conditional-access-policies",
        ),
        provider_keys=frozenset({"limit", "scopes"}),
        config_fields=(
            {
                "name": "credential_ref",
                "label": "Vault credential",
                "help": (
                    "Vault key containing the M365 client credential JSON. "
                    "See docs/connectors/cloud-permissions-m365.md."
                ),
                "type": "secret_ref",
                "required": True,
                "default": None,
            },
            {
                "name": "scopes",
                "label": "Microsoft Graph scopes",
                "help": "Optional delegated/application scope list; defaults to Microsoft Graph .default.",
                "type": "array",
                "items": {"type": "string"},
                "required": False,
                "default": None,
            },
            {
                "name": "vault_path",
                "label": "Vault path",
                "help": "Optional path to the local credential vault.",
                "type": "string",
                "required": False,
                "default": None,
            },
            {
                "name": "limit",
                "label": "Maximum resources",
                "help": "Optional maximum number of resources returned after the full read-only scan.",
                "type": "number",
                "required": False,
                "default": None,
            },
        ),
        permission_hint=(
            "Grant the Microsoft Graph read-only permissions listed in "
            "docs/connectors/cloud-permissions-m365.md."
        ),
    )


__all__ = [
    "AwsCloudAdapter",
    "AzureCloudAdapter",
    "CloudConnectorAdapter",
    "GcpCloudAdapter",
    "M365CloudAdapter",
]
