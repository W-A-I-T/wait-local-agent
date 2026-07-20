from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any


class _FallbackAwsError(Exception):
    """Fallback for test environments where botocore is not installed yet."""


try:
    import botocore.exceptions as _botocore_exceptions
except ImportError:
    BotoCoreError: type[BaseException] = _FallbackAwsError
    ClientError: type[BaseException] = _FallbackAwsError
    NoCredentialsError: type[BaseException] = _FallbackAwsError
else:
    BotoCoreError = _botocore_exceptions.BotoCoreError
    ClientError = _botocore_exceptions.ClientError
    NoCredentialsError = _botocore_exceptions.NoCredentialsError

AWS_ERROR_TYPES: tuple[type[BaseException], ...] = (BotoCoreError, ClientError, NoCredentialsError)

AwsConfig = Mapping[str, Any] | None


class AwsInventoryConnector:
    """Read-only inventory connector for AWS account resources."""

    module_id = "aws-inventory"
    name = "AWS Inventory"
    version = "1.0"
    asset_types = [
        "cloud-bucket",
        "cloud-iam-user",
        "cloud-instance",
        "cloud-security-group",
    ]

    def manifest(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": "Read-only inventory of AWS EC2, S3, security group, and IAM resources.",
            "asset_type": "cloud-resource",
            "asset_types": self.asset_types,
            "read_only": True,
            "dependencies": ["boto3"],
            "platforms": ["cloud"],
        }

    def scope(self, config: AwsConfig = None) -> dict[str, Any]:
        return {
            "read_only": True,
            "stdlib_only": False,
            "paths": ["aws:ec2", "aws:s3", "aws:iam"],
            "operations": [
                "ec2.describe_instances",
                "s3.list_buckets",
                "ec2.describe_security_groups",
                "iam.list_users",
            ],
            "network": True,
            "shell": False,
        }

    def validate_config(self, config: AwsConfig = None) -> dict[str, Any]:
        errors: list[str] = []
        if config is not None and not isinstance(config, Mapping):
            errors.append("config must be a mapping when provided")
            return {"ok": False, "errors": errors}

        if isinstance(config, Mapping):
            unsupported_keys = sorted(set(config) - {"limit", "region", "session"})
            if unsupported_keys:
                errors.append(f"unsupported config keys: {', '.join(unsupported_keys)}")

            if "limit" in config:
                limit = config["limit"]
                if not isinstance(limit, int) or limit < 0:
                    errors.append("limit must be a non-negative integer")

            if "region" in config and (not isinstance(config["region"], str) or not config["region"].strip()):
                errors.append("region must be a non-empty string")

            session = config.get("session")
            if session is not None and not callable(getattr(session, "client", None)):
                errors.append("session must provide a client(service_name) method")

        return {"ok": not errors, "errors": errors}

    def preview(self, config: AwsConfig = None) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation["ok"]:
            return self._invalid_result(validation["errors"])

        return self._collect_result(config, preview=True, default_limit=10)

    def collect(self, config: AwsConfig = None) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation["ok"]:
            return self._invalid_result(validation["errors"])

        return self._collect_result(config, preview=False, default_limit=None)

    def _collect_result(self, config: AwsConfig, *, preview: bool, default_limit: int | None) -> dict[str, Any]:
        limit = self._config_limit(config, default=default_limit)
        if limit == 0:
            return self._result([], preview=preview)

        session = self._session(config)
        records = [
            *self._ec2_instance_records(session, config),
            *self._s3_bucket_records(session),
            *self._security_group_records(session),
            *self._iam_user_records(session),
        ]
        records.sort(key=lambda record: str(record["asset_id"]))
        if limit is not None:
            records = records[:limit]
        return self._result(records, preview=preview)

    @staticmethod
    def _config_limit(config: AwsConfig, default: int | None) -> int | None:
        if isinstance(config, Mapping) and "limit" in config:
            return int(config["limit"])
        return default

    @staticmethod
    def _session(config: AwsConfig) -> Any:
        if isinstance(config, Mapping) and config.get("session") is not None:
            return config["session"]

        from importlib import import_module

        boto3 = import_module("boto3")
        region = config.get("region") if isinstance(config, Mapping) else None
        if isinstance(region, str):
            return boto3.Session(region_name=region)
        return boto3.Session()

    @staticmethod
    def _client(session: Any, service_name: str) -> Any:
        return session.client(service_name)

    def _ec2_instance_records(self, session: Any, config: AwsConfig) -> list[dict[str, Any]]:
        try:
            ec2 = self._client(session, "ec2")
            response = ec2.describe_instances()
        except AWS_ERROR_TYPES:
            return []

        region = self._region_name(config, session, ec2)
        records: list[dict[str, Any]] = []
        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                instance_id = str(instance.get("InstanceId", ""))
                if not instance_id:
                    continue
                state = instance.get("State", {}).get("Name", "")
                records.append(
                    {
                        "asset_type": "cloud-instance",
                        "asset_id": f"aws:ec2:{instance_id}",
                        "name": instance_id,
                        "attributes": {
                            "instance_id": instance_id,
                            "instance_type": instance.get("InstanceType", ""),
                            "state": state,
                            "region": region,
                            "vpc_id": instance.get("VpcId", ""),
                            "private_ip": instance.get("PrivateIpAddress", ""),
                        },
                    }
                )
        return records

    def _s3_bucket_records(self, session: Any) -> list[dict[str, Any]]:
        try:
            s3 = self._client(session, "s3")
            response = s3.list_buckets()
        except AWS_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for bucket in response.get("Buckets", []):
            name = str(bucket.get("Name", ""))
            if not name:
                continue
            records.append(
                {
                    "asset_type": "cloud-bucket",
                    "asset_id": f"aws:s3:{name}",
                    "name": name,
                    "attributes": {
                        "name": name,
                        "creation_date": self._format_value(bucket.get("CreationDate", "")),
                    },
                }
            )
        return records

    def _security_group_records(self, session: Any) -> list[dict[str, Any]]:
        try:
            ec2 = self._client(session, "ec2")
            response = ec2.describe_security_groups()
        except AWS_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for security_group in response.get("SecurityGroups", []):
            group_id = str(security_group.get("GroupId", ""))
            if not group_id:
                continue
            records.append(
                {
                    "asset_type": "cloud-security-group",
                    "asset_id": f"aws:sg:{group_id}",
                    "name": security_group.get("GroupName", group_id),
                    "attributes": {
                        "group_id": group_id,
                        "group_name": security_group.get("GroupName", ""),
                        "vpc_id": security_group.get("VpcId", ""),
                        "ingress_rule_count": len(security_group.get("IpPermissions", [])),
                    },
                }
            )
        return records

    def _iam_user_records(self, session: Any) -> list[dict[str, Any]]:
        try:
            iam = self._client(session, "iam")
            response = iam.list_users()
        except AWS_ERROR_TYPES:
            return []

        records: list[dict[str, Any]] = []
        for user in response.get("Users", []):
            user_name = str(user.get("UserName", ""))
            if not user_name:
                continue
            records.append(
                {
                    "asset_type": "cloud-iam-user",
                    "asset_id": f"aws:iam:{user_name}",
                    "name": user_name,
                    "attributes": {
                        "user_name": user_name,
                        "user_id": user.get("UserId", ""),
                        "create_date": self._format_value(user.get("CreateDate", "")),
                    },
                }
            )
        return records

    @staticmethod
    def _region_name(config: AwsConfig, session: Any, ec2_client: Any) -> str:
        if isinstance(config, Mapping) and isinstance(config.get("region"), str):
            return str(config["region"])
        session_region = getattr(session, "region_name", None)
        if isinstance(session_region, str):
            return session_region
        client_meta = getattr(ec2_client, "meta", None)
        client_region = getattr(client_meta, "region_name", None)
        if isinstance(client_region, str):
            return client_region
        return ""

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
            "module_id": AwsInventoryConnector.module_id,
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
