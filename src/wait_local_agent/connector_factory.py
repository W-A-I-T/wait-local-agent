"""Build isolated, read-only clients for stored connector instances."""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Callable, Mapping
from dataclasses import fields, replace
from typing import Any, Protocol, cast

import httpx

from wait_local_agent.autotask import AutotaskClient
from wait_local_agent.config import Settings
from wait_local_agent.connectwise import ConnectWiseClient
from wait_local_agent.dattormm import DattoRmmAdapter
from wait_local_agent.halopsa import HaloPSAClient
from wait_local_agent.m365_auth import M365Connection, M365TokenProvider, validate_m365_credentials
from wait_local_agent.m365_graph import M365GraphClient
from wait_local_agent.models import ConnectorInstance
from wait_local_agent.ncentral import NCentralRmmAdapter
from wait_local_agent.net_security import (
    PinnedIpTransport,
    Resolver,
    validate_provider_origin,
)
from wait_local_agent.ninjaone import NinjaOneRmmAdapter
from wait_local_agent.servicenow import ServiceNowClient
from wait_local_agent.store import _contains_sensitive_config_key
from wait_local_agent.syncro import SyncroClient
from wait_local_agent.vault import SecretVault


class ConnectorFactoryError(Exception):
    """Raised when a connector instance cannot be converted safely."""


class ConnectorInstanceStore(Protocol):
    def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstance | None:
        ...


class VaultReader(Protocol):
    def get(self, key: str) -> Any:
        ...


type ReadClient = (
    HaloPSAClient
    | ConnectWiseClient
    | AutotaskClient
    | SyncroClient
    | ServiceNowClient
    | NinjaOneRmmAdapter
    | DattoRmmAdapter
    | NCentralRmmAdapter
    | M365GraphClient
)
type Builder = Callable[[Settings, httpx.BaseTransport], ReadClient]

SUPPORTED_CONNECTOR_TYPES: frozenset[str]


def _build_halopsa(settings: Settings, transport: httpx.BaseTransport) -> HaloPSAClient:
    return HaloPSAClient(settings, transport=transport)


def _build_connectwise(settings: Settings, transport: httpx.BaseTransport) -> ConnectWiseClient:
    return ConnectWiseClient(settings, transport=transport)


def _build_autotask(settings: Settings, transport: httpx.BaseTransport) -> AutotaskClient:
    return AutotaskClient(settings, transport=transport)


def _build_syncro(settings: Settings, transport: httpx.BaseTransport) -> SyncroClient:
    return SyncroClient(settings, transport=transport)


def _build_servicenow(settings: Settings, transport: httpx.BaseTransport) -> ServiceNowClient:
    return ServiceNowClient(settings, transport=transport)


def _build_ninjaone(settings: Settings, transport: httpx.BaseTransport) -> NinjaOneRmmAdapter:
    return NinjaOneRmmAdapter(settings, transport=transport)


def _build_dattormm(settings: Settings, transport: httpx.BaseTransport) -> DattoRmmAdapter:
    return DattoRmmAdapter(settings, transport=transport)


def _build_ncentral(settings: Settings, transport: httpx.BaseTransport) -> NCentralRmmAdapter:
    return NCentralRmmAdapter(settings, transport=transport)


def _build_m365(settings: Settings, transport: httpx.BaseTransport) -> M365GraphClient:
    return M365GraphClient(settings, transport=transport)


_BUILDERS: dict[str, Builder] = {
    "halopsa": _build_halopsa,
    "connectwise": _build_connectwise,
    "autotask": _build_autotask,
    "syncro": _build_syncro,
    "servicenow": _build_servicenow,
    "ninjaone": _build_ninjaone,
    "dattormm": _build_dattormm,
    "ncentral": _build_ncentral,
    "m365": _build_m365,
}
SUPPORTED_CONNECTOR_TYPES = frozenset(_BUILDERS)

_HALO_CREDENTIAL_KEYS = frozenset({"client_id", "client_secret", "tenant"})
_CONNECTWISE_CREDENTIAL_KEYS = frozenset({"company", "public_key", "private_key", "client_id"})
_AUTOTASK_CREDENTIAL_KEYS = frozenset({"integration_code", "username", "secret"})
_SYNCRO_CREDENTIAL_KEYS = frozenset({"api_key", "subdomain"})
_SERVICENOW_CREDENTIAL_KEYS = frozenset({"username", "password"})
_NINJAONE_CREDENTIAL_KEYS = frozenset({"access_token"})
_DATTORMM_CREDENTIAL_KEYS = frozenset({"access_token"})
_NCENTRAL_CREDENTIAL_KEYS = frozenset({"access_token"})
_M365_CONFIG_KEYS: frozenset[str] = frozenset()
_HALO_CONFIG_KEYS = frozenset({"base_url"})
_CONNECTWISE_CONFIG_KEYS = frozenset({"base_url", "api_version"})
_AUTOTASK_CONFIG_KEYS = frozenset({"base_url"})
_SYNCRO_CONFIG_KEYS = frozenset({"base_url"})
_SERVICENOW_CONFIG_KEYS = frozenset({"base_url", "api_version"})
_NINJAONE_CONFIG_KEYS = frozenset({"base_url", "organization_map_json", "page_size"})
_DATTORMM_CONFIG_KEYS = frozenset({"base_url", "site_map_json", "page_size"})
_NCENTRAL_CONFIG_KEYS = frozenset({"base_url", "org_unit_map_json", "page_size"})
# Syncro derives its origin from the credential subdomain. All other
# instance-backed providers require an explicit, policy-validated base URL.
_BASE_URL_REQUIRED_BY_TYPE: dict[str, bool] = {
    "halopsa": True,
    "connectwise": True,
    "autotask": True,
    "syncro": False,
    "servicenow": True,
    "ninjaone": True,
    "dattormm": True,
    "ncentral": True,
    "m365": False,
}
_VERSION_PATTERN = re.compile(r"^[0-9]{4}\.[0-9]+$")
_SUBDOMAIN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SERVICENOW_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,20}$")

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
    expected = {
        "halopsa": "client_id, client_secret, tenant",
        "connectwise": "company, public_key, private_key, client_id",
        "autotask": "integration_code, username, secret",
        "syncro": "api_key, subdomain",
        "servicenow": "username, password",
        "ninjaone": "access_token",
        "dattormm": "access_token",
        "ncentral": "access_token",
        "m365": "mode plus the exact fields for client_credentials or static_token",
    }[connector_type]
    labels = {
        "halopsa": "HaloPSA",
        "connectwise": "ConnectWise",
        "autotask": "Autotask",
        "syncro": "Syncro",
        "servicenow": "ServiceNow",
        "ninjaone": "NinjaOne",
        "dattormm": "Datto RMM",
        "ncentral": "N-central",
        "m365": "Microsoft 365",
    }
    return ConnectorFactoryError(
        f"invalid {labels[connector_type]} credentials; expected keys: {expected}"
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

    if connector_type == "m365":
        try:
            return validate_m365_credentials(payload)
        except Exception as exc:
            raise _credential_error(connector_type) from exc

    expected = {
        "halopsa": _HALO_CREDENTIAL_KEYS,
        "connectwise": _CONNECTWISE_CREDENTIAL_KEYS,
        "autotask": _AUTOTASK_CREDENTIAL_KEYS,
        "syncro": _SYNCRO_CREDENTIAL_KEYS,
        "servicenow": _SERVICENOW_CREDENTIAL_KEYS,
        "ninjaone": _NINJAONE_CREDENTIAL_KEYS,
        "dattormm": _DATTORMM_CREDENTIAL_KEYS,
        "ncentral": _NCENTRAL_CREDENTIAL_KEYS,
        "m365": frozenset(),
    }[connector_type]
    if set(payload) != expected or any(not _non_empty_string(value) for value in payload.values()):
        raise _credential_error(connector_type)
    if connector_type == "syncro":
        subdomain = cast(str, payload["subdomain"]).strip().casefold()
        if not _SUBDOMAIN_PATTERN.fullmatch(subdomain):
            raise _credential_error(connector_type)
        payload["subdomain"] = subdomain
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

    expected = {
        "halopsa": _HALO_CONFIG_KEYS,
        "connectwise": _CONNECTWISE_CONFIG_KEYS,
        "autotask": _AUTOTASK_CONFIG_KEYS,
        "syncro": _SYNCRO_CONFIG_KEYS,
        "servicenow": _SERVICENOW_CONFIG_KEYS,
        "ninjaone": _NINJAONE_CONFIG_KEYS,
        "dattormm": _DATTORMM_CONFIG_KEYS,
        "ncentral": _NCENTRAL_CONFIG_KEYS,
        "m365": _M365_CONFIG_KEYS,
    }[connector_type]
    if set(payload) - expected:
        raise ConnectorFactoryError("connector config_json contains unsupported fields")
    base_url = payload.get("base_url")
    if _BASE_URL_REQUIRED_BY_TYPE[connector_type] and not _non_empty_string(base_url):
        raise ConnectorFactoryError("connector config_json requires a base_url")
    if connector_type == "connectwise" and "api_version" in payload:
        version = payload["api_version"]
        if not isinstance(version, str):
            raise ConnectorFactoryError("ConnectWise API version is invalid")
    if connector_type == "servicenow" and "api_version" in payload:
        version = payload["api_version"]
        if not isinstance(version, str):
            raise ConnectorFactoryError("ServiceNow API version is invalid")
    map_keys = {
        "ninjaone": "organization_map_json",
        "dattormm": "site_map_json",
        "ncentral": "org_unit_map_json",
    }
    map_key = map_keys.get(connector_type)
    if map_key is not None and map_key in payload:
        mapping = payload[map_key]
        if not isinstance(mapping, str) or not mapping.strip():
            raise ConnectorFactoryError(f"{connector_type} tenant mapping is invalid")
        try:
            parsed_mapping = json.loads(mapping)
        except ValueError as exc:
            raise ConnectorFactoryError(f"{connector_type} tenant mapping is invalid") from exc
        if not isinstance(parsed_mapping, dict):
            raise ConnectorFactoryError(f"{connector_type} tenant mapping is invalid")
    if "page_size" in payload:
        page_size = payload["page_size"]
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ConnectorFactoryError("connector page_size is invalid")
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
    syncro_subdomain: str | None = None,
) -> str:
    if connector_type == "m365":
        # The profile has no origin input. Keep the Graph origin a code-level
        # constant so a vault record cannot turn this into an SSRF primitive.
        return "https://graph.microsoft.com/v1.0"
    base_url = config.get("base_url")
    if connector_type == "syncro" and not _non_empty_string(base_url):
        normalized_subdomain = syncro_subdomain.strip().casefold() if isinstance(syncro_subdomain, str) else ""
        if not _SUBDOMAIN_PATTERN.fullmatch(normalized_subdomain):
            raise ConnectorFactoryError("invalid Syncro credentials; expected a valid subdomain")
        base_url = f"https://{normalized_subdomain}.syncromsp.com"
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


def _validate_servicenow_version(value: object) -> str:
    if not isinstance(value, str):
        raise ConnectorFactoryError("ServiceNow API version is invalid")
    version = value.strip().strip("/")
    if version and not _SERVICENOW_VERSION_PATTERN.fullmatch(version):
        raise ConnectorFactoryError("ServiceNow API version is invalid")
    return version


def _config_page_size(config: Mapping[str, object], default: int) -> int:
    value = config.get("page_size", default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


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
            "syncro_base_url": "",
            "servicenow_base_url": "",
            "servicenow_api_version": "",
            "autotask_base_url": "",
            "ninjaone_base_url": "",
            "ninjaone_access_token": "",
            "ninjaone_organization_map_json": "",
            "ninjaone_page_size": 50,
            "datto_rmm_base_url": "",
            "datto_rmm_access_token": "",
            "datto_rmm_site_map_json": "",
            "datto_rmm_page_size": 50,
            "ncentral_base_url": "",
            "ncentral_access_token": "",
            "ncentral_org_unit_map_json": "",
            "ncentral_page_size": 50,
            "m365_graph_base_url": "",
            "m365_access_token": "",
            "m365_page_size": base_settings.m365_page_size,
        }
    )
    if connector_type == "m365":
        values["m365_graph_base_url"] = base_url
        if credentials.get("mode") == "static_token":
            values["m365_access_token"] = credentials["access_token"]
    elif connector_type == "halopsa":
        values.update(
            {
                "halopsa_base_url": base_url,
                "halopsa_client_id": credentials["client_id"],
                "halopsa_client_secret": credentials["client_secret"],
                "halopsa_tenant": credentials["tenant"],
            }
        )
    elif connector_type == "connectwise":
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
    elif connector_type == "autotask":
        values.update(
            {
                "autotask_base_url": base_url,
                "autotask_username": credentials["username"],
                "autotask_secret": credentials["secret"],
                "autotask_integration_code": credentials["integration_code"],
            }
        )
    elif connector_type == "syncro":
        values.update(
            {
                "syncro_base_url": base_url,
                "syncro_api_token": credentials["api_key"],
            }
        )
    elif connector_type == "servicenow":
        effective_version = config.get("api_version", base_settings.servicenow_api_version)
        values.update(
            {
                "servicenow_base_url": base_url,
                "servicenow_username": credentials["username"],
                "servicenow_password": credentials["password"],
                "servicenow_api_version": _validate_servicenow_version(effective_version),
            }
        )
    elif connector_type == "ninjaone":
        values.update(
            {
                "ninjaone_base_url": base_url,
                "ninjaone_access_token": credentials["access_token"],
                "ninjaone_organization_map_json": str(config.get("organization_map_json", "")),
                "ninjaone_page_size": _config_page_size(config, base_settings.ninjaone_page_size),
            }
        )
    elif connector_type == "dattormm":
        values.update(
            {
                "datto_rmm_base_url": base_url,
                "datto_rmm_access_token": credentials["access_token"],
                "datto_rmm_site_map_json": str(config.get("site_map_json", "")),
                "datto_rmm_page_size": _config_page_size(config, base_settings.datto_rmm_page_size),
            }
        )
    else:
        values.update(
            {
                "ncentral_base_url": base_url,
                "ncentral_access_token": credentials["access_token"],
                "ncentral_org_unit_map_json": str(config.get("org_unit_map_json", "")),
                "ncentral_page_size": _config_page_size(config, base_settings.ncentral_page_size),
            }
        )
    return replace(base_settings, **cast(Any, values))


def validate_connector_instance(
    instance: ConnectorInstance,
    *,
    base_settings: Settings,
    vault: VaultReader | None = None,
) -> None:
    """Validate stored-instance credentials and configuration without probing."""
    connector_type = instance.connector_type.casefold().strip() if isinstance(instance.connector_type, str) else ""
    if connector_type not in _BUILDERS:
        raise ConnectorFactoryError("unsupported connector_type")
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
        syncro_subdomain=credentials.get("subdomain"),
    )
    _sanitized_settings(
        base_settings,
        connector_type=connector_type,
        config=config,
        credentials=credentials,
        base_url=base_url,
    )


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
        syncro_subdomain=credentials.get("subdomain"),
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
            allowed_hosts=(
                (*base_settings.connector_instance_allowed_hosts, "graph.microsoft.com")
                if connector_type == "m365"
                else base_settings.connector_instance_allowed_hosts
            ),
            timeout=base_settings.connector_timeout_seconds,
            resolver=resolver or socket.getaddrinfo,
            transport=inner_transport,
        )
        if connector_type == "m365":
            return M365GraphClient(
                per_instance_settings,
                transport=pinned,
                connection=M365Connection(
                    graph_base_url=per_instance_settings.m365_graph_base_url,
                    token_provider=M365TokenProvider(credentials),
                    profile_id=instance.connector_instance_id,
                    tier="client-scoped",
                ),
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
