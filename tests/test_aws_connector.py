from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from wait_local_agent.cloud_connectors.aws import AwsInventoryConnector, NoCredentialsError


class FakeEc2Client:
    def __init__(self, *, fail_instances: bool = False, fail_security_groups: bool = False) -> None:
        self.fail_instances = fail_instances
        self.fail_security_groups = fail_security_groups
        self.meta = type("Meta", (), {"region_name": "us-west-2"})()

    def describe_instances(self) -> dict[str, Any]:
        if self.fail_instances:
            raise NoCredentialsError()
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-002",
                            "InstanceType": "t3.small",
                            "State": {"Name": "stopped"},
                            "VpcId": "vpc-2",
                            "PrivateIpAddress": "10.0.2.10",
                        },
                        {
                            "InstanceId": "i-001",
                            "InstanceType": "t3.micro",
                            "State": {"Name": "running"},
                            "VpcId": "vpc-1",
                            "PrivateIpAddress": "10.0.1.10",
                        },
                    ]
                }
            ]
        }

    def describe_security_groups(self) -> dict[str, Any]:
        if self.fail_security_groups:
            raise NoCredentialsError()
        return {
            "SecurityGroups": [
                {
                    "GroupId": "sg-001",
                    "GroupName": "web",
                    "VpcId": "vpc-1",
                    "IpPermissions": [{"FromPort": 443}, {"FromPort": 80}],
                }
            ]
        }


class FakeS3Client:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def list_buckets(self) -> dict[str, Any]:
        if self.fail:
            raise NoCredentialsError()
        return {
            "Buckets": [
                {
                    "Name": "wait-artifacts",
                    "CreationDate": datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
                }
            ]
        }


class FakeIamClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def list_users(self) -> dict[str, Any]:
        if self.fail:
            raise NoCredentialsError()
        return {
            "Users": [
                {
                    "UserName": "automation",
                    "UserId": "AIDAEXAMPLE",
                    "CreateDate": datetime(2025, 5, 6, 7, 8, tzinfo=UTC),
                }
            ]
        }


class FakeSession:
    def __init__(
        self,
        *,
        region_name: str = "ca-central-1",
        fail_instances: bool = False,
        fail_security_groups: bool = False,
        fail_s3: bool = False,
        fail_iam: bool = False,
    ) -> None:
        self.region_name = region_name
        self.fail_instances = fail_instances
        self.fail_security_groups = fail_security_groups
        self.fail_s3 = fail_s3
        self.fail_iam = fail_iam
        self.requested_services: list[str] = []

    def client(self, service_name: str) -> Any:
        self.requested_services.append(service_name)
        if service_name == "ec2":
            return FakeEc2Client(
                fail_instances=self.fail_instances,
                fail_security_groups=self.fail_security_groups,
            )
        if service_name == "s3":
            return FakeS3Client(fail=self.fail_s3)
        if service_name == "iam":
            return FakeIamClient(fail=self.fail_iam)
        raise AssertionError(f"unexpected service: {service_name}")


class EmptyIdEc2Client:
    meta = type("Meta", (), {"region_name": "ap-southeast-2"})()

    def describe_instances(self) -> dict[str, Any]:
        return {"Reservations": [{"Instances": [{"InstanceType": "t3.nano"}]}]}

    def describe_security_groups(self) -> dict[str, Any]:
        return {"SecurityGroups": [{"GroupName": "missing-id"}]}


class EmptyIdS3Client:
    def list_buckets(self) -> dict[str, Any]:
        return {"Buckets": [{"CreationDate": datetime(2026, 1, 1, tzinfo=UTC)}]}


class EmptyIdIamClient:
    def list_users(self) -> dict[str, Any]:
        return {"Users": [{"UserId": "AIDAMISSING"}]}


class EmptyIdSession:
    region_name = None

    def client(self, service_name: str) -> Any:
        if service_name == "ec2":
            return EmptyIdEc2Client()
        if service_name == "s3":
            return EmptyIdS3Client()
        if service_name == "iam":
            return EmptyIdIamClient()
        raise AssertionError(f"unexpected service: {service_name}")


def _connector() -> AwsInventoryConnector:
    return AwsInventoryConnector()


def _items_by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["canonical_asset"]["asset_id"]: item for item in result["items"]}


def test_manifest_and_scope_advertise_read_only_aws_inventory() -> None:
    manifest = _connector().manifest()
    assert manifest["module_id"] == "aws-inventory"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["cloud"]
    assert manifest["asset_type"] == "cloud-resource"
    assert manifest["asset_types"] == [
        "cloud-bucket",
        "cloud-iam-user",
        "cloud-instance",
        "cloud-security-group",
    ]

    scope = _connector().scope()
    assert scope["read_only"] is True
    assert scope["network"] is True
    assert scope["shell"] is False
    assert scope["paths"] == ["aws:ec2", "aws:s3", "aws:iam"]
    assert scope["operations"] == [
        "ec2.describe_instances",
        "s3.list_buckets",
        "ec2.describe_security_groups",
        "iam.list_users",
    ]


def test_collect_maps_all_supported_resource_types_to_canonical_assets() -> None:
    session = FakeSession()
    result = _connector().collect({"session": session})
    items = _items_by_id(result)

    assert result["module_id"] == "aws-inventory"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 5
    assert list(items) == [
        "aws:ec2:i-001",
        "aws:ec2:i-002",
        "aws:iam:automation",
        "aws:s3:wait-artifacts",
        "aws:sg:sg-001",
    ]
    assert session.requested_services == ["ec2", "s3", "ec2", "iam"]

    instance = items["aws:ec2:i-001"]["canonical_asset"]
    assert instance["asset_type"] == "cloud-instance"
    assert instance["asset_id"] == "aws:ec2:i-001"
    assert instance["name"] == "i-001"
    assert instance["attributes"] == {
        "instance_id": "i-001",
        "instance_type": "t3.micro",
        "state": "running",
        "region": "ca-central-1",
        "vpc_id": "vpc-1",
        "private_ip": "10.0.1.10",
    }

    bucket = items["aws:s3:wait-artifacts"]["canonical_asset"]
    assert bucket["asset_type"] == "cloud-bucket"
    assert bucket["asset_id"] == "aws:s3:wait-artifacts"
    assert bucket["attributes"] == {
        "name": "wait-artifacts",
        "creation_date": "2026-01-02T03:04:00+00:00",
    }

    security_group = items["aws:sg:sg-001"]["canonical_asset"]
    assert security_group["asset_type"] == "cloud-security-group"
    assert security_group["asset_id"] == "aws:sg:sg-001"
    assert security_group["attributes"] == {
        "group_id": "sg-001",
        "group_name": "web",
        "vpc_id": "vpc-1",
        "ingress_rule_count": 2,
    }

    user = items["aws:iam:automation"]["canonical_asset"]
    assert user["asset_type"] == "cloud-iam-user"
    assert user["asset_id"] == "aws:iam:automation"
    assert user["attributes"] == {
        "user_name": "automation",
        "user_id": "AIDAEXAMPLE",
        "create_date": "2025-05-06T07:08:00+00:00",
    }


def test_collect_emits_one_observation_per_asset_attribute() -> None:
    result = _connector().collect({"session": FakeSession()})
    instance_observations = _items_by_id(result)["aws:ec2:i-001"]["observations"]

    assert instance_observations == [
        {
            "asset_type": "cloud-instance",
            "asset_id": "aws:ec2:i-001",
            "key": "cloud.instance_id",
            "value": "i-001",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "aws:ec2:i-001",
            "key": "cloud.instance_type",
            "value": "t3.micro",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "aws:ec2:i-001",
            "key": "cloud.state",
            "value": "running",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "aws:ec2:i-001",
            "key": "cloud.region",
            "value": "ca-central-1",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "aws:ec2:i-001",
            "key": "cloud.vpc_id",
            "value": "vpc-1",
        },
        {
            "asset_type": "cloud-instance",
            "asset_id": "aws:ec2:i-001",
            "key": "cloud.private_ip",
            "value": "10.0.1.10",
        },
    ]
    assert len(result["observations"]) == sum(len(item["observations"]) for item in result["items"])


def test_region_config_overrides_session_region() -> None:
    result = _connector().collect({"session": FakeSession(region_name="us-east-1"), "region": "eu-west-1"})
    instance = _items_by_id(result)["aws:ec2:i-001"]["canonical_asset"]
    assert instance["attributes"]["region"] == "eu-west-1"


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
        "aws:ec2:i-001",
        "aws:ec2:i-002",
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
        {"region": ""},
        {"session": object()},
        {"profile": "not-supported"},
    ],
)
def test_invalid_config_returns_not_ok(config: Any) -> None:
    result = _connector().collect(config)

    assert result["ok"] is False
    assert result["assets"] == []
    assert result["observations"] == []
    assert result["errors"]


def test_aws_error_for_one_resource_type_is_swallowed() -> None:
    result = _connector().collect({"session": FakeSession(fail_instances=True)})
    asset_ids = [item["canonical_asset"]["asset_id"] for item in result["items"]]

    assert result["ok"] is True
    assert "aws:ec2:i-001" not in asset_ids
    assert asset_ids == [
        "aws:iam:automation",
        "aws:s3:wait-artifacts",
        "aws:sg:sg-001",
    ]


@pytest.mark.parametrize(
    ("session", "absent_asset_id"),
    [
        (FakeSession(fail_s3=True), "aws:s3:wait-artifacts"),
        (FakeSession(fail_security_groups=True), "aws:sg:sg-001"),
        (FakeSession(fail_iam=True), "aws:iam:automation"),
    ],
)
def test_aws_errors_are_isolated_per_resource_type(session: FakeSession, absent_asset_id: str) -> None:
    result = _connector().collect({"session": session})
    asset_ids = [item["canonical_asset"]["asset_id"] for item in result["items"]]

    assert result["ok"] is True
    assert absent_asset_id not in asset_ids
    assert len(asset_ids) == 4


def test_skips_aws_records_without_required_ids_and_falls_back_to_client_region() -> None:
    result = _connector().collect({"session": EmptyIdSession()})

    assert result["ok"] is True
    assert result["items"] == []
    assert _connector()._region_name({}, EmptyIdSession(), EmptyIdEc2Client()) == "ap-southeast-2"
    assert _connector()._region_name({}, object(), object()) == ""


def test_creates_boto3_session_from_region_config(monkeypatch: pytest.MonkeyPatch) -> None:
    created_regions: list[str | None] = []

    def _session_factory(region_name: str | None = None) -> FakeSession:
        created_regions.append(region_name)
        return FakeSession(region_name=region_name or "")

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(Session=_session_factory))

    result = _connector().collect({"region": "us-east-2", "limit": 1})

    assert result["ok"] is True
    assert created_regions == ["us-east-2"]
    assert result["items"][0]["canonical_asset"]["attributes"]["region"] == "us-east-2"


def test_creates_ambient_boto3_session_without_region(monkeypatch: pytest.MonkeyPatch) -> None:
    created_regions: list[str | None] = []

    def _session_factory(region_name: str | None = None) -> FakeSession:
        created_regions.append(region_name)
        return FakeSession(region_name=region_name or "ca-central-1")

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(Session=_session_factory))

    result = _connector().collect({"limit": 1})

    assert result["ok"] is True
    assert created_regions == [None]
    assert result["items"][0]["canonical_asset"]["attributes"]["region"] == "ca-central-1"


def test_format_value_supports_plain_dates() -> None:
    assert _connector()._format_value(date(2026, 7, 19)) == "2026-07-19"
