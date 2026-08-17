"""Build isolated, read-only clients for stored connector instances."""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Callable, Mapping
from dataclasses import fields, replace
from typing import Any, Protocol, cast

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.connectwise import ConnectWiseClient
from wait_local_agent.halopsa import HaloPSAClient
from wait_local_agent.models import ConnectorInstance
from wait_local_agent.net_security import (
    PinnedIpTransport,
    Resolver,
    validate_provider_origin,
)
from wait_local_agent.store import _contains_sensitive_config_key
from wait_local_agent.vault import SecretVault


class ConnectorFactoryError(Exception):
    """Raised when a connector instance cannot be converted safely."""


class ConnectorInstanceStore(Protocol):
    def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstance | None:
        ...


class VaultReader(Protocol):
    def get(self, key: str) -> Any:
        ...


type ReadClient = HaloPSAClient | ConnectWiseClient
type Builder = Callable[[Settings, httpx.BaseTransport], ReadClient]

SUPPORTED_CONNECTOR_TYPES: frozenset[str]


def _build_halopsa(settings: Settings, transport: httpx.BaseTransport) -> HaloPSAClient:
    return HaloPSAClient(settings, transport=transport)


def _build_connectwise(settings: Settings, transport: httpx.BaseTransport) -> ConnectWiseClient:
    return ConnectWiseClient(settings, transport=transport)


_BUILDERS: dict[str, Builder] = {
    "halopsa": _build_halopsa,
    "connectwise": _build_connectwise,
}
SUPPORTED_CONNECTOR_TYPES = frozenset(_BUILDERS)

_HALO_CREDENTIAL_KEYS = frozenset({"client_id", "client_secret", "tenant"})
_CONNECTWISE_CREDENTIAL_KEYS = frozenset({"company", "public_key", "private_key", "client_id"})
_HALO_CONFIG_KEYS = frozenset({"base_url"})
_CONNECTWISE_CONFIG_KEYS = frozenset({"base_url", "api_version"})
_VERSION_PATTERN = re.compile(r"^[0-9]{4}\.[0-9]+$")

# Credential-shaped fields are derived from the current Settings dataclass so
# newly added *_token/*_secret/etc. fields fail closed until deliberately
# classified. The special fields are provider identifiers that are credentials
# despite not having a credential-shaped suffix.
_SPECIAL_SECRET_SETTING_FIELDS = frozenset(
    {
        "halopsa_client_id",
        "halopsa_tenant",
        "halopsa_token_url",
        "connectwise_company",
        "connectwise_client_id",
        "kaseya_rmm_token_id",
    }
)
_SECRET_SUFFIXES = ("_secret", "_token", "_password", "_key", "_username")
_SECRET_SETTING_FIELDS = frozenset(
    field.name
    for field in fields(Settings)
    if field.name.endswith(_SECRET_SUFFIXES) or field.name in _SPECIAL_SECRET_SETTING_FIELDS
)


class _DuplicateCredentialKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateCredentialKey
        result[key] = value
    return result


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _credential_error(connector_type: str) -> ConnectorFactoryError:
    if connector_type == "halopsa":
        return ConnectorFactoryError(
            "invalid HaloPSA credentials; expected keys: client_id, client_secret, tenant"
        )
    return ConnectorFactoryError(
        "invalid ConnectWise credentials; expected keys: company, public_key, private_key, client_id"
    )


def _load_credentials(
    instance: ConnectorInstance,
    *,
    connector_type: str,
    base_settings: Settings,
    vault: VaultReader | None,
) -> dict[str, str]:
    credential_ref = instance.credential_ref
    if not isinstance(credential_ref, str) or not credential_ref.strip():
        raise ConnectorFactoryError("connector credential reference is required")
    try:
        secret = (vault or SecretVault(base_settings.vault_path)).get(credential_ref)
    except Exception as exc:
        raise ConnectorFactoryError("connector credentials could not be read") from exc
    if not isinstance(secret, str) or not secret:
        raise ConnectorFactoryError("connector credentials were not found")
    try:
        payload = json.loads(secret, object_pairs_hook=_reject_duplicate_keys)
    except Exception as exc:
        raise ConnectorFactoryError("connector credentials must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ConnectorFactoryError("connector credentials must be a JSON object")

    expected = _HALO_CREDENTIAL_KEYS if connector_type == "halopsa" else _CONNECTWISE_CREDENTIAL_KEYS
    if set(payload) != expected or any(not _non_empty_string(value) for value in payload.values()):
        raise _credential_error(connector_type)
    return {key: value for key, value in payload.items() if isinstance(value, str)}


def _load_config(instance: ConnectorInstance, *, connector_type: str) -> dict[str, object]:
    try:
        payload = json.loads(instance.config_json or "{}")
    except Exception as exc:
        raise ConnectorFactoryError("connector config_json must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ConnectorFactoryError("connector config_json must be a JSON object")
    if _contains_sensitive_config_key(payload):
        raise ConnectorFactoryError("connector config_json must not contain credentials")

    expected = _HALO_CONFIG_KEYS if connector_type == "halopsa" else _CONNECTWISE_CONFIG_KEYS
    if set(payload) - expected:
        raise ConnectorFactoryError("connector config_json contains unsupported fields")
    base_url = payload.get("base_url")
    if not _non_empty_string(base_url):
        raise ConnectorFactoryError("connector config_json requires a base_url")
    if connector_type == "connectwise" and "api_version" in payload:
        version = payload["api_version"]
        if not isinstance(version, str):
            raise ConnectorFactoryError("ConnectWise API version is invalid")
    return payload


def _api_base_url(base_url: str, *, connector_type: str) -> str:
    stripped = base_url.rstrip("/")
    if connector_type == "halopsa":
        return stripped if stripped.endswith("/api") else f"{stripped}/api"
    suffix = "/v4_6_release/apis/3.0"
    return stripped if stripped.endswith(suffix) else f"{stripped}{suffix}"


def _origin(url: httpx.URL) -> tuple[str, str, int]:
    scheme = url.scheme.casefold()
    host = (url.host or "").casefold().rstrip(".")
    port = url.port or (443 if scheme == "https" else 80)
    return scheme, host, port


def _validate_urls(
    config: Mapping[str, object],
    *,
    connector_type: str,
    allowed_hosts: tuple[str, ...],
) -> str:
    base_url = config["base_url"]
    if not isinstance(base_url, str):
        raise ConnectorFactoryError("connector base_url is invalid")
    try:
        api_url = validate_provider_origin(base_url, allowed_hosts=allowed_hosts)
        if connector_type == "halopsa":
            token_url = f"{_api_base_url(str(api_url), connector_type=connector_type)}/auth/token"
            token_origin = validate_provider_origin(token_url, allowed_hosts=allowed_hosts)
            if _origin(api_url) != _origin(token_origin):
                raise ConnectorFactoryError("HaloPSA token origin must match the API origin")
        return str(api_url).rstrip("/")
    except ConnectorFactoryError:
        raise
    except Exception as exc:
        raise ConnectorFactoryError("connector origin failed network policy validation") from exc


def _validate_connectwise_version(value: object) -> str:
    if not isinstance(value, str):
        raise ConnectorFactoryError("ConnectWise API version is invalid")
    version = value.strip()
    if len(version) > 20 or not _VERSION_PATTERN.fullmatch(version):
        raise ConnectorFactoryError("ConnectWise API version is invalid")
    return version


def _sanitized_settings(
    base_settings: Settings,
    *,
    connector_type: str,
    config: Mapping[str, object],
    credentials: Mapping[str, str],
    base_url: str,
) -> Settings:
    values: dict[str, object] = {
        field_name: ""
        for field_name in _SECRET_SETTING_FIELDS
        if field_name != "vault_path"
    }
    values.update(
        {
            "allow_write_actions": False,
            "allow_http_probing": base_settings.allow_http_probing,
            "connector_timeout_seconds": base_settings.connector_timeout_seconds,
            "connector_instance_allowed_hosts": base_settings.connector_instance_allowed_hosts,
            "vault_path": base_settings.vault_path,
            "halopsa_base_url": "",
            "halopsa_token_url": "",  # nosec B105: clear inherited token endpoint
            "halopsa_ticket_write_endpoint": "",
            "halopsa_action_write_endpoint": "",
            "connectwise_base_url": "",
        }
    )
    if connector_type == "halopsa":
        values.update(
            {
                "halopsa_base_url": base_url,
                "halopsa_client_id": credentials["client_id"],
                "halopsa_client_secret": credentials["client_secret"],
                "halopsa_tenant": credentials["tenant"],
            }
        )
    else:
        effective_version = config.get("api_version", base_settings.connectwise_api_version)
        values.update(
            {
                "connectwise_base_url": base_url,
                "connectwise_company": credentials["company"],
                "connectwise_public_key": credentials["public_key"],
                "connectwise_private_key": credentials["private_key"],
                "connectwise_client_id": credentials["client_id"],
                "connectwise_api_version": _validate_connectwise_version(effective_version),
            }
        )
    return replace(base_settings, **cast(Any, values))


def build_read_client(
    instance: ConnectorInstance,
    *,
    base_settings: Settings,
    vault: VaultReader | None = None,
    resolver: Resolver | None = None,
    inner_transport: httpx.BaseTransport | None = None,
) -> ReadClient:
    """Build a read-only, per-instance provider client."""
    connector_type = instance.connector_type.casefold().strip() if isinstance(instance.connector_type, str) else ""
    builder = _BUILDERS.get(connector_type)
    if builder is None:
        raise ConnectorFactoryError("unsupported connector_type")
    if instance.status != "active":
        raise ConnectorFactoryError("connector instance is not active")

    credentials = _load_credentials(
        instance,
        connector_type=connector_type,
        base_settings=base_settings,
        vault=vault,
    )
    config = _load_config(instance, connector_type=connector_type)
    base_url = _validate_urls(
        config,
        connector_type=connector_type,
        allowed_hosts=base_settings.connector_instance_allowed_hosts,
    )
    per_instance_settings = _sanitized_settings(
        base_settings,
        connector_type=connector_type,
        config=config,
        credentials=credentials,
        base_url=base_url,
    )
    try:
        pinned = PinnedIpTransport(
            allowed_hosts=base_settings.connector_instance_allowed_hosts,
            timeout=base_settings.connector_timeout_seconds,
            resolver=resolver or socket.getaddrinfo,
            transport=inner_transport,
        )
        return builder(per_instance_settings, pinned)
    except ConnectorFactoryError:
        raise
    except Exception as exc:
        raise ConnectorFactoryError("connector client could not be constructed") from exc


def build_read_client_for(
    store: ConnectorInstanceStore,
    connector_instance_id: str,
    *,
    base_settings: Settings,
    vault: VaultReader | None = None,
    resolver: Resolver | None = None,
) -> ReadClient:
    """Load an instance from storage and build its isolated read client."""
    try:
        instance = store.get_connector_instance(connector_instance_id)
    except Exception as exc:
        raise ConnectorFactoryError("connector instance could not be loaded") from exc
    if instance is None:
        raise ConnectorFactoryError("connector instance was not found")
    if instance.status != "active":
        raise ConnectorFactoryError("connector instance is not active")
    return build_read_client(
        instance,
        base_settings=base_settings,
        vault=vault,
        resolver=resolver,
    )
