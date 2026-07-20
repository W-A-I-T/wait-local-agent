from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from wait_local_agent.cloud_connectors.azure import AzureError, AzureInventoryConnector

VM_ID_1 = "/subscriptions/sub-1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-001"
VM_ID_2 = "/subscriptions/sub-1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-002"
STORAGE_ID = "/subscriptions/sub-1/resourceGroups/rg-data/providers/Microsoft.Storage/storageAccounts/waitdata"
NSG_ID = "/subscriptions/sub-1/resourceGroups/rg-net/providers/Microsoft.Network/networkSecurityGroups/web-nsg"
ROLE_ID = "/subscriptions/sub-1/providers/Microsoft.Authorization/roleAssignments/role-001"


class FakeVirtualMachines:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def list_all(self) -> list[Any]:
        if self.fail:
            raise AzureError("compute unavailable")
        return [
            SimpleNamespace(
                id=VM_ID_2,
                name="vm-002",
                location="eastus",
                hardware_profile=SimpleNamespace(vm_size="Standard_B2s"),
                provisioning_state="Succeeded",
            ),
            SimpleNamespace(
                id=VM_ID_1,
                name="vm-001",
                location="canadacentral",
                hardware_profile=SimpleNamespace(vm_size="Standard_B1s"),
                provisioning_state="Succeeded",
            ),
        ]


class FakeComputeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.virtual_machines = FakeVirtualMachines(fail=fail)


class FakeStorageAccounts:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def list(self) -> list[Any]:
        if self.fail:
            raise AzureError("storage unavailable")
        return [
            SimpleNamespace(
                id=STORAGE_ID,
                name="waitdata",
                location="canadacentral",
                kind="StorageV2",
                sku=SimpleNamespace(name="Standard_LRS"),
            )
        ]


class FakeStorageClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.storage_accounts = FakeStorageAccounts(fail=fail)


class FakeNetworkSecurityGroups:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def list_all(self) -> list[Any]:
        if self.fail:
            raise AzureError("network unavailable")
        return [
            SimpleNamespace(
                id=NSG_ID,
                name="web-nsg",
                location="canadacentral",
                security_rules=[SimpleNamespace(name="https"), SimpleNamespace(name="ssh")],
            )
        ]


class FakeNetworkClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.network_security_groups = FakeNetworkSecurityGroups(fail=fail)


class FakeRoleAssignments:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def list_for_subscription(self) -> list[Any]:
        if self.fail:
            raise AzureError("authorization unavailable")
        return [
            SimpleNamespace(
                id=ROLE_ID,
                name="role-001",
                principal_id="principal-001",
                role_definition_id="/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/reader",
                scope="/subscriptions/sub-1",
            )
        ]


class FakeAuthorizationClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.role_assignments = FakeRoleAssignments(fail=fail)


class FakeSession:
    def __init__(
        self,
        *,
        fail_compute: bool = False,
        fail_storage: bool = False,
        fail_network: bool = False,
        fail_authorization: bool = False,
    ) -> None:
        self.fail_compute = fail_compute
        self.fail_storage = fail_storage
        self.fail_network = fail_network
        self.fail_authorization = fail_authorization
        self.requested_services: list[str] = []

    def client(self, service_name: str) -> Any:
        self.requested_services.append(service_name)
        if service_name == "compute":
            return FakeComputeClient(fail=self.fail_compute)
        if service_name == "storage":
            return FakeStorageClient(fail=self.fail_storage)
        if service_name == "network":
            return FakeNetworkClient(fail=self.fail_network)
        if service_name == "authorization":
            return FakeAuthorizationClient(fail=self.fail_authorization)
        raise AssertionError(f"unexpected service: {service_name}")


class EmptyIdComputeClient:
    virtual_machines = SimpleNamespace(list_all=lambda: [SimpleNamespace(name="")])


class EmptyIdStorageClient:
    storage_accounts = SimpleNamespace(list=lambda: [SimpleNamespace(kind="StorageV2")])


class EmptyIdNetworkClient:
    network_security_groups = SimpleNamespace(list_all=lambda: [SimpleNamespace(location="westus")])


class EmptyIdAuthorizationClient:
    role_assignments = SimpleNamespace(list_for_subscription=lambda: [SimpleNamespace(scope="/subscriptions/sub-1")])


class EmptyIdSession:
    def client(self, service_name: str) -> Any:
        if service_name == "compute":
            return EmptyIdComputeClient()
        if service_name == "storage":
            return EmptyIdStorageClient()
        if service_name == "network":
            return EmptyIdNetworkClient()
        if service_name == "authorization":
            return EmptyIdAuthorizationClient()
        raise AssertionError(f"unexpected service: {service_name}")


def _connector() -> AzureInventoryConnector:
    return AzureInventoryConnector()


def _items_by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["canonical_asset"]["asset_id"]: item for item in result["items"]}


def test_manifest_and_scope_advertise_read_only_azure_inventory() -> None:
    manifest = _connector().manifest()
    assert manifest["module_id"] == "azure-inventory"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["cloud"]
    assert manifest["asset_type"] == "cloud-resource"
    assert manifest["asset_types"] == [
        "cloud-iam-assignment",
        "cloud-instance",
        "cloud-security-group",
        "cloud-storage-account",
    ]
    assert manifest["dependencies"] == [
        "azure-identity",
        "azure-mgmt-authorization",
        "azure-mgmt-compute",
        "azure-mgmt-network",
        "azure-mgmt-storage",
    ]

    scope = _connector().scope()
    assert scope["read_only"] is True
    assert scope["network"] is True
    assert scope["shell"] is False
    assert scope["paths"] == ["azure:compute", "azure:storage", "azure:network", "azure:authorization"]
    assert scope["operations"] == [
        "compute.virtual_machines.list_all",
        "storage.storage_accounts.list",
        "network.network_security_groups.list_all",
        "authorization.role_assignments.list_for_subscription",
    ]


def test_collect_maps_all_supported_resource_types_to_canonical_assets() -> None:
    session = FakeSession()
    result = _connector().collect({"session": session})
    items = _items_by_id(result)

    assert result["module_id"] == "azure-inventory"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 5
    assert list(items) == [
        f"azure:compute:{VM_ID_1}",
        f"azure:compute:{VM_ID_2}",
        f"azure:nsg:{NSG_ID}",
        f"azure:role-assignment:{ROLE_ID}",
        f"azure:storage:{STORAGE_ID}",
    ]
    assert session.requested_services == ["compute", "storage", "network", "authorization"]

    virtual_machine = items[f"azure:compute:{VM_ID_1}"]["canonical_asset"]
    assert virtual_machine["asset_type"] == "cloud-instance"
    assert virtual_machine["name"] == "vm-001"
    assert virtual_machine["attributes"] == {
        "resource_id": VM_ID_1,
        "name": "vm-001",
        "vm_size": "Standard_B1s",
        "location": "canadacentral",
        "provisioning_state": "Succeeded",
        "resource_group": "rg-app",
    }

    storage_account = items[f"azure:storage:{STORAGE_ID}"]["canonical_asset"]
    assert storage_account["asset_type"] == "cloud-storage-account"
    assert storage_account["attributes"] == {
        "resource_id": STORAGE_ID,
        "name": "waitdata",
        "location": "canadacentral",
        "kind": "StorageV2",
        "sku": "Standard_LRS",
    }

    security_group = items[f"azure:nsg:{NSG_ID}"]["canonical_asset"]
    assert security_group["asset_type"] == "cloud-security-group"
    assert security_group["attributes"] == {
        "resource_id": NSG_ID,
        "name": "web-nsg",
        "location": "canadacentral",
        "security_rule_count": 2,
    }

    role_assignment = items[f"azure:role-assignment:{ROLE_ID}"]["canonical_asset"]
    assert role_assignment["asset_type"] == "cloud-iam-assignment"
    assert role_assignment["attributes"] == {
        "assignment_id": ROLE_ID,
        "name": "role-001",
        "principal_id": "principal-001",
        "role_definition_id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/reader",
        "scope": "/subscriptions/sub-1",
    }


def test_collect_emits_one_observation_per_asset_attribute() -> None:
    result = _connector().collect({"session": FakeSession()})
    virtual_machine_observations = _items_by_id(result)[f"azure:compute:{VM_ID_1}"]["observations"]

    assert virtual_machine_observations == [
        {
            "asset_type": "cloud-instance",
            "asset_id": f"azure:compute:{VM_ID_1}",
            "key": "cloud.resource_id",
            "value": VM_ID_1,
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": f"azure:compute:{VM_ID_1}",
            "key": "cloud.name",
            "value": "vm-001",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": f"azure:compute:{VM_ID_1}",
            "key": "cloud.vm_size",
            "value": "Standard_B1s",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": f"azure:compute:{VM_ID_1}",
            "key": "cloud.location",
            "value": "canadacentral",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": f"azure:compute:{VM_ID_1}",
            "key": "cloud.provisioning_state",
            "value": "Succeeded",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": f"azure:compute:{VM_ID_1}",
            "key": "cloud.resource_group",
            "value": "rg-app",
        },
    ]
    assert len(result["observations"]) == sum(len(item["observations"]) for item in result["items"])


def test_preview_marks_preview_and_uses_default_limit() -> None:
    result = _connector().preview({"session": FakeSession()})

    assert result["ok"] is True
    assert result["preview"] is True
    assert result["count"] == 5


def test_preview_returns_not_ok_for_invalid_config() -> None:
    result = _connector().preview({"limit": "bad"})

    assert result["ok"] is False
    assert result["assets"] == []
    assert result["observations"] == []
    assert any("limit" in error for error in result["errors"])


def test_collect_honors_explicit_limit_after_deterministic_sort() -> None:
    result = _connector().collect({"session": FakeSession(), "limit": 2})

    assert result["ok"] is True
    assert result["count"] == 2
    assert [item["canonical_asset"]["asset_id"] for item in result["items"]] == [
        f"azure:compute:{VM_ID_1}",
        f"azure:compute:{VM_ID_2}",
    ]


def test_collect_with_limit_zero_returns_empty_without_clients() -> None:
    session = FakeSession()
    result = _connector().collect({"session": session, "limit": 0})

    assert result["ok"] is True
    assert result["preview"] is False
    assert result["items"] == []
    assert result["assets"] == []
    assert result["observations"] == []
    assert result["count"] == 0
    assert session.requested_services == []


@pytest.mark.parametrize(
    "config",
    [
        ["not", "a", "mapping"],
        {"limit": -1},
        {"limit": "bad"},
        {"subscription_id": ""},
        {"session": object()},
        {"tenant_id": "not-supported"},
    ],
)
def test_invalid_config_returns_not_ok(config: Any) -> None:
    result = _connector().collect(config)

    assert result["ok"] is False
    assert result["assets"] == []
    assert result["observations"] == []
    assert result["errors"]


def test_azure_error_for_one_resource_type_is_swallowed() -> None:
    result = _connector().collect({"session": FakeSession(fail_compute=True)})
    asset_ids = [item["canonical_asset"]["asset_id"] for item in result["items"]]

    assert result["ok"] is True
    assert f"azure:compute:{VM_ID_1}" not in asset_ids
    assert asset_ids == [
        f"azure:nsg:{NSG_ID}",
        f"azure:role-assignment:{ROLE_ID}",
        f"azure:storage:{STORAGE_ID}",
    ]


@pytest.mark.parametrize(
    ("session", "absent_asset_id"),
    [
        (FakeSession(fail_storage=True), f"azure:storage:{STORAGE_ID}"),
        (FakeSession(fail_network=True), f"azure:nsg:{NSG_ID}"),
        (FakeSession(fail_authorization=True), f"azure:role-assignment:{ROLE_ID}"),
    ],
)
def test_azure_errors_are_isolated_per_resource_type(session: FakeSession, absent_asset_id: str) -> None:
    result = _connector().collect({"session": session})
    asset_ids = [item["canonical_asset"]["asset_id"] for item in result["items"]]

    assert result["ok"] is True
    assert absent_asset_id not in asset_ids
    assert len(asset_ids) == 4


def test_skips_azure_records_without_required_ids() -> None:
    result = _connector().collect({"session": EmptyIdSession()})

    assert result["ok"] is True
    assert result["items"] == []
    assert _connector()._resource_group(VM_ID_1) == "rg-app"
    assert _connector()._resource_group("missing-resource-group") == ""


def test_creates_azure_sdk_session_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    created_clients: list[tuple[str, str, str]] = []

    class FakeCredential:
        pass

    def _credential_factory() -> FakeCredential:
        return FakeCredential()

    def _client_factory(service_name: str) -> type[Any]:
        class FakeSdkClient:
            def __init__(self, credential: FakeCredential, subscription_id: str) -> None:
                created_clients.append((service_name, credential.__class__.__name__, subscription_id))
                self.virtual_machines = FakeVirtualMachines()
                self.storage_accounts = FakeStorageAccounts()
                self.network_security_groups = FakeNetworkSecurityGroups()
                self.role_assignments = FakeRoleAssignments()

        return FakeSdkClient

    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=_credential_factory))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.compute",
        SimpleNamespace(ComputeManagementClient=_client_factory("compute")),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.storage",
        SimpleNamespace(StorageManagementClient=_client_factory("storage")),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.network",
        SimpleNamespace(NetworkManagementClient=_client_factory("network")),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=_client_factory("authorization")),
    )

    result = _connector().collect({"subscription_id": "sub-1", "limit": 1})

    assert result["ok"] is True
    assert result["count"] == 1
    assert created_clients == [
        ("compute", "FakeCredential", "sub-1"),
        ("storage", "FakeCredential", "sub-1"),
        ("network", "FakeCredential", "sub-1"),
        ("authorization", "FakeCredential", "sub-1"),
    ]


def test_format_value_supports_dates() -> None:
    assert _connector()._format_value(datetime(2026, 7, 20, 1, 2, tzinfo=UTC)) == "2026-07-20T01:02:00+00:00"
    assert _connector()._format_value(date(2026, 7, 20)) == "2026-07-20"
