from __future__ import annotations

import asyncio
import builtins
import runpy
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import wait_local_agent.cloud_connectors.aws as aws_module
import wait_local_agent.cloud_connectors.azure as azure_module
import wait_local_agent.cloud_connectors.gcp as gcp_module
import wait_local_agent.cloud_connectors.m365 as m365_module

ROOT = Path(__file__).parents[1]


class ConnectorError(Exception):
    pass


class AwsEdgeSession:
    region_name = "edge-region"

    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()

    def client(self, service_name: str) -> Any:
        if service_name in self.failures:
            if service_name == "ec2":
                return SimpleNamespace(
                    describe_instances=_raising(ConnectorError),
                    describe_security_groups=_raising(ConnectorError),
                )
            return SimpleNamespace(**{_aws_method(service_name): _raising(ConnectorError)})
        if service_name == "sts":
            return SimpleNamespace(get_caller_identity=lambda: {"Account": "123"})
        if service_name == "ec2":
            return SimpleNamespace(
                describe_instances=lambda: {"Reservations": []},
                describe_security_groups=lambda: {"SecurityGroups": []},
            )
        return SimpleNamespace(**{_aws_method(service_name): lambda: _aws_response(service_name)})


def _aws_method(service_name: str) -> str:
    return {
        "ec2:instances": "describe_instances",
        "ec2:security-groups": "describe_security_groups",
        "s3:buckets": "list_buckets",
        "iam:users": "list_users",
        "ec2": "describe_instances",
        "s3": "list_buckets",
        "iam": "list_users",
    }.get(service_name, service_name)


def _aws_response(service_name: str) -> dict[str, Any]:
    if service_name == "ec2":
        return {"Reservations": [], "SecurityGroups": []}
    if service_name == "s3":
        return {"Buckets": []}
    return {"Users": []}


def _raising(error_type: type[BaseException]) -> Any:
    def raise_error(*args: Any, **kwargs: Any) -> None:
        raise error_type("unavailable")

    return raise_error


def test_aws_preflight_and_detailed_outcomes_cover_authz_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = aws_module.AwsInventoryConnector()
    monkeypatch.setattr(aws_module, "AWS_ERROR_TYPES", (ConnectorError,))
    connector.preflight({"session": AwsEdgeSession()})
    for source, service in (
        ("ec2:instances", "ec2"),
        ("s3:buckets", "s3"),
        ("ec2:security-groups", "ec2"),
        ("iam:users", "iam"),
    ):
        with pytest.raises(ConnectorError):
            if source == "ec2:instances":
                connector._ec2_instance_records(AwsEdgeSession({service}), {}, strict=True)
            elif source == "s3:buckets":
                connector._s3_bucket_records(AwsEdgeSession({service}), strict=True)
            elif source == "ec2:security-groups":
                connector._security_group_records(AwsEdgeSession({service}), strict=True)
            else:
                connector._iam_user_records(AwsEdgeSession({service}), strict=True)
    detailed = connector.collect_detailed({"session": AwsEdgeSession({"ec2", "s3", "iam"})})
    assert {outcome["source_id"] for outcome in detailed["outcomes"]} == {
        "ec2:instances",
        "s3:buckets",
        "ec2:security-groups",
        "iam:users",
    }


def test_aws_detailed_empty_limit_does_not_call_clients() -> None:
    result = aws_module.AwsInventoryConnector().collect_detailed({"session": AwsEdgeSession(), "limit": 0})
    assert result["result"]["items"] == []
    assert result["outcomes"] == []
    invalid = aws_module.AwsInventoryConnector().collect_detailed({"limit": "bad"})
    assert invalid["result"]["ok"] is False
    limited = aws_module.AwsInventoryConnector().collect_detailed({"session": AwsEdgeSession(), "limit": 1})
    assert limited["result"]["count"] == 0


def test_aws_missing_botocore_uses_fallback_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def fail_botocore(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "botocore.exceptions":
            raise ImportError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_botocore)
    namespace = runpy.run_path(str(ROOT / "src/wait_local_agent/cloud_connectors/aws.py"))
    assert namespace["ClientError"] is namespace["_FallbackAwsError"]


class AzureEdgeSession:
    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()

    def client(self, service_name: str) -> Any:
        if service_name == "subscriptions":
            return SimpleNamespace(subscriptions=SimpleNamespace(get=lambda _: None))
        method = {
            "compute": "list_all",
            "storage": "list",
            "network": "list_all",
            "authorization": "list_for_subscription",
        }[service_name]
        target = SimpleNamespace(**{method: _raising(ConnectorError) if service_name in self.failures else lambda: []})
        return SimpleNamespace(
            virtual_machines=target,
            storage_accounts=target,
            network_security_groups=target,
            role_assignments=target,
        )


def test_azure_preflight_env_and_detailed_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = azure_module.AzureInventoryConnector()
    monkeypatch.setattr(azure_module, "AZURE_ERROR_TYPES", (ConnectorError,))
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "env-subscription")
    connector.preflight({"session": AzureEdgeSession()})
    connector.preflight({"session": AzureEdgeSession(), "subscription_id": "configured-subscription"})
    assert connector._session({"credential": object()}).subscription_id == "env-subscription"
    detailed = connector.collect_detailed(
        {"session": AzureEdgeSession({"compute", "storage", "network", "authorization"})}
    )
    assert {outcome["source_id"] for outcome in detailed["outcomes"]} == {
        "compute:virtual-machines",
        "storage:accounts",
        "network:security-groups",
        "authorization:role-assignments",
    }
    assert connector.collect_detailed({"limit": "bad"})["result"]["ok"] is False
    assert connector.collect_detailed({"session": AzureEdgeSession(), "limit": 0})["result"]["count"] == 0
    assert connector.collect_detailed({"session": AzureEdgeSession(), "limit": 1})["result"]["count"] == 0


def test_azure_strict_resource_errors_reraise() -> None:
    connector = azure_module.AzureInventoryConnector()
    methods = (
        lambda: connector._virtual_machine_records(AzureEdgeSession({"compute"}), strict=True),
        lambda: connector._storage_account_records(AzureEdgeSession({"storage"}), strict=True),
        lambda: connector._network_security_group_records(AzureEdgeSession({"network"}), strict=True),
        lambda: connector._role_assignment_records(AzureEdgeSession({"authorization"}), strict=True),
    )
    for method in methods:
        with pytest.raises(ConnectorError):
            method()


def test_azure_sdk_session_routes_clients_and_handles_values(monkeypatch: pytest.MonkeyPatch) -> None:
    clients: list[str] = []

    def factory(name: str) -> type[Any]:
        class Client:
            def __init__(self, *args: Any) -> None:
                clients.append(name)

        return Client

    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.resource.subscriptions",
        SimpleNamespace(SubscriptionClient=factory("subscriptions")),
    )
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.compute", SimpleNamespace(ComputeManagementClient=factory("compute"))
    )
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.storage", SimpleNamespace(StorageManagementClient=factory("storage"))
    )
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.network", SimpleNamespace(NetworkManagementClient=factory("network"))
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=factory("authorization")),
    )
    session = azure_module._AzureSdkSession(credential=object(), subscription_id="sub")
    for service in ("subscriptions", "compute", "storage", "network", "authorization"):
        session.client(service)
    with pytest.raises(ValueError):
        session.client("unsupported")
    assert azure_module.AzureInventoryConnector._value({"key": "value"}, "key") == "value"
    assert azure_module.AzureInventoryConnector._value(SimpleNamespace(key="attribute"), "key") == "attribute"


def test_azure_missing_sdk_errors_use_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def fail_azure_core(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "azure.core.exceptions":
            raise ImportError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_azure_core)
    monkeypatch.setitem(sys.modules, "azure.core.exceptions", None)
    namespace = runpy.run_path(str(ROOT / "src/wait_local_agent/cloud_connectors/azure.py"))
    assert namespace["AzureError"] is namespace["_FallbackAzureError"]


class GcpEdgeSession:
    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()

    def client(self, service_name: str) -> Any:
        if service_name in self.failures:
            return SimpleNamespace(**{_gcp_method(service_name): _raising(ConnectorError)})
        return SimpleNamespace(**{_gcp_method(service_name): lambda **_: []})


def _gcp_method(service_name: str) -> str:
    return {
        "resource-manager": "search_projects",
        "compute": "aggregated_list",
        "storage": "list_buckets",
        "iam": "list_service_accounts",
    }[service_name]


def test_gcp_preflight_variants_and_detailed_outcomes() -> None:
    connector = gcp_module.GCPInventoryConnector()
    calls: list[str] = []
    for resource_manager in (
        SimpleNamespace(get_project=lambda **_: calls.append("get_project")),
        SimpleNamespace(get=lambda **_: calls.append("get")),
        SimpleNamespace(search_projects=lambda: calls.append("search")),
    ):
        connector.preflight(
            {
                "session": SimpleNamespace(
                    client=lambda _, resource_manager=resource_manager: resource_manager
                ),
                "project_id": "p",
            }
        )
    connector.preflight(
        {
            "session": SimpleNamespace(
                client=lambda _: SimpleNamespace(search_projects=lambda: calls.append("search"))
            )
        }
    )
    assert calls == ["get_project", "get", "search", "search"]
    detailed = connector.collect_detailed(
        {"session": GcpEdgeSession({"resource-manager", "compute", "storage", "iam"}), "project_id": "p"}
    )
    assert detailed["outcomes"][0]["source_id"] == "resourcemanager:projects"
    assert connector.collect_detailed({"limit": "bad"})["result"]["ok"] is False
    assert connector.collect_detailed({"session": GcpEdgeSession(), "limit": 0})["result"]["count"] == 0
    assert connector.collect_detailed({"session": GcpEdgeSession(), "limit": 1})["result"]["count"] == 0


def test_gcp_strict_errors_and_helper_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = gcp_module.GCPInventoryConnector()
    monkeypatch.setattr(gcp_module, "GCP_ERROR_TYPES", (ConnectorError,))
    with pytest.raises(ConnectorError):
        connector._project_records(GcpEdgeSession({"resource-manager"}), strict=True)
    with pytest.raises(ConnectorError):
        connector._compute_instance_records(GcpEdgeSession({"compute"}), {}, "p", strict=True)
    with pytest.raises(ConnectorError):
        connector._storage_bucket_records(GcpEdgeSession({"storage"}), "p", strict=True)
    with pytest.raises(ConnectorError):
        connector._iam_service_account_records(GcpEdgeSession({"iam"}), "p", strict=True)
    assert list(connector._iterable(None)) == []
    assert list(connector._iterable({"projects": [1]})) == [1]
    assert list(connector._iterable({"other": 1})) == [1]
    assert list(connector._iter_aggregated({"items": {"zone": {"instances": []}}})) == [("zone", {"instances": []})]
    assert list(connector._iter_aggregated([("zone", {})])) == [("zone", {})]
    assert list(connector._iter_aggregated({"items": []})) == []
    assert connector._private_ip(SimpleNamespace(network_interfaces=[{"networkIP": "10.0.0.1"}])) == "10.0.0.1"
    assert connector._private_ip(SimpleNamespace(network_interfaces=[])) == ""
    assert connector._private_ip(SimpleNamespace(network_interfaces=[{"network_i_p": ""}])) == ""
    assert connector._text(None) == ""
    assert connector._format_value(SimpleNamespace(ToDatetime=lambda: datetime(2026, 1, 1))) == "2026-01-01T00:00:00"
    assert connector._format_value(SimpleNamespace(name="ACTIVE")) == "ACTIVE"


def test_gcp_sdk_session_routes_clients_and_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = {
        "google.cloud.resourcemanager_v3": SimpleNamespace(ProjectsClient=lambda **_: object()),
        "google.cloud.compute_v1": SimpleNamespace(InstancesClient=lambda **_: object()),
        "google.cloud.storage": SimpleNamespace(Client=lambda **_: object()),
        "google.cloud.iam_admin_v1": SimpleNamespace(IAMClient=lambda **_: object()),
    }
    monkeypatch.setattr(gcp_module, "import_module", lambda name: modules[name])
    session = gcp_module._GoogleCloudSession()
    for service in ("resource-manager", "compute", "storage", "iam"):
        assert session.client(service) is not None
    with pytest.raises(ValueError):
        session.client("unsupported")


def test_gcp_missing_sdk_errors_use_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def fail_google(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in {"google.api_core", "google.auth"}:
            raise ImportError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_google)
    namespace = runpy.run_path(str(ROOT / "src/wait_local_agent/cloud_connectors/gcp.py"))
    assert namespace["RefreshError"] is namespace["_FallbackGcpError"]


class M365EdgeClient:
    def __init__(self, error_collection: str | None = None) -> None:
        self.organization = SimpleNamespace(get=lambda: {"value": []})
        self.identity = SimpleNamespace(
            conditional_access=SimpleNamespace(
                policies=_M365Collection([], error_collection == "policies")
            )
        )
        for name in ("users", "groups", "applications", "service_principals"):
            setattr(self, name, _M365Collection([], error_collection == name))


class _M365Collection:
    def __init__(self, values: list[Any], fail: bool = False) -> None:
        self.values = values
        self.fail = fail

    def get(self) -> dict[str, Any]:
        if self.fail:
            raise ConnectorError("unavailable")
        return {"value": self.values}


def test_m365_preflight_shape_and_detailed_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m365_module, "M365_ERROR_TYPES", (ConnectorError,))
    connector = m365_module.M365InventoryConnector()
    connector.preflight({"client": M365EdgeClient()})
    with pytest.raises(RuntimeError, match="organization"):
        connector.preflight({"client": SimpleNamespace()})
    detailed = connector.collect_detailed({"client": M365EdgeClient("users")})
    assert detailed["outcomes"][0]["source_id"] == "users"
    assert m365_module.M365InventoryConnector._response_values(None) == []
    assert m365_module.M365InventoryConnector._response_values([1]) == [1]
    assert m365_module.M365InventoryConnector._response_values({"value": [2]}) == [2]
    assert m365_module.M365InventoryConnector._response_values(SimpleNamespace(value=[3])) == [3]
    assert m365_module.M365InventoryConnector._field({"id": 1}, "id", 0) == 1
    assert m365_module.M365InventoryConnector._field(SimpleNamespace(id=2), "id", 0) == 2
    assert not m365_module.M365InventoryConnector._has_graph_client_shape(SimpleNamespace())


def test_m365_strict_errors_and_resolve_inside_running_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m365_module, "M365_ERROR_TYPES", (ConnectorError,))
    connector = m365_module.M365InventoryConnector()
    for name in ("users", "groups", "applications", "service_principals", "policies"):
        client = M365EdgeClient(name)
        if name == "policies":
            method = connector._conditional_access_policy_records
        else:
            method_name = "service_principal" if name == "service_principals" else name.rstrip("s")
            method = getattr(connector, f"_{method_name}_records")
        with pytest.raises(ConnectorError):
            method(client, strict=True)

    async def exercise() -> None:
        assert m365_module.M365InventoryConnector._resolve(async_value()) == {"ok": True}
        with pytest.raises(ConnectorError):
            m365_module.M365InventoryConnector._resolve(async_error())
        assert m365_module.M365InventoryConnector._resolve(NonCoroutineAwaitable()) == {"ok": True}

    async def async_value() -> dict[str, bool]:
        return {"ok": True}

    async def async_error() -> dict[str, bool]:
        raise ConnectorError("worker failure")

    class NonCoroutineAwaitable:
        def __await__(self) -> Any:
            async def value() -> dict[str, bool]:
                return {"ok": True}

            return value().__await__()

    asyncio.run(exercise())

    assert connector.collect_detailed({"client": M365EdgeClient(), "limit": 0})["result"]["count"] == 0
    assert connector.collect_detailed({"client": M365EdgeClient(), "limit": 1})["result"]["count"] == 0
    assert connector.collect_detailed({"limit": "bad"})["result"]["ok"] is False
    assert connector.validate_config(None)["ok"] is True


def test_m365_missing_sdk_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def fail_kiota(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "kiota_abstractions.api_error":
            raise ImportError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_kiota)
    namespace = runpy.run_path(str(ROOT / "src/wait_local_agent/cloud_connectors/m365.py"))
    assert namespace["M365ApiError"] is namespace["_FallbackM365Error"]
