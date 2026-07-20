from __future__ import annotations

import sys
from collections.abc import Coroutine
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

import wait_local_agent.cloud_connectors.m365 as m365_module
from wait_local_agent.cloud_connectors.m365 import M365InventoryConnector


class FakeGraphError(Exception):
    pass


type FakeCollectionResponse = dict[str, Any]
type FakeCollectionGetResult = FakeCollectionResponse | Coroutine[Any, Any, FakeCollectionResponse]


class FakeCollectionBase:
    def __init__(
        self,
        values: list[Any],
        *,
        fail: bool = False,
        calls: list[str] | None = None,
        name: str = "",
    ) -> None:
        self.values = values
        self.fail = fail
        self.calls = calls
        self.name = name

    def get(self) -> FakeCollectionGetResult:
        return self._response()

    def _response(self) -> FakeCollectionResponse:
        if self.calls is not None:
            self.calls.append(self.name)
        if self.fail:
            raise FakeGraphError()
        return {"value": self.values}


class FakeCollection(FakeCollectionBase):
    def get(self) -> FakeCollectionResponse:
        return self._response()


class FakeAsyncCollection(FakeCollectionBase):
    async def get(self) -> FakeCollectionResponse:
        return self._response()


class FakeClient:
    def __init__(
        self,
        *,
        users: list[Any] | None = None,
        groups: list[Any] | None = None,
        applications: list[Any] | None = None,
        service_principals: list[Any] | None = None,
        policies: list[Any] | None = None,
        fail_users: bool = False,
        fail_groups: bool = False,
        fail_applications: bool = False,
        fail_service_principals: bool = False,
        fail_policies: bool = False,
        async_users: bool = False,
    ) -> None:
        self.calls: list[str] = []
        user_collection = FakeAsyncCollection if async_users else FakeCollection
        self.users = user_collection(
            users if users is not None else _users(),
            fail=fail_users,
            calls=self.calls,
            name="users",
        )
        self.groups = FakeCollection(
            groups if groups is not None else _groups(),
            fail=fail_groups,
            calls=self.calls,
            name="groups",
        )
        self.applications = FakeCollection(
            applications if applications is not None else _applications(),
            fail=fail_applications,
            calls=self.calls,
            name="applications",
        )
        self.service_principals = FakeCollection(
            service_principals if service_principals is not None else _service_principals(),
            fail=fail_service_principals,
            calls=self.calls,
            name="service_principals",
        )
        self.identity = SimpleNamespace(
            conditional_access=SimpleNamespace(
                policies=FakeCollection(
                    policies if policies is not None else _policies(),
                    fail=fail_policies,
                    calls=self.calls,
                    name="conditional_access.policies",
                )
            )
        )


def _users() -> list[Any]:
    return [
        SimpleNamespace(
            id="u1",
            display_name="Ada Admin",
            user_principal_name="ada@example.com",
            mail="ada@example.com",
            account_enabled=True,
            job_title="Administrator",
            department="IT",
            created_date_time=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        )
    ]


def _groups() -> list[dict[str, Any]]:
    return [
        {
            "id": "g1",
            "display_name": "Helpdesk",
            "mail": "helpdesk@example.com",
            "mail_enabled": True,
            "security_enabled": True,
            "group_types": ["Unified"],
            "created_date_time": datetime(2025, 5, 6, 7, 8, tzinfo=UTC),
        }
    ]


def _applications() -> list[Any]:
    return [
        SimpleNamespace(
            id="a1",
            app_id="app-client-id",
            display_name="WAIT Local Agent",
            sign_in_audience="AzureADMyOrg",
            created_date_time=datetime(2024, 4, 3, 2, 1, tzinfo=UTC),
        )
    ]


def _service_principals() -> list[Any]:
    return [
        SimpleNamespace(
            id="sp1",
            app_id="sp-client-id",
            display_name="WAIT Local Agent SP",
            service_principal_type="Application",
            account_enabled=True,
            app_owner_organization_id="tenant-1",
        )
    ]


def _policies() -> list[dict[str, Any]]:
    return [
        {
            "id": "cap1",
            "display_name": "Require MFA",
            "state": "enabled",
            "created_date_time": datetime(2023, 3, 2, 1, tzinfo=UTC),
            "modified_date_time": datetime(2026, 6, 5, 4, tzinfo=UTC),
        }
    ]


def _connector() -> M365InventoryConnector:
    return M365InventoryConnector()


def _items_by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["canonical_asset"]["asset_id"]: item for item in result["items"]}


@pytest.fixture(autouse=True)
def _fake_graph_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m365_module, "M365_ERROR_TYPES", (FakeGraphError,))


def test_manifest_and_scope_advertise_read_only_m365_inventory() -> None:
    manifest = _connector().manifest()
    assert manifest["module_id"] == "m365-inventory"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["cloud"]
    assert manifest["asset_type"] == "cloud-resource"
    assert manifest["asset_types"] == [
        "m365-application",
        "m365-conditional-access-policy",
        "m365-group",
        "m365-service-principal",
        "m365-user",
    ]
    assert manifest["dependencies"] == ["msgraph-sdk"]

    scope = _connector().scope()
    assert scope["read_only"] is True
    assert scope["network"] is True
    assert scope["shell"] is False
    assert scope["paths"] == [
        "m365:users",
        "m365:groups",
        "m365:applications",
        "m365:service-principals",
        "m365:conditional-access-policies",
    ]
    assert scope["operations"] == [
        "graph.users.list",
        "graph.groups.list",
        "graph.applications.list",
        "graph.service_principals.list",
        "graph.identity.conditional_access.policies.list",
    ]


def test_collect_maps_all_supported_resource_types_to_canonical_assets() -> None:
    client = FakeClient()
    result = _connector().collect({"client": client})
    items = _items_by_id(result)

    assert result["module_id"] == "m365-inventory"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 5
    assert list(items) == [
        "m365:application:a1",
        "m365:conditional-access-policy:cap1",
        "m365:group:g1",
        "m365:service-principal:sp1",
        "m365:user:u1",
    ]
    assert client.calls == [
        "users",
        "groups",
        "applications",
        "service_principals",
        "conditional_access.policies",
    ]

    application = items["m365:application:a1"]["canonical_asset"]
    assert application["asset_type"] == "m365-application"
    assert application["attributes"] == {
        "application_id": "a1",
        "app_id": "app-client-id",
        "display_name": "WAIT Local Agent",
        "sign_in_audience": "AzureADMyOrg",
        "created_date_time": "2024-04-03T02:01:00+00:00",
    }

    policy = items["m365:conditional-access-policy:cap1"]["canonical_asset"]
    assert policy["asset_type"] == "m365-conditional-access-policy"
    assert policy["attributes"] == {
        "policy_id": "cap1",
        "display_name": "Require MFA",
        "state": "enabled",
        "created_date_time": "2023-03-02T01:00:00+00:00",
        "modified_date_time": "2026-06-05T04:00:00+00:00",
    }

    group = items["m365:group:g1"]["canonical_asset"]
    assert group["asset_type"] == "m365-group"
    assert group["attributes"] == {
        "group_id": "g1",
        "display_name": "Helpdesk",
        "mail": "helpdesk@example.com",
        "mail_enabled": True,
        "security_enabled": True,
        "group_types": ["Unified"],
        "created_date_time": "2025-05-06T07:08:00+00:00",
    }

    service_principal = items["m365:service-principal:sp1"]["canonical_asset"]
    assert service_principal["asset_type"] == "m365-service-principal"
    assert service_principal["attributes"] == {
        "service_principal_id": "sp1",
        "app_id": "sp-client-id",
        "display_name": "WAIT Local Agent SP",
        "service_principal_type": "Application",
        "account_enabled": True,
        "app_owner_organization_id": "tenant-1",
    }

    user = items["m365:user:u1"]["canonical_asset"]
    assert user["asset_type"] == "m365-user"
    assert user["attributes"] == {
        "user_id": "u1",
        "display_name": "Ada Admin",
        "user_principal_name": "ada@example.com",
        "mail": "ada@example.com",
        "account_enabled": True,
        "job_title": "Administrator",
        "department": "IT",
        "created_date_time": "2026-01-02T03:04:00+00:00",
    }


def test_collect_emits_one_observation_per_asset_attribute() -> None:
    result = _connector().collect({"client": FakeClient()})
    user_observations = _items_by_id(result)["m365:user:u1"]["observations"]

    assert user_observations == [
        {
            "asset_type": "m365-user",
            "asset_id": "m365:user:u1",
            "key": "cloud.user_id",
            "value": "u1",
        },
        {
            "asset_type": "m365-user",
            "asset_id": "m365:user:u1",
            "key": "cloud.display_name",
            "value": "Ada Admin",
        },
        {
            "asset_type": "m365-user",
            "asset_id": "m365:user:u1",
            "key": "cloud.user_principal_name",
            "value": "ada@example.com",
        },
        {
            "asset_type": "m365-user",
            "asset_id": "m365:user:u1",
            "key": "cloud.mail",
            "value": "ada@example.com",
        },
        {
            "asset_type": "m365-user",
            "asset_id": "m365:user:u1",
            "key": "cloud.account_enabled",
            "value": True,
        },
        {
            "asset_type": "m365-user",
            "asset_id": "m365:user:u1",
            "key": "cloud.job_title",
            "value": "Administrator",
        },
        {
            "asset_type": "m365-user",
            "asset_id": "m365:user:u1",
            "key": "cloud.department",
            "value": "IT",
        },
        {
            "asset_type": "m365-user",
            "asset_id": "m365:user:u1",
            "key": "cloud.created_date_time",
            "value": "2026-01-02T03:04:00+00:00",
        },
    ]
    assert len(result["observations"]) == sum(len(item["observations"]) for item in result["items"])


def test_preview_marks_preview_and_uses_default_limit() -> None:
    users = [SimpleNamespace(id=f"u{i:02d}", display_name=f"User {i:02d}") for i in range(12)]
    result = _connector().preview(
        {
            "client": FakeClient(
                users=users,
                groups=[],
                applications=[],
                service_principals=[],
                policies=[],
            )
        }
    )

    assert result["ok"] is True
    assert result["preview"] is True
    assert result["count"] == 10


def test_preview_returns_not_ok_for_invalid_config() -> None:
    result = _connector().preview({"limit": "bad"})

    assert result["ok"] is False
    assert result["assets"] == []
    assert result["observations"] == []
    assert any("limit" in error for error in result["errors"])


def test_collect_honors_explicit_limit_after_deterministic_sort() -> None:
    result = _connector().collect({"client": FakeClient(), "limit": 2})

    assert result["ok"] is True
    assert result["count"] == 2
    assert [item["canonical_asset"]["asset_id"] for item in result["items"]] == [
        "m365:application:a1",
        "m365:conditional-access-policy:cap1",
    ]


def test_collect_with_limit_zero_returns_empty_without_clients() -> None:
    client = FakeClient()
    result = _connector().collect({"client": client, "limit": 0})

    assert result["ok"] is True
    assert result["preview"] is False
    assert result["items"] == []
    assert result["assets"] == []
    assert result["observations"] == []
    assert result["count"] == 0
    assert client.calls == []


@pytest.mark.parametrize(
    "config",
    [
        ["not", "a", "mapping"],
        {"limit": -1},
        {"limit": "bad"},
        {"client": object()},
        {"credential": object()},
        {"scopes": []},
        {"scopes": [""]},
        {"tenant": "not-supported"},
    ],
)
def test_invalid_config_returns_not_ok(config: Any) -> None:
    result = _connector().collect(config)

    assert result["ok"] is False
    assert result["assets"] == []
    assert result["observations"] == []
    assert result["errors"]


def test_m365_error_for_one_resource_type_is_swallowed() -> None:
    result = _connector().collect({"client": FakeClient(fail_users=True)})
    asset_ids = [item["canonical_asset"]["asset_id"] for item in result["items"]]

    assert result["ok"] is True
    assert "m365:user:u1" not in asset_ids
    assert asset_ids == [
        "m365:application:a1",
        "m365:conditional-access-policy:cap1",
        "m365:group:g1",
        "m365:service-principal:sp1",
    ]


@pytest.mark.parametrize(
    ("client", "absent_asset_id"),
    [
        (FakeClient(fail_groups=True), "m365:group:g1"),
        (FakeClient(fail_applications=True), "m365:application:a1"),
        (FakeClient(fail_service_principals=True), "m365:service-principal:sp1"),
        (FakeClient(fail_policies=True), "m365:conditional-access-policy:cap1"),
    ],
)
def test_m365_errors_are_isolated_per_resource_type(client: FakeClient, absent_asset_id: str) -> None:
    result = _connector().collect({"client": client})
    asset_ids = [item["canonical_asset"]["asset_id"] for item in result["items"]]

    assert result["ok"] is True
    assert absent_asset_id not in asset_ids
    assert len(asset_ids) == 4


def test_skips_m365_records_without_required_ids() -> None:
    result = _connector().collect(
        {
            "client": FakeClient(
                users=[SimpleNamespace(display_name="missing-id")],
                groups=[{"display_name": "missing-id"}],
                applications=[SimpleNamespace(display_name="missing-id")],
                service_principals=[SimpleNamespace(display_name="missing-id")],
                policies=[{"display_name": "missing-id"}],
            )
        }
    )

    assert result["ok"] is True
    assert result["items"] == []


def test_creates_graph_client_from_credential_and_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    created_clients: list[dict[str, Any]] = []
    credential = SimpleNamespace(get_token=lambda *scopes: object())

    class FakeGraphServiceClient(FakeClient):
        def __init__(self, *, credentials: Any, scopes: list[str]) -> None:
            created_clients.append({"credentials": credentials, "scopes": scopes})
            super().__init__(
                groups=[],
                applications=[],
                service_principals=[],
                policies=[],
            )

    monkeypatch.setitem(sys.modules, "msgraph", SimpleNamespace(GraphServiceClient=FakeGraphServiceClient))

    result = _connector().collect({"credential": credential, "scopes": ["User.Read.All"], "limit": 1})

    assert result["ok"] is True
    assert created_clients == [{"credentials": credential, "scopes": ["User.Read.All"]}]
    assert result["items"][0]["canonical_asset"]["asset_id"] == "m365:user:u1"


def test_creates_graph_client_with_default_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    created_clients: list[dict[str, Any]] = []
    default_credentials: list[Any] = []

    class FakeDefaultAzureCredential:
        def __init__(self) -> None:
            default_credentials.append(self)

        def get_token(self, *scopes: str) -> object:
            return object()

    class FakeGraphServiceClient(FakeClient):
        def __init__(self, *, credentials: Any, scopes: list[str]) -> None:
            created_clients.append({"credentials": credentials, "scopes": scopes})
            super().__init__(
                groups=[],
                applications=[],
                service_principals=[],
                policies=[],
            )

    monkeypatch.setitem(sys.modules, "msgraph", SimpleNamespace(GraphServiceClient=FakeGraphServiceClient))
    monkeypatch.setitem(
        sys.modules,
        "azure.identity",
        SimpleNamespace(DefaultAzureCredential=FakeDefaultAzureCredential),
    )

    result = _connector().collect({"limit": 1})

    assert result["ok"] is True
    assert created_clients == [
        {
            "credentials": default_credentials[0],
            "scopes": ["https://graph.microsoft.com/.default"],
        }
    ]
    assert result["items"][0]["canonical_asset"]["asset_id"] == "m365:user:u1"


def test_resolves_async_graph_get_calls() -> None:
    result = _connector().collect(
        {
            "client": FakeClient(
                async_users=True,
                groups=[],
                applications=[],
                service_principals=[],
                policies=[],
            )
        }
    )

    assert result["ok"] is True
    assert result["items"][0]["canonical_asset"]["asset_id"] == "m365:user:u1"


def test_format_value_supports_plain_dates() -> None:
    assert _connector()._format_value(date(2026, 7, 19)) == "2026-07-19"
