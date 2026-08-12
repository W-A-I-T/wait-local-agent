from __future__ import annotations

import json
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, cast

import pytest

import wait_local_agent.cloud_connectors._safe as safe_module
import wait_local_agent.cloud_connectors.adapters as adapters_module
from wait_local_agent.cloud_connectors.adapters import (
    AwsCloudAdapter,
    AzureCloudAdapter,
    CloudCredentialError,
    GcpCloudAdapter,
)
from wait_local_agent.collectors import (
    CollectionStatus,
    CollectorRegistry,
    CollectorService,
    SourceOutcome,
    default_registry,
)
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault, SecretVaultError


class _AccessDeniedError(Exception):
    pass


class _FakeConnector:
    module_id = "aws-inventory"

    def __init__(
        self, *, preflight_error: Exception | None = None, records: list[dict[str, Any]] | None = None
    ) -> None:
        self.preflight_error = preflight_error
        self.records = records or []
        self.seen_runtime: list[dict[str, Any]] = []

    def manifest(self) -> dict[str, Any]:
        return {"version": "1.0"}

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "errors": []}

    def preflight(self, config: dict[str, Any]) -> None:
        self.seen_runtime.append(config)
        if self.preflight_error is not None:
            raise self.preflight_error

    def collect_detailed(self, config: dict[str, Any], *, preview: bool) -> dict[str, Any]:
        self.seen_runtime.append(config)
        return {
            "result": {
                "assets": self.records,
                "observations": [
                    {
                        "asset_id": record["asset_id"],
                        "asset_type": record["asset_type"],
                        "key": "cloud.name",
                        "value": record["name"],
                    }
                    for record in self.records
                ],
            },
            "outcomes": [],
        }


class _LegacyConnector(_FakeConnector):
    collect_detailed = None  # type: ignore[assignment]

    def preview(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"assets": self.records, "observations": []}

    def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"assets": self.records, "observations": []}


def test_safe_cloud_outcomes_classify_provider_failures_and_bounds() -> None:
    class _AccessDeniedByName(Exception):
        pass

    class _StatusError(Exception):
        status_code = 403

    class _NestedCode:
        code = "UnauthorizedOperation"

    class _NestedError(Exception):
        error = _NestedCode()

    class _ResponseError(Exception):
        response = {"Error": {"Code": "AccessDenied"}}

    assert safe_module.provider_outcome(
        "aws", PermissionError(), permission_hint="check IAM"
    )["status"] == "not_authorized"
    assert safe_module.provider_outcome(
        "aws", _AccessDeniedByName(), permission_hint="check IAM"
    )["status"] == "not_authorized"
    assert safe_module.provider_outcome(
        "aws", _StatusError(), permission_hint="check IAM"
    )["status"] == "not_authorized"
    assert safe_module.provider_outcome(
        "aws", _NestedError(), permission_hint="check IAM"
    )["status"] == "not_authorized"
    assert safe_module.provider_outcome(
        "aws", _ResponseError(), permission_hint="check IAM"
    )["status"] == "not_authorized"
    assert safe_module.provider_outcome(
        "aws", ImportError(), permission_hint="check IAM"
    )["error_code"] == "sdk_unavailable"
    assert safe_module.provider_outcome(
        "aws", RuntimeError(), permission_hint="check IAM"
    )["error_code"] == "collection_unavailable"
    assert safe_module.truncation_outcome("aws", limit=3)["status"] == "partial"
    assert safe_module.result_status(0, []) == "empty"
    assert safe_module.result_status(2, [{"status": "unavailable"}]) == "partial"
    assert safe_module.result_status(0, [{"status": "not_authorized"}]) == "not_authorized"
    assert safe_module.result_status(0, [{"status": "unavailable"}]) == "unavailable"
    assert safe_module.result_status(0, [{"status": "partial"}]) == "partial"
    assert safe_module.result_errors([{"error_code": "bad", "error_detail": "failed"}, {"status": "empty"}]) == [
        "bad: failed"
    ]


class _ValidationConnector(_FakeConnector):
    def __init__(self, errors: list[str]) -> None:
        super().__init__()
        self.errors = errors

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"ok": not self.errors, "errors": self.errors}


class _NoPreflightConnector(_FakeConnector):
    preflight = None  # type: ignore[assignment]


class _BrokenVault:
    def __init__(self, error: Exception | None = None, value: str | None = None) -> None:
        self.error = error
        self.value = value

    def get(self, key: str) -> str | None:
        if self.error:
            raise self.error
        return self.value


def _vault(tmp_path) -> SecretVault:
    vault = SecretVault.initialize(tmp_path / "vault")
    vault.set("aws-readonly", "SUPER-SECRET-MATERIAL")
    return vault


def _adapter(tmp_path, connector: _FakeConnector) -> AwsCloudAdapter:
    return AwsCloudAdapter(
        connector=connector,
        vault=_vault(tmp_path),
        runtime_config_factory=lambda _config: {"session": "fake-runtime"},
    )


def test_registry_contains_four_governed_cloud_adapters() -> None:
    module_ids = {module.manifest.id for module in default_registry.list()}

    assert {"cloud-aws", "cloud-azure", "cloud-gcp", "cloud-m365"} <= module_ids
    assert len(module_ids) == 14


def test_authorization_preflight_is_not_reported_as_empty_and_secret_stays_runtime_only(tmp_path) -> None:
    connector = _FakeConnector(preflight_error=_AccessDeniedError("SUPER-SECRET-MATERIAL"))
    adapter = _adapter(tmp_path, connector)

    validation = adapter.validate_config({"credential_ref": "aws-readonly"})
    result = adapter.collect({"credential_ref": "aws-readonly"})

    assert validation.passed is True
    assert "SUPER-SECRET-MATERIAL" not in validation.message
    assert result.status is CollectionStatus.NOT_AUTHORIZED
    assert result.status is not CollectionStatus.EMPTY
    assert result.source_outcomes[0].remediation_hint
    assert all("SUPER-SECRET-MATERIAL" not in str(outcome) for outcome in result.source_outcomes)
    assert len(connector.seen_runtime) == 3
    assert all(runtime == {"session": "fake-runtime"} for runtime in connector.seen_runtime)


def test_successful_empty_cloud_read_is_empty(tmp_path) -> None:
    adapter = _adapter(tmp_path, _FakeConnector())

    result = adapter.collect({"credential_ref": "aws-readonly"})

    assert result.status is CollectionStatus.EMPTY
    assert result.source_outcomes == ()


def test_collector_service_persists_reference_but_not_credential_material(tmp_path) -> None:
    record = {
        "asset_type": "cloud-instance",
        "asset_id": "aws:ec2:i-1",
        "name": "i-1",
        "attributes": {"state": "running"},
    }
    adapter = _adapter(tmp_path, _FakeConnector(records=[record]))
    registry = CollectorRegistry()
    registry.register(adapter)
    store = Store(tmp_path / "state.db")

    run = CollectorService(store, registry).run(
        "cloud-aws",
        {"credential_ref": "aws-readonly"},
        confirm=True,
        client_id="test-client",
    )

    source = store.list_collector_sources(client_id="test-client")[0]
    assert '"credential_ref":"[redacted]"' in source.config_json
    assert "SUPER-SECRET-MATERIAL" not in source.config_json
    assert "SUPER-SECRET-MATERIAL" not in run.result_json
    assert json.loads(run.result_json)["status"] == "success"


def test_adapter_validation_and_preview_cover_invalid_and_failed_preflight(tmp_path) -> None:
    adapter = AzureCloudAdapter(
        connector=_ValidationConnector(["limit must be a non-negative integer"]),
        vault=_vault(tmp_path),
        runtime_config_factory=lambda _config: {"session": "fake-runtime"},
    )

    invalid = adapter.validate_config(
        {"credential_ref": " ", "vault_path": " ", "unexpected": True, "limit": "bad"}
    )
    assert invalid.passed is False
    assert "credential_ref must be a non-empty vault reference" in invalid.errors
    assert "vault_path must be a non-empty path when provided" in invalid.errors
    assert "subscription_id is required" in invalid.errors
    assert "unsupported config keys: unexpected" in invalid.errors
    assert "limit must be a non-negative integer" in invalid.errors

    with pytest.raises(ValueError, match="collector config must be a mapping"):
        adapter.preview([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="collector configuration is invalid"):
        adapter.collect({"credential_ref": "aws-readonly"})

    failing = AzureCloudAdapter(
        connector=_FakeConnector(preflight_error=RuntimeError("down")),
        vault=_vault(tmp_path),
        runtime_config_factory=lambda _config: {"session": "fake-runtime"},
    )
    config = {"credential_ref": "aws-readonly", "subscription_id": "sub-1"}
    preview = failing.preview(config)
    assert preview.estimated_assets == 0
    assert preview.metadata == {"status": "unavailable"}
    assert preview.warnings == ["Verify provider connectivity and retry."]


def test_adapter_legacy_collect_and_outcome_normalization(tmp_path) -> None:
    record = {"asset_id": "asset-1", "asset_type": "thing", "name": "Thing", "attributes": {"x": 1}}
    adapter = _adapter(tmp_path, _LegacyConnector(records=[record]))
    assert adapter.preview({"credential_ref": "aws-readonly"}).estimated_assets == 1
    result = adapter.collect({"credential_ref": "aws-readonly"})
    assert result.status is CollectionStatus.SUCCESS
    assert result.assets[0].display_name == "Thing"

    raw = [
        "ignored",
        {"source_id": "bad", "exception": PermissionError("no")},
        {
            "source_id": "ok",
            "status": "success",
            "record_count": 2,
            "error_code": "code",
            "error_detail": "detail",
            "remediation_hint": "hint",
        },
        {"source_id": "unknown", "status": "not-a-status"},
    ]
    outcomes = adapter._outcomes(raw)
    assert outcomes[0].status is CollectionStatus.NOT_AUTHORIZED
    assert outcomes[1].record_count == 2
    assert outcomes[1].remediation_hint == "hint"
    assert outcomes[2].status is CollectionStatus.UNAVAILABLE
    assert adapter._outcomes(None) == ()


def test_runtime_factory_receives_no_secret_and_rejects_secret_material(tmp_path) -> None:
    seen: list[Mapping[str, Any]] = []
    adapter = _adapter(tmp_path, _FakeConnector())

    def safe_factory(config: Mapping[str, Any]) -> Mapping[str, Any]:
        seen.append(config)
        return {"session": "safe-runtime"}

    adapter.runtime_config_factory = safe_factory

    runtime = adapter._runtime_config({"credential_ref": "aws-readonly"})

    assert runtime == {"session": "safe-runtime"}
    assert seen == [{}]
    assert "SUPER-SECRET-MATERIAL" not in repr(seen)

    adapter.runtime_config_factory = lambda _config: {"session": "SUPER-SECRET-MATERIAL"}
    with pytest.raises(CloudCredentialError, match="credential material"):
        adapter._runtime_config({"credential_ref": "aws-readonly"})


def test_runtime_factory_failure_is_safe_through_collector_service(tmp_path) -> None:
    secret = "SUPER-SECRET-MATERIAL"

    def failing_factory(_config: Mapping[str, Any]) -> Mapping[str, Any]:
        raise RuntimeError(secret)

    adapter = AwsCloudAdapter(
        connector=_FakeConnector(),
        vault=_vault(tmp_path),
        runtime_config_factory=failing_factory,
    )
    registry = CollectorRegistry()
    registry.register(adapter)
    store = Store(tmp_path / "state.db")

    run = CollectorService(store, registry).run(
        "cloud-aws",
        {"credential_ref": "aws-readonly"},
        confirm=True,
        client_id="factory-failure",
    )

    assert secret not in run.result_json


def test_cloud_manifest_schemas_are_ui_safe_and_include_vault_path() -> None:
    adapters = [AwsCloudAdapter(), AzureCloudAdapter(), GcpCloudAdapter(), adapters_module.M365CloudAdapter()]
    for adapter in adapters:
        fields = {field["name"]: field for field in adapter.manifest.config_schema}
        assert fields["vault_path"]["type"] == "string"
        assert all(
            field["type"] in {"string", "number", "boolean", "enum", "array", "secret_ref"}
            for field in fields.values()
        )
    scopes = {field["name"]: field for field in adapters[-1].manifest.config_schema}["scopes"]
    assert scopes["type"] == "array"
    assert scopes["items"] == {"type": "string"}


def test_adapter_handles_missing_preflight_and_provider_runtime_branches(monkeypatch, tmp_path) -> None:
    adapter = _adapter(tmp_path, _NoPreflightConnector())
    validation = adapter.validate_config({"credential_ref": "aws-readonly"})
    assert validation.passed is True
    assert "preflight=unavailable" in validation.message

    secret_vault = _BrokenVault(value="{}")
    aws = AwsCloudAdapter(connector=_FakeConnector(), vault=cast(Any, secret_vault))
    azure = AzureCloudAdapter(connector=_FakeConnector(), vault=cast(Any, secret_vault))
    gcp = GcpCloudAdapter(connector=_FakeConnector(), vault=cast(Any, secret_vault))
    m365 = adapters_module.M365CloudAdapter(connector=_FakeConnector(), vault=cast(Any, secret_vault))
    monkeypatch.setattr(
        adapters_module.CloudConnectorAdapter,
        "_aws_session",
        staticmethod(lambda secret, config: "aws-session"),
    )
    monkeypatch.setattr(
        adapters_module.CloudConnectorAdapter,
        "_azure_credential",
        staticmethod(lambda secret: "azure-credential"),
    )
    monkeypatch.setattr(
        adapters_module.CloudConnectorAdapter,
        "_gcp_session",
        staticmethod(lambda secret, config: "gcp-session"),
    )
    assert aws._runtime_config({"credential_ref": "ref"})["session"] == "aws-session"
    assert azure._runtime_config({"credential_ref": "ref"})["credential"] == "azure-credential"
    assert gcp._runtime_config({"credential_ref": "ref"})["session"] == "gcp-session"
    assert m365._runtime_config({"credential_ref": "ref"})["credential"] == "azure-credential"


def test_adapter_vault_and_secret_mapping_errors_are_sanitized(tmp_path) -> None:
    adapter = _adapter(tmp_path, _FakeConnector())
    for vault in (_BrokenVault(error=SecretVaultError("secret")), _BrokenVault(error=ValueError("bad"))):
        adapter.vault = vault  # type: ignore[assignment]
        with pytest.raises(CloudCredentialError, match="could not be read"):
            adapter._read_secret({}, "ref")
    adapter.vault = _BrokenVault(value=None)  # type: ignore[assignment]
    with pytest.raises(CloudCredentialError, match="not found"):
        adapter._read_secret({}, "ref")

    for secret, message in (("not-json", "not valid JSON"), ("[]", "must be a JSON object")):
        with pytest.raises(CloudCredentialError, match=message):
            adapter._secret_mapping(secret)


def test_adapter_credential_factories_cover_provider_specific_paths(monkeypatch) -> None:
    class FakeBoto3:
        def Session(self, **kwargs: Any) -> dict[str, Any]:
            return kwargs

    monkeypatch.setattr(adapters_module, "import_module", lambda name: FakeBoto3())
    assert AwsCloudAdapter._aws_session('{"aws_access_key_id":"id"}', {"region": "us-west-2"}) == {
        "aws_access_key_id": "id",
        "region_name": "us-west-2",
    }
    assert AwsCloudAdapter._aws_session('{"aws_access_key_id":"id"}', {"region": 123}) == {
        "aws_access_key_id": "id",
    }
    with pytest.raises(CloudCredentialError, match="no supported fields"):
        AwsCloudAdapter._aws_session("{}", {})

    class FakeCredential:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(
        adapters_module,
        "import_module",
        lambda name: SimpleNamespace(ClientSecretCredential=FakeCredential),
    )
    credential = AzureCloudAdapter._azure_credential(
        '{"tenant_id":"tenant","client_id":"client","client_secret":"secret"}'
    )
    assert credential.kwargs["tenant_id"] == "tenant"
    with pytest.raises(CloudCredentialError, match="incomplete"):
        AzureCloudAdapter._azure_credential("{\"tenant_id\":\"tenant\"}")

    class FakeCredentials:
        @classmethod
        def from_service_account_info(cls, values: Mapping[str, Any]) -> dict[str, Any]:
            return dict(values)

    monkeypatch.setattr(
        adapters_module,
        "import_module",
        lambda name: SimpleNamespace(Credentials=FakeCredentials),
    )
    session = GcpCloudAdapter._gcp_session('{"project_id":"project"}', {})
    assert session.project_id == ""
    assert session.credentials == {"project_id": "project"}


def test_adapter_exception_classification_and_status_aggregation(tmp_path) -> None:
    adapter = _adapter(tmp_path, _FakeConnector())
    assert adapter._classify_exception(PermissionError()) is CollectionStatus.NOT_AUTHORIZED
    assert adapter._classify_exception(cast(Any, SimpleNamespace(status_code=401))) is CollectionStatus.NOT_AUTHORIZED
    assert adapter._classify_exception(
        cast(Any, SimpleNamespace(code="AccessDenied"))
    ) is CollectionStatus.NOT_AUTHORIZED
    assert adapter._classify_exception(
        cast(Any, SimpleNamespace(error=SimpleNamespace(code="403")))
    ) is CollectionStatus.NOT_AUTHORIZED
    assert adapter._classify_exception(
        cast(Any, SimpleNamespace(response={"Error": {"Code": "UnauthorizedOperation"}}))
    ) is CollectionStatus.NOT_AUTHORIZED
    assert adapter._classify_exception(
        cast(Any, SimpleNamespace(response={"Error": {"Code": "Other"}}))
    ) is CollectionStatus.UNAVAILABLE
    assert adapter._classify_exception(RuntimeError()) is CollectionStatus.UNAVAILABLE
    sdk_outcome = adapter._outcome_from_exception("sdk", ImportError("optional"))
    assert sdk_outcome.error_code == "sdk_unavailable"

    assert adapter._status_from_value("bad") is CollectionStatus.UNAVAILABLE
    success = (SourceOutcome("success", CollectionStatus.SUCCESS),)
    unauthorized = (SourceOutcome("unauthorized", CollectionStatus.NOT_AUTHORIZED),)
    unavailable = (SourceOutcome("unavailable", CollectionStatus.UNAVAILABLE),)
    mixed = (
        SourceOutcome("unauthorized", CollectionStatus.NOT_AUTHORIZED),
        SourceOutcome("unavailable", CollectionStatus.UNAVAILABLE),
    )
    assert adapter._status_for_outcomes(0, ()) is CollectionStatus.EMPTY
    assert adapter._status_for_outcomes(2, success) is CollectionStatus.SUCCESS
    assert adapter._status_for_outcomes(0, unauthorized) is CollectionStatus.NOT_AUTHORIZED
    assert adapter._status_for_outcomes(0, unavailable) is CollectionStatus.UNAVAILABLE
    assert adapter._status_for_outcomes(2, unavailable) is CollectionStatus.PARTIAL
    assert adapter._status_for_outcomes(0, mixed) is CollectionStatus.PARTIAL
