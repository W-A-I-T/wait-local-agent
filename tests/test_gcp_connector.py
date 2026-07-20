from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from wait_local_agent.cloud_connectors.gcp import DefaultCredentialsError, GCPInventoryConnector


class FakeResourceManagerClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def search_projects(self) -> list[Any]:
        if self.fail:
            raise DefaultCredentialsError("missing credentials")
        return [
            SimpleNamespace(
                project_id="wait-prod",
                display_name="WAIT Production",
                name="projects/123456789",
                state="ACTIVE",
            )
        ]


class FakeComputeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requested: list[dict[str, str]] = []

    def aggregated_list(self, *, project: str) -> list[tuple[str, Any]]:
        self.requested.append({"method": "aggregated_list", "project": project})
        if self.fail:
            raise DefaultCredentialsError("missing credentials")
        return [
            (
                "zones/us-central1-b",
                SimpleNamespace(
                    instances=[
                        SimpleNamespace(
                            id=202,
                            name="worker-2",
                            machine_type="zones/us-central1-b/machineTypes/e2-small",
                            status="TERMINATED",
                            network_interfaces=[SimpleNamespace(network_i_p="10.10.2.5")],
                        ),
                        SimpleNamespace(
                            id=101,
                            name="worker-1",
                            machine_type="zones/us-central1-b/machineTypes/e2-medium",
                            status="RUNNING",
                            network_interfaces=[SimpleNamespace(network_i_p="10.10.1.5")],
                        ),
                    ]
                ),
            )
        ]

    def list(self, *, project: str, zone: str) -> list[Any]:
        self.requested.append({"method": "list", "project": project, "zone": zone})
        if self.fail:
            raise DefaultCredentialsError("missing credentials")
        return [
            SimpleNamespace(
                id=303,
                name="zonal-worker",
                machine_type=f"zones/{zone}/machineTypes/e2-standard-2",
                status="RUNNING",
                network_interfaces=[{"networkIP": "10.10.3.5"}],
            )
        ]


class FakeStorageClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requested_projects: list[str] = []

    def list_buckets(self, *, project: str) -> list[Any]:
        self.requested_projects.append(project)
        if self.fail:
            raise DefaultCredentialsError("missing credentials")
        return [
            SimpleNamespace(
                name="wait-artifacts",
                location="US",
                storage_class="STANDARD",
                time_created=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
            )
        ]


class FakeIamClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requested_names: list[str] = []

    def list_service_accounts(self, *, name: str) -> list[Any]:
        self.requested_names.append(name)
        if self.fail:
            raise DefaultCredentialsError("missing credentials")
        return [
            SimpleNamespace(
                email="automation@wait-prod.iam.gserviceaccount.com",
                unique_id="100000000000000000001",
                display_name="Automation",
                disabled=False,
            )
        ]


class FakeSession:
    def __init__(
        self,
        *,
        fail_projects: bool = False,
        fail_compute: bool = False,
        fail_storage: bool = False,
        fail_iam: bool = False,
    ) -> None:
        self.resource_manager = FakeResourceManagerClient(fail=fail_projects)
        self.compute = FakeComputeClient(fail=fail_compute)
        self.storage = FakeStorageClient(fail=fail_storage)
        self.iam = FakeIamClient(fail=fail_iam)
        self.requested_services: list[str] = []

    def client(self, service_name: str) -> Any:
        self.requested_services.append(service_name)
        if service_name == "resource-manager":
            return self.resource_manager
        if service_name == "compute":
            return self.compute
        if service_name == "storage":
            return self.storage
        if service_name == "iam":
            return self.iam
        raise AssertionError(f"unexpected service: {service_name}")


class EmptyIdResourceManagerClient:
    def search_projects(self) -> list[Any]:
        return [SimpleNamespace(display_name="Missing ID")]


class EmptyIdComputeClient:
    def aggregated_list(self, *, project: str) -> list[tuple[str, Any]]:
        return [("zones/us-central1-a", SimpleNamespace(instances=[SimpleNamespace(machine_type="e2-micro")]))]


class EmptyIdStorageClient:
    def list_buckets(self, *, project: str) -> list[Any]:
        return [SimpleNamespace(location="US")]


class EmptyIdIamClient:
    def list_service_accounts(self, *, name: str) -> list[Any]:
        return [SimpleNamespace(unique_id="missing-email")]


class EmptyIdSession:
    def client(self, service_name: str) -> Any:
        if service_name == "resource-manager":
            return EmptyIdResourceManagerClient()
        if service_name == "compute":
            return EmptyIdComputeClient()
        if service_name == "storage":
            return EmptyIdStorageClient()
        if service_name == "iam":
            return EmptyIdIamClient()
        raise AssertionError(f"unexpected service: {service_name}")


def _connector() -> GCPInventoryConnector:
    return GCPInventoryConnector()


def _items_by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["canonical_asset"]["asset_id"]: item for item in result["items"]}


def test_manifest_and_scope_advertise_read_only_gcp_inventory() -> None:
    manifest = _connector().manifest()
    assert manifest["module_id"] == "gcp-inventory"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["cloud"]
    assert manifest["asset_type"] == "cloud-resource"
    assert manifest["asset_types"] == [
        "cloud-bucket",
        "cloud-iam-service-account",
        "cloud-instance",
        "cloud-project",
    ]
    assert manifest["dependencies"] == [
        "google-cloud-compute",
        "google-cloud-iam",
        "google-cloud-resource-manager",
        "google-cloud-storage",
    ]

    scope = _connector().scope()
    assert scope["read_only"] is True
    assert scope["network"] is True
    assert scope["shell"] is False
    assert scope["paths"] == ["gcp:resourcemanager", "gcp:compute", "gcp:storage", "gcp:iam"]
    assert scope["operations"] == [
        "resourcemanager.projects.search",
        "compute.instances.aggregated_list",
        "storage.buckets.list",
        "iam.serviceAccounts.list",
    ]


def test_collect_maps_all_supported_resource_types_to_canonical_assets() -> None:
    session = FakeSession()
    result = _connector().collect({"session": session})
    items = _items_by_id(result)

    assert result["module_id"] == "gcp-inventory"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 5
    assert list(items) == [
        "gcp:compute:wait-prod:us-central1-b:101",
        "gcp:compute:wait-prod:us-central1-b:202",
        "gcp:iam:automation@wait-prod.iam.gserviceaccount.com",
        "gcp:project:wait-prod",
        "gcp:storage:wait-artifacts",
    ]
    assert session.requested_services == ["resource-manager", "compute", "storage", "iam"]

    instance = items["gcp:compute:wait-prod:us-central1-b:101"]["canonical_asset"]
    assert instance["asset_type"] == "cloud-instance"
    assert instance["name"] == "worker-1"
    assert instance["attributes"] == {
        "project_id": "wait-prod",
        "instance_id": "101",
        "name": "worker-1",
        "machine_type": "e2-medium",
        "status": "RUNNING",
        "zone": "us-central1-b",
        "private_ip": "10.10.1.5",
    }

    service_account = items["gcp:iam:automation@wait-prod.iam.gserviceaccount.com"]["canonical_asset"]
    assert service_account["asset_type"] == "cloud-iam-service-account"
    assert service_account["attributes"] == {
        "project_id": "wait-prod",
        "email": "automation@wait-prod.iam.gserviceaccount.com",
        "unique_id": "100000000000000000001",
        "display_name": "Automation",
        "disabled": False,
    }

    project = items["gcp:project:wait-prod"]["canonical_asset"]
    assert project["asset_type"] == "cloud-project"
    assert project["attributes"] == {
        "project_id": "wait-prod",
        "display_name": "WAIT Production",
        "name": "projects/123456789",
        "state": "ACTIVE",
    }

    bucket = items["gcp:storage:wait-artifacts"]["canonical_asset"]
    assert bucket["asset_type"] == "cloud-bucket"
    assert bucket["attributes"] == {
        "project_id": "wait-prod",
        "name": "wait-artifacts",
        "location": "US",
        "storage_class": "STANDARD",
        "time_created": "2026-01-02T03:04:00+00:00",
    }


def test_collect_emits_one_observation_per_asset_attribute() -> None:
    result = _connector().collect({"session": FakeSession()})
    instance_observations = _items_by_id(result)["gcp:compute:wait-prod:us-central1-b:101"]["observations"]

    assert instance_observations == [
        {
            "asset_type": "cloud-instance",
            "asset_id": "gcp:compute:wait-prod:us-central1-b:101",
            "key": "cloud.project_id",
            "value": "wait-prod",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "gcp:compute:wait-prod:us-central1-b:101",
            "key": "cloud.instance_id",
            "value": "101",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "gcp:compute:wait-prod:us-central1-b:101",
            "key": "cloud.name",
            "value": "worker-1",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "gcp:compute:wait-prod:us-central1-b:101",
            "key": "cloud.machine_type",
            "value": "e2-medium",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "gcp:compute:wait-prod:us-central1-b:101",
            "key": "cloud.status",
            "value": "RUNNING",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "gcp:compute:wait-prod:us-central1-b:101",
            "key": "cloud.zone",
            "value": "us-central1-b",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "gcp:compute:wait-prod:us-central1-b:101",
            "key": "cloud.private_ip",
            "value": "10.10.1.5",
        },
    ]
    assert len(result["observations"]) == sum(len(item["observations"]) for item in result["items"])


def test_zone_config_uses_zonal_compute_list() -> None:
    session = FakeSession()
    result = _connector().collect({"session": session, "zone": "northamerica-northeast2-a"})
    instance = _items_by_id(result)["gcp:compute:wait-prod:northamerica-northeast2-a:303"]["canonical_asset"]

    assert instance["attributes"]["zone"] == "northamerica-northeast2-a"
    assert session.compute.requested == [
        {"method": "list", "project": "wait-prod", "zone": "northamerica-northeast2-a"}
    ]


def test_project_id_config_collects_project_scoped_resources_when_project_search_fails() -> None:
    session = FakeSession(fail_projects=True)
    result = _connector().collect({"session": session, "project_id": "configured-project"})
    asset_ids = [item["canonical_asset"]["asset_id"] for item in result["items"]]

    assert result["ok"] is True
    assert "gcp:project:configured-project" not in asset_ids
    assert asset_ids == [
        "gcp:compute:configured-project:us-central1-b:101",
        "gcp:compute:configured-project:us-central1-b:202",
        "gcp:iam:automation@wait-prod.iam.gserviceaccount.com",
        "gcp:storage:wait-artifacts",
    ]


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
        "gcp:compute:wait-prod:us-central1-b:101",
        "gcp:compute:wait-prod:us-central1-b:202",
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
        {"project_id": ""},
        {"zone": ""},
        {"session": object()},
        {"region": "not-supported"},
    ],
)
def test_invalid_config_returns_not_ok(config: Any) -> None:
    result = _connector().collect(config)

    assert result["ok"] is False
    assert result["assets"] == []
    assert result["observations"] == []
    assert result["errors"]


@pytest.mark.parametrize(
    ("session", "absent_asset_id"),
    [
        (FakeSession(fail_compute=True), "gcp:compute:wait-prod:us-central1-b:101"),
        (FakeSession(fail_storage=True), "gcp:storage:wait-artifacts"),
        (FakeSession(fail_iam=True), "gcp:iam:automation@wait-prod.iam.gserviceaccount.com"),
    ],
)
def test_gcp_errors_are_isolated_per_resource_type(session: FakeSession, absent_asset_id: str) -> None:
    result = _connector().collect({"session": session})
    asset_ids = [item["canonical_asset"]["asset_id"] for item in result["items"]]

    assert result["ok"] is True
    assert absent_asset_id not in asset_ids


def test_skips_gcp_records_without_required_ids() -> None:
    result = _connector().collect({"session": EmptyIdSession(), "project_id": "wait-prod"})

    assert result["ok"] is True
    assert result["items"] == []


def test_creates_google_cloud_clients_from_imported_sdk_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_clients: list[str] = []

    class ImportedResourceManagerClient(FakeResourceManagerClient):
        def __init__(self) -> None:
            requested_clients.append("resource-manager")
            super().__init__()

    class ImportedComputeClient(FakeComputeClient):
        def __init__(self) -> None:
            requested_clients.append("compute")
            super().__init__()

    class ImportedStorageClient(FakeStorageClient):
        def __init__(self) -> None:
            requested_clients.append("storage")
            super().__init__()

    class ImportedIamClient(FakeIamClient):
        def __init__(self) -> None:
            requested_clients.append("iam")
            super().__init__()

    monkeypatch.setitem(sys.modules, "google", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "google.cloud", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "google.cloud.resourcemanager_v3",
        SimpleNamespace(ProjectsClient=ImportedResourceManagerClient),
    )
    monkeypatch.setitem(
        sys.modules,
        "google.cloud.compute_v1",
        SimpleNamespace(InstancesClient=ImportedComputeClient),
    )
    monkeypatch.setitem(sys.modules, "google.cloud.storage", SimpleNamespace(Client=ImportedStorageClient))
    monkeypatch.setitem(sys.modules, "google.cloud.iam_admin_v1", SimpleNamespace(IAMClient=ImportedIamClient))

    result = _connector().collect({"limit": 1})

    assert result["ok"] is True
    assert result["count"] == 1
    assert requested_clients == ["resource-manager", "compute", "storage", "iam"]


def test_format_value_supports_plain_dates() -> None:
    assert _connector()._format_value(date(2026, 7, 20)) == "2026-07-20"
